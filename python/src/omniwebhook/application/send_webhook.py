"""Hacer un intento de entrega (sección 8).

Firmar, validar el destino, enviar, clasificar y decir cuándo corresponde el próximo
intento. No programa el reintento: eso lo hace quien integra, llamando de nuevo con
`attempt + 1` cuando llegue `next_at`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from omniwebhook.application.ports import (
    AsyncDeliveryLedger,
    AsyncDnsResolver,
    AsyncHttpTransport,
    AttemptRecord,
    Clock,
    DeliveryLedger,
    DnsResolver,
    HttpTransport,
    MessageSigner,
    RandomSource,
    Timer,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)
from omniwebhook.domain.delivery import AttemptOutcome, classify_delivery, state_after
from omniwebhook.domain.destination import DestinationProblem, inspect_destination, select_address
from omniwebhook.domain.errors import ConfigurationError, positive_integer
from omniwebhook.domain.ip_address import allowed_networks as _allowed_networks
from omniwebhook.domain.message import DEFAULT_MAX_PAYLOAD_BYTES, OutgoingMessage
from omniwebhook.domain.package_version import USER_AGENT
from omniwebhook.domain.retry import RetryPolicy, next_attempt

DEFAULT_TIMEOUT_SECONDS: Final = 20
DEFAULT_CONTENT_TYPE: Final = "application/json"


@dataclass(frozen=True, slots=True)
class Endpoint:
    id: str
    """Cómo llama al destino quien integra. Es lo que queda en el registro, en lugar de la URL."""
    url: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Delivery:
    endpoint: Endpoint
    message_id: str
    """El mismo en todos los intentos de un mensaje."""
    payload: bytes
    attempt: int = 1
    """El número de este intento. El primero es el 1."""


@dataclass(frozen=True, slots=True)
class _Attempted:
    """Cómo terminó un intento, antes de clasificarlo."""

    outcome: AttemptOutcome
    retry_after: str | None = None
    problem: DestinationProblem | None = None


@dataclass(frozen=True, slots=True)
class _Planned:
    """Un intento firmado cuya URL pasó la revisión. Falta saber a qué dirección va."""

    host: str
    literal_address: str | None
    headers: Mapping[str, str]


_NETWORK_FAILURE: Final = _Attempted(AttemptOutcome(failure="network"))


def _blocked(problem: DestinationProblem) -> _Attempted:
    return _Attempted(AttemptOutcome(failure="blocked"), problem=problem)


def _attempted(response: TransportResponse | TransportFailure) -> _Attempted:
    if isinstance(response, TransportFailure):
        return _Attempted(AttemptOutcome(failure=response.failure))
    return _Attempted(AttemptOutcome(status=response.status), retry_after=response.retry_after)


class _Sending:
    """Lo que comparten las dos variantes: todo menos la entrada/salida."""

    def __init__(
        self,
        *,
        signer: MessageSigner,
        clock: Clock,
        timer: Timer,
        random: RandomSource,
        retry_policy: RetryPolicy | None = None,
        allow_http: bool = False,
        allowed_networks: Sequence[str] = (),
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        content_type: str = DEFAULT_CONTENT_TYPE,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._signer = signer
        self._clock = clock
        self._timer = timer
        self._random = random
        self._retry_policy = retry_policy or RetryPolicy()
        self._allow_http = allow_http
        self._allowed = _allowed_networks(allowed_networks)
        self._timeout_seconds = positive_integer("timeout_seconds", timeout_seconds)
        # Los nombres van en minúsculas para que una cabecera extra no conviva con la firma.
        self._base_headers = {
            **{name.lower(): value for name, value in (headers or {}).items()},
            "content-type": content_type,
            "user-agent": USER_AGENT,
        }
        self._max_payload_bytes = positive_integer("max_payload_bytes", max_payload_bytes)

    def _check(self, delivery: Delivery) -> None:
        """Lo que impide hacer el intento y es un error de quien integra, no un resultado."""
        positive_integer("attempt", delivery.attempt)
        if len(delivery.payload) > self._max_payload_bytes:
            raise ConfigurationError(
                f"el payload supera el máximo de {self._max_payload_bytes} bytes: no se envía"
            )

    def _plan(self, delivery: Delivery, at: int) -> _Planned | _Attempted:
        signing = self._signer.sign(
            OutgoingMessage(
                id=delivery.message_id,
                timestamp=at,
                payload=delivery.payload,
                endpoint_id=delivery.endpoint.id,
            )
        )
        if signing.outcome != "signed":
            raise ConfigurationError(f"no se puede firmar el mensaje: {signing.outcome}")

        inspected = inspect_destination(delivery.endpoint.url, allow_http=self._allow_http)
        if isinstance(inspected, str):
            return _blocked(inspected)
        return _Planned(
            host=inspected.host,
            literal_address=inspected.literal_address,
            headers={**self._base_headers, **signing.headers},
        )

    def _request(
        self, delivery: Delivery, plan: _Planned, addresses: Sequence[str]
    ) -> TransportRequest | _Attempted:
        selected = select_address(addresses, self._allowed)
        if isinstance(selected, str):
            return _blocked(selected)
        return TransportRequest(
            url=delivery.endpoint.url,
            address=selected.address,
            headers=plan.headers,
            body=delivery.payload,
            timeout_seconds=self._timeout_seconds,
        )

    def _conclude(
        self, delivery: Delivery, at: int, duration_ms: int, attempted: _Attempted
    ) -> AttemptRecord:
        delivery_class = classify_delivery(attempted.outcome)
        following = (
            next_attempt(
                attempt=delivery.attempt,
                now=self._clock.now(),
                random=self._random.next(),
                retry_after=attempted.retry_after,
                policy=self._retry_policy,
            )
            if delivery_class == "retryable"
            else None
        )
        return AttemptRecord(
            message_id=delivery.message_id,
            endpoint_id=delivery.endpoint.id,
            attempt=delivery.attempt,
            at=at,
            delivery_class=delivery_class,
            state=state_after(delivery_class, following is not None),
            status=attempted.outcome.status,
            problem=attempted.problem,
            duration_ms=duration_ms,
            next_at=None if following is None else following.next_at,
        )


class SendWebhook(_Sending):
    """El caso de uso de envío, sincrónico."""

    def __init__(
        self,
        *,
        signer: MessageSigner,
        transport: HttpTransport,
        resolver: DnsResolver,
        ledger: DeliveryLedger,
        clock: Clock,
        timer: Timer,
        random: RandomSource,
        retry_policy: RetryPolicy | None = None,
        allow_http: bool = False,
        allowed_networks: Sequence[str] = (),
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        content_type: str = DEFAULT_CONTENT_TYPE,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            signer=signer,
            clock=clock,
            timer=timer,
            random=random,
            retry_policy=retry_policy,
            allow_http=allow_http,
            allowed_networks=allowed_networks,
            timeout_seconds=timeout_seconds,
            content_type=content_type,
            max_payload_bytes=max_payload_bytes,
            headers=headers,
        )
        self._transport = transport
        self._resolver = resolver
        self._ledger = ledger

    def execute(self, delivery: Delivery) -> AttemptRecord:
        """Hace un intento. Devuelve lo mismo que guarda en el registro."""
        self._check(delivery)
        at = self._clock.now()
        started_ms = self._timer.now_ms()
        attempted = self._attempt(delivery, at)
        record = self._conclude(delivery, at, self._timer.now_ms() - started_ms, attempted)
        self._ledger.record(record)
        return record

    def _attempt(self, delivery: Delivery, at: int) -> _Attempted:
        plan = self._plan(delivery, at)
        if isinstance(plan, _Attempted):
            return plan

        addresses: Sequence[str]
        if plan.literal_address is not None:
            addresses = [plan.literal_address]
        else:
            try:
                addresses = self._resolver.resolve(plan.host)
            except Exception:
                return _NETWORK_FAILURE

        request = self._request(delivery, plan, addresses)
        if isinstance(request, _Attempted):
            return request
        try:
            return _attempted(self._transport.post(request))
        except Exception:
            return _NETWORK_FAILURE


class AsyncSendWebhook(_Sending):
    """El caso de uso de envío, asincrónico."""

    def __init__(
        self,
        *,
        signer: MessageSigner,
        transport: AsyncHttpTransport,
        resolver: AsyncDnsResolver,
        ledger: AsyncDeliveryLedger,
        clock: Clock,
        timer: Timer,
        random: RandomSource,
        retry_policy: RetryPolicy | None = None,
        allow_http: bool = False,
        allowed_networks: Sequence[str] = (),
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        content_type: str = DEFAULT_CONTENT_TYPE,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            signer=signer,
            clock=clock,
            timer=timer,
            random=random,
            retry_policy=retry_policy,
            allow_http=allow_http,
            allowed_networks=allowed_networks,
            timeout_seconds=timeout_seconds,
            content_type=content_type,
            max_payload_bytes=max_payload_bytes,
            headers=headers,
        )
        self._transport = transport
        self._resolver = resolver
        self._ledger = ledger

    async def execute(self, delivery: Delivery) -> AttemptRecord:
        """Hace un intento. Devuelve lo mismo que guarda en el registro."""
        self._check(delivery)
        at = self._clock.now()
        started_ms = self._timer.now_ms()
        attempted = await self._attempt(delivery, at)
        record = self._conclude(delivery, at, self._timer.now_ms() - started_ms, attempted)
        await self._ledger.record(record)
        return record

    async def _attempt(self, delivery: Delivery, at: int) -> _Attempted:
        plan = self._plan(delivery, at)
        if isinstance(plan, _Attempted):
            return plan

        addresses: Sequence[str]
        if plan.literal_address is not None:
            addresses = [plan.literal_address]
        else:
            try:
                addresses = await self._resolver.resolve(plan.host)
            except Exception:
                return _NETWORK_FAILURE

        request = self._request(delivery, plan, addresses)
        if isinstance(request, _Attempted):
            return request
        try:
            return _attempted(await self._transport.post(request))
        except Exception:
            return _NETWORK_FAILURE
