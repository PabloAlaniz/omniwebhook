import { DatabaseSync } from 'node:sqlite';
import { describe, expect, it } from 'vitest';
import {
  ConfigurationError,
  type D1Like,
  d1Client,
  SqliteIdempotencyStore,
  sqliteClient,
  sqliteStoreSchema,
} from '../../src/index';
import { describeIdempotencyStore } from '../contracts/idempotency-store';

function database(): DatabaseSync {
  const db = new DatabaseSync(':memory:');
  db.exec(sqliteStoreSchema());
  return db;
}

/** Una base D1 de mentira sobre `node:sqlite`, con la misma forma que el binding. */
function fakeD1(db: DatabaseSync): D1Like {
  return {
    prepare: (sql) => ({
      bind: (...values) => ({
        all: async () => ({ results: db.prepare(sql).all(...(values as never[])) }),
      }),
    }),
  };
}

describeIdempotencyStore(
  'SqliteIdempotencyStore',
  () => new SqliteIdempotencyStore(sqliteClient(database())),
);

describeIdempotencyStore(
  'SqliteIdempotencyStore sobre D1',
  () => new SqliteIdempotencyStore(d1Client(fakeD1(database()))),
);

describe('SqliteIdempotencyStore', () => {
  it('crear el esquema dos veces no falla', () => {
    const db = database();
    expect(() => db.exec(sqliteStoreSchema())).not.toThrow();
  });

  it('usa la tabla indicada', async () => {
    const db = new DatabaseSync(':memory:');
    db.exec(sqliteStoreSchema('reservas'));
    const store = new SqliteIdempotencyStore(sqliteClient(db), { table: 'reservas' });

    await store.claim({ key: 'k', token: 't', now: 1000, leaseSeconds: 60 });

    expect(db.prepare('SELECT key, state FROM reservas').all()).toEqual([
      { key: 'k', state: 'reserved' },
    ]);
  });

  it('purgeExpired borra sólo lo vencido', async () => {
    const store = new SqliteIdempotencyStore(sqliteClient(database()));
    await store.claim({ key: 'vieja', token: 'a', now: 1000, leaseSeconds: 10 });
    await store.claim({ key: 'vigente', token: 'a', now: 1000, leaseSeconds: 500 });

    expect(await store.purgeExpired(1010)).toBe(1);
    expect(await store.claim({ key: 'vigente', token: 'b', now: 1011, leaseSeconds: 10 })).toBe(
      'in_progress',
    );
  });

  it.each(['Eventos', 'a b', 'x; DROP TABLE y', '', 'main.eventos'])(
    'rechaza el nombre de tabla «%s»',
    (table) => {
      const client = sqliteClient(database());
      expect(() => new SqliteIdempotencyStore(client, { table })).toThrow(ConfigurationError);
      expect(() => sqliteStoreSchema(table)).toThrow(ConfigurationError);
    },
  );
});
