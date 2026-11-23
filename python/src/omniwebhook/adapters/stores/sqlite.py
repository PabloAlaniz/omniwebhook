"""Almacén de reservas sobre SQLite.

Cada operación es una sola sentencia, así que es atómica sin transacciones explícitas. La
tabla tiene la misma forma que la del paquete de TypeScript, que la usa también sobre D1.

Sólo hay variante sincrónica: el módulo `sqlite3` de la biblioteca estándar no es
asincrónico. Desde código asincrónico, conviene correrlo en un hilo (`asyncio.to_thread`).
"""

import re
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from omniwebhook.adapters.stores.postgres import Row, _claim_params, _complete_params, _not_claimed
from omniwebhook.application.ports import ClaimRequest, CompleteRequest, ReleaseRequest
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.reservation import ClaimOutcome


class SqliteClient(Protocol):
    """Lo mínimo que hace falta de una base SQLite.

    Ejecuta una sentencia con parámetros `?`, la confirma y devuelve las filas.
    """

    def query(self, text: str, params: Sequence[object]) -> Sequence[Row]: ...


class Sqlite3Client:
    """Adapta una conexión de `sqlite3`.

    Confirma cada sentencia y las ejecuta de a una, así una misma conexión se puede usar
    desde varios hilos si se abrió con `check_same_thread=False`.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = threading.Lock()

    def query(self, text: str, params: Sequence[object]) -> Sequence[Row]:
        with self._lock:
            rows = self._connection.execute(text, params).fetchall()
            self._connection.commit()
            return rows


_IDENTIFIER: Final = re.compile(r"[a-z_][a-z0-9_]*")
DEFAULT_TABLE: Final = "omniwebhook_events"


def _checked_sqlite_table(table: str) -> str:
    if not isinstance(table, str) or _IDENTIFIER.fullmatch(table) is None:
        raise ConfigurationError("table tiene que ser un identificador en minúsculas")
    return table


def sqlite_store_schema(table: str = DEFAULT_TABLE) -> str:
    """El SQL que crea la tabla de reservas. Se puede correr más de una vez."""
    return f"""CREATE TABLE IF NOT EXISTS {_checked_sqlite_table(table)} (
  key TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ('reserved', 'completed')),
  token TEXT NOT NULL,
  expires_at INTEGER NOT NULL
) WITHOUT ROWID"""


@dataclass(frozen=True, slots=True)
class _Statements:
    """Las sentencias de cada operación. El nombre de la tabla ya está comprobado."""

    table: str

    @property
    def claim(self) -> str:
        return (
            f"INSERT INTO {self.table} AS e (key, state, token, expires_at) "  # noqa: S608
            "VALUES (?, 'reserved', ?, ?) "
            "ON CONFLICT (key) DO UPDATE "
            "SET state = 'reserved', token = excluded.token, expires_at = excluded.expires_at "
            "WHERE e.expires_at <= ? "
            "RETURNING key"
        )

    @property
    def state(self) -> str:
        return f"SELECT state FROM {self.table} WHERE key = ?"  # noqa: S608

    @property
    def complete(self) -> str:
        return (
            f"UPDATE {self.table} SET state = 'completed', expires_at = ? "  # noqa: S608
            "WHERE key = ? AND token = ? AND state = 'reserved' RETURNING key"
        )

    @property
    def release(self) -> str:
        return f"DELETE FROM {self.table} WHERE key = ? AND token = ? AND state = 'reserved' RETURNING key"  # noqa: S608

    @property
    def purge(self) -> str:
        return f"DELETE FROM {self.table} WHERE expires_at <= ? RETURNING key"  # noqa: S608


class SqliteIdempotencyStore:
    def __init__(self, client: SqliteClient, *, table: str = DEFAULT_TABLE) -> None:
        self._client = client
        self._sql = _Statements(_checked_sqlite_table(table))

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
