"""La política de URLs de destino (sección 8.1)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from omniwebhook.domain.ip_address import is_blocked_address, is_ip_address

UrlProblem = Literal["invalid_url", "scheme", "credentials"]
AddressProblem = Literal["unresolved", "blocked_address"]
DestinationProblem = UrlProblem | AddressProblem
"""Por qué la política rechazó un destino, en el orden en que se revisa."""
DestinationVerdict = Literal["allowed"] | DestinationProblem


@dataclass(frozen=True, slots=True)
class InspectedDestination:
    """Un destino cuya URL pasó la revisión. Falta revisar las direcciones a las que se conecta."""

    host: str
    literal_address: str | None
    """La dirección, si el host es una IP literal; `None` si es un nombre que hay que resolver."""


def inspect_destination(url: str, *, allow_http: bool = False) -> InspectedDestination | UrlProblem:
    """Revisa lo que se puede saber de la URL sola: forma, esquema y credenciales."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port
    except ValueError:
        return "invalid_url"
    if not host:
        return "invalid_url"

    if parts.scheme != "https" and not (parts.scheme == "http" and allow_http):
        return "scheme"
    if parts.username or parts.password:
        return "credentials"

    return InspectedDestination(host=host, literal_address=host if is_ip_address(host) else None)


@dataclass(frozen=True, slots=True)
class SelectedAddress:
    address: str


def select_address(addresses: Sequence[str]) -> SelectedAddress | AddressProblem:
    """Elige la dirección a la que conectarse.

    Tiene que haber alguna y ninguna puede estar bloqueada. Devuelve la primera.
    """
    if not addresses:
        return "unresolved"
    if any(is_blocked_address(address) for address in addresses):
        return "blocked_address"
    return SelectedAddress(addresses[0])


def evaluate_destination(
    url: str, *, allow_http: bool = False, resolved: Sequence[str]
) -> DestinationVerdict:
    """La política completa, dadas las direcciones a las que resolvió el nombre."""
    inspected = inspect_destination(url, allow_http=allow_http)
    if isinstance(inspected, str):
        return inspected
    addresses = resolved if inspected.literal_address is None else [inspected.literal_address]
    selected = select_address(addresses)
    return selected if isinstance(selected, str) else "allowed"
