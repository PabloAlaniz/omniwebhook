import type {
  ClaimRequest,
  CompleteRequest,
  IdempotencyStore,
  ReleaseRequest,
} from '../../application/ports';
import { ConfigurationError } from '../../domain/errors';
import type { ClaimOutcome } from '../../domain/reservation';

/**
 * Lo mínimo que hace falta de una base SQLite: ejecutar una sentencia con parámetros `?` y
 * devolver las filas como objetos. Cada llamada tiene que quedar confirmada al volver.
 * `d1Client` y `sqliteClient` adaptan los clientes habituales.
 */
export interface SqliteClient {
  all(sql: string, params: readonly unknown[]): Promise<readonly unknown[]>;
}

/** Lo que se usa de una base D1 de Cloudflare. No depende de sus tipos. */
export interface D1Like {
  prepare(sql: string): {
    bind(...values: unknown[]): { all(): Promise<{ readonly results: readonly unknown[] }> };
  };
}

/** Adapta una base D1 (el binding de un Worker). */
export function d1Client(db: D1Like): SqliteClient {
  return {
    async all(sql, params) {
      const { results } = await db
        .prepare(sql)
        .bind(...params)
        .all();
      return results;
    },
  };
}

/**
 * Lo que se usa de una base SQLite sincrónica con sentencias preparadas: `node:sqlite`,
 * `better-sqlite3` y `bun:sqlite` lo cumplen.
 */
export interface PreparedSqlite {
  prepare(sql: string): { all(...params: never[]): unknown[] };
}

/** Adapta una base SQLite sincrónica (`node:sqlite`, `better-sqlite3`, `bun:sqlite`). */
export function sqliteClient(db: PreparedSqlite): SqliteClient {
  return {
    async all(sql, params) {
      const statement = db.prepare(sql) as { all(...values: unknown[]): unknown[] };
      return statement.all(...params);
    },
  };
}

export interface SqliteStoreOptions {
  /** La tabla de reservas. Por defecto, `omniwebhook_events`. */
  readonly table?: string;
}

const IDENTIFIER = /^[a-z_][a-z0-9_]*$/;
const DEFAULT_TABLE = 'omniwebhook_events';

export function checkedSqliteTable(table: string): string {
  if (!IDENTIFIER.test(table)) {
    throw new ConfigurationError('table tiene que ser un identificador en minúsculas');
  }
  return table;
}

/** El SQL que crea la tabla de reservas. Se puede correr más de una vez. */
export function sqliteStoreSchema(table: string = DEFAULT_TABLE): string {
  const name = checkedSqliteTable(table);
  return `CREATE TABLE IF NOT EXISTS ${name} (
  key TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ('reserved', 'completed')),
  token TEXT NOT NULL,
  expires_at INTEGER NOT NULL
) WITHOUT ROWID`;
}

/**
 * Almacén de reservas sobre SQLite: D1, `node:sqlite`, `better-sqlite3`, libSQL… Cada
 * operación es una sola sentencia, así que es atómica sin transacciones explícitas. La
 * tabla tiene la misma forma que la del paquete de Python.
 */
export class SqliteIdempotencyStore implements IdempotencyStore {
  private readonly table: string;

  constructor(
    private readonly client: SqliteClient,
    options: SqliteStoreOptions = {},
  ) {
    this.table = checkedSqliteTable(options.table ?? DEFAULT_TABLE);
  }

  async claim({ key, token, now, leaseSeconds }: ClaimRequest): Promise<ClaimOutcome> {
    const taken = await this.client.all(
      `INSERT INTO ${this.table} AS e (key, state, token, expires_at)
       VALUES (?, 'reserved', ?, ?)
       ON CONFLICT (key) DO UPDATE
         SET state = 'reserved', token = excluded.token, expires_at = excluded.expires_at
         WHERE e.expires_at <= ?
       RETURNING key`,
      [key, token, now + leaseSeconds, now],
    );
    if (taken.length > 0) return 'claimed';

    const current = await this.client.all(`SELECT state FROM ${this.table} WHERE key = ?`, [key]);
    const row = current[0] as { state?: unknown } | undefined;
    // Sin fila: quien la tenía la liberó recién. Para quien pregunta, seguía en curso.
    return row?.state === 'completed' ? 'duplicate' : 'in_progress';
  }

  async complete({ key, token, now, retentionSeconds }: CompleteRequest): Promise<boolean> {
    const rows = await this.client.all(
      `UPDATE ${this.table} SET state = 'completed', expires_at = ?
       WHERE key = ? AND token = ? AND state = 'reserved'
       RETURNING key`,
      [now + retentionSeconds, key, token],
    );
    return rows.length > 0;
  }

  async release({ key, token }: ReleaseRequest): Promise<boolean> {
    const rows = await this.client.all(
      `DELETE FROM ${this.table} WHERE key = ? AND token = ? AND state = 'reserved' RETURNING key`,
      [key, token],
    );
    return rows.length > 0;
  }

  /** Borra las entradas vencidas y devuelve cuántas eran. Conviene correrlo cada tanto. */
  async purgeExpired(now: number): Promise<number> {
    const rows = await this.client.all(
      `DELETE FROM ${this.table} WHERE expires_at <= ? RETURNING key`,
      [now],
    );
    return rows.length;
  }
}
