"""Cómo terminó la recepción de un pedido (sección 6)."""

from collections.abc import Mapping
from typing import Final, Literal

from omniwebhook.domain.verification import Rejection

ReceptionOutcome = (
    Literal["ok", "duplicate", "in_progress", "failed", "too_large", "unprocessable"] | Rejection
)

DEFAULT_MAX_BODY_BYTES: Final = 1_048_576
"""El tamaño máximo del cuerpo de un pedido, en bytes, si no se indica otro (sección 6.2)."""

_STATUS: Final[Mapping[str, int]] = {
    "ok": 200,
    "duplicate": 200,
    "in_progress": 409,
    "missing": 401,
    "ambiguous": 401,
    "malformed": 401,
    "invalid": 401,
    "stale": 401,
    "too_large": 413,
    "unprocessable": 422,
    "unconfigured": 500,
    "failed": 500,
}


def http_status_for(outcome: ReceptionOutcome) -> int:
    """El estado HTTP sugerido para cada resultado (sección 6.3)."""
    return _STATUS[outcome]
