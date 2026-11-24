import json
from dataclasses import replace
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from omniwebhook import (
    AsyncMemoryDeliveryLedger,
    AttemptRecord,
    Delivery,
    Endpoint,
    FailureSummary,
    IncomingRequest,
    MemoryDeliveryLedger,
    MemoryIdempotencyStore,
    TransportFailure,
    TransportRequest,
    TransportResponse,
    Verification,
    Verified,
    create_receiver,
    create_sender,
)
from omniwebhook.otel import (
    AsyncOtelDeliveryLedger,
    AsyncOtelTransport,
    OtelDeliveryLedger,
    OtelReceptionObserver,
    OtelTransport,
)
from omniwebhook.standard import native_signer, standard_signer
from tests.support.dobles import Cronometro

AHORA = 1_700_000_000
SECRETO = "whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="
PEDIDO = TransportRequest(
    url="https://hooks.ejemplo.test/entrada/token-secreto?clave=1",
    address="93.184.216.34",
    headers={"webhook-id": "msg_1", "webhook-signature": "v1,firma-secreta"},
    body=b'{"dato":"privado"}',
    timeout_seconds=20,
)


class Metricas:
    def __init__(self) -> None:
        self._lector = InMemoryMetricReader()
        self.meter = MeterProvider(metric_readers=[self._lector]).get_meter("prueba")

    def puntos(self, nombre: str) -> tuple[str | None, list[tuple[dict[str, Any], Any, Any]]]:
        """La unidad de una métrica y sus puntos: atributos, valor (o cuenta) y suma."""
        datos = self._lector.get_metrics_data()
        metricas = [
            metrica
            for recurso in (datos.resource_metrics if datos else [])
            for alcance in recurso.scope_metrics
            for metrica in alcance.metrics
            if metrica.name == nombre
        ]
        if not metricas:
            return None, []
        puntos = [
            (
                dict(punto.attributes or {}),
                getattr(punto, "value", None) if hasattr(punto, "value") else punto.count,
                getattr(punto, "sum", None),
            )
            for punto in metricas[0].data.data_points
        ]
        return metricas[0].unit, puntos


def _trazas() -> tuple[trace.Tracer, InMemorySpanExporter]:
    exportador = InMemorySpanExporter()
    proveedor = TracerProvider()
    proveedor.add_span_processor(SimpleSpanProcessor(exportador))
    return proveedor.get_tracer("prueba"), exportador


class Verificado:
    def verify(self, request: IncomingRequest) -> Verification:
        return Verified(event_key="prueba:1", timestamp=None)


def test_el_observador_cuenta_las_recepciones_por_resultado_y_mide_en_segundos() -> None:
    metricas = Metricas()
    recibir = create_receiver(
        verifier=Verificado(),
        store=MemoryIdempotencyStore(),
        observer=OtelReceptionObserver(meter=metricas.meter),
        timer=Cronometro(paso=250),
    )
    pedido = IncomingRequest(headers=[], query=[], body=b"")

    for _ in range(3):
        recibir.execute(pedido, lambda _evento: None)

    unidad, puntos = metricas.puntos("omniwebhook.receptions")
    assert unidad == "{reception}"
    assert sorted((atributos["omniwebhook.reception.outcome"], valor) for atributos, valor, _ in puntos) == [
        ("duplicate", 2),
        ("ok", 1),
    ]
    unidad, puntos = metricas.puntos("omniwebhook.reception.duration")
    assert unidad == "s"
    assert ({"omniwebhook.reception.outcome": "ok"}, 1, 0.25) in puntos


def _intento(**cambios: Any) -> AttemptRecord:
    datos: dict[str, Any] = {
        "message_id": "msg_1",
        "endpoint_id": "ep_1",
        "attempt": 1,
        "at": AHORA,
        "delivery_class": "delivered",
        "state": "delivered",
        "status": 200,
        "problem": None,
        "duration_ms": 40,
        "next_at": None,
    }
    return AttemptRecord(**{**datos, **cambios})


def test_el_registro_guarda_cada_intento_y_lo_cuenta_por_clase_y_estado() -> None:
    metricas = Metricas()
    adentro = MemoryDeliveryLedger()
    registro = OtelDeliveryLedger(adentro, meter=metricas.meter)

    registro.record(_intento())
    registro.record(_intento(delivery_class="retryable", state="pending", status=503, next_at=AHORA + 5))
    registro.record(_intento(delivery_class="blocked", state="blocked", status=None, duration_ms=0))

    assert len(adentro.attempts()) == 3
    unidad, puntos = metricas.puntos("omniwebhook.delivery.attempts")
    assert unidad == "{attempt}"
    atributos = [punto[0] for punto in puntos]
    assert {
        "omniwebhook.delivery.class": "delivered",
        "omniwebhook.delivery.state": "delivered",
        "http.response.status_code": 200,
    } in atributos
    assert {"omniwebhook.delivery.class": "blocked", "omniwebhook.delivery.state": "blocked"} in atributos
    unidad, puntos = metricas.puntos("omniwebhook.delivery.attempt.duration")
    assert unidad == "s"
    assert sorted(punto[2] for punto in puntos) == [0, 0.04, 0.04]
    assert "ep_1" not in json.dumps(atributos)
    assert "msg_1" not in json.dumps(atributos)


