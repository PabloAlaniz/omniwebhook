"""La política de URLs de destino (sección 8.1).

La forma de la URL se comprueba acá, carácter por carácter, antes de que la vea el
analizador de URLs de la plataforma: los analizadores no coinciden entre sí ante una URL
rara, y esa diferencia es lo que aprovecha quien quiere llegar a una dirección interna.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from omniwebhook.domain.ip_address import AllowedNetworks, is_blocked_address, is_ip_address
from omniwebhook.domain.ip_address import allowed_networks as _allowed_networks

UrlProblem = Literal["invalid_url", "scheme", "credentials"]
AddressProblem = Literal["unresolved", "blocked_address"]
DestinationProblem = UrlProblem | AddressProblem
"""Por qué la política rechazó un destino, en el orden en que se revisa."""
DestinationVerdict = Literal["allowed"] | DestinationProblem

_FORBIDDEN: Final = re.compile(r"[\x00-\x20\x7f\\]")
_SCHEME: Final = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*):")
_AUTHORITY: Final = re.compile(r"//([^/?#]*)(?:[/?#]|$)")
_LABEL: Final = re.compile(r"[A-Za-z0-9_-]{1,63}")
_NUMERIC_LABEL: Final = re.compile(r"[0-9]+|0[xX][0-9A-Fa-f]*")
_PORT: Final = re.compile(r"[0-9]{1,5}")
_MAX_NAME_LENGTH: Final = 253
_MAX_PORT: Final = 65_535


@dataclass(frozen=True, slots=True)
class InspectedDestination:
    """Un destino cuya URL pasó la revisión. Falta revisar las direcciones a las que se conecta."""

    host: str
    """El host en minúsculas; una IPv6 literal va sin corchetes."""
    literal_address: str | None
    """La dirección, si el host es una IP literal; `None` si es un nombre que hay que resolver."""


def _valid_port(port: str | None) -> bool:
    return port is None or (_PORT.fullmatch(port) is not None and int(port) <= _MAX_PORT)


def _bracketed(hostport: str) -> InspectedDestination | None:
    """Una IPv6 literal entre corchetes, con puerto opcional."""
    inner, closing, after = hostport[1:].partition("]")
    port = after[1:] if after.startswith(":") else None
    if not closing or (after and port is None) or not _valid_port(port):
        return None
    if ":" not in inner or not is_ip_address(inner):
        return None
    address = inner.lower()
    return InspectedDestination(host=address, literal_address=address)


def _named(hostport: str) -> InspectedDestination | None:
    """Una IPv4 literal o un nombre, con puerto opcional."""
    name, colon, after = hostport.partition(":")
    if not _valid_port(after if colon else None) or len(name) > _MAX_NAME_LENGTH:
        return None
    labels = name.removesuffix(".").split(".")
    if any(_LABEL.fullmatch(label) is None for label in labels):
        return None
    if is_ip_address(name):
        return InspectedDestination(host=name, literal_address=name)
    # Hay analizadores que leen como dirección un nombre que termina en un número.
    if _NUMERIC_LABEL.fullmatch(labels[-1]) is not None:
        return None
    return InspectedDestination(host=name.lower(), literal_address=None)


def inspect_destination(url: str, *, allow_http: bool = False) -> InspectedDestination | UrlProblem:
    """Revisa lo que se puede saber de la URL sola: forma, esquema y credenciales."""
    scheme = _SCHEME.match(url)
    if scheme is None or _FORBIDDEN.search(url) is not None:
        return "invalid_url"
    name = scheme.group(1).lower()
    if name != "https" and not (name == "http" and allow_http):
        return "scheme"

    authority = _AUTHORITY.match(url, scheme.end())
    if authority is None:
        return "invalid_url"
    _, at, hostport = authority.group(1).rpartition("@")
    inspected = _bracketed(hostport) if hostport.startswith("[") else _named(hostport)
    if inspected is None:
        return "invalid_url"
    return "credentials" if at else inspected


@dataclass(frozen=True, slots=True)
class SelectedAddress:
    address: str


def select_address(
    addresses: Sequence[str], allowed: AllowedNetworks | None = None
) -> SelectedAddress | AddressProblem:
    """Elige la dirección a la que conectarse.

    Tiene que haber alguna y ninguna puede estar bloqueada. Devuelve la primera.
    """
    if not addresses:
        return "unresolved"
    if any(is_blocked_address(address, allowed) for address in addresses):
        return "blocked_address"
    return SelectedAddress(addresses[0])


def evaluate_destination(
    url: str,
    *,
    allow_http: bool = False,
    allowed_networks: Sequence[str] = (),
    resolved: Sequence[str],
) -> DestinationVerdict:
    """La política completa, dadas las direcciones a las que resolvió el nombre.

    Lanza `ConfigurationError` si alguna red permitida no tiene la forma de la sección 8.1.
    """
    allowed = _allowed_networks(allowed_networks)
    inspected = inspect_destination(url, allow_http=allow_http)
    if isinstance(inspected, str):
        return inspected
    addresses = resolved if inspected.literal_address is None else [inspected.literal_address]
    selected = select_address(addresses, allowed)
    return selected if isinstance(selected, str) else "allowed"
