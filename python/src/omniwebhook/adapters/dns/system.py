"""Resuelve nombres con el sistema operativo. Un nombre que no existe da una lista vacía."""

import asyncio
import socket
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final

AddressInfo = Sequence[tuple[Any, Any, Any, str, tuple[Any, ...]]]
"""Lo que devuelve `socket.getaddrinfo`."""

_NOT_FOUND: Final = frozenset(
    code for code in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", None)) if code is not None
)


def _addresses(found: AddressInfo) -> list[str]:
    return list(dict.fromkeys(str(entry[4][0]) for entry in found))


def _system_lookup(host: str) -> AddressInfo:
    return socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)


async def _async_system_lookup(host: str) -> AddressInfo:
    return await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)


class SystemDnsResolver:
    def __init__(self, *, lookup: Callable[[str], AddressInfo] = _system_lookup) -> None:
        self._lookup = lookup

    def resolve(self, host: str) -> list[str]:
        try:
            return _addresses(self._lookup(host))
        except socket.gaierror as error:
            if error.errno in _NOT_FOUND:
                return []
            raise


class AsyncSystemDnsResolver:
    def __init__(self, *, lookup: Callable[[str], Awaitable[AddressInfo]] = _async_system_lookup) -> None:
        self._lookup = lookup

    async def resolve(self, host: str) -> list[str]:
        try:
            return _addresses(await self._lookup(host))
        except socket.gaierror as error:
            if error.errno in _NOT_FOUND:
                return []
            raise
