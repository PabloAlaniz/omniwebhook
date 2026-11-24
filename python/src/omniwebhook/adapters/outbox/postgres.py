"""Bandeja de salida sobre PostgreSQL.

Cada operación es una sola sentencia, así que es atómica y sirve con varios procesos a la
vez. La tabla es la misma que usa el paquete de TypeScript.

Para encolar en la misma transacción que el cambio que origina el mensaje, se la construye
con `PsycopgConnectionClient(conexion)`: si la transacción no se confirma, el mensaje no
existe.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from omniwebhook.adapters.outbox.memory import checked_settle
from omniwebhook.adapters.stores.postgres import AsyncSqlClient, Row, SqlClient, _checked_table
from omniwebhook.application.ports import (
    EnqueueRequest,
    OutboxClaimRequest,
    OutboxEntry,
    RequeueRequest,
    SettleRequest,
)

DEFAULT_OUTBOX_TABLE: Final = "omniwebhook_outbox"


def postgres_outbox_schema(table: str = DEFAULT_OUTBOX_TABLE) -> str:
    """El SQL que crea la tabla de la bandeja y su índice (sección 8.5). Se puede correr más de una vez."""
    name = _checked_table(table)
    bare = name.rsplit(".", 1)[-1]
    return f"""CREATE TABLE IF NOT EXISTS {name} (
  seq bigint GENERATED ALWAYS AS IDENTITY,
  message_id text NOT NULL,
  endpoint_id text NOT NULL,
  payload bytea NOT NULL,
  attempt integer NOT NULL DEFAULT 1,
  available_at bigint NOT NULL,
  state text NOT NULL DEFAULT 'pending',
  token text,
  lease_expires_at bigint,
  PRIMARY KEY (message_id, endpoint_id)
);
CREATE INDEX IF NOT EXISTS {bare}_due_idx ON {name} (state, available_at)"""


@dataclass(frozen=True, slots=True)
class _Statements:
    """Las sentencias de cada operación. El nombre de la tabla ya está comprobado."""

    table: str

    @property
    def enqueue(self) -> str:
        return (
            f"INSERT INTO {self.table} (message_id, endpoint_id, payload, available_at) "  # noqa: S608
            "VALUES (%s, %s, %s, %s) ON CONFLICT (message_id, endpoint_id) DO NOTHING RETURNING seq"
        )

    @property
    def claim(self) -> str:
        # SKIP LOCKED: dos procesos que piden a la vez se reparten las filas en vez de esperarse.
        return (
            f"UPDATE {self.table} SET token = %s, lease_expires_at = %s "  # noqa: S608
            "WHERE (message_id, endpoint_id) IN ("
            f"SELECT message_id, endpoint_id FROM {self.table} "
            "WHERE state = 'pending' AND available_at <= %s "
            "AND (lease_expires_at IS NULL OR lease_expires_at <= %s) "
            "ORDER BY available_at, seq LIMIT %s FOR UPDATE SKIP LOCKED) "
            "RETURNING message_id, endpoint_id, payload, attempt, available_at, seq"
        )

    @property
    def _mine(self) -> str:
        return "WHERE message_id = %s AND endpoint_id = %s AND token = %s AND state = 'pending' RETURNING seq"

    @property
    def retry(self) -> str:
        return (
            f"UPDATE {self.table} SET attempt = attempt + 1, available_at = %s, "  # noqa: S608
            f"token = NULL, lease_expires_at = NULL {self._mine}"
        )

    @property
    def close(self) -> str:
        return f"UPDATE {self.table} SET state = %s, token = NULL, lease_expires_at = NULL {self._mine}"  # noqa: S608

    @property
    def requeue(self) -> str:
        return (
            f"UPDATE {self.table} SET state = 'pending', attempt = 1, available_at = %s, "  # noqa: S608
            "token = NULL, lease_expires_at = NULL "
            "WHERE endpoint_id = %s AND state NOT IN ('pending', 'delivered') "
            "AND available_at BETWEEN %s AND %s RETURNING seq"
        )

    @property
    def purge(self) -> str:
        return f"DELETE FROM {self.table} WHERE state <> 'pending' AND available_at < %s RETURNING seq"  # noqa: S608


def _enqueue_params(request: EnqueueRequest) -> Sequence[object]:
    return (request.message_id, request.endpoint_id, bytes(request.payload), request.now)


def _claim_params(request: OutboxClaimRequest) -> Sequence[object]:
    return (request.token, request.now + request.lease_seconds, request.now, request.now, request.limit)


def _requeue_params(request: RequeueRequest) -> Sequence[object]:
    return (request.now, request.endpoint_id, request.since, request.until)


def _entries(rows: Sequence[Row]) -> list[OutboxEntry]:
    # RETURNING no garantiza el orden de la subconsulta.
    ordered = sorted(rows, key=lambda row: (int(str(row[4])), int(str(row[5]))))
    return [
        OutboxEntry(
            message_id=str(row[0]),
            endpoint_id=str(row[1]),
            payload=bytes(row[2]),  # type: ignore[call-overload]
            attempt=int(str(row[3])),
        )
        for row in ordered
    ]


def _settle(statements: _Statements, request: SettleRequest) -> tuple[str, Sequence[object]]:
    checked_settle(request)
    pair = (request.message_id, request.endpoint_id, request.token)
    if request.state == "pending":
        return statements.retry, (request.next_at, *pair)
    return statements.close, (request.state, *pair)


class PostgresOutbox:
    """La bandeja sobre PostgreSQL, sincrónica."""

    def __init__(self, client: SqlClient, *, table: str = DEFAULT_OUTBOX_TABLE) -> None:
        self._client = client
        self._statements = _Statements(_checked_table(table))

    def enqueue(self, request: EnqueueRequest) -> bool:
        return bool(self._client.query(self._statements.enqueue, _enqueue_params(request)))

    def claim(self, request: OutboxClaimRequest) -> list[OutboxEntry]:
        return _entries(self._client.query(self._statements.claim, _claim_params(request)))

    def settle(self, request: SettleRequest) -> bool:
        return bool(self._client.query(*_settle(self._statements, request)))

    def requeue(self, request: RequeueRequest) -> int:
        return len(self._client.query(self._statements.requeue, _requeue_params(request)))

    def purge_settled_before(self, at: int) -> int:
        """Borra las entradas cerradas que estaban disponibles desde antes de `at`. Devuelve cuántas eran."""
        return len(self._client.query(self._statements.purge, (at,)))


class AsyncPostgresOutbox:
    """La bandeja sobre PostgreSQL, asincrónica."""

    def __init__(self, client: AsyncSqlClient, *, table: str = DEFAULT_OUTBOX_TABLE) -> None:
        self._client = client
        self._statements = _Statements(_checked_table(table))

    async def enqueue(self, request: EnqueueRequest) -> bool:
        return bool(await self._client.query(self._statements.enqueue, _enqueue_params(request)))

    async def claim(self, request: OutboxClaimRequest) -> list[OutboxEntry]:
        return _entries(await self._client.query(self._statements.claim, _claim_params(request)))

    async def settle(self, request: SettleRequest) -> bool:
        return bool(await self._client.query(*_settle(self._statements, request)))

    async def requeue(self, request: RequeueRequest) -> int:
        return len(await self._client.query(self._statements.requeue, _requeue_params(request)))

    async def purge_settled_before(self, at: int) -> int:
        return len(await self._client.query(self._statements.purge, (at,)))


class _Cursor(Protocol):
    def fetchall(self) -> Sequence[Any]: ...


class _Connection(Protocol):
    def execute(self, query: Any, params: Any) -> _Cursor: ...


class _AsyncCursor(Protocol):
    async def fetchall(self) -> Sequence[Any]: ...


class _AsyncConnection(Protocol):
    async def execute(self, query: Any, params: Any) -> _AsyncCursor: ...


class PsycopgConnectionClient:
    """Un cliente sobre una conexión de psycopg ya abierta, que no confirma nada.

    Sirve para encolar dentro de una transacción: confirmar o deshacer queda en manos de
    quien abrió la conexión.
    """

    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def query(self, text: str, params: Sequence[object]) -> Sequence[Row]:
        return self._connection.execute(text, params).fetchall()


class AsyncPsycopgConnectionClient:
    """Lo mismo, sobre una conexión asincrónica."""

    def __init__(self, connection: _AsyncConnection) -> None:
        self._connection = connection

    async def query(self, text: str, params: Sequence[object]) -> Sequence[Row]:
        cursor = await self._connection.execute(text, params)
        return await cursor.fetchall()
