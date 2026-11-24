import type {
  EnqueueRequest,
  Outbox,
  OutboxClaimRequest,
  OutboxEntry,
  RequeueRequest,
  SettleRequest,
} from '../../application/ports';
import { checkedTable, type SqlClient } from '../stores/postgres';

export interface PostgresOutboxOptions {
  /** La tabla de la bandeja, con esquema opcional. Por defecto, `omniwebhook_outbox`. */
  readonly table?: string;
}

const DEFAULT_TABLE = 'omniwebhook_outbox';

/** El SQL que crea la tabla de la bandeja y su índice (sección 8.5). Se puede correr más de una vez. */
export function postgresOutboxSchema(table: string = DEFAULT_TABLE): string {
  const name = checkedTable(table);
  const bare = name.split('.').pop();
  return `CREATE TABLE IF NOT EXISTS ${name} (
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
CREATE INDEX IF NOT EXISTS ${bare}_due_idx ON ${name} (state, available_at)`;
}

interface ClaimedRow {
  readonly message_id: string;
  readonly endpoint_id: string;
  readonly payload: Uint8Array;
  readonly attempt: number;
  readonly available_at: string | number;
  readonly seq: string | number;
}

/**
 * Bandeja de salida sobre PostgreSQL. Cada operación es una sola sentencia, así que es atómica
 * y sirve con varios procesos a la vez; la tabla es la misma que usa el paquete de Python.
 *
 * Para encolar en la misma transacción que el cambio que origina el mensaje, se la construye
 * con el cliente de esa transacción: si la transacción no se confirma, el mensaje no existe.
 */
export class PostgresOutbox implements Outbox {
  private readonly table: string;

  constructor(
    private readonly client: SqlClient,
    options: PostgresOutboxOptions = {},
  ) {
    this.table = checkedTable(options.table ?? DEFAULT_TABLE);
  }

  async enqueue({ messageId, endpointId, payload, now }: EnqueueRequest): Promise<boolean> {
    const result = await this.client.query(
      `INSERT INTO ${this.table} (message_id, endpoint_id, payload, available_at)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (message_id, endpoint_id) DO NOTHING
       RETURNING seq`,
      [messageId, endpointId, Buffer.from(payload), now],
    );
    return result.rows.length > 0;
  }

  async claim({ token, now, limit, leaseSeconds }: OutboxClaimRequest): Promise<OutboxEntry[]> {
    // SKIP LOCKED: dos procesos que piden a la vez se reparten las filas en vez de esperarse.
    const result = await this.client.query(
      `UPDATE ${this.table} SET token = $1, lease_expires_at = $2
       WHERE (message_id, endpoint_id) IN (
         SELECT message_id, endpoint_id FROM ${this.table}
         WHERE state = 'pending' AND available_at <= $3
           AND (lease_expires_at IS NULL OR lease_expires_at <= $3)
         ORDER BY available_at, seq
         LIMIT $4
         FOR UPDATE SKIP LOCKED
       )
       RETURNING message_id, endpoint_id, payload, attempt, available_at, seq`,
      [token, now + leaseSeconds, now, limit],
    );
    // RETURNING no garantiza el orden de la subconsulta.
    return (result.rows as ClaimedRow[])
      .map((row) => ({ row, at: Number(row.available_at), seq: Number(row.seq) }))
      .sort((a, b) => a.at - b.at || a.seq - b.seq)
      .map(({ row }) => ({
        messageId: row.message_id,
        endpointId: row.endpoint_id,
        payload: Uint8Array.from(row.payload),
        attempt: row.attempt,
      }));
  }

  async settle(request: SettleRequest): Promise<boolean> {
    const { messageId, endpointId, token } = request;
    const mine = `WHERE message_id = $1 AND endpoint_id = $2 AND token = $3 AND state = 'pending'`;
    const result =
      request.state === 'pending'
        ? await this.client.query(
            `UPDATE ${this.table}
             SET attempt = attempt + 1, available_at = $4, token = NULL, lease_expires_at = NULL
             ${mine} RETURNING seq`,
            [messageId, endpointId, token, request.nextAt],
          )
        : await this.client.query(
            `UPDATE ${this.table} SET state = $4, token = NULL, lease_expires_at = NULL
             ${mine} RETURNING seq`,
            [messageId, endpointId, token, request.state],
          );
    return result.rows.length > 0;
  }

  async requeue({ endpointId, from, to, now }: RequeueRequest): Promise<number> {
    const result = await this.client.query(
      `UPDATE ${this.table}
       SET state = 'pending', attempt = 1, available_at = $4, token = NULL, lease_expires_at = NULL
       WHERE endpoint_id = $1 AND state NOT IN ('pending', 'delivered')
         AND available_at BETWEEN $2 AND $3
       RETURNING seq`,
      [endpointId, from, to, now],
    );
    return result.rows.length;
  }

  /** Borra las entradas cerradas que estaban disponibles desde antes de `at`. Devuelve cuántas eran. */
  async purgeSettledBefore(at: number): Promise<number> {
    const result = await this.client.query(
      `DELETE FROM ${this.table} WHERE state <> 'pending' AND available_at < $1 RETURNING seq`,
      [at],
    );
    return result.rows.length;
  }
}
