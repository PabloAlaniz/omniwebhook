import { describe, expect, it, vi } from 'vitest';
import {
  ConfigurationError,
  type DynamoDbDocumentClient,
  dynamoDbClient,
  type KeyValueClient,
  KeyValueIdempotencyStore,
  MemoryKeyValueClient,
  workersKvClient,
} from '../../src/index';
import { describeIdempotencyStore } from '../contracts/idempotency-store';

const NOW = 1_700_000_000;

/** Una tabla en memoria que cumple las dos condiciones que usa el adaptador de DynamoDB. */
function fakeDynamo() {
  const items = new Map<string, Record<string, unknown>>();
  const failed = () =>
    Object.assign(new Error('condición'), { name: 'ConditionalCheckFailedException' });
  const holds = (
    current: Record<string, unknown> | undefined,
    expression: string,
    values?: Record<string, unknown>,
  ) =>
    expression === 'attribute_not_exists(#k)'
      ? current === undefined
      : current?.version === values?.[':expected'];
  const document: DynamoDbDocumentClient = {
    get: vi.fn(async ({ Key }) => ({ Item: items.get(String(Key.pk ?? Key.id)) })),
    put: vi.fn(async ({ Item, ConditionExpression, ExpressionAttributeValues }) => {
      const key = String(Item.pk ?? Item.id);
      if (!holds(items.get(key), ConditionExpression, ExpressionAttributeValues)) throw failed();
      items.set(key, Item);
    }),
    delete: vi.fn(async ({ Key, ConditionExpression, ExpressionAttributeValues }) => {
      const key = String(Key.pk ?? Key.id);
      if (!holds(items.get(key), ConditionExpression, ExpressionAttributeValues)) throw failed();
      items.delete(key);
    }),
  };
  return { document, items };
}

/** Un espacio de nombres de Workers KV en memoria. */
function fakeKv() {
  const values = new Map<string, string>();
  const ttls = new Map<string, number>();
  return {
    values,
    ttls,
    namespace: {
      get: async (key: string) => values.get(key) ?? null,
      put: async (key: string, value: string, { expirationTtl }: { expirationTtl: number }) => {
        values.set(key, value);
        ttls.set(key, expirationTtl);
      },
      delete: async (key: string) => {
        values.delete(key);
      },
    },
  };
}

describeIdempotencyStore(
  'KeyValueIdempotencyStore en memoria',
  () => new KeyValueIdempotencyStore(new MemoryKeyValueClient()),
);
describeIdempotencyStore(
  'KeyValueIdempotencyStore sobre DynamoDB',
  () => new KeyValueIdempotencyStore(dynamoDbClient(fakeDynamo().document, { table: 'eventos' })),
);
describeIdempotencyStore(
  'KeyValueIdempotencyStore sobre Workers KV',
  () => new KeyValueIdempotencyStore(workersKvClient(fakeKv().namespace)),
);