def test_si_el_registro_de_adentro_falla_no_cuenta_el_intento() -> None:
    metricas = Metricas()

    class Roto:
        def record(self, attempt: AttemptRecord) -> None:
            raise RuntimeError("sin base de datos")

    with pytest.raises(RuntimeError, match="sin base de datos"):
        OtelDeliveryLedger(Roto(), meter=metricas.meter).record(_intento())
    assert metricas.puntos("omniwebhook.delivery.attempts")[1] == []


async def test_el_registro_sirve_como_fuente_de_la_salud_en_las_dos_variantes() -> None:
    metricas = Metricas()
    gone = _intento(delivery_class="gone", state="gone", status=410)
    registro = OtelDeliveryLedger(MemoryDeliveryLedger(), meter=metricas.meter)
    asincronico = AsyncOtelDeliveryLedger(AsyncMemoryDeliveryLedger(), meter=metricas.meter)

    registro.record(gone)
    await asincronico.record(gone)

    esperado = FailureSummary(failures=1, failing_since=AHORA, gone=True)
    assert registro.failures_of("ep_1", 0) == esperado
    assert await asincronico.failures_of("ep_1", 0) == esperado
    assert len(metricas.puntos("omniwebhook.delivery.attempts")[1]) == 1


def test_un_registro_que_no_da_el_resumen_de_fallos_lo_dice() -> None:
    class Minimo:
        def record(self, attempt: AttemptRecord) -> None:
            pass

    with pytest.raises(RuntimeError, match="resumen de fallos"):
        OtelDeliveryLedger(Minimo(), meter=Metricas().meter).failures_of("ep_1", 0)


class Transporte:
    def __init__(self, respuesta: TransportResponse | TransportFailure | Exception) -> None:
        self.respuesta = respuesta
        self.enviados: list[TransportRequest] = []

    def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
        self.enviados.append(request)
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta


def _trazar(
    respuesta: TransportResponse | TransportFailure, url: str = PEDIDO.url
) -> tuple[ReadableSpan, Transporte]:
    tracer, exportador = _trazas()
    adentro = Transporte(respuesta)
    OtelTransport(adentro, tracer=tracer).post(replace(PEDIDO, url=url))
    return exportador.get_finished_spans()[0], adentro


def test_una_entrega_es_un_tramo_de_cliente_http_sin_error() -> None:
    tramo, _ = _trazar(TransportResponse(200))

    assert tramo.name == "POST"
    assert tramo.kind == SpanKind.CLIENT
    assert dict(tramo.attributes or {}) == {
        "http.request.method": "POST",
        "server.address": "hooks.ejemplo.test",
        "server.port": 443,
        "url.scheme": "https",
        "omniwebhook.message.id": "msg_1",
        "http.response.status_code": 200,
    }
    assert tramo.status.status_code == StatusCode.UNSET


def test_el_tramo_no_lleva_la_url_completa_el_cuerpo_ni_la_firma() -> None:
    tramo, _ = _trazar(TransportResponse(200))

    texto = tramo.to_json()
    for secreto in ("token-secreto", "clave=1", "firma-secreta", "privado"):
        assert secreto not in texto


def test_manda_traceparent_con_el_identificador_del_tramo_sin_tocar_lo_demas() -> None:
    tramo, adentro = _trazar(TransportResponse(200))
    contexto = tramo.get_span_context()
    assert contexto is not None
    enviado = adentro.enviados[0]

    # Las banderas del final dependen de la versión del SDK; lo que importa es que esté muestreado.
    identificadores = f"00-{contexto.trace_id:032x}-{contexto.span_id:016x}-"
    assert enviado.headers["traceparent"].startswith(identificadores)
    assert int(enviado.headers["traceparent"].removeprefix(identificadores), 16) & 1
    assert {**enviado.headers, **PEDIDO.headers} == dict(enviado.headers)
    assert enviado.body == PEDIDO.body
    assert "traceparent" not in PEDIDO.headers


