import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from omniwebhook import (
    AsyncDispatchDue,
    AsyncMemoryOutbox,
    AttemptRecord,
    ConfigurationError,
    Delivery,
    DispatchDue,
    Dispatched,
    DispatchResult,
    EnqueueRequest,
    MemoryDeliveryLedger,
    MemoryOutbox,
    OutboxClaimRequest,
    ResolvedEndpoint,
    SettleRequest,
    TransportRequest,
    TransportResponse,
    create_async_dispatcher,
    create_dispatcher,
    create_sender,
)
from omniwebhook.standard import native_signer, standard_signer
from tests.contracts.outbox import CASOS_DE_BANDEJA, reproducir_bandeja, reproducir_bandeja_async
from tests.support.vectors import Caso, nombre

AHORA = 1_700_000_000
CUERPO = b'{"type":"pedido.creado"}'


@pytest.mark.parametrize("caso", CASOS_DE_BANDEJA, ids=nombre)
def test_contrato_de_la_bandeja_en_memoria(caso: Caso) -> None:
    reproducir_bandeja(MemoryOutbox(), caso["steps"])


@pytest.mark.parametrize("caso", CASOS_DE_BANDEJA, ids=nombre)
async def test_contrato_de_la_bandeja_asincronica_en_memoria(caso: Caso) -> None:
    await reproducir_bandeja_async(AsyncMemoryOutbox(), caso["steps"])


def _intento(entrega: Delivery, **cambios: Any) -> AttemptRecord:
    datos: dict[str, Any] = {
        "message_id": entrega.message_id,
        "endpoint_id": entrega.endpoint.id,
        "attempt": entrega.attempt,
        "at": AHORA,
        "delivery_class": "delivered",
        "state": "delivered",
        "status": 200,
        "problem": None,
        "duration_ms": 5,
        "next_at": None,
    }
    return AttemptRecord(**{**datos, **cambios})


@dataclass
class Banco:
    """Arma el despacho con dobles, en la variante que toque, y lo ejecuta."""

    asincronico: bool
    opciones: dict[str, Any] = field(default_factory=dict)
    respuestas: list[dict[str, Any] | Exception] = field(default_factory=list)
    destinos: dict[str, str] | Exception | None = None
    ahora: int = AHORA
    entregas: list[Delivery] = field(default_factory=list)
    bandeja: MemoryOutbox = field(default_factory=MemoryOutbox)
    tandas: int = 0

    def encolar(self, mensaje: str, destino: str = "ep_1") -> None:
        self.bandeja.enqueue(
            EnqueueRequest(message_id=mensaje, endpoint_id=destino, payload=CUERPO, now=self.ahora)
        )

    def _resolver(self, destino: str) -> ResolvedEndpoint | None:
        if isinstance(self.destinos, Exception):
            raise self.destinos
        if self.destinos is None:
            return ResolvedEndpoint(f"https://hooks.ejemplo.test/{destino}")
        url = self.destinos.get(destino)
        return None if url is None else ResolvedEndpoint(url)

    def _enviar(self, entrega: Delivery) -> AttemptRecord:
        self.entregas.append(entrega)
        respuesta = self.respuestas.pop(0) if self.respuestas else {}
        if isinstance(respuesta, Exception):
            raise respuesta
        return _intento(entrega, **respuesta)

    def despachar(self) -> DispatchResult:
        banco = self
        self.tandas += 1
        comunes: dict[str, Any] = {
            "clock": type("Reloj", (), {"now": lambda _self: banco.ahora})(),
            "tokens": type("Tokens", (), {"next": lambda _self: f"d-{banco.tandas}"})(),
            **self.opciones,
        }

        if not self.asincronico:

            class Destinos:
                def resolve(self, endpoint_id: str) -> ResolvedEndpoint | None:
                    return banco._resolver(endpoint_id)

            class Envio:
                def execute(self, delivery: Delivery) -> AttemptRecord:
                    return banco._enviar(delivery)

            return DispatchDue(outbox=self.bandeja, endpoints=Destinos(), sender=Envio(), **comunes).execute()

        class BandejaAsincronica:
            async def enqueue(self, request: EnqueueRequest) -> bool:
                return banco.bandeja.enqueue(request)

            async def claim(self, request: OutboxClaimRequest) -> Any:
                return banco.bandeja.claim(request)

            async def settle(self, request: SettleRequest) -> bool:
                return banco.bandeja.settle(request)

        class DestinosAsincronicos:
            async def resolve(self, endpoint_id: str) -> ResolvedEndpoint | None:
                return banco._resolver(endpoint_id)

        class EnvioAsincronico:
            async def execute(self, delivery: Delivery) -> AttemptRecord:
                return banco._enviar(delivery)

        return asyncio.run(
            AsyncDispatchDue(
                outbox=BandejaAsincronica(),
                endpoints=DestinosAsincronicos(),
                sender=EnvioAsincronico(),
                **comunes,
            ).execute()
        )


