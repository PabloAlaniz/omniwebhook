"""El recorrido de verificación que comparten todos los esquemas (sección 4.1)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from omniwebhook.adapters.clock import system_clock
from omniwebhook.adapters.crypto import equal_in_constant_time, utf8
from omniwebhook.application.ports import Clock, Verifier
from omniwebhook.domain.errors import ConfigurationError, positive_integer
from omniwebhook.domain.freshness import DEFAULT_TOLERANCE_SECONDS, is_fresh
from omniwebhook.domain.incoming_request import IncomingRequest
from omniwebhook.domain.verification import Rejected, Verification, Verified

ReadProblem = Literal["missing", "ambiguous", "malformed"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Reading:
    """Lo que un esquema saca de un pedido bien formado."""

    timestamp: int | None
    """La marca de tiempo firmada, en segundos; `None` si el esquema no lleva una."""
    received: Sequence[str]
    """Las firmas recibidas, ya normalizadas para compararlas como texto."""
    event_key: Callable[[], str]
    """La clave del evento. Sólo se calcula si la firma resulta válida."""


R = TypeVar("R", bound=Reading)


class SchemeDefinition(Protocol[R]):
    """Lo que distingue a un esquema de otro."""

    def key_of(self, secret: str) -> bytes | None:
        """Convierte un secreto en la clave del HMAC; `None` si no se puede usar."""
        ...

    def read(self, request: IncomingRequest) -> R | ReadProblem:
        """Lee el pedido, o dice por qué no se puede."""
        ...

    def expected(self, key: bytes, reading: R, request: IncomingRequest) -> str:
        """La firma que debería haber llegado para esta clave, como texto."""
        ...


def text_key(secret: str) -> bytes | None:
    """La clave de los esquemas cuyo secreto es el texto completo, en UTF-8."""
    return utf8(secret)


def checked_secrets(secrets: Sequence[str]) -> tuple[str, ...]:
    """Los secretos como lista. Un texto suelto es un error de quien configura, no un secreto por letra."""
    if isinstance(secrets, str | bytes):
        raise ConfigurationError("secrets tiene que ser una lista de secretos, no un texto")
    return tuple(secrets)


def usable_keys(key_of: Callable[[str], bytes | None], secrets: Sequence[str]) -> tuple[bytes, ...] | None:
    """Las claves de todos los secretos, o `None` si no hay ninguno o alguno no se puede usar."""
    keys: list[bytes] = []
    for secret in secrets:
        key = key_of(secret) if isinstance(secret, str) and secret else None
        if key is None:
            return None
        keys.append(key)
    return tuple(keys) or None


class _SchemeVerifier(Generic[R]):
    def __init__(
        self,
        definition: SchemeDefinition[R],
        secrets: Sequence[str],
        clock: Clock | None,
        tolerance_seconds: int,
    ) -> None:
        self._definition = definition
        self._keys = usable_keys(definition.key_of, checked_secrets(secrets))
        self._clock = clock or system_clock
        self._tolerance_seconds = positive_integer("tolerance_seconds", tolerance_seconds)

    def verify(self, request: IncomingRequest) -> Verification:
        if self._keys is None:
            return Rejected("unconfigured")

        reading = self._definition.read(request)
        if isinstance(reading, str):
            return Rejected(reading)

        valid = False
        for key in self._keys:
            expected = self._definition.expected(key, reading, request)
            for received in reading.received:
                if equal_in_constant_time(expected, received):
                    valid = True
        if not valid:
            return Rejected("invalid")

        timestamp = reading.timestamp
        if timestamp is not None and not is_fresh(self._clock.now(), timestamp, self._tolerance_seconds):
            return Rejected("stale")
        return Verified(event_key=reading.event_key(), timestamp=timestamp)


def scheme_verifier(
    definition: SchemeDefinition[R],
    *,
    secrets: Sequence[str],
    clock: Clock | None = None,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
) -> Verifier:
    """Arma el verificador de un esquema aplicando las comprobaciones en el orden de la sección 4.1."""
    return _SchemeVerifier(definition, secrets, clock, tolerance_seconds)
