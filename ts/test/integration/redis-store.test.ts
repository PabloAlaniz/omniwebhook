import { createClient } from 'redis';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  ConfigurationError,
  ioredisClient,
  nodeRedisClient,
  RedisIdempotencyStore,
} from '../../src/index';
import { describeIdempotencyStore } from '../contracts/idempotency-store';

const url = process.env.OMNIWEBHOOK_REDIS_URL;
if (url === undefined) {
  throw new Error(
    'Falta OMNIWEBHOOK_REDIS_URL: los tests de integración necesitan un Redis de prueba.',
  );
}

const PREFIX = 'omniwebhook:test:ts:';
const redis = createClient({ url });
const client = nodeRedisClient(redis);

async function clean(): Promise<void> {
  const keys = await redis.keys(`${PREFIX}*`);
  if (keys.length > 0) await redis.del(keys);
}

beforeAll(async () => {
  await redis.connect();
});

afterAll(async () => {
  await clean();
  await redis.quit();
});

async function emptyStore(): Promise<RedisIdempotencyStore> {
  await clean();
  return new RedisIdempotencyStore(client, { prefix: PREFIX });
}

describeIdempotencyStore('RedisIdempotencyStore', emptyStore);

describe('RedisIdempotencyStore', () => {
  const NOW = 1_700_000_000;

  it('entre pedidos simultáneos por la misma clave, uno solo la reserva', async () => {
    const store = await emptyStore();

    const outcomes = await Promise.all(
      Array.from({ length: 20 }, (_, index) =>
        store.claim({ key: 'evt:carrera', token: `t-${index}`, now: NOW, leaseSeconds: 300 }),
      ),
    );

    expect(outcomes.filter((outcome) => outcome === 'claimed')).toHaveLength(1);
    expect(outcomes.filter((outcome) => outcome === 'in_progress')).toHaveLength(19);
  });

  it('las entradas se borran solas: la reserva dura el plazo más la gracia y lo completado, la retención', async () => {
    const store = new RedisIdempotencyStore(client, { prefix: PREFIX, graceSeconds: 60 });
    await clean();

    await store.claim({ key: 'evt:ttl', token: 't-1', now: NOW, leaseSeconds: 300 });
    expect(await redis.ttl(`${PREFIX}evt:ttl`)).toBeGreaterThan(300);
    expect(await redis.ttl(`${PREFIX}evt:ttl`)).toBeLessThanOrEqual(360);

    await store.complete({ key: 'evt:ttl', token: 't-1', now: NOW, retentionSeconds: 1000 });
    expect(await redis.ttl(`${PREFIX}evt:ttl`)).toBeGreaterThan(900);
    expect(await redis.hGetAll(`${PREFIX}evt:ttl`)).toEqual({
      state: 'completed',
      token: 't-1',
      expires_at: String(NOW + 1000),
    });
  });

  it('funciona con un cliente que recibe los argumentos como ioredis', async () => {
    await clean();
    const store = new RedisIdempotencyStore(
      ioredisClient({
        eval: (script, numKeys, ...rest) =>
          redis.eval(script, { keys: rest.slice(0, numKeys), arguments: rest.slice(numKeys) }),
      }),
      { prefix: PREFIX },
    );

    expect(await store.claim({ key: 'evt:io', token: 't', now: NOW, leaseSeconds: 5 })).toBe(
      'claimed',
    );
    expect(await store.release({ key: 'evt:io', token: 'otro' })).toBe(false);
    expect(await store.release({ key: 'evt:io', token: 't' })).toBe(true);
  });

  it.each([
    ['un prefijo vacío', { prefix: '' }],
    ['una gracia negativa', { graceSeconds: -1 }],
    ['una gracia con decimales', { graceSeconds: 1.5 }],
  ])('rechaza %s', (_what, options) => {
    expect(() => new RedisIdempotencyStore(client, options)).toThrow(ConfigurationError);
  });

  it('una respuesta inesperada del servidor es un error, no un resultado', async () => {
    const store = new RedisIdempotencyStore({ eval: async () => 'otra-cosa' });

    await expect(store.claim({ key: 'k', token: 't', now: NOW, leaseSeconds: 1 })).rejects.toThrow(
      /inesperada/,
    );
  });
});
