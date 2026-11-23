import { describe, expect, it } from 'vitest';
import {
  ConfigurationError,
  githubScheme,
  hmacBodyScheme,
  mercadoPagoScheme,
  stripeScheme,
  tiktokScheme,
} from '../../src/index';
import { standardScheme } from '../../src/standard';

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