describe('KeyValueIdempotencyStore', () => {
  const claim = (store: KeyValueIdempotencyStore, token: string, key = 'evt:1') =>
    store.claim({ key, token, now: NOW, leaseSeconds: 300 });

  it('dice qué garantía da según el cliente', () => {
    expect(new KeyValueIdempotencyStore(new MemoryKeyValueClient()).guarantee).toBe('atomic');
    expect(new KeyValueIdempotencyStore(workersKvClient(fakeKv().namespace)).guarantee).toBe(
      'best-effort',
    );
  });

  it('entre pedidos simultáneos por la misma clave, uno solo la reserva', async () => {
    const store = new KeyValueIdempotencyStore(new MemoryKeyValueClient());

    const outcomes = await Promise.all(
      Array.from({ length: 20 }, (_, index) => claim(store, `t-${index}`)),
    );

    expect(outcomes.filter((outcome) => outcome === 'claimed')).toHaveLength(1);
    expect(outcomes.filter((outcome) => outcome === 'in_progress')).toHaveLength(19);
  });

  it('si pierde la escritura, vuelve a mirar: quien ganó la tiene en curso', async () => {
    const client = new MemoryKeyValueClient();
    const store = new KeyValueIdempotencyStore(client);
    const rival = new KeyValueIdempotencyStore(client);
    // El rival reserva justo después de que este proceso leyó que la clave estaba libre.
    const get = client.get.bind(client);
    let interfered = false;
    client.get = async (key) => {
      const record = await get(key);
      if (!interfered) {
        interfered = true;
        await claim(rival, 't-rival');
      }
      return record;
    };

    expect(await claim(store, 't-lento')).toBe('in_progress');
    expect(
      await rival.complete({ key: 'evt:1', token: 't-rival', now: NOW, retentionSeconds: 60 }),
    ).toBe(true);
    expect(await claim(store, 't-lento')).toBe('duplicate');
  });

  it('si la escritura se pierde siempre, deja de insistir y lo da por en curso', async () => {
    const put = vi.fn(async () => false);
    const store = new KeyValueIdempotencyStore({
      conditional: true,
      get: async () => null,
      put,
      delete: async () => false,
    });

    expect(await claim(store, 't-1')).toBe('in_progress');
    expect(put).toHaveBeenCalledTimes(3);
  });

  it('quien perdió su reserva no pisa a quien la tomó después', async () => {
    const client = new MemoryKeyValueClient();
    const store = new KeyValueIdempotencyStore(client);
    await claim(store, 't-viejo');
    // Venció el plazo y otro proceso tomó la clave entre la lectura y la escritura del primero.
    const get = client.get.bind(client);
    let interfered = false;
    client.get = async (key) => {
      const record = await get(key);
      if (!interfered) {
        interfered = true;
        await store.claim({ key: 'evt:1', token: 't-nuevo', now: NOW + 301, leaseSeconds: 300 });
      }
      return record;
    };

    expect(
      await store.complete({
        key: 'evt:1',
        token: 't-viejo',
        now: NOW + 302,
        retentionSeconds: 60,
      }),
    ).toBe(false);
    expect(await store.release({ key: 'evt:1', token: 't-nuevo' })).toBe(true);
  });

  it('guarda el mismo JSON que el paquete de Python y le pone vencimiento', async () => {
    const kv = fakeKv();
    const store = new KeyValueIdempotencyStore(workersKvClient(kv.namespace), {
      prefix: 'p:',
      graceSeconds: 60,
    });

    await claim(store, 't-1');
    expect(JSON.parse(kv.values.get('p:evt:1') ?? '')).toEqual({
      state: 'reserved',
      token: 't-1',
      expires_at: NOW + 300,
    });
    expect(kv.ttls.get('p:evt:1')).toBe(360);

    await store.complete({ key: 'evt:1', token: 't-1', now: NOW, retentionSeconds: 1000 });
    expect(kv.values.get('p:evt:1')).toBe(
      `{"state":"completed","token":"t-1","expires_at":${NOW + 1000}}`,
    );
    expect(kv.ttls.get('p:evt:1')).toBe(1000);
  });

  it('una entrada que no es suya es un error, no un resultado', async () => {
    const client: KeyValueClient = {
      conditional: true,
      get: async () => ({ value: '{"otra":"cosa"}', version: '1' }),
      put: async () => true,
      delete: async () => true,
    };
    const store = new KeyValueIdempotencyStore(client);

    await expect(claim(store, 't-1')).rejects.toThrow(/no es de omniwebhook/);
    await expect(store.release({ key: 'evt:1', token: 't-1' })).rejects.toThrow(
      /no es de omniwebhook/,
    );
    client.get = async () => ({ value: 'no es json', version: '1' });
    await expect(claim(store, 't-1')).rejects.toThrow(/no es de omniwebhook/);
  });

  it.each([
    ['un prefijo vacío', { prefix: '' }],
    ['una gracia negativa', { graceSeconds: -1 }],
    ['una gracia con decimales', { graceSeconds: 1.5 }],
  ])('rechaza %s', (_what, options) => {
    expect(() => new KeyValueIdempotencyStore(new MemoryKeyValueClient(), options)).toThrow(
      ConfigurationError,
    );
  });
});

describe('workersKvClient', () => {
  it('nunca pide un vencimiento menor que el mínimo del servicio', async () => {
    const kv = fakeKv();

    await workersKvClient(kv.namespace).put('k', 'v', { ttlSeconds: 5, onlyIf: null });

    expect(kv.ttls.get('k')).toBe(60);
  });
});

describe('dynamoDbClient', () => {
  it('lee de forma consistente y escribe con condición y vencimiento', async () => {
    const { document, items } = fakeDynamo();
    const client = dynamoDbClient(document, {
      table: 'eventos',
      keyAttribute: 'id',
      now: () => NOW,
    });

    expect(await client.put('k', 'v1', { ttlSeconds: 30, onlyIf: null })).toBe(true);
    expect(items.get('k')).toMatchObject({ id: 'k', value: 'v1', ttl: NOW + 30 });
    expect(await client.put('k', 'v2', { ttlSeconds: 30, onlyIf: null })).toBe(false);

    const record = await client.get('k');
    expect(document.get).toHaveBeenLastCalledWith({
      TableName: 'eventos',
      Key: { id: 'k' },
      ConsistentRead: true,
    });
    expect(record?.value).toBe('v1');
    const version = record?.version ?? '';

    expect(await client.put('k', 'v2', { ttlSeconds: 30, onlyIf: 'otra' })).toBe(false);
    expect(await client.put('k', 'v2', { ttlSeconds: 30, onlyIf: version })).toBe(true);
    expect(await client.delete('k', { onlyIf: version })).toBe(false);
    expect(await client.delete('k', { onlyIf: (await client.get('k'))?.version ?? '' })).toBe(true);
    expect(await client.get('k')).toBeNull();
  });

  it('un error que no es de la condición se propaga', async () => {
    const { document } = fakeDynamo();
    document.put = async () => {
      throw new Error('sin permisos');
    };

    await expect(
      dynamoDbClient(document, { table: 't' }).put('k', 'v', { ttlSeconds: 1, onlyIf: null }),
    ).rejects.toThrow('sin permisos');
  });

  it.each([
    ['una tabla vacía', { table: '' }],
    ['un atributo de clave vacío', { table: 't', keyAttribute: '' }],
  ])('rechaza %s', (_what, options) => {
    expect(() => dynamoDbClient(fakeDynamo().document, options)).toThrow(ConfigurationError);
  });

  it('por defecto usa el reloj del sistema para el vencimiento', async () => {
    const { document, items } = fakeDynamo();

    await dynamoDbClient(document, { table: 't' }).put('k', 'v', { ttlSeconds: 10, onlyIf: null });

    expect(Number(items.get('k')?.ttl)).toBeGreaterThan(Date.now() / 1000);
  });
});
