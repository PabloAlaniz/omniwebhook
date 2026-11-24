"""Arma el caso de uso de recepción con el reloj del sistema y tokens aleatorios por defecto."""

from omniwebhook.adapters.clock import system_clock
from omniwebhook.adapters.tokens import random_tokens
from omniwebhook.application.ports import (
    AsyncIdempotencyStore,
    Clock,
    IdempotencyStore,
    TokenGenerator,
    Verifier,
)
from omniwebhook.application.receive_webhook import AsyncReceiveWebhook, EventKeyOverride, ReceiveWebhook
from omniwebhook.domain.reception import DEFAULT_MAX_BODY_BYTES
from omniwebhook.domain.reservation import DEFAULT_LEASE_SECONDS, DEFAULT_RETENTION_SECONDS


def create_receiver(
    *,
    verifier: Verifier,
    store: IdempotencyStore,
    clock: Clock | None = None,
    tokens: TokenGenerator | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    event_key: EventKeyOverride | None = None,
) -> ReceiveWebhook:
    return ReceiveWebhook(
        verifier=verifier,
        store=store,
        clock=clock or system_clock,
        tokens=tokens or random_tokens,
        lease_seconds=lease_seconds,
        retention_seconds=retention_seconds,
        max_body_bytes=max_body_bytes,
        event_key=event_key,
    )


def create_async_receiver(
    *,
    verifier: Verifier,
    store: AsyncIdempotencyStore,
    clock: Clock | None = None,
    tokens: TokenGenerator | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    event_key: EventKeyOverride | None = None,
) -> AsyncReceiveWebhook:
    return AsyncReceiveWebhook(
        verifier=verifier,
        store=store,
        clock=clock or system_clock,
        tokens=tokens or random_tokens,
        lease_seconds=lease_seconds,
        retention_seconds=retention_seconds,
        max_body_bytes=max_body_bytes,
        event_key=event_key,
    )
