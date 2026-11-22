"""La política de reintentos (sección 8.3)."""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from omniwebhook.domain.errors import ConfigurationError, positive_integer

DEFAULT_RETRY_SCHEDULE: Final = (5, 300, 1800, 7200, 18_000, 36_000, 50_400, 72_000, 86_400)
"""Las esperas entre intentos, en segundos. Con esta lista hay diez intentos."""
DEFAULT_MAX_DELAY_SECONDS: Final = 86_400
DEFAULT_JITTER_RATIO: Final = 0.1


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """La política de reintentos es un dato. Lo que no se indica toma el valor por defecto."""

    schedule: Sequence[int] = DEFAULT_RETRY_SCHEDULE
    max_delay_seconds: int = DEFAULT_MAX_DELAY_SECONDS
    jitter_ratio: float = DEFAULT_JITTER_RATIO

    def __post_init__(self) -> None:
        # Se comprueba al configurarla, para no descubrir el error en un reintento.
        for delay in self.schedule:
            if isinstance(delay, bool) or not isinstance(delay, int) or delay < 0:
                raise ConfigurationError("schedule tiene que ser una lista de enteros no negativos")
        object.__setattr__(self, "schedule", tuple(self.schedule))
        positive_integer("max_delay_seconds", self.max_delay_seconds)
        if not self.jitter_ratio >= 0:
            raise ConfigurationError("jitter_ratio no puede ser negativo")


@dataclass(frozen=True, slots=True)
class NextAttempt:
    delay_seconds: int
    next_at: int


_MONTHS: Final = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_HTTP_DATE: Final = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), ([0-9]{2}) ([A-Z][a-z]{2}) ([0-9]{4}) "
    r"([0-9]{2}):([0-9]{2}):([0-9]{2}) GMT"
)
_WHOLE_SECONDS: Final = re.compile(r"[0-9]+")
# Más dígitos que estos ya superan cualquier tope: no hace falta convertir el número.
_MAX_SECONDS_DIGITS: Final = 18


def _parse_http_date(text: str) -> int | None:
    """La época Unix de una fecha HTTP como `Sun, 06 Nov 1994 08:49:37 GMT`; `None` si no lo es."""
    match = _HTTP_DATE.fullmatch(text)
    if match is None:
        return None
    day, month_name, year, hour, minute, second = match.groups()
    if month_name not in _MONTHS:
        return None
    try:
        moment = datetime(
            int(year),
            _MONTHS.index(month_name) + 1,
            int(day),
            int(hour),
            int(minute),
            int(second),
            tzinfo=UTC,
        )
    except ValueError:
        return None
    return int(moment.timestamp())


def retry_after_seconds(value: str | None, now: int) -> int | None:
    """Los segundos que pide `retry-after`; `None` si falta, no se entiende o ya pasó."""
    if value is None:
        return None
    if _WHOLE_SECONDS.fullmatch(value) is not None:
        return (
            int(value[:_MAX_SECONDS_DIGITS]) if len(value) <= _MAX_SECONDS_DIGITS else 10**_MAX_SECONDS_DIGITS
        )
    at = _parse_http_date(value)
    return None if at is None or at < now else at - now


def next_attempt(
    *,
    attempt: int,
    now: int,
    random: float,
    retry_after: str | None = None,
    policy: RetryPolicy | None = None,
) -> NextAttempt | None:
    """Cuándo corresponde el próximo intento después de uno que falló y se puede reintentar.

    `attempt` es el número del intento que acaba de fallar (el primero es el 1) y `random`
    un número en [0, 1) para la variación. Devuelve `None` si no quedan intentos.
    """
    policy = policy or RetryPolicy()
    if attempt > len(policy.schedule):
        return None

    base = policy.schedule[attempt - 1]
    requested = retry_after_seconds(retry_after, now) or 0
    capped = min(max(base, requested), policy.max_delay_seconds)
    delay_seconds = capped + math.floor(capped * policy.jitter_ratio * random)
    return NextAttempt(delay_seconds=delay_seconds, next_at=now + delay_seconds)
