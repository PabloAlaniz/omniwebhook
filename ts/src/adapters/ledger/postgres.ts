import type { AttemptRecord, DeliveryLedger } from '../../application/ports';
import { checkedTable, type SqlClient } from '../stores/postgres';

export interface PostgresLedgerOptions {
  /** La tabla de intentos, con esquema opcional. Por defecto, `omniwebhook_attempts`. */
  readonly table?: string;
}

const DEFAULT_TABLE = 'omniwebhook_attempts';

const COLUMNS =
  'message_id, endpoint_id, attempt, at, delivery_class, state, status, problem, duration_ms, next_at';

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

interface Row {
  readonly message_id: string;
  readonly endpoint_id: string;
  readonly attempt: number;
  readonly at: string | number;
  readonly delivery_class: AttemptRecord['deliveryClass'];
  readonly state: AttemptRecord['state'];
  readonly status: number | null;
  readonly problem: AttemptRecord['problem'];
  readonly duration_ms: string | number;
  readonly next_at: string | number | null;
}

// Los clientes devuelven `bigint` como texto para no perder precisión. Los valores de acá
// (segundos y milisegundos) entran en un número.
function toRecord(row: Row): AttemptRecord {
  return {
    messageId: row.message_id,
    endpointId: row.endpoint_id,
    attempt: Number(row.attempt),
    at: Number(row.at),
    deliveryClass: row.delivery_class,
    state: row.state,
    status: row.status === null ? null : Number(row.status),
    problem: row.problem,
    durationMs: Number(row.duration_ms),
    nextAt: row.next_at === null ? null : Number(row.next_at),
  };
}

/**
 * Registro de entregas sobre PostgreSQL. Cada intento es una fila; la tabla es la misma que
 * usa el paquete de Python.
 */
export class PostgresDeliveryLedger implements DeliveryLedger {
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
      [
        attempt.messageId,
        attempt.endpointId,
        attempt.attempt,
        attempt.at,
        attempt.deliveryClass,
        attempt.state,
        attempt.status,
        attempt.problem,
        attempt.durationMs,
        attempt.nextAt,
      ],
    );
  }

  /** Los intentos de un mensaje hacia un destino, en el orden en que se registraron. */
  async attemptsOf(messageId: string, endpointId: string): Promise<readonly AttemptRecord[]> {
    const result = await this.client.query(
      `SELECT ${COLUMNS} FROM ${this.table} WHERE message_id = $1 AND endpoint_id = $2 ORDER BY id`,
      [messageId, endpointId],
    );
    return result.rows.map((row) => toRecord(row as Row));
  }

  /** Borra los intentos que empezaron antes de `at` y devuelve cuántos eran. */
  async purgeBefore(at: number): Promise<number> {
    const result = await this.client.query(`DELETE FROM ${this.table} WHERE at < $1 RETURNING id`, [
      at,
    ]);
    return result.rows.length;
  }
}
