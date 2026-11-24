import { describe, expect, it, vi } from 'vitest';
import {
  type AttemptRecord,
  ConfigurationError,
  MemoryDeliveryLedger,
  SendWebhook,
  type SendWebhookDependencies,
  type TransportRequest,
  type TransportResponse,
  USER_AGENT,
} from '../../src/index';
import { standardScheme, standardSigner } from '../../src/standard';

const NOW = 1_700_000_000;
const SECRETS = ['whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE='];
const PAYLOAD = new TextEncoder().encode('{"type":"pedido.creado"}');
const PUBLIC = '93.184.216.34';

function build(
  overrides: Partial<SendWebhookDependencies> = {},
  response: TransportResponse = { status: 200, retryAfter: null },
) {
  const ledger = new MemoryDeliveryLedger();
  const post = vi.fn(async (_request: TransportRequest) => response);
  const resolve = vi.fn(async (_host: string): Promise<readonly string[]> => [PUBLIC]);
  let ms = 0;
  const send = new SendWebhook({
    signer: standardSigner({ secrets: SECRETS }),
    transport: { post },
    resolver: { resolve },
    ledger,
    clock: { now: () => NOW },
    timer: { nowMs: () => (ms += 40) },
    random: { next: () => 0 },
    ...overrides,
  });
  const execute = (attempt = 1, url = 'https://hooks.ejemplo.test/entrada') =>
    send.execute({
      endpoint: { id: 'ep_1', url },
      message: { id: 'msg_1', payload: PAYLOAD },
      attempt,
    });
  return { execute, post, resolve, ledger };
}

function sent(post: ReturnType<typeof build>['post']): TransportRequest {
  const request = post.mock.calls[0]?.[0];
  if (request === undefined) throw new Error('no se envió nada');
  return request;
}

