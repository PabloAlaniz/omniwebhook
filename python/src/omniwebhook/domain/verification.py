"""El resultado de verificar un pedido (sección 4)."""

from dataclasses import dataclass
from typing import Literal

Rejection = Literal["unconfigured", "missing", "ambiguous", "malformed", "invalid", "stale"]
"""Por qué se rechazó un pedido. El orden es el de las comprobaciones."""


@dataclass(frozen=True, slots=True)
class Verified:
    event_key: str
    """La clave que identifica al evento para no procesarlo dos veces."""
    timestamp: int | None
    """La marca de tiempo firmada, en segundos; `None` si el esquema no lleva una."""
    outcome: Literal["ok"] = "ok"


@dataclass(frozen=True, slots=True)
class Rejected:
    outcome: Rejection


Verification = Verified | Rejected
