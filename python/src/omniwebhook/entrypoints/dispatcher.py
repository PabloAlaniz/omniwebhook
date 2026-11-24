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
    AsyncOutbox,
    Clock,
    EndpointDirectory,
    Outbox,
    TokenGenerator,
)


def create_dispatcher(
    *,
    outbox: Outbox,
    endpoints: EndpointDirectory,
    sender: AttemptSender,
    clock: Clock | None = None,
    tokens: TokenGenerator | None = None,
    limit: int = DEFAULT_DISPATCH_LIMIT,
    lease_seconds: int = DEFAULT_DISPATCH_LEASE_SECONDS,
) -> DispatchDue:
    return DispatchDue(
        outbox=outbox,
        endpoints=endpoints,
        sender=sender,
        clock=clock or system_clock,
        tokens=tokens or random_tokens,
        limit=limit,
        lease_seconds=lease_seconds,
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
) -> AsyncDispatchDue:
    return AsyncDispatchDue(
        outbox=outbox,
        endpoints=endpoints,
        sender=sender,
        clock=clock or system_clock,
        tokens=tokens or random_tokens,
        limit=limit,
        lease_seconds=lease_seconds,
    )
