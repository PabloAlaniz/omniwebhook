"""Varios emisores en una misma URL (sección 4.7)."""

from collections.abc import Sequence
from dataclasses import dataclass

from omniwebhook.application.ports import Verifier
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.verification import Rejected, Verification


@dataclass(frozen=True, slots=True)
class VerifierRoute:
    """Un emisor de los que atiende una misma URL."""

    header: str
    """La cabecera que sólo manda este emisor: su presencia decide que el pedido es suyo."""
    verifier: Verifier


class _Routed:
    def __init__(self, routes: Sequence[VerifierRoute]) -> None:
        self._routes = [VerifierRoute(route.header.strip(), route.verifier) for route in routes]

    def verify(self, request: IncomingRequest) -> Verification:
        matching = [route for route in self._routes if field_values(request.headers, route.header)]
        if not matching:
            return Rejected("missing")
        if len(matching) > 1:
            return Rejected("ambiguous")
        return matching[0].verifier.verify(request)


def routed_verifier(routes: Sequence[VerifierRoute]) -> Verifier:
    """Atiende a varios emisores en una misma URL.

    El pedido se verifica con la única ruta cuya cabecera llegó: sin ninguna es `missing`
    y con más de una, `ambiguous`. Nunca prueba un esquema después de otro.
    """
    if not routes:
        raise ConfigurationError("routes no puede estar vacío")
    seen: set[str] = set()
    for route in routes:
        name = route.header.strip().lower() if isinstance(route.header, str) else ""
        if name == "":
            raise ConfigurationError("header no puede estar vacío")
        if name in seen:
            raise ConfigurationError(f"header está repetido entre rutas: {name}")
        seen.add(name)
    return _Routed(routes)
