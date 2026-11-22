"""Reservas de eventos (sección 6.1)."""

from typing import Final, Literal

ClaimOutcome = Literal["claimed", "in_progress", "duplicate"]
"""Qué devolvió el almacén al pedir la reserva de un evento."""

DEFAULT_LEASE_SECONDS: Final = 300
DEFAULT_RETENTION_SECONDS: Final = 604_800
