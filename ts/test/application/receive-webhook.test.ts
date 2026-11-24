import { describe, expect, it, vi } from 'vitest';
import {
  httpStatusFor,
  MemoryIdempotencyStore,
  type PayloadSchema,
  ReceiveWebhook,
  type ReceiveWebhookDependencies,
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
  readonly max_body_bytes: number;
  readonly payload: 'none' | 'accepts' | 'rejects';
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
      maxBodyBytes: c.max_body_bytes,
      ...(c.payload === 'none'
        ? {}
        : {
            payload: {
              '~standard': {
                validate: (value: unknown) =>
                  c.payload === 'accepts' ? { value } : { issues: [{ message: 'rechazado' }] },
              },
            },
          }),
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
    ['maxBodyBytes', { maxBodyBytes: 0 }],
    ['leaseSeconds', { leaseSeconds: 0 }],
    ['leaseSeconds', { leaseSeconds: 1.5 }],
    ['retentionSeconds', { retentionSeconds: -1 }],
  ])('rechaza un %s inválido al construirse', (_name, overrides) => {
    expect(() => build(overrides)).toThrow(/entero mayor que cero/);
  });

  describe('con un validador de payload', () => {
    interface Pedido {
      readonly tipo: string;
    }
    const esquema: PayloadSchema<Pedido> = {
      '~standard': {
        validate: async (value) => {
          const tipo = (value as { tipo?: unknown } | null)?.tipo;
          return typeof tipo === 'string'
            ? { value: { tipo } }
            : { issues: [{ message: 'falta tipo', path: ['tipo'] }] };
        },
      },
    };
    const conCuerpo = (texto: string) => ({ ...request, body: new TextEncoder().encode(texto) });

    function validated(overrides: Partial<ReceiveWebhookDependencies<Pedido>> = {}) {
      const store = new MemoryIdempotencyStore();
      const receive = new ReceiveWebhook<Pedido>({
        verifier: verified,
        store,
        clock,
        tokens: { next: () => 't-1' },
        payload: esquema,
        ...overrides,
      });
      return { receive, store };
    }

    it('le pasa al procesamiento el payload que devolvió el validador', async () => {
      const { receive } = validated();
      const tipos: string[] = [];

      const result = await receive.execute(conCuerpo('{"tipo":"pago","de_mas":1}'), (event) => {
        tipos.push(event.payload.tipo);
        expect(event.payload).toEqual({ tipo: 'pago' });
      });

      expect(result).toEqual({ outcome: 'ok', eventKey: 'prueba:1' });
      expect(tipos).toEqual(['pago']);
    });

    it('un payload rechazado devuelve el motivo y no toca el almacén', async () => {
      const claim = vi.fn();
      const { receive } = validated({ store: { claim, complete: vi.fn(), release: vi.fn() } });
      const handler = vi.fn();

      const result = await receive.execute(conCuerpo('{"otro":1}'), handler);

      expect(result).toEqual({
        outcome: 'unprocessable',
        eventKey: 'prueba:1',
        issues: [{ message: 'falta tipo', path: ['tipo'] }],
      });
      expect(httpStatusFor(result.outcome)).toBe(422);
      expect(handler).not.toHaveBeenCalled();
      expect(claim).not.toHaveBeenCalled();
    });

    it.each([
      ['texto suelto', 'no es json'],
      ['con marca de orden de bytes', '\ufeff{"tipo":"pago"}'],
      ['vacío', ''],
    ])('un cuerpo que no es JSON (%s) no llega al validador', async (_what, texto) => {
      const validate = vi.fn();
      const { receive } = validated({ payload: { '~standard': { validate } } });

      const result = await receive.execute(conCuerpo(texto), () => {});

      expect(result).toMatchObject({ outcome: 'unprocessable', eventKey: 'prueba:1' });
      expect(validate).not.toHaveBeenCalled();
    });

    it('un pedido que no verifica no llega al validador', async () => {
      const validate = vi.fn();
      const { receive } = validated({
        verifier: { verify: async () => ({ outcome: 'invalid' }) },
        payload: { '~standard': { validate } },
      });

      expect(await receive.execute(conCuerpo('{"tipo":"pago"}'), () => {})).toEqual({
        outcome: 'invalid',
      });
      expect(validate).not.toHaveBeenCalled();
    });

    it('el observador ve el rechazo con la clave del evento', async () => {
      const onReception = vi.fn();
      const { receive } = validated({ observer: { onReception }, timer: { nowMs: () => 0 } });

      await receive.execute(conCuerpo('{}'), () => {});

      expect(onReception).toHaveBeenCalledWith({
        outcome: 'unprocessable',
        eventKey: 'prueba:1',
        durationMs: 0,
      });
    });
  });

  describe('con un observador', () => {
    function observed(overrides: Parameters<typeof build>[0] = {}) {
      const onReception = vi.fn();
      let ms = 0;
      const timer = { nowMs: () => (ms += 25) };
      return { onReception, ...build({ observer: { onReception }, timer, ...overrides }) };
    }

    it('informa el resultado, la clave y la duración, una vez por pedido', async () => {
      const { receive, onReception } = observed();

      await receive.execute(request, () => {});
      await receive.execute(request, () => {});

      expect(onReception.mock.calls).toEqual([
        [{ outcome: 'ok', eventKey: 'prueba:1', durationMs: 25 }],
        [{ outcome: 'duplicate', eventKey: 'prueba:1', durationMs: 25 }],
      ]);
    });

    it('informa un rechazo sin clave de evento', async () => {
      const { receive, onReception } = observed({
        verifier: { verify: async () => ({ outcome: 'invalid' }) },
      });

      await receive.execute(request, () => {});

      expect(onReception).toHaveBeenCalledWith({
        outcome: 'invalid',
        eventKey: null,
        durationMs: 25,
      });
    });

    it('lo llama después de liberar la reserva cuando el procesamiento falla', async () => {
      const { receive, store, onReception } = observed();
      let libre: string | undefined;
      onReception.mockImplementation(() => {
        libre = 'pendiente';
      });

      await receive.execute(request, () => {
        throw new Error('falló');
      });
      libre = await store.claim({ key: 'prueba:1', token: 'otro', now: 1, leaseSeconds: 1 });

      expect(onReception).toHaveBeenCalledWith(expect.objectContaining({ outcome: 'failed' }));
      expect(libre).toBe('claimed');
    });

    it('si el observador lanza, el resultado no cambia', async () => {
      const { receive, onReception } = observed();
      onReception.mockImplementation(() => {
        throw new Error('falló la telemetría');
      });

      expect(await receive.execute(request, () => {})).toEqual({
        outcome: 'ok',
        eventKey: 'prueba:1',
      });
    });

    it('no recibe el cuerpo, las cabeceras ni nada más que los tres datos', async () => {
      const { receive, onReception } = observed();

      await receive.execute({ ...request, headers: [['x-firma', 'secreta']] }, () => {});

      expect(Object.keys(onReception.mock.calls[0]?.[0] ?? {}).sort()).toEqual([
        'durationMs',
        'eventKey',
        'outcome',
      ]);
    });

    it('sin cronómetro es un error de configuración', () => {
      expect(() => build({ observer: { onReception: () => {} } })).toThrow(/timer/);
    });
  });
});
