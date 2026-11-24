import asyncio
from typing import Any

import pytest

from omniwebhook import (
    AsyncMemoryIdempotencyStore,
    AsyncReceiveWebhook,
    ClaimRequest,
    CompleteRequest,
    ConfigurationError,
    IncomingRequest,
    MemoryIdempotencyStore,
    ReceiveWebhook,
    Reception,
    Rejected,
    ReleaseRequest,
    Verification,
    Verified,
    VerifiedEvent,
    http_status_for,
)
from omniwebhook.domain.reservation import ClaimOutcome
from omniwebhook.standard import standard_scheme
from tests.contracts.idempotency_store import reproducir, reproducir_async
from tests.support.dobles import RelojFijo, TokensFijos
from tests.support.vectors import Caso, a_pedido, casos, nombre

CASOS = casos("recibir/caso-de-uso")
PEDIDO = IncomingRequest(headers=[], query=[], body=b"")


class Falla(Exception):
    pass


def _comprobar(caso: Caso, resultado: Reception, llamadas: int, falla: Falla) -> None:
    esperado = caso["expected"]
    assert resultado.outcome == esperado["outcome"]
    assert http_status_for(resultado.outcome) == esperado["status"]
    assert llamadas == (1 if esperado["handler_called"] else 0)
    assert resultado.event_key == esperado.get("event_key")
    assert resultado.error is (falla if esperado["outcome"] == "failed" else None)


def _opciones(caso: Caso) -> dict[str, Any]:
    reloj = RelojFijo(caso["now"])
    return {
        "verifier": standard_scheme(secrets=caso["secrets"], clock=reloj),
        "clock": reloj,
        "tokens": TokensFijos(caso["token"]),
        "lease_seconds": caso["lease_seconds"],
        "retention_seconds": caso["retention_seconds"],
        "max_body_bytes": caso["max_body_bytes"],
    }


@pytest.mark.parametrize("caso", CASOS, ids=nombre)
def test_vectores(caso: Caso) -> None:
    almacen = MemoryIdempotencyStore()
    reproducir(almacen, caso["before"])
    falla = Falla("falló el procesamiento")
    eventos: list[VerifiedEvent] = []

    def procesar(evento: VerifiedEvent) -> None:
        eventos.append(evento)
        if caso["handler"] == "fails":
            raise falla

    resultado = ReceiveWebhook(store=almacen, **_opciones(caso)).execute(a_pedido(caso["request"]), procesar)

    _comprobar(caso, resultado, len(eventos), falla)
    reproducir(almacen, caso["after"])


@pytest.mark.parametrize("caso", CASOS, ids=nombre)
async def test_vectores_en_la_variante_asincrona(caso: Caso) -> None:
    almacen = AsyncMemoryIdempotencyStore()
    await reproducir_async(almacen, caso["before"])
    falla = Falla("falló el procesamiento")
    eventos: list[VerifiedEvent] = []

    async def procesar(evento: VerifiedEvent) -> None:
        await asyncio.sleep(0)
        eventos.append(evento)
        if caso["handler"] == "fails":
            raise falla

    recibir = AsyncReceiveWebhook(store=almacen, **_opciones(caso))
    resultado = await recibir.execute(a_pedido(caso["request"]), procesar)

    _comprobar(caso, resultado, len(eventos), falla)
    await reproducir_async(almacen, caso["after"])


class Verificado:
    def verify(self, request: IncomingRequest) -> Verification:
        return Verified(event_key="prueba:1", timestamp=None)


class AlmacenEspia:
    def __init__(self) -> None:
        self.pedidos: list[object] = []

    def claim(self, request: ClaimRequest) -> ClaimOutcome:
        self.pedidos.append(request)
        return "claimed"

    def complete(self, request: CompleteRequest) -> bool:
        self.pedidos.append(request)
        return True

    def release(self, request: ReleaseRequest) -> bool:
        self.pedidos.append(request)
        return True


def _recibir(**cambios: Any) -> tuple[ReceiveWebhook, MemoryIdempotencyStore]:
    almacen = MemoryIdempotencyStore()
    opciones: dict[str, Any] = {
        "verifier": Verificado(),
        "store": almacen,
        "clock": RelojFijo(),
        "tokens": TokensFijos(),
    }
    return ReceiveWebhook(**{**opciones, **cambios}), almacen


