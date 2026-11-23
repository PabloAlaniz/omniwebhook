import { DatabaseSync } from 'node:sqlite';
import { describe, expect, it } from 'vitest';
import {
  type AttemptRecord,
  ConfigurationError,
  SqliteDeliveryLedger,
  sqliteClient,
  sqliteLedgerSchema,
} from '../../src/index';

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

function emptyLedger(): SqliteDeliveryLedger {
  const db = new DatabaseSync(':memory:');
  db.exec(sqliteLedgerSchema());
  return new SqliteDeliveryLedger(sqliteClient(db));
}

describe('SqliteDeliveryLedger', () => {
  it('guarda cada intento y los devuelve tal cual, en orden', async () => {
    const ledger = emptyLedger();

    await ledger.record(PENDING);
    await ledger.record(BLOCKED);
    await ledger.record({ ...PENDING, endpointId: 'ep_2' });

    expect(await ledger.attemptsOf('msg_1', 'ep_1')).toEqual([PENDING, BLOCKED]);
  });

  it('un reenvío repite el número de intento sin chocar', async () => {
    const ledger = emptyLedger();

    await ledger.record(PENDING);
    await ledger.record({ ...PENDING, at: PENDING.at + 60, state: 'delivered', nextAt: null });

    expect(await ledger.attemptsOf('msg_1', 'ep_1')).toHaveLength(2);
  });

  it('purgeBefore borra sólo los intentos anteriores', async () => {
    const ledger = emptyLedger();
    await ledger.record(PENDING);
    await ledger.record(BLOCKED);

    expect(await ledger.purgeBefore(BLOCKED.at)).toBe(1);
    expect(await ledger.attemptsOf('msg_1', 'ep_1')).toEqual([BLOCKED]);
  });

  it('crear el esquema dos veces no falla', () => {
    const db = new DatabaseSync(':memory:');
    db.exec(sqliteLedgerSchema('intentos'));
    expect(() => db.exec(sqliteLedgerSchema('intentos'))).not.toThrow();
  });

  it.each(['Intentos', 'a b', 'x; DROP TABLE y', '', 'main.intentos'])(
    'rechaza el nombre de tabla «%s»',
    (table) => {
      const client = sqliteClient(new DatabaseSync(':memory:'));
      expect(() => new SqliteDeliveryLedger(client, { table })).toThrow(ConfigurationError);
      expect(() => sqliteLedgerSchema(table)).toThrow(ConfigurationError);
    },
  );
});
