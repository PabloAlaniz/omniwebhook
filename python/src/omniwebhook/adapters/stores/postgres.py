"""Almacén de reservas sobre PostgreSQL.

Cada operación es una sola sentencia, así que es atómica sin transacciones explícitas y
sirve con varios procesos a la vez.
"""

import re
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import Any, Final, Protocol

from omniwebhook.application.ports import ClaimRequest, CompleteRequest, ReleaseRequest
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.reservation import ClaimOutcome

Row = Sequence[object]


class SqlClient(Protocol):
    """Lo mínimo que hace falta de un cliente de PostgreSQL.

    Ejecuta una sentencia con parámetros `%s`, la confirma y devuelve las filas.
    """

    def query(self, text: str, params: Sequence[object]) -> Sequence[Row]: ...


class AsyncSqlClient(Protocol):
    """La variante asincrónica de `SqlClient`."""

    async def query(self, text: str, params: Sequence[object]) -> Sequence[Row]: ...


_IDENTIFIER: Final = re.compile(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?")
DEFAULT_TABLE: Final = "omniwebhook_events"


def _checked_table(table: str) -> str:
    if not isinstance(table, str) or _IDENTIFIER.fullmatch(table) is None:
        raise ConfigurationError("table tiene que ser un identificador en minúsculas, con esquema opcional")
    return table


def postgres_store_schema(table: str = DEFAULT_TABLE) -> str:
    """El SQL que crea la tabla de reservas. Se puede correr más de una vez."""
    return f"""CREATE TABLE IF NOT EXISTS {_checked_table(table)} (
  key text PRIMARY KEY,
  state text NOT NULL CHECK (state IN ('reserved', 'completed')),
  token text NOT NULL,
  expires_at bigint NOT NULL
)"""


@dataclass(frozen=True, slots=True)
class _Statements:
    """Las sentencias de cada operación. El nombre de la tabla ya está comprobado."""

    table: str

    @property
    def claim(self) -> str:
        return (
            f"INSERT INTO {self.table} AS e (key, state, token, expires_at) "  # noqa: S608
            "VALUES (%s, 'reserved', %s, %s) "
            "ON CONFLICT (key) DO UPDATE "
            "SET state = 'reserved', token = EXCLUDED.token, expires_at = EXCLUDED.expires_at "
            "WHERE e.expires_at <= %s "
            "RETURNING key"
        )

    @property
    def state(self) -> str:
        return f"SELECT state FROM {self.table} WHERE key = %s"  # noqa: S608

    @property
    def complete(self) -> str:
        return (
            f"UPDATE {self.table} SET state = 'completed', expires_at = %s "  # noqa: S608
            "WHERE key = %s AND token = %s AND state = 'reserved' RETURNING key"
        )

    @property
    def release(self) -> str:
        return f"DELETE FROM {self.table} WHERE key = %s AND token = %s AND state = 'reserved' RETURNING key"  # noqa: S608

    @property
    def purge(self) -> str:
        return f"DELETE FROM {self.table} WHERE expires_at <= %s RETURNING key"  # noqa: S608


def _claim_params(request: ClaimRequest) -> Sequence[object]:
    return (request.key, request.token, request.now + request.lease_seconds, request.now)


def _complete_params(request: CompleteRequest) -> Sequence[object]:
    return (request.now + request.retention_seconds, request.key, request.token)


def _not_claimed(rows: Sequence[Row]) -> ClaimOutcome:
    # Sin fila: quien la tenía la liberó recién. Para quien pregunta, seguía en curso.
    return "duplicate" if rows and rows[0][0] == "completed" else "in_progress"


class PostgresIdempotencyStore:
    def __init__(self, client: SqlClient, *, table: str = DEFAULT_TABLE) -> None:
        self._client = client
        self._sql = _Statements(_checked_table(table))

    def claim(self, request: ClaimRequest) -> ClaimOutcome:
        if self._client.query(self._sql.claim, _claim_params(request)):
            return "claimed"
        return _not_claimed(self._client.query(self._sql.state, (request.key,)))

    def complete(self, request: CompleteRequest) -> bool:
        return bool(self._client.query(self._sql.complete, _complete_params(request)))

    def release(self, request: ReleaseRequest) -> bool:
        return bool(self._client.query(self._sql.release, (request.key, request.token)))

    def purge_expired(self, now: int) -> int:
        """Borra las entradas vencidas y devuelve cuántas eran. Conviene correrlo cada tanto."""
        return len(self._client.query(self._sql.purge, (now,)))


class AsyncPostgresIdempotencyStore:
    def __init__(self, client: AsyncSqlClient, *, table: str = DEFAULT_TABLE) -> None:
        self._client = client
        self._sql = _Statements(_checked_table(table))

    async def claim(self, request: ClaimRequest) -> ClaimOutcome:
        if await self._client.query(self._sql.claim, _claim_params(request)):
            return "claimed"
        return _not_claimed(await self._client.query(self._sql.state, (request.key,)))

    async def complete(self, request: CompleteRequest) -> bool:
        return bool(await self._client.query(self._sql.complete, _complete_params(request)))

    async def release(self, request: ReleaseRequest) -> bool:
        return bool(await self._client.query(self._sql.release, (request.key, request.token)))

    async def purge_expired(self, now: int) -> int:
        """Borra las entradas vencidas y devuelve cuántas eran. Conviene correrlo cada tanto."""
        return len(await self._client.query(self._sql.purge, (now,)))


class _Cursor(Protocol):
    def fetchall(self) -> Sequence[Any]: ...


class _Connection(Protocol):
    def execute(self, query: Any, params: Any) -> _Cursor: ...


class _AsyncCursor(Protocol):
    async def fetchall(self) -> Sequence[Any]: ...


class _AsyncConnection(Protocol):
    async def execute(self, query: Any, params: Any) -> _AsyncCursor: ...


class PsycopgClient:
    """Adapta psycopg 3 sin importarlo.

    Recibe una función que entrega una conexión como administrador de contexto y confirma
    al salir, como `pool.connection` de un pool de conexiones.
    """

    def __init__(self, connection: Callable[[], AbstractContextManager[_Connection]]) -> None:
        self._connection = connection

    def query(self, text: str, params: Sequence[object]) -> Sequence[Row]:
        with self._connection() as connection:
            return connection.execute(text, params).fetchall()


class AsyncPsycopgClient:
    """La variante asincrónica de `PsycopgClient`, para un pool asincrónico."""

    def __init__(self, connection: Callable[[], AbstractAsyncContextManager[_AsyncConnection]]) -> None:
        self._connection = connection

    async def query(self, text: str, params: Sequence[object]) -> Sequence[Row]:
        async with self._connection() as connection:
            cursor = await connection.execute(text, params)
            return await cursor.fetchall()
