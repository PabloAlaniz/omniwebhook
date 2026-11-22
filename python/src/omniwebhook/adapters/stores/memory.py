"""Almacén de reservas en memoria.

Sirve para tests y para un único proceso: no comparte nada entre procesos ni sobrevive a
un reinicio.
"""

import threading
from dataclasses import dataclass
from typing import Literal

from omniwebhook.application.ports import ClaimRequest, CompleteRequest, ReleaseRequest
from omniwebhook.domain.reservation import ClaimOutcome


@dataclass(frozen=True, slots=True)
class _Entry:
    state: Literal["reserved", "completed"]
    token: str
    until: int


class MemoryIdempotencyStore:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def claim(self, request: ClaimRequest) -> ClaimOutcome:
        with self._lock:
            entry = self._entries.get(request.key)
            if entry is not None and request.now < entry.until:
                return "in_progress" if entry.state == "reserved" else "duplicate"
            self._entries[request.key] = _Entry(
                "reserved", request.token, request.now + request.lease_seconds
            )
            return "claimed"

    def complete(self, request: CompleteRequest) -> bool:
        with self._lock:
            if not self._reserved_by(request.key, request.token):
                return False
            self._entries[request.key] = _Entry(
                "completed", request.token, request.now + request.retention_seconds
            )
            return True

    def release(self, request: ReleaseRequest) -> bool:
        with self._lock:
            if not self._reserved_by(request.key, request.token):
                return False
            del self._entries[request.key]
            return True

    def _reserved_by(self, key: str, token: str) -> bool:
        entry = self._entries.get(key)
        return entry is not None and entry.state == "reserved" and entry.token == token


class AsyncMemoryIdempotencyStore:
    """El mismo almacén para código asincrónico. Ninguna operación espera, así que no bloquea."""

    def __init__(self) -> None:
        self._store = MemoryIdempotencyStore()

    async def claim(self, request: ClaimRequest) -> ClaimOutcome:
        return self._store.claim(request)

    async def complete(self, request: CompleteRequest) -> bool:
        return self._store.complete(request)

    async def release(self, request: ReleaseRequest) -> bool:
        return self._store.release(request)
