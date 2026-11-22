import { createHmac } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  createReceiver,
  hmacBodyScheme,
  MemoryIdempotencyStore,
  randomTokens,
  systemClock,
  toIncomingRequest,
  toResponse,
} from '../../src/index';

describe('toIncomingRequest', () => {
  it('conserva cabeceras, parámetros repetidos y el cuerpo crudo', async () => {
    const request = new Request('https://receptor.test/hooks?data.id=1&data.id=2&tipo=pago', {
      method: 'POST',
      headers: { 'X-Firma': 'abc', 'content-type': 'application/json' },
      body: '{"ñ":1}',
    });

    const incoming = await toIncomingRequest(request);

    expect(incoming.headers).toContainEqual(['x-firma', 'abc']);
    expect(incoming.query).toEqual([
      ['data.id', '1'],
      ['data.id', '2'],
      ['tipo', 'pago'],
    ]);
    expect(new TextDecoder().decode(incoming.body)).toBe('{"ñ":1}');
  });
});

describe('toResponse', () => {
  it.each([
    ['ok', 200],
    ['in_progress', 409],
    ['invalid', 401],
    ['failed', 500],
  ] as const)('%s → %d, sin cuerpo', async (outcome, status) => {
    const response = toResponse({ outcome });

    expect(response.status).toBe(status);
    expect(await response.text()).toBe('');
  });
});

describe('createReceiver', () => {
  it('funciona de punta a punta con el reloj y los tokens por defecto', async () => {
    const receive = createReceiver({
      verifier: hmacBodyScheme({ secrets: ['secreto-de-prueba'], header: 'x-firma' }),
      store: new MemoryIdempotencyStore(),
    });
    const body = new TextEncoder().encode('hola');
    const firma = createHmac('sha256', 'secreto-de-prueba').update(body).digest('hex');
    const request = { headers: [['x-firma', firma]] as const, query: [], body };
    const procesados: string[] = [];

    const primero = await receive.execute(request, (event) => {
      procesados.push(event.eventKey);
    });
    const segundo = await receive.execute(request, (event) => {
      procesados.push(event.eventKey);
    });

    expect(primero.outcome).toBe('ok');
    expect(segundo.outcome).toBe('duplicate');
    expect(procesados).toHaveLength(1);
  });
});

describe('valores por defecto', () => {
  it('el reloj del sistema da segundos enteros cercanos a ahora', () => {
    const now = systemClock.now();

    expect(Number.isInteger(now)).toBe(true);
    expect(Math.abs(now - Date.now() / 1000)).toBeLessThan(2);
  });

  it('los tokens aleatorios no se repiten', () => {
    expect(randomTokens.next()).not.toBe(randomTokens.next());
  });
});
