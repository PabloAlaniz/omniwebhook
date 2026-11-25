import { describe, expect, it } from 'vitest';
import {
  ConfigurationError,
  githubScheme,
  googlePubSubScheme,
  hmacBodyScheme,
  mercadoPagoScheme,
  sharedTokenScheme,
  stripeScheme,
  tiktokScheme,
} from '../../src/index';
import { standardPublicKeyScheme, standardScheme } from '../../src/standard';

describe('configuración de los esquemas', () => {
  it.each([0, -1, 1.5, Number.NaN])(
    'rechaza la tolerancia %s: la frescura no se puede desactivar',
    (toleranceSeconds) => {
      for (const build of [standardScheme, stripeScheme, tiktokScheme, mercadoPagoScheme]) {
        expect(() => build({ secrets: ['c2VjcmV0bw=='], toleranceSeconds })).toThrow(
          ConfigurationError,
        );
      }
    },
  );

  it('hmacBodyScheme rechaza una cabecera vacía', () => {
    expect(() => hmacBodyScheme({ secrets: ['s'], header: ' ' })).toThrow(/header/);
  });

  it('hmacBodyScheme rechaza un nombre vacío', () => {
    expect(() => hmacBodyScheme({ secrets: ['s'], header: 'x-firma', name: '' })).toThrow(/name/);
  });

  it('hmacBodyScheme rechaza una codificación desconocida', () => {
    const encoding = 'base32' as 'hex';

    expect(() => hmacBodyScheme({ secrets: ['s'], header: 'x-firma', encoding })).toThrow(
      /encoding/,
    );
  });

  it('sharedTokenScheme exige header o query, y sólo uno de los dos', () => {
    expect(() => sharedTokenScheme({ secrets: ['s'] })).toThrow(/header o query/);
    expect(() => sharedTokenScheme({ secrets: ['s'], header: 'x-token', query: 'token' })).toThrow(
      /header o query/,
    );
  });

  it.each([
    [{ header: ' ' }, /header/],
    [{ query: '' }, /query/],
    [{ header: 'x-token', name: '' }, /name/],
    [{ header: 'x-token', idHeader: ' ' }, /idHeader/],
    [{ header: 7 as unknown as string }, /header/],
  ])('sharedTokenScheme rechaza las opciones %j', (options, message) => {
    expect(() => sharedTokenScheme({ secrets: ['s'], ...options })).toThrow(ConfigurationError);
    expect(() => sharedTokenScheme({ secrets: ['s'], ...options })).toThrow(message);
  });

  it('googlePubSubScheme rechaza un parámetro vacío', () => {
    expect(() => googlePubSubScheme({ secrets: ['s'], query: ' ' })).toThrow(/query/);
  });

  it('un aviso de Pub/Sub no toma el identificador de un campo heredado', async () => {
    const body = new TextEncoder().encode('{"message":{"data":"e30="}}');
    const prototype = Object.prototype as { messageId?: string };
    prototype.messageId = 'heredado';
    try {
      const result = await googlePubSubScheme({ secrets: ['s'] }).verify({
        headers: [],
        query: [['token', 's']],
        body,
      });

      expect(result).toMatchObject({ outcome: 'ok' });
      expect(result.outcome === 'ok' && result.eventKey).toMatch(/^google-pubsub:sha256:/);
    } finally {
      delete prototype.messageId;
    }
  });

  it('sin reloj inyectado usa el del sistema', async () => {
    const result = await githubScheme({ secrets: ['s'] }).verify({
      headers: [],
      query: [],
      body: new Uint8Array(),
    });

    expect(result).toEqual({ outcome: 'missing' });
  });

  it('el esquema estándar acepta otro firmante que cumpla el contrato', async () => {
    const verifier = standardScheme({
      secrets: ['c2VjcmV0bw=='],
      clock: { now: () => 100 },
      signer: { sign: (_key, id, timestamp) => `v1,${id}-${timestamp}` },
    });

    const result = await verifier.verify({
      headers: [
        ['webhook-id', 'm1'],
        ['webhook-timestamp', '100'],
        ['webhook-signature', 'v1,m1-100'],
      ],
      query: [],
      body: new Uint8Array(),
    });

    expect(result).toEqual({ outcome: 'ok', eventKey: 'standard:m1', timestamp: 100 });
  });
});

describe('configuración de la firma asimétrica', () => {
  const key = (bytes: Uint8Array) => `whpk_${Buffer.from(bytes).toString('base64')}`;
  const publicKeys = [key(Uint8Array.from({ length: 32 }, (_, index) => index))];

  it.each(['', 'ep.1', undefined, 7])('rechaza el identificador de destino %j', (endpointId) => {
    expect(() => standardPublicKeyScheme({ publicKeys, endpointId: endpointId as string })).toThrow(
      /endpointId/,
    );
  });

  it('rechaza una tolerancia inválida', () => {
    expect(() =>
      standardPublicKeyScheme({ publicKeys, endpointId: 'ep_1', toleranceSeconds: 0 }),
    ).toThrow(ConfigurationError);
  });

  it.each([
    ['ff', new Uint8Array(32).fill(0xff)],
    ['00', new Uint8Array(32)],
    ['rango', Uint8Array.from({ length: 32 }, (_, index) => index)],
  ])('una clave que no sirve para verificar (%s) nunca verifica ni lanza', async (_name, raw) => {
    const scheme = standardPublicKeyScheme({
      publicKeys: [key(raw)],
      endpointId: 'ep_1',
      clock: { now: () => 1_700_000_000 },
    });

    const result = await scheme.verify({
      headers: [
        ['webhook-id', 'msg_1'],
        ['webhook-timestamp', '1700000000'],
        ['webhook-signature', `v2a,${Buffer.from(new Uint8Array(64).fill(1)).toString('base64')}`],
      ],
      query: [],
      body: new TextEncoder().encode('{}'),
    });

    expect(result).toEqual({ outcome: 'invalid' });
  });
});