def test_el_tramo_es_hijo_de_la_operacion_que_estaba_activa() -> None:
    tracer, exportador = _trazas()
    transporte = OtelTransport(Transporte(TransportResponse(200)), tracer=tracer)

    with tracer.start_as_current_span("registrar pedido") as padre:
        transporte.post(PEDIDO)

    hijo = next(tramo for tramo in exportador.get_finished_spans() if tramo.name == "POST")
    contexto = hijo.get_span_context()
    assert contexto is not None
    assert contexto.trace_id == padre.get_span_context().trace_id
    assert hijo.parent is not None
    assert hijo.parent.span_id == padre.get_span_context().span_id


@pytest.mark.parametrize(
    ("respuesta", "tipo", "estado"),
    [
        (TransportResponse(503), "503", 503),
        (TransportResponse(404), "404", 404),
        (TransportFailure("timeout"), "timeout", None),
        (TransportFailure("network"), "network", None),
    ],
)
def test_un_intento_que_falla_marca_el_tramo_con_error(
    respuesta: TransportResponse | TransportFailure, tipo: str, estado: int | None
) -> None:
    tramo, _ = _trazar(respuesta)

    atributos = dict(tramo.attributes or {})
    assert atributos["error.type"] == tipo
    assert atributos.get("http.response.status_code") == estado
    assert tramo.status.status_code == StatusCode.ERROR


def test_una_redireccion_no_es_un_error_del_tramo() -> None:
    assert _trazar(TransportResponse(302))[0].status.status_code == StatusCode.UNSET


def test_si_el_transporte_lanza_el_tramo_se_cierra_con_error_y_la_excepcion_sigue() -> None:
    tracer, exportador = _trazas()

    with pytest.raises(TypeError):
        OtelTransport(Transporte(TypeError("fallo interno")), tracer=tracer).post(PEDIDO)

    tramo = exportador.get_finished_spans()[0]
    assert dict(tramo.attributes or {})["error.type"] == "TypeError"
    assert tramo.end_time is not None


@pytest.mark.parametrize("url", ["https://[::1/x", "ftp://a.test/", "no es una url"])
def test_con_una_url_que_no_se_interpreta_el_tramo_no_lleva_datos_del_destino(url: str) -> None:
    assert "server.address" not in dict(_trazar(TransportFailure("network"), url)[0].attributes or {})


def test_el_puerto_es_el_de_la_url_si_lo_trae_y_el_del_esquema_si_no() -> None:
    http = dict(_trazar(TransportResponse(200), "http://a.test/")[0].attributes or {})
    propio = dict(_trazar(TransportResponse(200), "https://a.test:8443/")[0].attributes or {})

    assert (http["server.port"], http["url.scheme"]) == (80, "http")
    assert propio["server.port"] == 8443


async def test_el_transporte_asincronico_hace_lo_mismo() -> None:
    tracer, exportador = _trazas()

    class Asincronico:
        def __init__(self, respuesta: TransportResponse | TransportFailure | Exception) -> None:
            self.adentro = Transporte(respuesta)

        async def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
            return self.adentro.post(request)

    lento = Asincronico(TransportFailure("timeout"))
    assert await AsyncOtelTransport(lento, tracer=tracer).post(PEDIDO) == TransportFailure("timeout")
    with pytest.raises(TypeError):
        await AsyncOtelTransport(Asincronico(TypeError("x")), tracer=tracer).post(PEDIDO)

    primero, segundo = exportador.get_finished_spans()
    assert dict(primero.attributes or {})["error.type"] == "timeout"
    assert "traceparent" in lento.adentro.enviados[0].headers
    assert dict(segundo.attributes or {})["error.type"] == "TypeError"


def test_de_punta_a_punta_un_intento_deja_un_tramo_y_una_metrica() -> None:
    tracer, exportador = _trazas()
    metricas = Metricas()

    class Resolucion:
        def resolve(self, host: str) -> list[str]:
            return ["93.184.216.34"]

    enviar = create_sender(
        signer=standard_signer(secrets=[SECRETO], signer=native_signer),
        ledger=OtelDeliveryLedger(MemoryDeliveryLedger(), meter=metricas.meter),
        transport=OtelTransport(Transporte(TransportResponse(200)), tracer=tracer),
        resolver=Resolucion(),
    )

    enviar.execute(
        Delivery(
            endpoint=Endpoint("ep_1", "https://hooks.ejemplo.test/entrada"), message_id="msg_9", payload=b"{}"
        )
    )

    assert dict(exportador.get_finished_spans()[0].attributes or {})["omniwebhook.message.id"] == "msg_9"
    assert len(metricas.puntos("omniwebhook.delivery.attempts")[1]) == 1