def _sonda(almacen: MemoryIdempotencyStore, clave: str = "prueba:1") -> ClaimOutcome:
    return almacen.claim(ClaimRequest(key=clave, token="sonda", now=1_700_000_000, lease_seconds=1))


def test_le_pasa_al_procesamiento_el_evento_verificado() -> None:
    recibir, _ = _recibir()
    eventos: list[VerifiedEvent] = []

    recibir.execute(PEDIDO, eventos.append)

    assert eventos == [VerifiedEvent(event_key="prueba:1", timestamp=None, request=PEDIDO)]


def test_un_pedido_rechazado_no_reserva_ni_procesa() -> None:
    class Rechaza:
        def verify(self, request: IncomingRequest) -> Verification:
            return Rejected("invalid")

    almacen = AlmacenEspia()
    recibir, _ = _recibir(verifier=Rechaza(), store=almacen)
    eventos: list[VerifiedEvent] = []

    resultado = recibir.execute(PEDIDO, eventos.append)

    assert resultado == Reception(outcome="invalid")
    assert eventos == []
    assert almacen.pedidos == []


def test_usa_la_clave_propia_de_quien_integra_cuando_se_la_dan() -> None:
    recibir, almacen = _recibir(event_key=lambda evento: f"{evento.event_key}:pago")
    eventos: list[VerifiedEvent] = []

    resultado = recibir.execute(PEDIDO, eventos.append)

    assert resultado == Reception(outcome="ok", event_key="prueba:1:pago")
    assert eventos[0].event_key == "prueba:1:pago"
    assert _sonda(almacen, "prueba:1:pago") == "duplicate"


def test_usa_los_plazos_por_defecto_de_la_especificacion() -> None:
    almacen = AlmacenEspia()
    recibir, _ = _recibir(store=almacen)

    recibir.execute(PEDIDO, lambda _evento: None)

    assert almacen.pedidos == [
        ClaimRequest(key="prueba:1", token="t-1", now=1_700_000_000, lease_seconds=300),
        CompleteRequest(key="prueba:1", token="t-1", now=1_700_000_000, retention_seconds=604_800),
    ]


@pytest.mark.parametrize(
    ("opcion", "valor"),
    [("max_body_bytes", 0), ("lease_seconds", 0), ("lease_seconds", 1.5), ("retention_seconds", -1)],
)
def test_rechaza_un_plazo_invalido_al_construirse(opcion: str, valor: object) -> None:
    with pytest.raises(ConfigurationError, match=f"{opcion} tiene que ser un entero mayor que cero"):
        _recibir(**{opcion: valor})
    with pytest.raises(ConfigurationError, match=opcion):
        AsyncReceiveWebhook(
            verifier=Verificado(),
            store=AsyncMemoryIdempotencyStore(),
            clock=RelojFijo(),
            tokens=TokensFijos(),
            **{opcion: valor},  # type: ignore[arg-type]
        )


def test_una_interrupcion_libera_la_reserva_y_sigue_su_camino() -> None:
    recibir, almacen = _recibir()

    def interrumpido(_evento: VerifiedEvent) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        recibir.execute(PEDIDO, interrumpido)

    assert _sonda(almacen) == "claimed"


async def test_una_cancelacion_libera_la_reserva_y_sigue_su_camino() -> None:
    almacen = AsyncMemoryIdempotencyStore()
    recibir = AsyncReceiveWebhook(
        verifier=Verificado(), store=almacen, clock=RelojFijo(), tokens=TokensFijos()
    )
    empezo = asyncio.Event()

    async def lento(_evento: VerifiedEvent) -> None:
        empezo.set()
        await asyncio.sleep(60)

    tarea = asyncio.create_task(recibir.execute(PEDIDO, lento))
    await empezo.wait()
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea

    sonda = ClaimRequest(key="prueba:1", token="sonda", now=1_700_000_000, lease_seconds=1)
    assert await almacen.claim(sonda) == "claimed"
