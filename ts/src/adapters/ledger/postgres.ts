import type { AttemptRecord, DeliveryLedger, EndpointFailureSource } from '../../application/ports';
import type { FailureSummary } from '../../domain/endpoint-health';
import { checkedTable, type SqlClient } from '../stores/postgres';
import {
  attemptParams,
  LEDGER_COLUMNS as COLUMNS,
  failuresQuery,
  type LedgerRow,
  toAttemptRecord,
  toFailureSummary,
} from './rows';

export interface PostgresLedgerOptions {
  /** La tabla de intentos, con esquema opcional. Por defecto, `omniwebhook_attempts`. */
  readonly table?: string;
}

const DEFAULT_TABLE = 'omniwebhook_attempts';

/** El nombre de la tabla sin el esquema: los índices viven en el esquema de su tabla. */
function bareName(table: string): string {
  return table.slice(table.indexOf('.') + 1);
}

/**
 * El SQL que crea la tabla de intentos y sus índices (sección 8.4). Son varias sentencias:
 * se corre sin parámetros. Se puede correr más de una vez.
 */
export function postgresLedgerSchema(table: string = DEFAULT_TABLE): string {
  const name = checkedTable(table);
  const bare = bareName(name);
  return `CREATE TABLE IF NOT EXISTS ${name} (
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
CREATE INDEX IF NOT EXISTS ${bare}_message_idx ON ${name} (message_id, endpoint_id);
CREATE INDEX IF NOT EXISTS ${bare}_endpoint_idx ON ${name} (endpoint_id, at)`;
}

/**
 * Registro de entregas sobre PostgreSQL. Cada intento es una fila; la tabla es la misma que
 * usa el paquete de Python.
 */
export class PostgresDeliveryLedger implements DeliveryLedger, EndpointFailureSource {
  private readonly table: string;

  constructor(
    private readonly client: SqlClient,
    options: PostgresLedgerOptions = {},
  ) {
    this.table = checkedTable(options.table ?? DEFAULT_TABLE);
  }

  async record(attempt: AttemptRecord): Promise<void> {
    await this.client.query(
      `INSERT INTO ${this.table} (${COLUMNS}) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id`,
      attemptParams(attempt),
    );
  }

  /** Los intentos de un mensaje hacia un destino, en el orden en que se registraron. */
  async attemptsOf(messageId: string, endpointId: string): Promise<readonly AttemptRecord[]> {
    const result = await this.client.query(
      `SELECT ${COLUMNS} FROM ${this.table} WHERE message_id = $1 AND endpoint_id = $2 ORDER BY id`,
      [messageId, endpointId],
    );
    return result.rows.map((row) => toAttemptRecord(row as LedgerRow));
  }

  /** El resumen de fallos de un destino desde `since` (sección 8.5). */
  async failuresOf(endpointId: string, since: number): Promise<FailureSummary> {
    const result = await this.client.query(failuresQuery(this.table, ['$1', '$1'], ['$2', '$2']), [
      endpointId,
      since,
    ]);
    return toFailureSummary(result.rows[0]);
  }

  /** Borra los intentos que empezaron antes de `at` y devuelve cuántos eran. */
  async purgeBefore(at: number): Promise<number> {
    const result = await this.client.query(`DELETE FROM ${this.table} WHERE at < $1 RETURNING id`, [
      at,
    ]);
    return result.rows.length;
  }
}
