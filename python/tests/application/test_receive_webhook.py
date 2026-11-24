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
    ReceptionObservation,
    Rejected,
    ReleaseRequest,
    Verification,
    Verified,
    VerifiedEvent,
    create_async_receiver,
    create_receiver,
    http_status_for,
)
from omniwebhook.domain.reservation import ClaimOutcome
from omniwebhook.standard import standard_scheme
from tests.contracts.idempotency_store import reproducir, reproducir_async
from tests.support.dobles import Cronometro, RelojFijo, TokensFijos
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
    if esperado["outcome"] == "unprocessable":
        assert isinstance(resultado.error, ValueError)
    else:
        assert resultado.error is (falla if esperado["outcome"] == "failed" else None)


def _rechazar(_valor: object) -> object:
    raise ValueError("rechazado")


def _opciones(caso: Caso) -> dict[str, Any]:
    reloj = RelojFijo(caso["now"])
    return {
        "verifier": standard_scheme(secrets=caso["secrets"], clock=reloj),
        "clock": reloj,
        "tokens": TokensFijos(caso["token"]),
        "lease_seconds": caso["lease_seconds"],
        "retention_seconds": caso["retention_seconds"],
        "max_body_bytes": caso["max_body_bytes"],
        "payload": {"none": None, "accepts": lambda valor: valor, "rejects": _rechazar}[caso["payload"]],
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


class Observador:
    def __init__(self, falla: Exception | None = None) -> None:
        self.vistos: list[ReceptionObservation] = []
        self.falla = falla

    def on_reception(self, observation: ReceptionObservation) -> None:
        self.vistos.append(observation)
        if self.falla is not None:
            raise self.falla


class Invalido:
    def verify(self, request: IncomingRequest) -> Verification:
        return Rejected("invalid")


def test_el_observador_recibe_el_resultado_la_clave_y_la_duracion_una_vez_por_pedido() -> None:
    observador = Observador()
    recibir, _ = _recibir(observer=observador, timer=Cronometro(paso=25))

    recibir.execute(PEDIDO, lambda _evento: None)
    recibir.execute(PEDIDO, lambda _evento: None)

    assert observador.vistos == [
        ReceptionObservation(outcome="ok", event_key="prueba:1", duration_ms=25),
        ReceptionObservation(outcome="duplicate", event_key="prueba:1", duration_ms=25),
    ]


def test_el_observador_recibe_un_rechazo_sin_clave_de_evento() -> None:
    observador = Observador()
    recibir, _ = _recibir(verifier=Invalido(), observer=observador, timer=Cronometro(paso=25))

    recibir.execute(PEDIDO, lambda _evento: None)

    assert observador.vistos == [ReceptionObservation(outcome="invalid", event_key=None, duration_ms=25)]


def test_al_observador_se_lo_llama_despues_de_liberar_la_reserva() -> None:
    observador = Observador()
    recibir, almacen = _recibir(observer=observador, timer=Cronometro())

    def falla(_evento: VerifiedEvent) -> None:
        raise Falla("falló")

    recibir.execute(PEDIDO, falla)

    assert [visto.outcome for visto in observador.vistos] == ["failed"]
    assert _sonda(almacen) == "claimed"


def test_si_el_observador_falla_el_resultado_no_cambia() -> None:
    recibir, _ = _recibir(observer=Observador(falla=RuntimeError("falló la telemetría")), timer=Cronometro())

    assert recibir.execute(PEDIDO, lambda _evento: None) == Reception(outcome="ok", event_key="prueba:1")


async def test_el_observador_tambien_ve_la_variante_asincronica() -> None:
    observador = Observador()
    recibir = AsyncReceiveWebhook(
        verifier=Verificado(),
        store=AsyncMemoryIdempotencyStore(),
        clock=RelojFijo(),
        tokens=TokensFijos(),
        observer=observador,
        timer=Cronometro(paso=25),
    )

    async def procesar(_evento: VerifiedEvent) -> None:
        return None

    await recibir.execute(PEDIDO, procesar)

    assert observador.vistos == [ReceptionObservation(outcome="ok", event_key="prueba:1", duration_ms=25)]


def test_un_observador_sin_cronometro_es_un_error_de_configuracion() -> None:
    with pytest.raises(ConfigurationError, match="timer"):
        _recibir(observer=Observador())


def test_create_receiver_pone_el_cronometro_por_defecto() -> None:
    observador = Observador()
    recibir = create_receiver(verifier=Verificado(), store=MemoryIdempotencyStore(), observer=observador)

    recibir.execute(PEDIDO, lambda _evento: None)

    assert [visto.outcome for visto in observador.vistos] == ["ok"]
    assert observador.vistos[0].duration_ms >= 0


def _con_tipo(valor: object) -> dict[str, str]:
    if not isinstance(valor, dict) or not isinstance(valor.get("tipo"), str):
        raise TypeError("falta tipo")
    return {"tipo": valor["tipo"]}


def _con_cuerpo(texto: str) -> IncomingRequest:
    return IncomingRequest(headers=[], query=[], body=texto.encode("utf-8"))


def test_el_procesamiento_recibe_el_payload_que_devolvio_el_validador() -> None:
    recibir, _ = _recibir(payload=_con_tipo)
    eventos: list[VerifiedEvent] = []

    resultado = recibir.execute(_con_cuerpo('{"tipo":"pago","de_mas":1}'), eventos.append)

    assert resultado == Reception(outcome="ok", event_key="prueba:1")
    assert eventos[0].payload == {"tipo": "pago"}


def test_sin_validador_el_payload_queda_vacio() -> None:
    recibir, _ = _recibir()
    eventos: list[VerifiedEvent] = []

    recibir.execute(_con_cuerpo('{"tipo":"pago"}'), eventos.append)

    assert eventos[0].payload is None


def test_un_payload_rechazado_devuelve_el_motivo_y_no_toca_el_almacen() -> None:
    almacen = AlmacenEspia()
    recibir, _ = _recibir(payload=_con_tipo, store=almacen)
    eventos: list[VerifiedEvent] = []

    resultado = recibir.execute(_con_cuerpo('{"otro":1}'), eventos.append)

    assert (resultado.outcome, resultado.event_key) == ("unprocessable", "prueba:1")
    assert isinstance(resultado.error, TypeError)
    assert http_status_for(resultado.outcome) == 422
    assert eventos == []
    assert almacen.pedidos == []


@pytest.mark.parametrize(
    "texto", ["no es json", "\ufeff{}", "", "[" * 100_000], ids=["texto", "bom", "vacío", "hondo"]
)
def test_un_cuerpo_que_no_es_json_no_llega_al_validador(texto: str) -> None:
    vistos: list[object] = []
    recibir, _ = _recibir(payload=vistos.append)

    resultado = recibir.execute(_con_cuerpo(texto), lambda _evento: None)

    assert resultado.outcome == "unprocessable"
    assert str(resultado.error) == "el cuerpo no es JSON"
    assert vistos == []


def test_un_pedido_que_no_verifica_no_llega_al_validador() -> None:
    vistos: list[object] = []
    recibir, _ = _recibir(verifier=Invalido(), payload=vistos.append)

    assert recibir.execute(_con_cuerpo("{}"), lambda _evento: None) == Reception(outcome="invalid")
    assert vistos == []


async def test_el_validador_tambien_corre_en_la_variante_asincronica() -> None:
    recibir = create_async_receiver(
        verifier=Verificado(), store=AsyncMemoryIdempotencyStore(), payload=_con_tipo
    )
    eventos: list[VerifiedEvent] = []

    async def procesar(evento: VerifiedEvent) -> None:
        eventos.append(evento)

    assert (await recibir.execute(_con_cuerpo('{"tipo":"alta"}'), procesar)).outcome == "ok"
    assert (await recibir.execute(_con_cuerpo("{}"), procesar)).outcome == "unprocessable"
    assert [evento.payload for evento in eventos] == [{"tipo": "alta"}]
