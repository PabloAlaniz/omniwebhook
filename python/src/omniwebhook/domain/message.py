"""Un mensaje a emitir y el resultado de firmarlo (sección 7)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

DEFAULT_MAX_PAYLOAD_BYTES: Final = 262_144
"""El tamaño máximo del payload de un mensaje, en bytes, si no se indica otro (sección 7)."""


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    id: str
    """Identifica al mensaje, no al intento: es el mismo en todos los reintentos."""
    timestamp: int
    """La hora del intento, en segundos."""
    payload: bytes
    """El cuerpo, byte a byte como se va a enviar."""
    endpoint_id: str | None = None
    """El identificador del destino. Lo necesita la firma asimétrica (sección 7.1)."""


MessageProblem = Literal["invalid_id", "invalid_timestamp"]
SigningProblem = MessageProblem | Literal["invalid_endpoint", "unconfigured"]


@dataclass(frozen=True, slots=True)
class Signed:
    headers: Mapping[str, str]
    outcome: Literal["signed"] = "signed"


@dataclass(frozen=True, slots=True)
class NotSigned:
    outcome: SigningProblem


Signing = Signed | NotSigned


def message_problem(message: OutgoingMessage) -> MessageProblem | None:
    """Lo que impide firmar un mensaje, mirando sólo el mensaje."""
    if message.id == "" or "." in message.id:
        return "invalid_id"
    timestamp: object = message.timestamp
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        return "invalid_timestamp"
    return None
