"""Frescura de un pedido (sección 4.4)."""

from typing import Final

DEFAULT_TOLERANCE_SECONDS: Final = 300


def is_fresh(now: int, timestamp: int, tolerance_seconds: int) -> bool:
    """Un pedido es reciente si su marca no se aleja de ahora más que la tolerancia, en ningún sentido."""
    return abs(now - timestamp) <= tolerance_seconds
