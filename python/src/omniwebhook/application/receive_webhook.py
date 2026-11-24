"""Recibir un webhook (sección 6.2): acotar el tamaño, verificar, reservar, procesar y completar.

Si el procesamiento falla, la reserva se libera para que el reintento del emisor funcione.
"""

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from omniwebhook.application.ports import (
    AsyncIdempotencyStore,
    ClaimRequest,
    Clock,
    CompleteRequest,
    IdempotencyStore,
    ReceptionObservation,
    ReceptionObserver,
    ReleaseRequest,
    Timer,
    TokenGenerator,
    Verifier,
)
from omniwebhook.domain.errors import ConfigurationError, positive_integer
from omniwebhook.domain.incoming_request import IncomingRequest
from omniwebhook.domain.reception import DEFAULT_MAX_BODY_BYTES, ReceptionOutcome
from omniwebhook.domain.reservation import DEFAULT_LEASE_SECONDS, DEFAULT_RETENTION_SECONDS


@dataclass(frozen=True, slots=True)
class VerifiedEvent:
    """Lo que recibe la función que procesa el evento: sólo existe si el pedido se verificó."""

    event_key: str
    timestamp: int | None
    request: IncomingRequest


@dataclass(frozen=True, slots=True)
class Reception:
    """Cómo terminó la recepción de un pedido."""

    outcome: ReceptionOutcome
    event_key: str | None = None
    """La clave del evento; `None` si el pedido no pasó la verificación."""
    error: Exception | None = None
    """El error del procesamiento, cuando el resultado es `failed`."""


EventHandler = Callable[[VerifiedEvent], object]
AsyncEventHandler = Callable[[VerifiedEvent], Awaitable[object]]
EventKeyOverride = Callable[[VerifiedEvent], str]
"""Reemplaza la clave del evento por una propia, calculada del pedido ya verificado."""


@dataclass(frozen=True, slots=True)
class _Reservation:
    """Un evento verificado y los pedidos al almacén que le corresponden."""

    event: VerifiedEvent
    token: str
    lease_seconds: int
    retention_seconds: int

    def claim(self, now: int) -> ClaimRequest:
        return ClaimRequest(
            key=self.event.event_key, token=self.token, now=now, lease_seconds=self.lease_seconds
        )

    def complete(self, now: int) -> CompleteRequest:
        return CompleteRequest(
            key=self.event.event_key, token=self.token, now=now, retention_seconds=self.retention_seconds
        )

    def release(self) -> ReleaseRequest:
        return ReleaseRequest(key=self.event.event_key, token=self.token)

    def ended(self, outcome: ReceptionOutcome, error: Exception | None = None) -> Reception:
        return Reception(outcome=outcome, event_key=self.event.event_key, error=error)


class _Receiving:
    """Lo que comparten las dos variantes: todo menos la entrada/salida."""

    def __init__(
        self,
        *,
        verifier: Verifier,
        clock: Clock,
        tokens: TokenGenerator,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        event_key: EventKeyOverride | None = None,
        observer: ReceptionObserver | None = None,
        timer: Timer | None = None,
    ) -> None:
        self._verifier = verifier
        self._clock = clock
        self._tokens = tokens
        self._lease_seconds = positive_integer("lease_seconds", lease_seconds)
        self._retention_seconds = positive_integer("retention_seconds", retention_seconds)
        self._max_body_bytes = positive_integer("max_body_bytes", max_body_bytes)
        self._event_key = event_key
        if observer is not None and timer is None:
            raise ConfigurationError("observer necesita timer para medir la duración")
        self._observer = observer
        self._timer = timer

    def _started(self) -> int | None:
        """Cuándo empezó la recepción; `None` si nadie la observa."""
        return None if self._observer is None or self._timer is None else self._timer.now_ms()

    def _observed(self, started_ms: int | None, reception: Reception) -> Reception:
        if started_ms is None or self._observer is None or self._timer is None:
            return reception
        # Una falla al medir no cambia el resultado de la recepción.
        with contextlib.suppress(Exception):
            self._observer.on_reception(
                ReceptionObservation(
                    outcome=reception.outcome,
                    event_key=reception.event_key,
                    duration_ms=self._timer.now_ms() - started_ms,
                )
            )
        return reception

    def _verify(self, request: IncomingRequest) -> _Reservation | Reception:
        # Antes que la firma: un pedido sin autenticar no elige cuánto trabajo cuesta rechazarlo.
        if len(request.body) > self._max_body_bytes:
            return Reception(outcome="too_large")

        verification = self._verifier.verify(request)
        if verification.outcome != "ok":
            return Reception(outcome=verification.outcome)

        event = VerifiedEvent(verification.event_key, verification.timestamp, request)
        if self._event_key is not None:
            event = replace(event, event_key=self._event_key(event))
        return _Reservation(event, self._tokens.next(), self._lease_seconds, self._retention_seconds)


