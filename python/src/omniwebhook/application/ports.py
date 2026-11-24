"""Los puertos: lo que los casos de uso necesitan del mundo exterior.

Lo que hace entrada/salida tiene dos variantes, una sincrónica y otra asincrónica con el
prefijo `Async`. Verificar y firmar son sólo cálculo, así que tienen una sola.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from omniwebhook.domain.delivery import DeliveryClass, DeliveryState
from omniwebhook.domain.destination import DestinationProblem
from omniwebhook.domain.incoming_request import IncomingRequest
from omniwebhook.domain.message import OutgoingMessage, Signing
from omniwebhook.domain.reception import ReceptionOutcome
from omniwebhook.domain.reservation import ClaimOutcome
from omniwebhook.domain.verification import Verification


class Verifier(Protocol):
    """Comprueba el origen de un pedido entrante. Cada esquema de firma es un adaptador de este puerto."""

    def verify(self, request: IncomingRequest) -> Verification: ...


class MessageSigner(Protocol):
    """Firma un mensaje a emitir. El formato estándar es un adaptador de este puerto."""

    def sign(self, message: OutgoingMessage) -> Signing: ...


class Clock(Protocol):
    """El tiempo actual, en segundos desde la época Unix."""

    def now(self) -> int: ...


class TokenGenerator(Protocol):
    """Genera el identificador con el que un proceso marca sus reservas."""

    def next(self) -> str: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimRequest:
    key: str
    token: str
    now: int
    lease_seconds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CompleteRequest:
    key: str
    token: str
    now: int
    retention_seconds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseRequest:
    key: str
    token: str


class IdempotencyStore(Protocol):
    """El almacén de reservas (sección 6.1). Las tres operaciones tienen que ser atómicas.

    `complete` y `release` devuelven si se aplicaron: sólo si la clave sigue reservada con
    el mismo token.
    """

    def claim(self, request: ClaimRequest) -> ClaimOutcome: ...

    def complete(self, request: CompleteRequest) -> bool: ...

    def release(self, request: ReleaseRequest) -> bool: ...


class AsyncIdempotencyStore(Protocol):
    """La variante asincrónica de `IdempotencyStore`."""

    async def claim(self, request: ClaimRequest) -> ClaimOutcome: ...

    async def complete(self, request: CompleteRequest) -> bool: ...

    async def release(self, request: ReleaseRequest) -> bool: ...


@dataclass(frozen=True, slots=True)
class ReceptionObservation:
    """Lo que se le informa al observador de cada recepción. Nunca incluye el cuerpo ni un secreto."""

    outcome: ReceptionOutcome
    event_key: str | None
    """La clave del evento; `None` si el pedido no llegó a verificarse."""
    duration_ms: int
    """Cuánto llevó la recepción completa, incluido el procesamiento."""


class ReceptionObserver(Protocol):
    """Observa las recepciones (sección 6.4). No cambia el resultado: si lanza, el error se descarta."""

    def on_reception(self, observation: ReceptionObservation) -> None: ...


class Timer(Protocol):
    """El tiempo transcurrido, en milisegundos, para medir cuánto tardó un intento."""

    def now_ms(self) -> int: ...


class RandomSource(Protocol):
    """Números en [0, 1) para la variación de los reintentos."""

    def next(self) -> float: ...


class DnsResolver(Protocol):
    """Resuelve un nombre a direcciones IP.

    Devuelve las direcciones del nombre; una lista vacía si el nombre no existe. Si la
    resolución falla por otro motivo, lanza: el intento cuenta como un error de red.
    """

    def resolve(self, host: str) -> Sequence[str]: ...


class AsyncDnsResolver(Protocol):
    """La variante asincrónica de `DnsResolver`."""

    async def resolve(self, host: str) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportRequest:
    url: str
    address: str
    """La dirección ya validada a la que hay que conectarse."""
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    retry_after: str | None = None


@dataclass(frozen=True, slots=True)
class TransportFailure:
    failure: Literal["network", "timeout"]


class HttpTransport(Protocol):
    """Hace el POST de un intento. No sigue redirecciones."""

    def post(self, request: TransportRequest) -> TransportResponse | TransportFailure: ...


class AsyncHttpTransport(Protocol):
    """La variante asincrónica de `HttpTransport`."""

    async def post(self, request: TransportRequest) -> TransportResponse | TransportFailure: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptRecord:
    """Lo que queda registrado de cada intento (sección 8.4). Nunca incluye la URL de destino."""

    message_id: str
    endpoint_id: str
    attempt: int
    """El número de intento. El primero es el 1."""
    at: int
    """Cuándo empezó el intento, en segundos."""
    delivery_class: DeliveryClass
    state: DeliveryState
    status: int | None
    """El estado HTTP, si hubo respuesta."""
    problem: DestinationProblem | None
    """Por qué la política de URLs rechazó el intento, si lo rechazó."""
    duration_ms: int
    next_at: int | None
    """Cuándo corresponde el próximo intento; `None` si no hay más."""


class DeliveryLedger(Protocol):
    """El registro de entregas."""

    def record(self, attempt: AttemptRecord) -> None: ...


class AsyncDeliveryLedger(Protocol):
    """La variante asincrónica de `DeliveryLedger`."""

    async def record(self, attempt: AttemptRecord) -> None: ...


OutboxState = DeliveryState | Literal["cancelled"]
"""El estado de una entrada de la bandeja de salida (sección 8.5)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EnqueueRequest:
    message_id: str
    endpoint_id: str
    payload: bytes
    """El cuerpo, byte a byte como se va a enviar."""
    now: int


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboxClaimRequest:
    token: str
    now: int
    limit: int
    """Cuántas entradas tomar, como mucho."""
    lease_seconds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboxEntry:
    """Una entrega tomada de la bandeja: lo que hace falta para hacer el intento."""

    message_id: str
    endpoint_id: str
    payload: bytes
    attempt: int
    """El número del intento que toca. El primero es el 1."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SettleRequest:
    message_id: str
    endpoint_id: str
    token: str
    state: OutboxState
    next_at: int | None = None
    """Desde cuándo vuelve a estar disponible. Obligatorio con `state="pending"`."""


class Outbox(Protocol):
    """La bandeja de salida (sección 8.5). Las tres operaciones tienen que ser atómicas."""

    def enqueue(self, request: EnqueueRequest) -> bool:
        """Devuelve si se encoló: `False` si ese mensaje ya estaba para ese destino."""
        ...

    def claim(self, request: OutboxClaimRequest) -> Sequence[OutboxEntry]:
        """Toma lo pendiente que ya venció, en orden, y lo deja tomado por `token`."""
        ...

    def settle(self, request: SettleRequest) -> bool:
        """Devuelve si se aplicó: sólo si la entrada sigue pendiente y la tomó ese mismo token."""
        ...


class AsyncOutbox(Protocol):
    """La variante asincrónica de `Outbox`."""

    async def enqueue(self, request: EnqueueRequest) -> bool: ...

    async def claim(self, request: OutboxClaimRequest) -> Sequence[OutboxEntry]: ...

    async def settle(self, request: SettleRequest) -> bool: ...


@dataclass(frozen=True, slots=True)
class ResolvedEndpoint:
    """Lo que hace falta saber de un destino para entregarle."""

    url: str


class EndpointDirectory(Protocol):
    """Dónde quien integra guarda sus destinos. La bandeja sólo conoce el identificador."""

    def resolve(self, endpoint_id: str) -> ResolvedEndpoint | None:
        """El destino, o `None` si no existe o está deshabilitado: su entrega se cancela."""
        ...


class AsyncEndpointDirectory(Protocol):
    """La variante asincrónica de `EndpointDirectory`."""

    async def resolve(self, endpoint_id: str) -> ResolvedEndpoint | None: ...
