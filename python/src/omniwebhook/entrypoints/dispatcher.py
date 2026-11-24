"""Arma el despacho de una tanda con el reloj del sistema y tokens aleatorios por defecto."""

from omniwebhook.adapters.clock import system_clock
from omniwebhook.adapters.tokens import random_tokens
from omniwebhook.application.dispatch_due import (
    DEFAULT_DISPATCH_LEASE_SECONDS,
    DEFAULT_DISPATCH_LIMIT,
    AsyncAttemptSender,
    AsyncDispatchDue,
    AttemptSender,
    DispatchDue,
)
from omniwebhook.application.ports import (
    AsyncEndpointDirectory,
    AsyncEndpointFailureSource,
    AsyncOutbox,
    Clock,
    EndpointDirectory,
    EndpointFailureSource,
    Outbox,
    TokenGenerator,
)
from omniwebhook.domain.endpoint_health import HealthPolicy


def create_dispatcher(
    *,
    outbox: Outbox,
    endpoints: EndpointDirectory,
    sender: AttemptSender,
    clock: Clock | None = None,
    tokens: TokenGenerator | None = None,
    limit: int = DEFAULT_DISPATCH_LIMIT,
    lease_seconds: int = DEFAULT_DISPATCH_LEASE_SECONDS,
    health: EndpointFailureSource | None = None,
    health_policy: HealthPolicy | None = None,
) -> DispatchDue:
    return DispatchDue(
        outbox=outbox,
        endpoints=endpoints,
        sender=sender,
        clock=clock or system_clock,
        tokens=tokens or random_tokens,
        limit=limit,
        lease_seconds=lease_seconds,
        health=health,
        health_policy=health_policy,
    )


def create_async_dispatcher(
    *,
    outbox: AsyncOutbox,
    endpoints: AsyncEndpointDirectory,
    sender: AsyncAttemptSender,
    clock: Clock | None = None,
    tokens: TokenGenerator | None = None,
    limit: int = DEFAULT_DISPATCH_LIMIT,
    lease_seconds: int = DEFAULT_DISPATCH_LEASE_SECONDS,
    health: AsyncEndpointFailureSource | None = None,
    health_policy: HealthPolicy | None = None,
) -> AsyncDispatchDue:
    return AsyncDispatchDue(
        outbox=outbox,
        endpoints=endpoints,
        sender=sender,
        clock=clock or system_clock,
        tokens=tokens or random_tokens,
        limit=limit,
        lease_seconds=lease_seconds,
        health=health,
        health_policy=health_policy,
    )
