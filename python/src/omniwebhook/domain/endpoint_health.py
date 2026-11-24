"""La salud de un destino, calculada de sus intentos (sección 8.5)."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from omniwebhook.domain.errors import positive_integer

DEFAULT_HEALTH_WINDOW_SECONDS: Final = 432_000
DEFAULT_HEALTH_MIN_FAILURES: Final = 5


@dataclass(frozen=True, slots=True)
class FailureSummary:
    """Los fallos de un destino desde su última entrega."""

    failures: int = 0
    """Cuántos intentos fallaron desde la última entrega."""
    failing_since: int | None = None
    """El menor `at` entre ellos; `None` si no hay ninguno."""
    gone: bool = False
    """Si alguno fue un 410."""


@dataclass(frozen=True, slots=True)
class HealthPolicy:
    """Hacen falta cantidad y tiempo para dar por caído un destino."""

    window_seconds: int = DEFAULT_HEALTH_WINDOW_SECONDS
    """Cuánto tiene que llevar fallando, en segundos. Por defecto, cinco días."""
    min_failures: int = DEFAULT_HEALTH_MIN_FAILURES
    """Cuántos fallos hacen falta, como mínimo."""

    def __post_init__(self) -> None:
        # Se comprueba al configurarla, para no descubrir el error al despachar.
        positive_integer("window_seconds", self.window_seconds)
        positive_integer("min_failures", self.min_failures)


@dataclass(frozen=True, slots=True)
class EndpointHealth:
    status: Literal["healthy", "failing", "disabled"]
    reason: Literal["gone", "failing"] | None = None
    """Por qué conviene deshabilitarlo; `None` si no está `disabled`."""


class _Attempt(Protocol):
    @property
    def at(self) -> int: ...

    @property
    def delivery_class(self) -> str: ...


def summarize_failures(attempts: Iterable[_Attempt], since: int = 0) -> FailureSummary:
    """El resumen de fallos de un destino a partir de sus intentos, en el orden en que se registraron.

    Sólo cuentan los de `since` en adelante y posteriores a la última entrega.
    """
    failures, failing_since, gone = 0, None, False
    for attempt in attempts:
        if attempt.at < since:
            continue
        if attempt.delivery_class == "delivered":
            failures, failing_since, gone = 0, None, False
            continue
        failures += 1
        failing_since = attempt.at if failing_since is None else min(failing_since, attempt.at)
        gone = gone or attempt.delivery_class == "gone"
    return FailureSummary(failures, failing_since, gone)


def endpoint_health(summary: FailureSummary, now: int, policy: HealthPolicy | None = None) -> EndpointHealth:
    """La salud de un destino según su resumen de fallos."""
    policy = policy or HealthPolicy()
    if summary.gone:
        return EndpointHealth("disabled", "gone")
    if summary.failing_since is None or summary.failures == 0:
        return EndpointHealth("healthy")
    if summary.failures >= policy.min_failures and now - summary.failing_since >= policy.window_seconds:
        return EndpointHealth("disabled", "failing")
    return EndpointHealth("failing")
