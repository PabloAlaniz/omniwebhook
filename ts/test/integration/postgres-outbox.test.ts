import pg from 'pg';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ConfigurationError, PostgresOutbox, postgresOutboxSchema } from '../../src/index';
import { describeOutbox } from '../contracts/outbox';

const url = process.env.OMNIWEBHOOK_PG_URL;
if (url === undefined) {
  throw new Error(
    'Falta OMNIWEBHOOK_PG_URL: los tests de integración necesitan un PostgreSQL de prueba.',
  );
}

const TABLE = 'omniwebhook_outbox_test';
const NOW = 1_700_000_000;
const pool = new pg.Pool({ connectionString: url });
const payload = new TextEncoder().encode('{"n":1}');

beforeAll(async () => {
  await pool.query(`DROP TABLE IF EXISTS ${TABLE}`);
  await pool.query(postgresOutboxSchema(TABLE));
});

afterAll(async () => {
  await pool.query(`DROP TABLE IF EXISTS ${TABLE}`);
  await pool.end();
});

async function emptyOutbox(): Promise<PostgresOutbox> {
  await pool.query(`TRUNCATE ${TABLE} RESTART IDENTITY`);
  return new PostgresOutbox(pool, { table: TABLE });
}

describeOutbox('PostgresOutbox', emptyOutbox);

describe('PostgresOutbox', () => {
  it('crear el esquema dos veces no falla', async () => {
    await expect(pool.query(postgresOutboxSchema(TABLE))).resolves.toBeDefined();
  });

  it('entre tomas simultáneas, cada entrega la toma un solo proceso', async () => {
    const outbox = await emptyOutbox();
    for (let index = 0; index < 50; index++) {
      await outbox.enqueue({ messageId: `msg_${index}`, endpointId: 'ep_1', payload, now: NOW });
    }

    const batches = await Promise.all(
      Array.from({ length: 20 }, (_, index) =>
        outbox.claim({ token: `d-${index}`, now: NOW, limit: 5, leaseSeconds: 300 }),
      ),
    );

    const taken = batches.flat().map((entry) => entry.messageId);
    expect(new Set(taken).size).toBe(taken.length);
    expect(taken.length).toBeGreaterThan(0);
    // Lo que una tanda no alcanzó a ver por estar bloqueado queda para la siguiente.
    const rest = await outbox.claim({ token: 'd-final', now: NOW, limit: 100, leaseSeconds: 300 });
    expect(taken.length + rest.length).toBe(50);
  });

  it('lo encolado en una transacción que se deshace no existe', async () => {
    const outbox = await emptyOutbox();
    const connection = await pool.connect();
    try {
      await connection.query('BEGIN');
      const inTransaction = new PostgresOutbox(connection, { table: TABLE });
      await inTransaction.enqueue({ messageId: 'msg_1', endpointId: 'ep_1', payload, now: NOW });
      await connection.query('ROLLBACK');
    } finally {
      connection.release();
    }

    expect(await outbox.claim({ token: 'd-1', now: NOW, limit: 10, leaseSeconds: 300 })).toEqual(
      [],
    );
  });

  it('lo encolado en una transacción confirmada sale, con el payload byte a byte', async () => {
    const outbox = await emptyOutbox();
    const bytes = Uint8Array.from([0, 255, 10, 13, 128]);
    const connection = await pool.connect();
    try {
      await connection.query('BEGIN');
      await new PostgresOutbox(connection, { table: TABLE }).enqueue({
        messageId: 'msg_1',
        endpointId: 'ep_1',
        payload: bytes,
        now: NOW,
      });
      await connection.query('COMMIT');
    } finally {
      connection.release();
    }

    const [entry] = await outbox.claim({ token: 'd-1', now: NOW, limit: 10, leaseSeconds: 300 });
    expect(entry).toEqual({ messageId: 'msg_1', endpointId: 'ep_1', payload: bytes, attempt: 1 });
  });

  it('purga sólo las entregas cerradas y viejas', async () => {
    const outbox = await emptyOutbox();
    await outbox.enqueue({ messageId: 'cerrada', endpointId: 'ep_1', payload, now: NOW });
    await outbox.enqueue({ messageId: 'pendiente', endpointId: 'ep_1', payload, now: NOW });
    await outbox.claim({ token: 'd-1', now: NOW, limit: 1, leaseSeconds: 300 });
    await outbox.settle({
      messageId: 'cerrada',
      endpointId: 'ep_1',
      token: 'd-1',
      state: 'delivered',
    });

    expect(await outbox.purgeSettledBefore(NOW)).toBe(0);
    expect(await outbox.purgeSettledBefore(NOW + 1)).toBe(1);
    const rest = await outbox.claim({ token: 'd-2', now: NOW, limit: 10, leaseSeconds: 300 });
    expect(rest.map((entry) => entry.messageId)).toEqual(['pendiente']);
  });

  it('rechaza un nombre de tabla que no es un identificador', () => {
    expect(() => new PostgresOutbox(pool, { table: 'x; DROP TABLE y' })).toThrow(
      ConfigurationError,
    );
    expect(() => postgresOutboxSchema('X')).toThrow(ConfigurationError);
  });
});
