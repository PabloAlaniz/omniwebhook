"""Marcas de tiempo firmadas."""

import re
from typing import Final

SECONDS_DIGITS: Final = 11
"""Las marcas en segundos tienen hasta 11 dígitos."""
SECONDS_OR_MILLIS_DIGITS: Final = 15
"""Un emisor que puede mandar milisegundos usa hasta 15."""

_MILLIS_THRESHOLD: Final = 100_000_000_000
_DIGITS: Final = re.compile(r"[0-9]+")


def parse_timestamp(text: str, max_digits: int) -> int | None:
    """Interpreta un entero decimal sin signo de hasta `max_digits` dígitos; si no lo es, `None`."""
    if len(text) > max_digits or _DIGITS.fullmatch(text) is None:
        return None
    return int(text)


def to_seconds(raw: int) -> int:
    """Lleva a segundos una marca que puede venir en milisegundos (sección 5.3)."""
    return raw // 1000 if raw >= _MILLIS_THRESHOLD else raw
