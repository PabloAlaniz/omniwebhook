import pg from 'pg';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  type AttemptRecord,
  ConfigurationError,
  PostgresDeliveryLedger,
  postgresLedgerSchema,
} from '../../src/index';

const url = process.env.OMNIWEBHOOK_PG_URL;
if (url === undefined) {
  throw new Error(
    'Falta OMNIWEBHOOK_PG_URL: los tests de integración necesitan un PostgreSQL de prueba.',
  );
}

const TABLE = 'omniwebhook_attempts_test';
const pool = new pg.Pool({ connectionString: url });

const PENDING: AttemptRecord = {
  messageId: 'msg_1',
  endpointId: 'ep_1',
  attempt: 1,
  at: 1_700_000_000,
  deliveryClass: 'retryable',
  state: 'pending',
  status: 503,
  problem: null,
  durationMs: 40,
  nextAt: 1_700_000_005,
};
const BLOCKED: AttemptRecord = {
  ...PENDING,
  attempt: 2,
  at: 1_700_000_005,
  deliveryClass: 'blocked',
  state: 'blocked',
  status: null,
  problem: 'blocked_address',
  durationMs: 0,
  nextAt: null,
};

beforeAll(async () => {
  await pool.query(`DROP TABLE IF EXISTS ${TABLE}`);
  await pool.query(postgresLedgerSchema(TABLE));
});

afterAll(async () => {
  await pool.query(`DROP TABLE IF EXISTS ${TABLE}`);
  await pool.end();
});

async function emptyLedger(): Promise<PostgresDeliveryLedger> {
  await pool.query(`TRUNCATE ${TABLE}`);
  return new PostgresDeliveryLedger(pool, { table: TABLE });
}

describe('PostgresDeliveryLedger', () => {
  it('guarda cada intento y los devuelve tal cual, en orden', async () => {
    const ledger = await emptyLedger();

    await ledger.record(PENDING);
    await ledger.record(BLOCKED);
    await ledger.record({ ...PENDING, endpointId: 'ep_2' });

    expect(await ledger.attemptsOf('msg_1', 'ep_1')).toEqual([PENDING, BLOCKED]);
  });

  it('un reenvío repite el número de intento sin chocar', async () => {
    const ledger = await emptyLedger();

    await ledger.record(PENDING);
    await ledger.record({ ...PENDING, at: PENDING.at + 60, state: 'delivered', nextAt: null });

    expect(await ledger.attemptsOf('msg_1', 'ep_1')).toHaveLength(2);
  });

  it('purgeBefore borra sólo los intentos anteriores', async () => {
    const ledger = await emptyLedger();
    await ledger.record(PENDING);
    await ledger.record(BLOCKED);

    expect(await ledger.purgeBefore(BLOCKED.at)).toBe(1);
    expect(await ledger.attemptsOf('msg_1', 'ep_1')).toEqual([BLOCKED]);
  });

  it('crear el esquema dos veces no falla', async () => {
    await expect(pool.query(postgresLedgerSchema(TABLE))).resolves.toBeDefined();
  });

  it('con esquema, los índices van sin esquema en el nombre', () => {
    const sql = postgresLedgerSchema('public.intentos');

    expect(sql).toContain('CREATE TABLE IF NOT EXISTS public.intentos');
    expect(sql).toContain('intentos_message_idx ON public.intentos');
  });

  it.each(['Intentos', 'a b', 'x; DROP TABLE y', ''])(
    'rechaza el nombre de tabla «%s»',
    (table) => {
      expect(() => new PostgresDeliveryLedger(pool, { table })).toThrow(ConfigurationError);
      expect(() => postgresLedgerSchema(table)).toThrow(ConfigurationError);
    },
  );
});