@pytest.fixture(params=[False, True], ids=["sincrónico", "asincrónico"])
def banco(request: pytest.FixtureRequest) -> Banco:
    return Banco(asincronico=bool(request.param))


def test_toma_lo_pendiente_hace_un_intento_y_lo_cierra_con_el_resultado(banco: Banco) -> None:
    banco.encolar("msg_1")

    resultado = banco.despachar()

    entrega = banco.entregas[0]
    assert (entrega.endpoint.id, entrega.endpoint.url) == ("ep_1", "https://hooks.ejemplo.test/ep_1")
    assert (entrega.message_id, entrega.payload, entrega.attempt) == ("msg_1", CUERPO, 1)
    assert resultado == DispatchResult(
        (Dispatched(message_id="msg_1", endpoint_id="ep_1", attempt=1, state="delivered", settled=True),), ()
    )
    assert banco.bandeja.state_of("msg_1", "ep_1") == "delivered"
    assert banco.despachar() == DispatchResult()


def test_un_fallo_reintentable_vuelve_a_salir_recien_cuando_corresponde(banco: Banco) -> None:
    banco.encolar("msg_1")
    banco.respuestas = [
        {"delivery_class": "retryable", "state": "pending", "status": 503, "next_at": AHORA + 5}
    ]

    assert banco.despachar().dispatched[0].state == "pending"
    banco.ahora += 4
    assert banco.despachar().dispatched == ()
    banco.ahora += 1
    segundo = banco.despachar().dispatched[0]
    assert (segundo.attempt, segundo.state) == (2, "delivered")
    assert banco.entregas[-1].attempt == 2


@pytest.mark.parametrize("estado", ["rejected", "blocked", "gone", "exhausted"])
def test_una_entrega_que_termina_queda_cerrada_en_ese_estado(banco: Banco, estado: str) -> None:
    banco.encolar("msg_1")
    banco.respuestas = [{"state": estado, "status": None}]

    banco.despachar()
    banco.ahora += 1_000_000

    assert banco.bandeja.state_of("msg_1", "ep_1") == estado
    assert banco.despachar().dispatched == ()


def test_un_destino_que_no_existe_cancela_la_entrega_sin_intentarla(banco: Banco) -> None:
    banco.destinos = {}
    banco.encolar("msg_1")

    resultado = banco.despachar()

    assert [(d.state, d.settled) for d in resultado.dispatched] == [("cancelled", True)]
    assert banco.entregas == []
    assert banco.bandeja.state_of("msg_1", "ep_1") == "cancelled"


def test_respeta_el_limite_de_la_tanda(banco: Banco) -> None:
    banco.opciones = {"limit": 2}
    for mensaje in ("msg_1", "msg_2", "msg_3"):
        banco.encolar(mensaje)

    assert [d.message_id for d in banco.despachar().dispatched] == ["msg_1", "msg_2"]
    assert [d.message_id for d in banco.despachar().dispatched] == ["msg_3"]


def test_si_un_intento_no_llega_a_hacerse_lo_informa_y_sigue_con_el_resto(banco: Banco) -> None:
    banco.encolar("msg_1")
    banco.encolar("msg_2")
    falla = ConfigurationError("no se puede firmar el mensaje: unconfigured")
    banco.respuestas = [falla]

    resultado = banco.despachar()

    assert [(f.message_id, f.error) for f in resultado.failures] == [("msg_1", falla)]
    assert [d.message_id for d in resultado.dispatched] == ["msg_2"]
    assert banco.bandeja.state_of("msg_1", "ep_1") == "pending"
    # Sigue tomada hasta que venza el plazo; después vuelve a salir.
    assert banco.despachar().dispatched == ()
    banco.ahora += 300
    assert [d.message_id for d in banco.despachar().dispatched] == ["msg_1"]


