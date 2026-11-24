"""Despachar una tanda (sección 8.5).

Tomar lo pendiente que ya venció, hacer un intento por cada entrega y cerrarla con el
resultado. No tiene bucle ni planificador: se llama desde un cron, una cola o un bucle
propio, tan seguido como haga falta.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol

from omniwebhook.application.ports import (
    AsyncEndpointDirectory,
    AsyncEndpointFailureSource,
    AsyncOutbox,
    AttemptRecord,
    Clock,
    EndpointDirectory,
    EndpointFailureSource,
    Outbox,
    OutboxClaimRequest,
    OutboxEntry,
    OutboxState,
    ResolvedEndpoint,
    SettleRequest,
    TokenGenerator,
)
from omniwebhook.application.send_webhook import Delivery, Endpoint
from omniwebhook.domain.endpoint_health import EndpointHealth, FailureSummary, HealthPolicy, endpoint_health
from omniwebhook.domain.errors import positive_integer

DEFAULT_DISPATCH_LIMIT: Final = 10
DEFAULT_DISPATCH_LEASE_SECONDS: Final = 300


class AttemptSender(Protocol):
    """Quien hace el intento: `SendWebhook`, o algo que elija cuál usar según el destino."""

    def execute(self, delivery: Delivery) -> AttemptRecord: ...


class AsyncAttemptSender(Protocol):
    """La variante asincrónica de `AttemptSender`."""

    async def execute(self, delivery: Delivery) -> AttemptRecord: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Dispatched:
    """Cómo terminó una entrega de la tanda."""

    message_id: str
    endpoint_id: str
    attempt: int
    state: OutboxState
    """El estado en que quedó la entrada."""
    settled: bool
    """`False` si otro proceso tomó la entrada mientras tanto: su resultado es el que vale."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DispatchFailure:
    """Una entrega que no llegó a intentarse. Sigue tomada hasta que venza el plazo."""

    message_id: str
    endpoint_id: str
    error: Exception


@dataclass(frozen=True, slots=True, kw_only=True)
class DisabledEndpoint:
    """Un destino que conviene deshabilitar. El paquete no lo hace: avisa."""

    endpoint_id: str
    health: EndpointHealth
    summary: FailureSummary


@dataclass(frozen=True, slots=True)
class DispatchResult:
    dispatched: Sequence[Dispatched] = field(default_factory=tuple)
    failures: Sequence[DispatchFailure] = field(default_factory=tuple)
    disabled: Sequence[DisabledEndpoint] = field(default_factory=tuple)
    """Los destinos que quedaron para deshabilitar, una vez cada uno. Vacío sin `health`."""


class _Dispatching:
    """Lo que comparten las dos variantes: todo menos la entrada/salida."""

    def __init__(
        self,
        *,
        clock: Clock,
        tokens: TokenGenerator,
        limit: int,
        lease_seconds: int,
        health_policy: HealthPolicy | None,
    ) -> None:
        self._clock = clock
        self._tokens = tokens
        self._limit = positive_integer("limit", limit)
        self._lease_seconds = positive_integer("lease_seconds", lease_seconds)
        self._health_policy = health_policy or HealthPolicy()

    @staticmethod
    def _assessable(entry: OutboxEntry, record: AttemptRecord, disabled: dict[str, DisabledEndpoint]) -> bool:
        """Si hay que mirar la salud del destino: el intento falló y todavía no se lo anotó."""
        return record.delivery_class != "delivered" and entry.endpoint_id not in disabled

    def _note(self, endpoint_id: str, summary: FailureSummary, disabled: dict[str, DisabledEndpoint]) -> None:
        """Anota el destino si, después de este intento, quedó para deshabilitar."""
        health = endpoint_health(summary, self._clock.now(), self._health_policy)
        if health.status == "disabled":
            disabled[endpoint_id] = DisabledEndpoint(endpoint_id=endpoint_id, health=health, summary=summary)

    def _claim(self, token: str) -> OutboxClaimRequest:
        return OutboxClaimRequest(
            token=token, now=self._clock.now(), limit=self._limit, lease_seconds=self._lease_seconds
        )

    @staticmethod
    def _cancel(entry: OutboxEntry, token: str) -> SettleRequest:
        return SettleRequest(
            message_id=entry.message_id, endpoint_id=entry.endpoint_id, token=token, state="cancelled"
        )

    @staticmethod
    def _delivery(entry: OutboxEntry, endpoint: ResolvedEndpoint) -> Delivery:
        return Delivery(
            endpoint=Endpoint(id=entry.endpoint_id, url=endpoint.url),
            message_id=entry.message_id,
            payload=entry.payload,
            attempt=entry.attempt,
        )

    @staticmethod
    def _close(entry: OutboxEntry, token: str, record: AttemptRecord) -> SettleRequest:
        if record.state == "pending" and record.next_at is None:
            raise RuntimeError("el intento quedó pendiente pero sin próximo intento")
        return SettleRequest(
            message_id=entry.message_id,
            endpoint_id=entry.endpoint_id,
            token=token,
            state=record.state,
            next_at=record.next_at,
        )

    @staticmethod
    def _done(entry: OutboxEntry, state: OutboxState, settled: bool) -> Dispatched:
        return Dispatched(
            message_id=entry.message_id,
            endpoint_id=entry.endpoint_id,
            attempt=entry.attempt,
            state=state,
            settled=settled,
        )

    @staticmethod
    def _failed(entry: OutboxEntry, error: Exception) -> DispatchFailure:
        return DispatchFailure(message_id=entry.message_id, endpoint_id=entry.endpoint_id, error=error)


