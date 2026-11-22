"""Direcciones IP a las que nunca se entrega (sección 8.1).

El análisis es propio, y no el de la biblioteca estándar, para que la misma cadena dé el
mismo resultado en todos los paquetes.
"""

import re
from dataclasses import dataclass
from typing import Final

_DECIMAL_OCTET: Final = re.compile(r"0|[1-9][0-9]{0,2}")
_HEX_GROUP: Final = re.compile(r"[0-9a-fA-F]{1,4}")

_Address = tuple[int, ...]
"""Una dirección IP como bytes: 4 para IPv4, 16 para IPv6."""


def _parse_ipv4(text: str) -> _Address | None:
    parts = text.split(".")
    if len(parts) != 4 or any(_DECIMAL_OCTET.fullmatch(part) is None for part in parts):
        return None
    octets = tuple(int(part) for part in parts)
    return octets if all(octet <= 255 for octet in octets) else None


def _parse_groups(text: str) -> list[int] | None:
    """Los grupos de 16 bits de un tramo como `2001:db8` o `ffff:10.0.0.1`."""
    if text == "":
        return []
    parts = text.split(":")
    groups: list[int] = []
    for index, part in enumerate(parts):
        if "." in part:
            # Una IPv4 embebida sólo puede ir al final y ocupa dos grupos.
            ipv4 = _parse_ipv4(part) if index == len(parts) - 1 else None
            if ipv4 is None:
                return None
            groups += [(ipv4[0] << 8) | ipv4[1], (ipv4[2] << 8) | ipv4[3]]
        elif _HEX_GROUP.fullmatch(part) is None:
            return None
        else:
            groups.append(int(part, 16))
    return groups


def _parse_ipv6(text: str) -> _Address | None:
    halves = text.split("::")
    if len(halves) > 2:
        return None
    compressed = len(halves) == 2

    head = _parse_groups(halves[0])
    tail = _parse_groups(halves[1]) if compressed else []
    if head is None or tail is None:
        return None
    # Una IPv4 embebida tiene que quedar en los últimos 32 bits.
    if compressed and "." in halves[0]:
        return None

    present = len(head) + len(tail)
    if present > 7 if compressed else present != 8:
        return None

    groups = [*head, *([0] * (8 - present)), *tail]
    return tuple(byte for group in groups for byte in (group >> 8, group & 0xFF))


def _parse_address(text: str) -> _Address | None:
    return _parse_ipv6(text) if ":" in text else _parse_ipv4(text)


@dataclass(frozen=True, slots=True)
class _Network:
    address: _Address
    prefix: int

    def contains(self, address: _Address) -> bool:
        if len(address) != len(self.address):
            return False
        bits = len(address) * 8
        shift = bits - self.prefix
        return _as_int(address) >> shift == _as_int(self.address) >> shift


def _as_int(address: _Address) -> int:
    value = 0
    for byte in address:
        value = (value << 8) | byte
    return value


def _network(cidr: str) -> _Network:
    text, _, prefix = cidr.partition("/")
    address = _parse_address(text)
    if address is None:
        raise ValueError(f"rango inválido: {cidr}")
    return _Network(address, int(prefix))


_BLOCKED: Final = tuple(
    _network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "64:ff9b::/96",
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)

_IPV4_MAPPED: Final = _network("::ffff:0:0/96")


def is_ip_address(text: str) -> bool:
    """Si el texto es una dirección IP literal."""
    return _parse_address(text) is not None


def is_blocked_address(text: str) -> bool:
    """Si no se puede entregar a esta dirección.

    Está bloqueada si cae en un rango bloqueado o si no es una dirección IP. Una IPv6 que
    envuelve una IPv4 se evalúa por la IPv4 que contiene.
    """
    parsed = _parse_address(text)
    if parsed is None:
        return True
    address = parsed[12:] if _IPV4_MAPPED.contains(parsed) else parsed
    return any(network.contains(address) for network in _BLOCKED)