def test_si_el_directorio_de_destinos_falla_la_entrega_tampoco_se_cierra(banco: Banco) -> None:
    banco.destinos = RuntimeError("sin base de datos")
    banco.encolar("msg_1")

    assert len(banco.despachar().failures) == 1
    assert banco.bandeja.state_of("msg_1", "ep_1") == "pending"


def test_un_intento_pendiente_sin_proximo_intento_es_un_error_y_no_un_cierre(banco: Banco) -> None:
    banco.encolar("msg_1")
    banco.respuestas = [{"state": "pending", "next_at": None}]

    assert len(banco.despachar().failures) == 1
    assert banco.bandeja.state_of("msg_1", "ep_1") == "pending"


def test_si_otro_proceso_tomo_la_entrega_lo_dice_y_no_pisa_su_resultado() -> None:
    banco = Banco(asincronico=False, opciones={"lease_seconds": 10})
    banco.encolar("msg_1")
    enviar = banco._enviar

    def tarda(entrega: Delivery) -> AttemptRecord:
        # El intento tardó más que la toma y otro proceso se la llevó.
        banco.bandeja.claim(OutboxClaimRequest(token="otro", now=AHORA + 10, limit=1, lease_seconds=300))
        return enviar(entrega)

    banco._enviar = tarda  # type: ignore[method-assign]

    resultado = banco.despachar()

    assert [(d.state, d.settled) for d in resultado.dispatched] == [("delivered", False)]
    assert banco.bandeja.state_of("msg_1", "ep_1") == "pending"


@pytest.mark.parametrize("opciones", [{"limit": 0}, {"lease_seconds": 1.5}])
def test_rechaza_una_configuracion_invalida(banco: Banco, opciones: dict[str, Any]) -> None:
    banco.opciones = opciones

    with pytest.raises(ConfigurationError, match=next(iter(opciones))):
        banco.despachar()


def test_cerrar_como_pendiente_exige_decir_desde_cuando() -> None:
    with pytest.raises(ConfigurationError, match="next_at"):
        MemoryOutbox().settle(SettleRequest(message_id="m", endpoint_id="e", token="t", state="pending"))


class _Transporte:
    def __init__(self) -> None:
        self.enviados: list[TransportRequest] = []

    def post(self, request: TransportRequest) -> TransportResponse:
        self.enviados.append(request)
        return TransportResponse(200)


class _Resolucion:
    def resolve(self, host: str) -> list[str]:
        return ["93.184.216.34"]


class _Destinos:
    def resolve(self, endpoint_id: str) -> ResolvedEndpoint | None:
        return ResolvedEndpoint("https://hooks.ejemplo.test/entrada")


def test_de_punta_a_punta_lo_encolado_se_firma_se_envia_y_queda_registrado() -> None:
    bandeja, registro, transporte = MemoryOutbox(), MemoryDeliveryLedger(), _Transporte()
    secreto = "whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="
    despacho = create_dispatcher(
        outbox=bandeja,
        endpoints=_Destinos(),
        sender=create_sender(
            signer=standard_signer(secrets=[secreto], signer=native_signer),
            ledger=registro,
            transport=transporte,
            resolver=_Resolucion(),
        ),
    )
    bandeja.enqueue(EnqueueRequest(message_id="msg_1", endpoint_id="ep_1", payload=CUERPO, now=AHORA))

    resultado = despacho.execute()

    assert [(d.message_id, d.state) for d in resultado.dispatched] == [("msg_1", "delivered")]
    assert transporte.enviados[0].body == CUERPO
    assert [(i.message_id, i.endpoint_id, i.attempt) for i in registro.attempts()] == [("msg_1", "ep_1", 1)]


async def test_create_async_dispatcher_usa_el_reloj_y_los_tokens_por_defecto() -> None:
    bandeja = AsyncMemoryOutbox()

    class Destinos:
        async def resolve(self, endpoint_id: str) -> ResolvedEndpoint | None:
            return None

    class Envio:
        async def execute(self, delivery: Delivery) -> AttemptRecord:
            raise AssertionError("no se tenía que intentar")

    await bandeja.enqueue(EnqueueRequest(message_id="msg_1", endpoint_id="ep_1", payload=CUERPO, now=1))

    resultado = await create_async_dispatcher(outbox=bandeja, endpoints=Destinos(), sender=Envio()).execute()

    assert [d.state for d in resultado.dispatched] == ["cancelled"]
    assert bandeja.state_of("msg_1", "ep_1") == "cancelled"
