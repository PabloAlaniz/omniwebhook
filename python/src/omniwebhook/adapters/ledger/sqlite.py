"""Registro de entregas sobre SQLite (sección 8.4).

Cada intento es una fila. La tabla tiene la misma forma que la del paquete de TypeScript.
Sólo hay variante sincrónica, como el almacén de reservas sobre SQLite.
"""

from dataclasses import dataclass
from typing import Final

from omniwebhook.adapters.ledger.postgres import (
    _COLUMNS,
    _params,
    _record,
    failure_summary,
    failures_query,
)
from omniwebhook.adapters.stores.sqlite import SqliteClient, _checked_sqlite_table
from omniwebhook.application.ports import AttemptRecord
from omniwebhook.domain.endpoint_health import FailureSummary

DEFAULT_LEDGER_TABLE: Final = "omniwebhook_attempts"


def sqlite_ledger_schema(table: str = DEFAULT_LEDGER_TABLE) -> str:
    """El SQL que crea la tabla de intentos y sus índices.

    Son varias sentencias: se corre con `executescript` o en una migración. Se puede correr
    más de una vez.
    """
    name = _checked_sqlite_table(table)
    return f"""CREATE TABLE IF NOT EXISTS {name} (
  id INTEGER PRIMARY KEY,
  message_id TEXT NOT NULL,
  endpoint_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  at INTEGER NOT NULL,
  delivery_class TEXT NOT NULL,
  state TEXT NOT NULL,
  status INTEGER,
  problem TEXT,
  duration_ms INTEGER NOT NULL,
  next_at INTEGER
);
CREATE INDEX IF NOT EXISTS {name}_message_idx ON {name} (message_id, endpoint_id);
CREATE INDEX IF NOT EXISTS {name}_endpoint_idx ON {name} (endpoint_id, at)"""


@dataclass(frozen=True, slots=True)
class _Statements:
    """Las sentencias de cada operación. El nombre de la tabla ya está comprobado."""

    table: str

    @property
    def record(self) -> str:
        return (
            f"INSERT INTO {self.table} ({_COLUMNS}) "  # noqa: S608
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id"
        )

    @property
    def attempts_of(self) -> str:
        return (
            f"SELECT {_COLUMNS} FROM {self.table} "  # noqa: S608
            "WHERE message_id = ? AND endpoint_id = ? ORDER BY id"
        )

    @property
    def failures(self) -> str:
        return failures_query(self.table, "?")

    @property
    def purge(self) -> str:
        return f"DELETE FROM {self.table} WHERE at < ? RETURNING id"  # noqa: S608


class SqliteDeliveryLedger:
    def __init__(self, client: SqliteClient, *, table: str = DEFAULT_LEDGER_TABLE) -> None:
        self._client = client
        self._sql = _Statements(_checked_sqlite_table(table))

    def record(self, attempt: AttemptRecord) -> None:
        self._client.query(self._sql.record, _params(attempt))

    def attempts_of(self, message_id: str, endpoint_id: str) -> list[AttemptRecord]:
        """Los intentos de un mensaje hacia un destino, en el orden en que se registraron."""
        return [_record(row) for row in self._client.query(self._sql.attempts_of, (message_id, endpoint_id))]

    def failures_of(self, endpoint_id: str, since: int) -> FailureSummary:
        """El resumen de fallos de un destino desde `since` (sección 8.5)."""
        return failure_summary(
            self._client.query(self._sql.failures, (endpoint_id, since, endpoint_id, since))
        )

    def purge_before(self, at: int) -> int:
        """Borra los intentos que empezaron antes de `at` y devuelve cuántos eran."""
        return len(self._client.query(self._sql.purge, (at,)))
