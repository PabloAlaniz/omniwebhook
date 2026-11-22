"""Clasificación de un intento de entrega (secciones 8.2 y 8.4)."""

from dataclasses import dataclass
from typing import Final, Literal

DeliveryFailure = Literal["network", "timeout", "blocked"]
"""Por qué un intento no llegó a tener respuesta."""
DeliveryClass = Literal["delivered", "gone", "retryable", "rejected", "blocked"]
DeliveryState = Literal["pending", "delivered", "rejected", "blocked", "gone", "exhausted"]

_RETRYABLE_STATUSES: Final = frozenset({408, 409, 425, 429})


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """Qué pasó en un intento: hubo respuesta, o no la hubo y por qué."""

    status: int | None = None
    failure: DeliveryFailure | None = None

    def __post_init__(self) -> None:
        if (self.status is None) == (self.failure is None):
            raise ValueError("un intento tiene un estado o una falla, no los dos ni ninguno")


def classify_delivery(outcome: AttemptOutcome) -> DeliveryClass:
    status = outcome.status
    if status is None:
        return "blocked" if outcome.failure == "blocked" else "retryable"
    if 200 <= status <= 299:
        return "delivered"
    if status == 410:
        return "gone"
    if status in _RETRYABLE_STATUSES or 500 <= status <= 599:
        return "retryable"
    return "rejected"


def state_after(delivery_class: DeliveryClass, has_next_attempt: bool) -> DeliveryState:
    """El estado en que queda la entrega: `retryable` sigue pendiente sólo si hay un próximo intento."""
    if delivery_class != "retryable":
        return delivery_class
    return "pending" if has_next_attempt else "exhausted"
