"""Registro de entregas sobre PostgreSQL (sección 8.4).

Cada intento es una fila. La tabla es la misma que usa el paquete de TypeScript.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from omniwebhook.adapters.stores.postgres import AsyncSqlClient, Row, SqlClient, _checked_table
from omniwebhook.application.ports import AttemptRecord
from omniwebhook.domain.endpoint_health import FailureSummary

DEFAULT_LEDGER_TABLE: Final = "omniwebhook_attempts"

_COLUMNS: Final = (
    "message_id, endpoint_id, attempt, at, delivery_class, state, status, problem, duration_ms, next_at"
)


def postgres_ledger_schema(table: str = DEFAULT_LEDGER_TABLE) -> str:
    """El SQL que crea la tabla de intentos y sus índices.

    Son varias sentencias: se corre sin parámetros. Se puede correr más de una vez.
    """
    name = _checked_table(table)
    # Los índices viven en el esquema de su tabla: su nombre va sin esquema.
    bare = name.rpartition(".")[2]
    return f"""CREATE TABLE IF NOT EXISTS {name} (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id text NOT NULL,
  endpoint_id text NOT NULL,
  attempt integer NOT NULL,
  at bigint NOT NULL,
  delivery_class text NOT NULL,
  state text NOT NULL,
  status integer,
  problem text,
  duration_ms bigint NOT NULL,
  next_at bigint
);
CREATE INDEX IF NOT EXISTS {bare}_message_idx ON {name} (message_id, endpoint_id);
CREATE INDEX IF NOT EXISTS {bare}_endpoint_idx ON {name} (endpoint_id, at)"""


def failures_query(table: str, mark: str) -> str:
    """El resumen de fallos de un destino (sección 8.5), en una sola consulta.

    Los intentos desde `since` posteriores a la última entrega. Recibe el destino y `since`
    dos veces cada uno.
    """
    # El nombre de la tabla ya está comprobado; los valores van como parámetros.
    return (
        "SELECT COUNT(*), MIN(at), "  # noqa: S608
        "COALESCE(MAX(CASE WHEN delivery_class = 'gone' THEN 1 ELSE 0 END), 0) "
        f"FROM {table} WHERE endpoint_id = {mark} AND at >= {mark} "
        f"AND id > (SELECT COALESCE(MAX(id), 0) FROM {table} "
        f"WHERE endpoint_id = {mark} AND at >= {mark} AND delivery_class = 'delivered')"
    )


def failure_summary(rows: Sequence[Sequence[object]]) -> FailureSummary:
    failures, failing_since, gone = rows[0]
    return FailureSummary(
        failures=int(str(failures)),
        failing_since=None if failing_since is None else int(str(failing_since)),
        gone=int(str(gone)) == 1,
    )


@dataclass(frozen=True, slots=True)
class _Statements:
    """Las sentencias de cada operación. El nombre de la tabla ya está comprobado."""

    table: str

    @property
    def record(self) -> str:
        return (
            f"INSERT INTO {self.table} ({_COLUMNS}) "  # noqa: S608
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
        )

    @property
    def attempts_of(self) -> str:
        return (
            f"SELECT {_COLUMNS} FROM {self.table} "  # noqa: S608
            "WHERE message_id = %s AND endpoint_id = %s ORDER BY id"
        )

    @property
    def failures(self) -> str:
        return failures_query(self.table, "%s")

    @property
    def purge(self) -> str:
        return f"DELETE FROM {self.table} WHERE at < %s RETURNING id"  # noqa: S608


def _params(attempt: AttemptRecord) -> Sequence[object]:
    return (
        attempt.message_id,
        attempt.endpoint_id,
        attempt.attempt,
        attempt.at,
        attempt.delivery_class,
        attempt.state,
        attempt.status,
        attempt.problem,
        attempt.duration_ms,
        attempt.next_at,
    )


def _record(row: Row) -> AttemptRecord:
    values = cast("Sequence[Any]", row)
    return AttemptRecord(
        message_id=values[0],
        endpoint_id=values[1],
        attempt=int(values[2]),
        at=int(values[3]),
        delivery_class=values[4],
        state=values[5],
        status=None if values[6] is None else int(values[6]),
        problem=values[7],
        duration_ms=int(values[8]),
        next_at=None if values[9] is None else int(values[9]),
    )


class PostgresDeliveryLedger:
    def __init__(self, client: SqlClient, *, table: str = DEFAULT_LEDGER_TABLE) -> None:
        self._client = client
        self._sql = _Statements(_checked_table(table))

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


class AsyncPostgresDeliveryLedger:
    def __init__(self, client: AsyncSqlClient, *, table: str = DEFAULT_LEDGER_TABLE) -> None:
        self._client = client
        self._sql = _Statements(_checked_table(table))

    async def record(self, attempt: AttemptRecord) -> None:
        await self._client.query(self._sql.record, _params(attempt))

    async def attempts_of(self, message_id: str, endpoint_id: str) -> list[AttemptRecord]:
        """Los intentos de un mensaje hacia un destino, en el orden en que se registraron."""
        rows = await self._client.query(self._sql.attempts_of, (message_id, endpoint_id))
        return [_record(row) for row in rows]

    async def failures_of(self, endpoint_id: str, since: int) -> FailureSummary:
        params = (endpoint_id, since, endpoint_id, since)
        return failure_summary(await self._client.query(self._sql.failures, params))

    async def purge_before(self, at: int) -> int:
        """Borra los intentos que empezaron antes de `at` y devuelve cuántos eran."""
        return len(await self._client.query(self._sql.purge, (at,)))
