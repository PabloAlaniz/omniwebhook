import { describe, expect, it, vi } from 'vitest';
import {
  type AttemptRecord,
  type AttemptSender,
  ConfigurationError,
  createDispatcher,
  DispatchDue,
  type DispatchDueDependencies,
  MemoryDeliveryLedger,
  MemoryOutbox,
  SendWebhook,
} from '../../src/index';
import { standardSigner } from '../../src/standard';
import { describeOutbox } from '../contracts/outbox';

describeOutbox('MemoryOutbox', () => new MemoryOutbox());

const NOW = 1_700_000_000;
const PAYLOAD = new TextEncoder().encode('{"type":"pedido.creado"}');

function record(overrides: Partial<AttemptRecord> = {}): AttemptRecord {
  return {
    messageId: 'msg_1',
    endpointId: 'ep_1',
    attempt: 1,
    at: NOW,
    deliveryClass: 'delivered',
    state: 'delivered',
    status: 200,
    problem: null,
    durationMs: 5,
    nextAt: null,
    ...overrides,
  };
}

async function build(overrides: Partial<DispatchDueDependencies> = {}) {
  const outbox = new MemoryOutbox();
  let now = NOW;
  let tokens = 0;
  const execute = vi.fn<AttemptSender['execute']>(async () => record());
  const resolve = vi.fn(async (id: string) => ({ url: `https://hooks.ejemplo.test/${id}` }));
  const dispatcher = new DispatchDue({
    outbox,
    endpoints: { resolve },
    sender: { execute },
    clock: { now: () => now },
    tokens: { next: () => `d-${++tokens}` },
    ...overrides,
  });
  const enqueue = (messageId: string, endpointId = 'ep_1') =>
    outbox.enqueue({ messageId, endpointId, payload: PAYLOAD, now });
  return { outbox, dispatcher, execute, resolve, enqueue, advance: (s: number) => (now += s) };
}

