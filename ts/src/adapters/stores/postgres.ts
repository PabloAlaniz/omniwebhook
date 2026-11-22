import type {
  ClaimRequest,
  CompleteRequest,
  IdempotencyStore,
  ReleaseRequest,
} from '../../application/ports';
import { ConfigurationError } from '../../domain/errors';
import type { ClaimOutcome } from '../../domain/reservation';

/**
 * Lo mínimo que hace falta de un cliente de PostgreSQL: ejecutar una consulta con
 * parámetros `$1, $2…` y devolver las filas. Lo cumplen los clientes habituales.
 */
export interface SqlClient {
  query(text: string, params: unknown[]): Promise<{ readonly rows: readonly unknown[] }>;
}

export interface PostgresStoreOptions {
  /** La tabla de reservas, con esquema opcional. Por defecto, `omniwebhook_events`. */
  readonly table?: string;
}

const IDENTIFIER = /^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$/;
const DEFAULT_TABLE = 'omniwebhook_events';

function checkedTable(table: string): string {
  if (!IDENTIFIER.test(table)) {
    throw new ConfigurationError(
      'table tiene que ser un identificador en minúsculas, con esquema opcional',
    );
  }
  return table;
}

/** El SQL que crea la tabla de reservas. Se puede correr más de una vez. */
export function postgresStoreSchema(table: string = DEFAULT_TABLE): string {
  const name = checkedTable(table);
  return `CREATE TABLE IF NOT EXISTS ${name} (
  key text PRIMARY KEY,
  state text NOT NULL CHECK (state IN ('reserved', 'completed')),
  token text NOT NULL,
  expires_at bigint NOT NULL
)`;
}

/**
 * Almacén de reservas sobre PostgreSQL. Cada operación es una sola sentencia, así que
 * es atómica sin transacciones explícitas y sirve con varios procesos a la vez.
 */
export class PostgresIdempotencyStore implements IdempotencyStore {
  private readonly table: string;

  constructor(
    private readonly client: SqlClient,
    options: PostgresStoreOptions = {},
  ) {
    this.table = checkedTable(options.table ?? DEFAULT_TABLE);
  }

  async claim({ key, token, now, leaseSeconds }: ClaimRequest): Promise<ClaimOutcome> {
    const taken = await this.client.query(
      `INSERT INTO ${this.table} AS e (key, state, token, expires_at)
       VALUES ($1, 'reserved', $2, $3)
       ON CONFLICT (key) DO UPDATE
         SET state = 'reserved', token = EXCLUDED.token, expires_at = EXCLUDED.expires_at
         WHERE e.expires_at <= $4
       RETURNING key`,
      [key, token, now + leaseSeconds, now],
    );
    if (taken.rows.length > 0) return 'claimed';

    const current = await this.client.query(`SELECT state FROM ${this.table} WHERE key = $1`, [
      key,
    ]);
    const row = current.rows[0] as { state?: unknown } | undefined;
    // Sin fila: quien la tenía la liberó recién. Para quien pregunta, seguía en curso.
    return row?.state === 'completed' ? 'duplicate' : 'in_progress';
  }

  async complete({ key, token, now, retentionSeconds }: CompleteRequest): Promise<boolean> {
    const result = await this.client.query(
      `UPDATE ${this.table} SET state = 'completed', expires_at = $3
       WHERE key = $1 AND token = $2 AND state = 'reserved'
       RETURNING key`,
      [key, token, now + retentionSeconds],
    );
    return result.rows.length > 0;
  }

  async release({ key, token }: ReleaseRequest): Promise<boolean> {
    const result = await this.client.query(
      `DELETE FROM ${this.table} WHERE key = $1 AND token = $2 AND state = 'reserved' RETURNING key`,
      [key, token],
    );
    return result.rows.length > 0;
  }

  /** Borra las entradas vencidas y devuelve cuántas eran. Conviene correrlo cada tanto. */
  async purgeExpired(now: number): Promise<number> {
    const result = await this.client.query(
      `DELETE FROM ${this.table} WHERE expires_at <= $1 RETURNING key`,
      [now],
    );
    return result.rows.length;
  }
}