class DispatchDue(_Dispatching):
    """El despacho de una tanda, sincrónico."""

    def __init__(
        self,
        *,
        outbox: Outbox,
        endpoints: EndpointDirectory,
        sender: AttemptSender,
        clock: Clock,
        tokens: TokenGenerator,
        limit: int = DEFAULT_DISPATCH_LIMIT,
        lease_seconds: int = DEFAULT_DISPATCH_LEASE_SECONDS,
        health: EndpointFailureSource | None = None,
        health_policy: HealthPolicy | None = None,
    ) -> None:
        super().__init__(
            clock=clock, tokens=tokens, limit=limit, lease_seconds=lease_seconds, health_policy=health_policy
        )
        self._outbox = outbox
        self._endpoints = endpoints
        self._sender = sender
        self._health = health

    def execute(self) -> DispatchResult:
        token = self._tokens.next()
        dispatched: list[Dispatched] = []
        failures: list[DispatchFailure] = []
        disabled: dict[str, DisabledEndpoint] = {}
        for entry in self._outbox.claim(self._claim(token)):
            try:
                dispatched.append(self._dispatch(entry, token, disabled))
            except Exception as error:
                # No se cierra: la entrada vuelve a salir cuando venza la toma.
                failures.append(self._failed(entry, error))
        return DispatchResult(tuple(dispatched), tuple(failures), tuple(disabled.values()))

    def _dispatch(self, entry: OutboxEntry, token: str, disabled: dict[str, DisabledEndpoint]) -> Dispatched:
        endpoint = self._endpoints.resolve(entry.endpoint_id)
        if endpoint is None:
            return self._done(entry, "cancelled", self._outbox.settle(self._cancel(entry, token)))
        record = self._sender.execute(self._delivery(entry, endpoint))
        settled = self._outbox.settle(self._close(entry, token, record))
        # Después de cerrar: si esto falla, la entrega ya quedó como corresponde.
        if self._health is not None and self._assessable(entry, record, disabled):
            summary = self._health.failures_of(entry.endpoint_id, endpoint.enabled_at)
            self._note(entry.endpoint_id, summary, disabled)
        return self._done(entry, record.state, settled)


class AsyncDispatchDue(_Dispatching):
    """El despacho de una tanda, asincrónico."""

    def __init__(
        self,
        *,
        outbox: AsyncOutbox,
        endpoints: AsyncEndpointDirectory,
        sender: AsyncAttemptSender,
        clock: Clock,
        tokens: TokenGenerator,
        limit: int = DEFAULT_DISPATCH_LIMIT,
        lease_seconds: int = DEFAULT_DISPATCH_LEASE_SECONDS,
        health: AsyncEndpointFailureSource | None = None,
        health_policy: HealthPolicy | None = None,
    ) -> None:
        super().__init__(
            clock=clock, tokens=tokens, limit=limit, lease_seconds=lease_seconds, health_policy=health_policy
        )
        self._outbox = outbox
        self._endpoints = endpoints
        self._sender = sender
        self._health = health

    async def execute(self) -> DispatchResult:
        token = self._tokens.next()
        dispatched: list[Dispatched] = []
        failures: list[DispatchFailure] = []
        disabled: dict[str, DisabledEndpoint] = {}
        for entry in await self._outbox.claim(self._claim(token)):
            try:
                dispatched.append(await self._dispatch(entry, token, disabled))
            except Exception as error:
                failures.append(self._failed(entry, error))
        return DispatchResult(tuple(dispatched), tuple(failures), tuple(disabled.values()))

    async def _dispatch(
        self, entry: OutboxEntry, token: str, disabled: dict[str, DisabledEndpoint]
    ) -> Dispatched:
        endpoint = await self._endpoints.resolve(entry.endpoint_id)
        if endpoint is None:
            return self._done(entry, "cancelled", await self._outbox.settle(self._cancel(entry, token)))
        record = await self._sender.execute(self._delivery(entry, endpoint))
        settled = await self._outbox.settle(self._close(entry, token, record))
        if self._health is not None and self._assessable(entry, record, disabled):
            summary = await self._health.failures_of(entry.endpoint_id, endpoint.enabled_at)
            self._note(entry.endpoint_id, summary, disabled)
        return self._done(entry, record.state, settled)
