import type { AttemptRecord, DeliveryLedger, EndpointFailureSource } from '../../application/ports';
import type { FailureSummary } from '../../domain/endpoint-health';
import { checkedSqliteTable, type SqliteClient } from '../stores/sqlite';
import {
  attemptParams,
  failuresQuery,
  LEDGER_COLUMNS,
  type LedgerRow,
  toAttemptRecord,
  toFailureSummary,
} from './rows';

export interface SqliteLedgerOptions {
  /** La tabla de intentos. Por defecto, `omniwebhook_attempts`. */
  readonly table?: string;
}

const DEFAULT_TABLE = 'omniwebhook_attempts';

/**
 * El SQL que crea la tabla de intentos y sus índices (sección 8.4). Son varias sentencias:
 * se corre como un script o en una migración. Se puede correr más de una vez.
 */
export function sqliteLedgerSchema(table: string = DEFAULT_TABLE): string {
  const name = checkedSqliteTable(table);
  return `CREATE TABLE IF NOT EXISTS ${name} (
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
CREATE INDEX IF NOT EXISTS ${name}_message_idx ON ${name} (message_id, endpoint_id);
CREATE INDEX IF NOT EXISTS ${name}_endpoint_idx ON ${name} (endpoint_id, at)`;
}

/**
 * Registro de entregas sobre SQLite: D1, `node:sqlite`, `better-sqlite3`, libSQL… Cada
 * intento es una fila; la tabla tiene la misma forma que la del paquete de Python.
 */
export class SqliteDeliveryLedger implements DeliveryLedger, EndpointFailureSource {
  private readonly table: string;

  constructor(
    private readonly client: SqliteClient,
    options: SqliteLedgerOptions = {},
  ) {
    this.table = checkedSqliteTable(options.table ?? DEFAULT_TABLE);
  }

  async record(attempt: AttemptRecord): Promise<void> {
    await this.client.all(
      `INSERT INTO ${this.table} (${LEDGER_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`,
      attemptParams(attempt),
    );
  }

  /** Los intentos de un mensaje hacia un destino, en el orden en que se registraron. */
  async attemptsOf(messageId: string, endpointId: string): Promise<readonly AttemptRecord[]> {
    const rows = await this.client.all(
      `SELECT ${LEDGER_COLUMNS} FROM ${this.table} WHERE message_id = ? AND endpoint_id = ? ORDER BY id`,
      [messageId, endpointId],
    );
    return rows.map((row) => toAttemptRecord(row as LedgerRow));
  }

  /** El resumen de fallos de un destino desde `since` (sección 8.5). */
  async failuresOf(endpointId: string, since: number): Promise<FailureSummary> {
    const rows = await this.client.all(failuresQuery(this.table, ['?', '?'], ['?', '?']), [
      endpointId,
      since,
      endpointId,
      since,
    ]);
    return toFailureSummary(rows[0]);
  }

  /** Borra los intentos que empezaron antes de `at` y devuelve cuántos eran. */
  async purgeBefore(at: number): Promise<number> {
    const rows = await this.client.all(`DELETE FROM ${this.table} WHERE at < ? RETURNING id`, [at]);
    return rows.length;
  }
}
