import pg from 'pg';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ConfigurationError, PostgresIdempotencyStore, postgresStoreSchema } from '../../src/index';
import { describeIdempotencyStore } from '../contracts/idempotency-store';

const url = process.env.OMNIWEBHOOK_PG_URL;
if (url === undefined) {
  throw new Error(
    'Falta OMNIWEBHOOK_PG_URL: los tests de integración necesitan un PostgreSQL de prueba.',
  );
}

const TABLE = 'omniwebhook_events_test';
const pool = new pg.Pool({ connectionString: url });

beforeAll(async () => {
  await pool.query(`DROP TABLE IF EXISTS ${TABLE}`);
  await pool.query(postgresStoreSchema(TABLE));
});

afterAll(async () => {
  await pool.query(`DROP TABLE IF EXISTS ${TABLE}`);
  await pool.end();
});

async function emptyStore(): Promise<PostgresIdempotencyStore> {
  await pool.query(`TRUNCATE ${TABLE}`);
  return new PostgresIdempotencyStore(pool, { table: TABLE });
}

describeIdempotencyStore('PostgresIdempotencyStore', emptyStore);

describe('PostgresIdempotencyStore', () => {
  it('crear el esquema dos veces no falla', async () => {
    await expect(pool.query(postgresStoreSchema(TABLE))).resolves.toBeDefined();
  });

  it('entre pedidos simultáneos por la misma clave, uno solo la reserva', async () => {
    const store = await emptyStore();

    const results = await Promise.all(
      Array.from({ length: 20 }, (_, i) =>
        store.claim({ key: 'carrera', token: `t-${i}`, now: 1000, leaseSeconds: 60 }),
      ),
    );

    expect(results.filter((r) => r === 'claimed')).toHaveLength(1);
    expect(results.filter((r) => r === 'in_progress')).toHaveLength(19);
  });

  it('purgeExpired borra sólo lo vencido', async () => {
    const store = await emptyStore();
    await store.claim({ key: 'vieja', token: 'a', now: 1000, leaseSeconds: 10 });
    await store.claim({ key: 'vigente', token: 'a', now: 1000, leaseSeconds: 500 });

    expect(await store.purgeExpired(1010)).toBe(1);
    expect(await store.claim({ key: 'vigente', token: 'b', now: 1011, leaseSeconds: 10 })).toBe(
      'in_progress',
    );
  });

  it.each(['Eventos', 'a b', 'x; DROP TABLE y', ''])('rechaza el nombre de tabla «%s»', (table) => {
    expect(() => new PostgresIdempotencyStore(pool, { table })).toThrow(ConfigurationError);
    expect(() => postgresStoreSchema(table)).toThrow(ConfigurationError);
  });

  it('acepta una tabla con esquema', () => {
    expect(postgresStoreSchema('public.eventos')).toContain('public.eventos');
  });
});
