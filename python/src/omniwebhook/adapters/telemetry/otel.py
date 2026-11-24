"""Telemetría con OpenTelemetry. Es el único módulo que importa `opentelemetry`.

Los nombres de las métricas y de los atributos son los mismos en los dos paquetes: los
paneles y las alertas sirven para un servicio en cualquiera de los dos lenguajes.
"""

from dataclasses import replace
from typing import Any, Final
from urllib.parse import urlsplit

from opentelemetry import propagate, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

from omniwebhook.application.ports import (
    AsyncDeliveryLedger,
    AsyncHttpTransport,
    AttemptRecord,
    DeliveryLedger,
    HttpTransport,
    ReceptionObservation,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)
from omniwebhook.domain.endpoint_health import FailureSummary

RECEPTIONS: Final = "omniwebhook.receptions"
RECEPTION_DURATION: Final = "omniwebhook.reception.duration"
ATTEMPTS: Final = "omniwebhook.delivery.attempts"
ATTEMPT_DURATION: Final = "omniwebhook.delivery.attempt.duration"
OUTCOME: Final = "omniwebhook.reception.outcome"
DELIVERY_CLASS: Final = "omniwebhook.delivery.class"
DELIVERY_STATE: Final = "omniwebhook.delivery.state"
MESSAGE_ID: Final = "omniwebhook.message.id"


class OtelReceptionObserver:
    """Cuenta las recepciones por resultado y mide cuánto tardan (sección 6.4). Va en `observer`.

    No pone la clave del evento como atributo: cada evento tiene la suya, y una métrica con
    un valor distinto por evento no se puede agregar.
    """

    def __init__(self, *, meter: Meter) -> None:
        self._receptions = meter.create_counter(
            RECEPTIONS, unit="{reception}", description="Pedidos de webhook recibidos, por resultado"
        )
        self._duration = meter.create_histogram(
            RECEPTION_DURATION,
            unit="s",
            description="Cuánto lleva recibir un webhook, incluido el procesamiento",
        )

    def on_reception(self, observation: ReceptionObservation) -> None:
        attributes = {OUTCOME: observation.outcome}
        self._receptions.add(1, attributes)
        self._duration.record(observation.duration_ms / 1000, attributes)


class _LedgerMetrics:
    """Las métricas de los intentos, iguales para las dos variantes del registro."""

    def __init__(self, ledger: Any, meter: Meter) -> None:
        self._ledger = ledger
        self._attempts = meter.create_counter(
            ATTEMPTS,
            unit="{attempt}",
            description="Intentos de entrega de webhooks, por clase y estado en que quedó la entrega",
        )
        self._duration = meter.create_histogram(
            ATTEMPT_DURATION, unit="s", description="Cuánto lleva un intento de entrega"
        )

    def _count(self, attempt: AttemptRecord) -> None:
        attributes: dict[str, str | int] = {
            DELIVERY_CLASS: attempt.delivery_class,
            DELIVERY_STATE: attempt.state,
        }
        if attempt.status is not None:
            attributes["http.response.status_code"] = attempt.status
        self._attempts.add(1, attributes)
        self._duration.record(attempt.duration_ms / 1000, attributes)

    def _source(self) -> Any:
        if not hasattr(self._ledger, "failures_of"):
            raise RuntimeError("el registro envuelto no da el resumen de fallos de un destino")
        return self._ledger


class OtelDeliveryLedger(_LedgerMetrics):
    """Envuelve un registro de entregas y cuenta los intentos por clase y estado. Va en `ledger`.

    Guarda cada intento en el registro de adentro y, si eso sale bien, lo cuenta y mide su
    duración. No pone el destino ni el mensaje como atributos. Sirve como fuente de la salud
    de los destinos si el registro de adentro lo es.
    """

    def __init__(self, ledger: DeliveryLedger, *, meter: Meter) -> None:
        super().__init__(ledger, meter)

    def record(self, attempt: AttemptRecord) -> None:
        self._ledger.record(attempt)
        self._count(attempt)

    def failures_of(self, endpoint_id: str, since: int) -> FailureSummary:
        summary: FailureSummary = self._source().failures_of(endpoint_id, since)
        return summary


class AsyncOtelDeliveryLedger(_LedgerMetrics):
    """La variante asincrónica de `OtelDeliveryLedger`."""

    def __init__(self, ledger: AsyncDeliveryLedger, *, meter: Meter) -> None:
        super().__init__(ledger, meter)

    async def record(self, attempt: AttemptRecord) -> None:
        await self._ledger.record(attempt)
        self._count(attempt)

    async def failures_of(self, endpoint_id: str, since: int) -> FailureSummary:
        summary: FailureSummary = await self._source().failures_of(endpoint_id, since)
        return summary


def _destination(url: str) -> dict[str, str | int]:
    """Lo que se puede decir del destino sin filtrar su URL: puede llevar un token en la ruta."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return {}
    if not parts.hostname or parts.scheme not in ("http", "https"):
        return {}
    return {
        "server.address": parts.hostname,
        "server.port": port or (443 if parts.scheme == "https" else 80),
        "url.scheme": parts.scheme,
    }


class _Spans:
    """El tramo de cada intento, igual para las dos variantes del transporte."""

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def _start(self, request: TransportRequest) -> tuple[Span, TransportRequest]:
        attributes: dict[str, str | int] = {"http.request.method": "POST", **_destination(request.url)}
        message_id = request.headers.get("webhook-id")
        if message_id is not None:
            attributes[MESSAGE_ID] = message_id
        span = self._tracer.start_span("POST", kind=SpanKind.CLIENT, attributes=attributes)
        headers = dict(request.headers)
        propagate.inject(headers, context=trace.set_span_in_context(span))
        return span, replace(request, headers=headers)

    @staticmethod
    def _fail(span: Span, kind: str) -> None:
        span.set_attribute("error.type", kind)
        span.set_status(Status(StatusCode.ERROR))

    def _finish(self, span: Span, response: TransportResponse | TransportFailure) -> None:
        if isinstance(response, TransportFailure):
            self._fail(span, response.failure)
            return
        span.set_attribute("http.response.status_code", response.status)
        if response.status >= 400:
            self._fail(span, str(response.status))


class OtelTransport(_Spans):
    """Envuelve un transporte: cada intento es un tramo de cliente HTTP. Va en `transport`.

    El tramo lleva los atributos de las convenciones semánticas, y el pedido la cabecera
    `traceparent`, para que quien recibe lo vea como continuación de la operación que lo
    originó. El tramo nunca lleva la URL completa, ni el cuerpo, ni la firma.
    """

    def __init__(self, transport: HttpTransport, *, tracer: Tracer) -> None:
        super().__init__(tracer)
        self._transport = transport

    def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
        span, traced = self._start(request)
        try:
            response = self._transport.post(traced)
            self._finish(span, response)
            return response
        except Exception as error:
            self._fail(span, type(error).__name__)
            raise
        finally:
            span.end()


class AsyncOtelTransport(_Spans):
    """La variante asincrónica de `OtelTransport`."""

    def __init__(self, transport: AsyncHttpTransport, *, tracer: Tracer) -> None:
        super().__init__(tracer)
        self._transport = transport

    async def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
        span, traced = self._start(request)
        try:
            response = await self._transport.post(traced)
            self._finish(span, response)
            return response
        except Exception as error:
            self._fail(span, type(error).__name__)
            raise
        finally:
            span.end()