describe('DispatchDue', () => {
  it('toma lo pendiente, hace un intento por entrega y la cierra con el resultado', async () => {
    const { dispatcher, outbox, execute, enqueue } = await build();
    await enqueue('msg_1');

    const result = await dispatcher.execute();

    expect(execute).toHaveBeenCalledWith({
      endpoint: { id: 'ep_1', url: 'https://hooks.ejemplo.test/ep_1' },
      message: { id: 'msg_1', payload: PAYLOAD },
      attempt: 1,
    });
    expect(result).toEqual({
      dispatched: [
        { messageId: 'msg_1', endpointId: 'ep_1', attempt: 1, state: 'delivered', settled: true },
      ],
      failures: [],
    });
    expect(outbox.stateOf('msg_1', 'ep_1')).toBe('delivered');
    expect((await dispatcher.execute()).dispatched).toEqual([]);
  });

  it('sin nada pendiente no hace nada', async () => {
    const { dispatcher, execute } = await build();

    expect(await dispatcher.execute()).toEqual({ dispatched: [], failures: [] });
    expect(execute).not.toHaveBeenCalled();
  });

  it('un fallo reintentable vuelve a salir recién cuando corresponde, con el intento siguiente', async () => {
    const { dispatcher, execute, enqueue, advance } = await build();
    await enqueue('msg_1');
    execute.mockResolvedValueOnce(
      record({ deliveryClass: 'retryable', state: 'pending', status: 503, nextAt: NOW + 5 }),
    );

    expect((await dispatcher.execute()).dispatched[0]).toMatchObject({ state: 'pending' });
    advance(4);
    expect((await dispatcher.execute()).dispatched).toEqual([]);
    advance(1);
    expect((await dispatcher.execute()).dispatched[0]).toMatchObject({
      attempt: 2,
      state: 'delivered',
    });
    expect(execute).toHaveBeenLastCalledWith(expect.objectContaining({ attempt: 2 }));
  });

  it.each(['rejected', 'blocked', 'gone', 'exhausted'] as const)(
    'una entrega que termina %s queda cerrada en ese estado',
    async (state) => {
      const { dispatcher, outbox, execute, enqueue, advance } = await build();
      await enqueue('msg_1');
      execute.mockResolvedValueOnce(record({ state, status: null }));

      await dispatcher.execute();
      advance(1_000_000);

      expect(outbox.stateOf('msg_1', 'ep_1')).toBe(state);
      expect((await dispatcher.execute()).dispatched).toEqual([]);
    },
  );

  it('un destino que no existe o está deshabilitado cancela la entrega sin intentarla', async () => {
    const { dispatcher, outbox, execute, enqueue } = await build({
      endpoints: { resolve: async () => null },
    });
    await enqueue('msg_1');

    const result = await dispatcher.execute();

    expect(result.dispatched).toEqual([
      { messageId: 'msg_1', endpointId: 'ep_1', attempt: 1, state: 'cancelled', settled: true },
    ]);
    expect(execute).not.toHaveBeenCalled();
    expect(outbox.stateOf('msg_1', 'ep_1')).toBe('cancelled');
  });

  it('respeta el límite de la tanda', async () => {
    const { dispatcher, enqueue } = await build({ limit: 2 });
    for (const id of ['msg_1', 'msg_2', 'msg_3']) await enqueue(id);

    expect((await dispatcher.execute()).dispatched.map((d) => d.messageId)).toEqual([
      'msg_1',
      'msg_2',
    ]);
    expect((await dispatcher.execute()).dispatched.map((d) => d.messageId)).toEqual(['msg_3']);
  });

  it('si un intento no llega a hacerse, lo informa, sigue con el resto y no cierra esa entrega', async () => {
    const { dispatcher, outbox, execute, enqueue, advance } = await build();
    await enqueue('msg_1');
    await enqueue('msg_2');
    const falla = new ConfigurationError('no se puede firmar el mensaje: unconfigured');
    execute.mockRejectedValueOnce(falla);

    const result = await dispatcher.execute();

    expect(result.failures).toEqual([{ messageId: 'msg_1', endpointId: 'ep_1', error: falla }]);
    expect(result.dispatched.map((d) => d.messageId)).toEqual(['msg_2']);
    expect(outbox.stateOf('msg_1', 'ep_1')).toBe('pending');
    // Sigue tomada hasta que venza el plazo; después vuelve a salir.
    expect((await dispatcher.execute()).dispatched).toEqual([]);
    advance(300);
    expect((await dispatcher.execute()).dispatched.map((d) => d.messageId)).toEqual(['msg_1']);
  });

  it('si el directorio de destinos falla, la entrega tampoco se cierra', async () => {
    const { dispatcher, outbox, enqueue } = await build({
      endpoints: {
        resolve: async () => {
          throw new Error('sin base de datos');
        },
      },
    });
    await enqueue('msg_1');

    expect((await dispatcher.execute()).failures).toHaveLength(1);
    expect(outbox.stateOf('msg_1', 'ep_1')).toBe('pending');
  });

  it('si otro proceso tomó la entrega mientras tanto, lo dice y no pisa su resultado', async () => {
    const { dispatcher, outbox, execute, enqueue } = await build({ leaseSeconds: 10 });
    await enqueue('msg_1');
    execute.mockImplementationOnce(async () => {
      // El intento tardó más que la toma y otro proceso se la llevó.
      await outbox.claim({ token: 'otro', now: NOW + 10, limit: 1, leaseSeconds: 300 });
      return record();
    });

    const result = await dispatcher.execute();

    expect(result.dispatched[0]).toMatchObject({ state: 'delivered', settled: false });
    expect(outbox.stateOf('msg_1', 'ep_1')).toBe('pending');
  });

  it('un intento pendiente sin próximo intento es un error, no un cierre', async () => {
    const { dispatcher, execute, enqueue } = await build();
    await enqueue('msg_1');
    execute.mockResolvedValueOnce(record({ state: 'pending', nextAt: null }));

    expect((await dispatcher.execute()).failures).toHaveLength(1);
  });

  it.each([
    ['limit', { limit: 0 }],
    ['leaseSeconds', { leaseSeconds: 1.5 }],
  ])('rechaza un %s inválido al construirse', async (name, overrides) => {
    await expect(build(overrides)).rejects.toThrow(new RegExp(name));
  });

  it('de punta a punta con SendWebhook: lo encolado se firma, se envía y queda registrado', async () => {
    const outbox = new MemoryOutbox();
    const ledger = new MemoryDeliveryLedger();
    const post = vi.fn(async () => ({ status: 200, retryAfter: null }));
    const dispatcher = createDispatcher({
      outbox,
      endpoints: { resolve: async () => ({ url: 'https://hooks.ejemplo.test/entrada' }) },
      sender: new SendWebhook({
        signer: standardSigner({ secrets: ['whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE='] }),
        transport: { post },
        resolver: { resolve: async () => ['93.184.216.34'] },
        ledger,
        clock: { now: () => NOW },
        timer: { nowMs: () => 0 },
        random: { next: () => 0 },
      }),
    });
    await outbox.enqueue({ messageId: 'msg_1', endpointId: 'ep_1', payload: PAYLOAD, now: NOW });

    const result = await dispatcher.execute();

    expect(result.dispatched).toMatchObject([{ messageId: 'msg_1', state: 'delivered' }]);
    expect(post).toHaveBeenCalledTimes(1);
    expect(ledger.attempts()).toMatchObject([
      { messageId: 'msg_1', endpointId: 'ep_1', attempt: 1 },
    ]);
  });
});
