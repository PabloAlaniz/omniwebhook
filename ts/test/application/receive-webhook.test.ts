import { describe, expect, it, vi } from 'vitest';
import {
  httpStatusFor,
  MemoryIdempotencyStore,
  ReceiveWebhook,
  type ReceptionOutcome,
  type Verifier,
} from '../../src/index';
import { standardScheme } from '../../src/standard';
import { playSteps } from '../support/store-steps';
import { loadVector, type RequestVector, type StoreStep, toRequest } from '../support/vectors';

interface ReceiveCase {
  readonly name: string;
  readonly secrets: readonly string[];
  readonly now: number;
  readonly token: string;
  readonly lease_seconds: number;
  readonly retention_seconds: number;
  readonly handler: 'succeeds' | 'fails';
  readonly before: readonly StoreStep[];
  readonly request: RequestVector;
  readonly expected: {
    readonly outcome: ReceptionOutcome;
    readonly status: number;
    readonly handler_called: boolean;
    readonly event_key?: string;
  };
  readonly after: readonly StoreStep[];
}

describe('vectores de recibir/caso-de-uso', () => {
  const vector = loadVector<ReceiveCase>('recibir/caso-de-uso');

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', async (_name, c) => {
    const clock = { now: () => c.now };
    const store = new MemoryIdempotencyStore();
    await playSteps(store, c.before);
    const falla = new Error('falló el procesamiento');
    const handler = vi.fn(() => {
      if (c.handler === 'fails') throw falla;
    });
    const receive = new ReceiveWebhook({
      verifier: standardScheme({ secrets: c.secrets, clock }),
      store,
      clock,
      tokens: { next: () => c.token },
      leaseSeconds: c.lease_seconds,
      retentionSeconds: c.retention_seconds,
    });

    const result = await receive.execute(toRequest(c.request), handler);

    expect(result.outcome).toBe(c.expected.outcome);
    expect(httpStatusFor(result.outcome)).toBe(c.expected.status);
    expect(handler).toHaveBeenCalledTimes(c.expected.handler_called ? 1 : 0);
    if (c.expected.event_key !== undefined) {
      expect(result).toMatchObject({ eventKey: c.expected.event_key });
    }
    if (result.outcome === 'failed') {
      expect(result.error).toBe(falla);
    }
    await playSteps(store, c.after);
  });
});

describe('vectores de recibir/respuesta-http', () => {
  const vector = loadVector<{
    name: string;
    outcome: ReceptionOutcome;
    expected: { status: number };
  }>('recibir/respuesta-http');

  it.each(vector.cases.map((c) => [c.outcome, c.expected.status] as const))(
    '%s → %d',
    (outcome, status) => {
      expect(httpStatusFor(outcome)).toBe(status);
    },
  );
});

describe('ReceiveWebhook', () => {
  const clock = { now: () => 1_700_000_000 };
  const request = { headers: [], query: [], body: new Uint8Array() };
  const verified: Verifier = {
    verify: async () => ({ outcome: 'ok', eventKey: 'prueba:1', timestamp: null }),
  };

  function build(overrides: Partial<ConstructorParameters<typeof ReceiveWebhook>[0]> = {}) {
    const store = new MemoryIdempotencyStore();
    const receive = new ReceiveWebhook({
      verifier: verified,
      store,
      clock,
      tokens: { next: () => 't-1' },
      ...overrides,
    });
    return { store, receive };
  }

  it('le pasa al procesamiento el evento verificado', async () => {
    const { receive } = build();
    const handler = vi.fn();

    await receive.execute(request, handler);

    expect(handler).toHaveBeenCalledWith({ eventKey: 'prueba:1', timestamp: null, request });
  });

  it('espera a un procesamiento asíncrono antes de completar', async () => {
    const { receive, store } = build();
    const pasos: string[] = [];

    const result = await receive.execute(request, async () => {
      await Promise.resolve();
      pasos.push('procesado');
    });

    expect(pasos).toEqual(['procesado']);
    expect(result.outcome).toBe('ok');
    expect(
      await store.claim({ key: 'prueba:1', token: 'otro', now: clock.now(), leaseSeconds: 1 }),
    ).toBe('duplicate');
  });

  it('libera la reserva cuando el procesamiento asíncrono se rechaza', async () => {
    const { receive, store } = build();

    const result = await receive.execute(request, () => Promise.reject(new Error('no')));

    expect(result.outcome).toBe('failed');
    expect(
      await store.claim({ key: 'prueba:1', token: 'otro', now: clock.now(), leaseSeconds: 1 }),
    ).toBe('claimed');
  });

  it('usa la clave propia de quien integra cuando se la dan', async () => {
    const { receive } = build({ eventKey: (event) => `${event.eventKey}:pago` });

    const result = await receive.execute(request, () => {});

    expect(result).toEqual({ outcome: 'ok', eventKey: 'prueba:1:pago' });
  });

  it('usa los plazos por defecto de la especificación', async () => {
    const claim = vi.fn(async () => 'claimed' as const);
    const complete = vi.fn(async () => true);
    const { receive } = build({ store: { claim, complete, release: async () => true } });

    await receive.execute(request, () => {});

    expect(claim).toHaveBeenCalledWith(expect.objectContaining({ leaseSeconds: 300 }));
    expect(complete).toHaveBeenCalledWith(expect.objectContaining({ retentionSeconds: 604_800 }));
  });

  it.each([
    ['leaseSeconds', { leaseSeconds: 0 }],
    ['leaseSeconds', { leaseSeconds: 1.5 }],
    ['retentionSeconds', { retentionSeconds: -1 }],
  ])('rechaza un %s inválido al construirse', (_name, overrides) => {
    expect(() => build(overrides)).toThrow(/entero mayor que cero/);
  });
});
