"""Arma el caso de uso de envío con los adaptadores de la biblioteca estándar por defecto.

Resuelve con el sistema y se conecta a la dirección validada.
"""

from collections.abc import Mapping

from omniwebhook.adapters.clock import MonotonicTimer, system_clock
from omniwebhook.adapters.dns.system import AsyncSystemDnsResolver, SystemDnsResolver
from omniwebhook.adapters.tokens import SystemRandom
from omniwebhook.adapters.transport.http_client import HttpClientTransport
from omniwebhook.adapters.transport.threaded import ThreadedTransport
from omniwebhook.application.ports import (
    AsyncDeliveryLedger,
    AsyncDnsResolver,
    AsyncHttpTransport,
    Clock,
    DeliveryLedger,
    DnsResolver,
    HttpTransport,
    MessageSigner,
    RandomSource,
    Timer,
)
from omniwebhook.application.send_webhook import (
    DEFAULT_CONTENT_TYPE,
    DEFAULT_TIMEOUT_SECONDS,
    AsyncSendWebhook,
    SendWebhook,
)
from omniwebhook.domain.retry import RetryPolicy


def create_sender(
    *,
    signer: MessageSigner,
    ledger: DeliveryLedger,
    transport: HttpTransport | None = None,
    resolver: DnsResolver | None = None,
    clock: Clock | None = None,
    timer: Timer | None = None,
    random: RandomSource | None = None,
    retry_policy: RetryPolicy | None = None,
    allow_http: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    content_type: str = DEFAULT_CONTENT_TYPE,
    headers: Mapping[str, str] | None = None,
) -> SendWebhook:
    return SendWebhook(
        signer=signer,
        ledger=ledger,
        transport=transport or HttpClientTransport(),
        resolver=resolver or SystemDnsResolver(),
        clock=clock or system_clock,
        timer=timer or MonotonicTimer(),
        random=random or SystemRandom(),
        retry_policy=retry_policy,
        allow_http=allow_http,
        timeout_seconds=timeout_seconds,
        content_type=content_type,
        headers=headers,
    )


def create_async_sender(
    *,
    signer: MessageSigner,
    ledger: AsyncDeliveryLedger,
    transport: AsyncHttpTransport | None = None,
    resolver: AsyncDnsResolver | None = None,
    clock: Clock | None = None,
    timer: Timer | None = None,
    random: RandomSource | None = None,
    retry_policy: RetryPolicy | None = None,
    allow_http: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    content_type: str = DEFAULT_CONTENT_TYPE,
    headers: Mapping[str, str] | None = None,
) -> AsyncSendWebhook:
    """Sin otro transporte, usa el de la biblioteca estándar en un hilo aparte."""
    return AsyncSendWebhook(
        signer=signer,
        ledger=ledger,
        transport=transport or ThreadedTransport(HttpClientTransport()),
        resolver=resolver or AsyncSystemDnsResolver(),
        clock=clock or system_clock,
        timer=timer or MonotonicTimer(),
        random=random or SystemRandom(),
        retry_policy=retry_policy,
        allow_http=allow_http,
        timeout_seconds=timeout_seconds,
        content_type=content_type,
        headers=headers,
    )