class ReceiveWebhook(_Receiving):
    """El caso de uso de recepción, sincrónico."""

    def __init__(
        self,
        *,
        verifier: Verifier,
        store: IdempotencyStore,
        clock: Clock,
        tokens: TokenGenerator,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        event_key: EventKeyOverride | None = None,
        observer: ReceptionObserver | None = None,
        timer: Timer | None = None,
    ) -> None:
        super().__init__(
            verifier=verifier,
            clock=clock,
            tokens=tokens,
            lease_seconds=lease_seconds,
            retention_seconds=retention_seconds,
            max_body_bytes=max_body_bytes,
            event_key=event_key,
            observer=observer,
            timer=timer,
        )
        self._store = store

    def execute(self, request: IncomingRequest, handler: EventHandler) -> Reception:
        started_ms = self._started()
        return self._observed(started_ms, self._receive(request, handler))

    def _receive(self, request: IncomingRequest, handler: EventHandler) -> Reception:
        reservation = self._verify(request)
        if isinstance(reservation, Reception):
            return reservation

        claim = self._store.claim(reservation.claim(self._clock.now()))
        if claim != "claimed":
            return reservation.ended(claim)

        try:
            handler(reservation.event)
        except Exception as error:
            self._store.release(reservation.release())
            return reservation.ended("failed", error)
        except BaseException:
            # Una interrupción no es un resultado: se libera la reserva y sigue su camino.
            self._store.release(reservation.release())
            raise

        self._store.complete(reservation.complete(self._clock.now()))
        return reservation.ended("ok")


class AsyncReceiveWebhook(_Receiving):
    """El caso de uso de recepción, asincrónico."""

    def __init__(
        self,
        *,
        verifier: Verifier,
        store: AsyncIdempotencyStore,
        clock: Clock,
        tokens: TokenGenerator,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        event_key: EventKeyOverride | None = None,
        observer: ReceptionObserver | None = None,
        timer: Timer | None = None,
    ) -> None:
        super().__init__(
            verifier=verifier,
            clock=clock,
            tokens=tokens,
            lease_seconds=lease_seconds,
            retention_seconds=retention_seconds,
            max_body_bytes=max_body_bytes,
            event_key=event_key,
            observer=observer,
            timer=timer,
        )
        self._store = store

    async def execute(self, request: IncomingRequest, handler: AsyncEventHandler) -> Reception:
        started_ms = self._started()
        return self._observed(started_ms, await self._receive(request, handler))

    async def _receive(self, request: IncomingRequest, handler: AsyncEventHandler) -> Reception:
        reservation = self._verify(request)
        if isinstance(reservation, Reception):
            return reservation

        claim = await self._store.claim(reservation.claim(self._clock.now()))
        if claim != "claimed":
            return reservation.ended(claim)

        try:
            await handler(reservation.event)
        except Exception as error:
            await self._store.release(reservation.release())
            return reservation.ended("failed", error)
        except BaseException:
            # Una cancelación no es un resultado: se libera la reserva y sigue su camino.
            await self._store.release(reservation.release())
            raise

        await self._store.complete(reservation.complete(self._clock.now()))
        return reservation.ended("ok")