describe('SendWebhook', () => {
  it('entrega: firma, envía a la dirección validada y registra el intento', async () => {
    const { execute, post, ledger } = build();

    const result = await execute();

    const expected: AttemptRecord = {
      messageId: 'msg_1',
      endpointId: 'ep_1',
      attempt: 1,
      at: NOW,
      deliveryClass: 'delivered',
      state: 'delivered',
      status: 200,
      problem: null,
      durationMs: 40,
      nextAt: null,
    };
    expect(result).toEqual(expected);
    expect(ledger.attempts()).toEqual([expected]);
    expect(sent(post)).toMatchObject({
      url: 'https://hooks.ejemplo.test/entrada',
      address: PUBLIC,
      body: PAYLOAD,
      timeoutSeconds: 20,
    });
  });

  it('lo que envía lo verifica un receptor con el mismo secreto', async () => {
    const { execute, post } = build();

    await execute();

    const { headers, body } = sent(post);
    const verification = await standardScheme({
      secrets: SECRETS,
      clock: { now: () => NOW },
    }).verify({
      headers: Object.entries(headers),
      query: [],
      body,
    });
    expect(verification).toEqual({ outcome: 'ok', eventKey: 'standard:msg_1', timestamp: NOW });
    expect(headers['content-type']).toBe('application/json');
  });

  it('las cabeceras extra no pisan la firma, el tipo de contenido ni user-agent', async () => {
    const { execute, post } = build({
      headers: {
        'X-Origen': 'tienda',
        'Webhook-Id': 'falso',
        'Content-Type': 'text/plain',
        'User-Agent': 'otro/1.0',
      },
      contentType: 'application/cloudevents+json',
    });

    await execute();

    const { headers } = sent(post);
    expect(headers).toMatchObject({
      'x-origen': 'tienda',
      'webhook-id': 'msg_1',
      'content-type': 'application/cloudevents+json',
      'user-agent': USER_AGENT,
    });
    expect(Object.keys(headers)).toHaveLength(6);
  });

  it('un fallo que se puede reintentar deja la entrega pendiente con su próximo intento', async () => {
    const { execute } = build({}, { status: 503, retryAfter: null });

    const result = await execute(2);

    expect(result).toMatchObject({
      deliveryClass: 'retryable',
      state: 'pending',
      status: 503,
      nextAt: NOW + 300,
    });
  });

  it('respeta retry-after y la variación', async () => {
    const { execute } = build({ random: { next: () => 0.5 } }, { status: 429, retryAfter: '1000' });

    const result = await execute(1);

    expect(result.nextAt).toBe(NOW + 1000 + 50);
  });

  it('usa la política de reintentos propia', async () => {
    const { execute } = build(
      { retryPolicy: { schedule: [7], jitterRatio: 0 } },
      { status: 500, retryAfter: null },
    );

    expect((await execute(1)).nextAt).toBe(NOW + 7);
    expect(await execute(2)).toMatchObject({ state: 'exhausted', nextAt: null });
  });

  it('después del último intento la entrega queda agotada', async () => {
    const { execute } = build({}, { failure: 'timeout' });

    const result = await execute(10);

    expect(result).toMatchObject({
      deliveryClass: 'retryable',
      state: 'exhausted',
      status: null,
      nextAt: null,
    });
  });

  it.each([
    [410, 'gone'],
    [404, 'rejected'],
    [302, 'rejected'],
  ] as const)('un estado %d no se reintenta: %s', async (status, state) => {
    const { execute } = build({}, { status, retryAfter: '5' });

    const result = await execute();

    expect(result).toMatchObject({ deliveryClass: state, state, status, nextAt: null });
  });

  it.each([
    ['esto no es una url', 'invalid_url'],
    ['http://hooks.ejemplo.test/entrada', 'scheme'],
    ['https://ana:clave@hooks.ejemplo.test/entrada', 'credentials'],
    ['https://127.0.0.1/entrada', 'blocked_address'],
  ] as const)('la política de URLs bloquea «%s» sin enviar nada', async (url, problem) => {
    const { execute, post } = build();

    const result = await execute(1, url);

    expect(result).toMatchObject({
      deliveryClass: 'blocked',
      state: 'blocked',
      problem,
      status: null,
      nextAt: null,
    });
    expect(post).not.toHaveBeenCalled();
  });

  it.each([
    [['10.0.0.5'], 'blocked_address'],
    [[PUBLIC, '169.254.169.254'], 'blocked_address'],
    [[], 'unresolved'],
  ] as const)('bloquea un nombre que resuelve a %j', async (addresses, problem) => {
    const { execute, post } = build({ resolver: { resolve: async () => addresses } });

    const result = await execute();

    expect(result).toMatchObject({ state: 'blocked', problem });
    expect(post).not.toHaveBeenCalled();
  });

  it('entrega a una dirección privada de una red permitida, conectando a esa dirección', async () => {
    const { execute, post } = build({
      allowedNetworks: ['192.168.0.0/16'],
      resolver: { resolve: async () => ['192.168.1.20'] },
    });

    const result = await execute();

    expect(result.state).toBe('delivered');
    expect(sent(post).address).toBe('192.168.1.20');
  });

  it('una red permitida no habilita los metadatos de la nube', async () => {
    const { execute, post } = build({
      allowedNetworks: ['0.0.0.0/0'],
      resolver: { resolve: async () => ['169.254.169.254'] },
    });

    expect(await execute()).toMatchObject({ state: 'blocked', problem: 'blocked_address' });
    expect(post).not.toHaveBeenCalled();
  });

  it('una red permitida inválida es un error de configuración al construir', () => {
    expect(() => build({ allowedNetworks: ['10.0.0.1/8'] })).toThrow(ConfigurationError);
  });

  it('con permiso expreso entrega a http', async () => {
    const { execute } = build({ allowHttp: true });

    expect((await execute(1, 'http://hooks.ejemplo.test/entrada')).state).toBe('delivered');
  });

  it('una dirección literal no se resuelve', async () => {
    const { execute, resolve, post } = build();

    await execute(1, 'https://93.184.216.34/entrada');

    expect(resolve).not.toHaveBeenCalled();
    expect(sent(post).address).toBe(PUBLIC);
  });

  it('si la resolución falla, cuenta como error de red y se reintenta', async () => {
    const { execute, post } = build({
      resolver: { resolve: () => Promise.reject(new Error('SERVFAIL')) },
    });

    const result = await execute();

    expect(result).toMatchObject({
      deliveryClass: 'retryable',
      state: 'pending',
      problem: null,
      nextAt: NOW + 5,
    });
    expect(post).not.toHaveBeenCalled();
  });

  it('si el transporte lanza, cuenta como error de red', async () => {
    const { execute } = build({
      transport: { post: () => Promise.reject(new Error('ECONNRESET')) },
    });

    expect(await execute()).toMatchObject({ deliveryClass: 'retryable', state: 'pending' });
  });

  it('el registro nunca guarda la URL de destino', async () => {
    const { execute, ledger } = build();

    await execute(1, 'https://hooks.ejemplo.test/entrada?token=secreto');

    expect(JSON.stringify(ledger.attempts())).not.toContain('ejemplo.test');
  });

  it('sin secretos no envía: es un error de configuración', async () => {
    const { execute, post, ledger } = build({ signer: standardSigner({ secrets: [] }) });

    await expect(execute()).rejects.toThrow(ConfigurationError);
    expect(post).not.toHaveBeenCalled();
    expect(ledger.attempts()).toEqual([]);
  });

  it('un payload del tamaño máximo se envía', async () => {
    const { execute, post } = build({ maxPayloadBytes: PAYLOAD.byteLength });

    expect((await execute()).state).toBe('delivered');
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('un payload más grande que el máximo no se firma, no se envía ni se registra', async () => {
    const sign = vi.fn();
    const { execute, post, ledger } = build({
      maxPayloadBytes: PAYLOAD.byteLength - 1,
      signer: { sign },
    });

    await expect(execute()).rejects.toThrow(ConfigurationError);
    expect(sign).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
    expect(ledger.attempts()).toEqual([]);
  });

  it('por defecto el máximo es de 256 KiB', async () => {
    const { post } = build();
    const send = (bytes: number) =>
      new SendWebhook({
        signer: standardSigner({ secrets: SECRETS }),
        transport: { post },
        resolver: { resolve: async () => [PUBLIC] },
        ledger: new MemoryDeliveryLedger(),
        clock: { now: () => NOW },
        timer: { nowMs: () => 0 },
        random: { next: () => 0 },
      }).execute({
        endpoint: { id: 'ep_1', url: 'https://hooks.ejemplo.test/entrada' },
        message: { id: 'msg_1', payload: new Uint8Array(bytes) },
        attempt: 1,
      });

    expect((await send(262_144)).state).toBe('delivered');
    await expect(send(262_145)).rejects.toThrow(/262144/);
  });

  it.each([0, -1, 1.5])('rechaza el número de intento %s', async (attempt) => {
    const { execute } = build();

    await expect(execute(attempt)).rejects.toThrow(/attempt/);
  });

  it.each([
    ['timeoutSeconds', { timeoutSeconds: 0 }],
    ['maxPayloadBytes', { maxPayloadBytes: 0 }],
    ['schedule', { retryPolicy: { schedule: [5, -1] } }],
    ['schedule', { retryPolicy: { schedule: [1.5] } }],
    ['maxDelaySeconds', { retryPolicy: { maxDelaySeconds: 0 } }],
    ['jitterRatio', { retryPolicy: { jitterRatio: -0.1 } }],
    ['jitterRatio', { retryPolicy: { jitterRatio: Number.NaN } }],
  ])('rechaza un %s inválido al construirse', (name, overrides) => {
    expect(() => build(overrides)).toThrow(new RegExp(name));
  });
});
