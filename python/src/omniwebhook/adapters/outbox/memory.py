"""Bandeja de salida en memoria, para tests y desarrollo. No sirve con más de un proceso."""

import threading
from dataclasses import dataclass

from omniwebhook.application.ports import (
    EnqueueRequest,
    OutboxClaimRequest,
    OutboxEntry,
    OutboxState,
    RequeueRequest,
    SettleRequest,
)
from omniwebhook.domain.errors import ConfigurationError


@dataclass(slots=True)
class _Row:
    message_id: str
    endpoint_id: str
    payload: bytes
    seq: int
    available_at: int
    attempt: int = 1
    state: OutboxState = "pending"
    token: str | None = None
    lease_expires_at: int | None = None


def checked_settle(request: SettleRequest) -> None:
    """Un cierre como pendiente tiene que decir desde cuándo vuelve a estar disponible."""
    if request.state == "pending" and request.next_at is None:
        raise ConfigurationError("next_at es obligatorio para cerrar una entrega como pendiente")


class MemoryOutbox:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], _Row] = {}
        self._lock = threading.Lock()

    def enqueue(self, request: EnqueueRequest) -> bool:
        pair = (request.message_id, request.endpoint_id)
        with self._lock:
            if pair in self._rows:
                return False
            self._rows[pair] = _Row(*pair, bytes(request.payload), len(self._rows), request.now)
            return True

    def claim(self, request: OutboxClaimRequest) -> list[OutboxEntry]:
        now = request.now
        with self._lock:
            due = [
                row
                for row in self._rows.values()
                if row.state == "pending"
                and row.available_at <= now
                and (row.lease_expires_at is None or row.lease_expires_at <= now)
            ]
            due.sort(key=lambda row: (row.available_at, row.seq))
            taken = due[: request.limit]
            for row in taken:
                row.token, row.lease_expires_at = request.token, now + request.lease_seconds
            return [
                OutboxEntry(
                    message_id=row.message_id,
                    endpoint_id=row.endpoint_id,
                    payload=row.payload,
                    attempt=row.attempt,
                )
                for row in taken
            ]

    def settle(self, request: SettleRequest) -> bool:
        checked_settle(request)
        with self._lock:
            row = self._rows.get((request.message_id, request.endpoint_id))
            if row is None or row.state != "pending" or row.token != request.token:
                return False
            if request.next_at is not None and request.state == "pending":
                row.attempt += 1
                row.available_at = request.next_at
            else:
                row.state = request.state
            row.token, row.lease_expires_at = None, None
            return True

    def requeue(self, request: RequeueRequest) -> int:
        with self._lock:
            again = [
                row
                for row in self._rows.values()
                if row.endpoint_id == request.endpoint_id
                and row.state not in ("pending", "delivered")
                and request.since <= row.available_at <= request.until
            ]
            for row in again:
                row.state, row.attempt, row.available_at = "pending", 1, request.now
                row.token, row.lease_expires_at = None, None
            return len(again)

    def state_of(self, message_id: str, endpoint_id: str) -> OutboxState | None:
        """El estado de una entrada, para comprobarlo en tests."""
        row = self._rows.get((message_id, endpoint_id))
        return None if row is None else row.state


class AsyncMemoryOutbox:
    """La bandeja en memoria, asincrónica."""

    def __init__(self) -> None:
        self._outbox = MemoryOutbox()

    async def enqueue(self, request: EnqueueRequest) -> bool:
        return self._outbox.enqueue(request)

    async def claim(self, request: OutboxClaimRequest) -> list[OutboxEntry]:
        return self._outbox.claim(request)

    async def settle(self, request: SettleRequest) -> bool:
        return self._outbox.settle(request)

    async def requeue(self, request: RequeueRequest) -> int:
        return self._outbox.requeue(request)

    def state_of(self, message_id: str, endpoint_id: str) -> OutboxState | None:
        return self._outbox.state_of(message_id, endpoint_id)
