import { createServer, type IncomingMessage, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { pinnedTo } from '../../src/adapters/transport/node';
import {
  createSender,
  fetchTransport,
  MemoryDeliveryLedger,
  randomMessageId,
} from '../../src/index';
import { createNodeSender, nodeDnsResolver, nodeTransport } from '../../src/node';
import { standardSigner } from '../../src/standard';

const BODY = new TextEncoder().encode('{"hola":"mundo"}');
const SECRETS = ['whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE='];

describe('fetchTransport', () => {
  const base = {
    url: 'https://hooks.ejemplo.test/entrada',
    address: '93.184.216.34',
    headers: { 'x-a': '1' },
    body: BODY,
    timeoutSeconds: 3,
  };

  it('hace un POST sin seguir redirecciones y devuelve estado y retry-after', async () => {
    const fake = vi.fn(
      async (_url: string | URL | Request, _init?: RequestInit) =>
        new Response('ignorado', { status: 429, headers: { 'retry-after': '30' } }),
    );

    const result = await fetchTransport({ fetch: fake }).post(base);

    expect(result).toEqual({ status: 429, retryAfter: '30' });
    const [url, init] = fake.mock.calls[0] ?? [];
    expect(url).toBe(base.url);
    expect(init).toMatchObject({ method: 'POST', redirect: 'manual', headers: { 'x-a': '1' } });
    expect(new Uint8Array(init?.body as ArrayBuffer)).toEqual(BODY);
  });

  it('sin retry-after devuelve null', async () => {
    const result = await fetchTransport({
      fetch: async () => new Response(null, { status: 204 }),
    }).post(base);

    expect(result).toEqual({ status: 204, retryAfter: null });
  });

  it.each([
    ['TimeoutError', 'timeout'],
    ['AbortError', 'timeout'],
    ['TypeError', 'network'],
  ] as const)('un error %s es %s', async (name, failure) => {
    const error = Object.assign(new Error('falló'), { name });

    const result = await fetchTransport({ fetch: () => Promise.reject(error) }).post(base);

    expect(result).toEqual({ failure });
  });

  it('algo lanzado que no es un Error es un error de red', async () => {
    const result = await fetchTransport({ fetch: () => Promise.reject('cadena') }).post(base);

    expect(result).toEqual({ failure: 'network' });
  });
});

describe('nodeTransport', () => {
  let server: Server;
  let port: number;
  const seen: Array<{
    method: string | undefined;
    host: string | undefined;
    firma: string | undefined;
    body: string;
  }> = [];

  async function read(request: IncomingMessage): Promise<string> {
    const chunks: Buffer[] = [];
    for await (const chunk of request) chunks.push(chunk as Buffer);
    return Buffer.concat(chunks).toString('utf8');
  }

  beforeAll(async () => {
    server = createServer(async (request, response) => {
      const body = await read(request);
      seen.push({
        method: request.method,
        host: request.headers.host,
        firma: request.headers['x-firma'] as string,
        body,
      });
      if (request.url === '/redirige') {
        response.writeHead(302, { location: '/otro' }).end();
      } else if (request.url === '/ocupado') {
        response.writeHead(503, { 'retry-after': '12' }).end();
      } else if (request.url === '/lento') {
        // No responde: el transporte tiene que cortar por tiempo.
      } else {
        response.writeHead(200).end('ok');
      }
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    port = (server.address() as AddressInfo).port;
  });

  afterAll(async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  });

  const request = (path: string, timeoutSeconds = 3) => ({
    // El nombre no existe: sólo llega si el transporte se conecta a la dirección fijada.
    url: `http://hooks.no-existe.invalid:${port}${path}`,
    address: '127.0.0.1',
    headers: { 'x-firma': 'abc', 'content-type': 'application/json' },
    body: BODY,
    timeoutSeconds,
  });

  it('se conecta a la dirección fijada y conserva el nombre del host', async () => {
    seen.length = 0;

    const result = await nodeTransport().post(request('/entrada'));

    expect(result).toEqual({ status: 200, retryAfter: null });
    expect(seen).toEqual([
      {
        method: 'POST',
        host: `hooks.no-existe.invalid:${port}`,
        firma: 'abc',
        body: '{"hola":"mundo"}',
      },
    ]);
  });

  it('no sigue redirecciones', async () => {
    seen.length = 0;

    const result = await nodeTransport().post(request('/redirige'));

    expect(result).toEqual({ status: 302, retryAfter: null });
    expect(seen).toHaveLength(1);
  });

  it('devuelve retry-after', async () => {
    expect(await nodeTransport().post(request('/ocupado'))).toEqual({
      status: 503,
      retryAfter: '12',
    });
  });

  it('corta por tiempo de espera', async () => {
    expect(await nodeTransport().post(request('/lento', 0.2))).toEqual({ failure: 'timeout' });
  });

  it('una conexión rechazada es un error de red', async () => {
    const closed = { ...request('/entrada'), url: 'http://hooks.no-existe.invalid:1/entrada' };

    expect(await nodeTransport().post(closed)).toEqual({ failure: 'network' });
  });

  it('createNodeSender entrega de punta a punta', async () => {
    seen.length = 0;
    const ledger = new MemoryDeliveryLedger();
    const send = createNodeSender({
      signer: standardSigner({ secrets: SECRETS }),
      ledger,
      allowHttp: true,
      // El servidor de prueba está en la máquina local, que la política bloquea: el
      // nombre resuelve a una dirección pública de mentira y el transporte la reemplaza.
      resolver: { resolve: async () => ['93.184.216.34'] },
      transport: { post: (r) => nodeTransport().post({ ...r, address: '127.0.0.1' }) },
    });

    const result = await send.execute({
      endpoint: { id: 'ep_1', url: `http://hooks.no-existe.invalid:${port}/entrada` },
      message: { id: randomMessageId(), payload: BODY },
      attempt: 1,
    });

    expect(result.state).toBe('delivered');
    expect(seen).toHaveLength(1);
    expect(ledger.attemptsOf(result.messageId, 'ep_1')).toHaveLength(1);
    expect(ledger.attemptsOf(result.messageId, 'otro')).toEqual([]);
  });
});

describe('la resolución fijada del transporte de Node', () => {
  it.each([
    ['93.184.216.34', 4],
    ['2606:4700:4700::1111', 6],
  ] as const)('responde %s sea cual sea el nombre', (address, family) => {
    const one = vi.fn();
    const all = vi.fn();

    pinnedTo(address)('otro-nombre.test', {}, one);
    pinnedTo(address)('otro-nombre.test', { all: true }, all);

    expect(one).toHaveBeenCalledWith(null, address, family);
    expect(all).toHaveBeenCalledWith(null, [{ address, family }]);
  });
});

describe('createNodeSender', () => {
  it('por defecto resuelve con el sistema y aplica la política de URLs', async () => {
    const send = createNodeSender({
      signer: standardSigner({ secrets: SECRETS }),
      ledger: new MemoryDeliveryLedger(),
    });

    const result = await send.execute({
      endpoint: { id: 'ep_local', url: 'https://localhost/entrada' },
      message: { id: 'msg_1', payload: BODY },
      attempt: 1,
    });

    expect(result).toMatchObject({ state: 'blocked', problem: 'blocked_address' });
  });
});

describe('nodeDnsResolver', () => {
  it('devuelve todas las direcciones del nombre', async () => {
    const resolver = nodeDnsResolver({
      lookup: async () => [{ address: '1.1.1.1' }, { address: '2606:4700:4700::1111' }],
    });

    expect(await resolver.resolve('hooks.ejemplo.test')).toEqual([
      '1.1.1.1',
      '2606:4700:4700::1111',
    ]);
  });

  it('un nombre que no existe da una lista vacía', async () => {
    const missing = Object.assign(new Error('no existe'), { code: 'ENOTFOUND' });
    const resolver = nodeDnsResolver({ lookup: () => Promise.reject(missing) });

    expect(await resolver.resolve('no-existe.invalid')).toEqual([]);
  });

  it('otro fallo de resolución se propaga', async () => {
    const failed = Object.assign(new Error('sin respuesta'), { code: 'EAI_AGAIN' });
    const resolver = nodeDnsResolver({ lookup: () => Promise.reject(failed) });

    await expect(resolver.resolve('hooks.ejemplo.test')).rejects.toBe(failed);
  });

  it('por defecto pregunta al sistema', async () => {
    const addresses = await nodeDnsResolver().resolve('localhost');

    expect(addresses.some((a) => a === '127.0.0.1' || a === '::1')).toBe(true);
  });
});

describe('createSender', () => {
  it('usa fetch, el reloj del sistema y la variación aleatoria por defecto', async () => {
    const original = globalThis.fetch;
    globalThis.fetch = vi.fn(async () => new Response(null, { status: 500 })) as typeof fetch;
    try {
      const send = createSender({
        signer: standardSigner({ secrets: SECRETS }),
        resolver: { resolve: async () => ['93.184.216.34'] },
        ledger: new MemoryDeliveryLedger(),
      });

      const result = await send.execute({
        endpoint: { id: 'ep_1', url: 'https://hooks.ejemplo.test/entrada' },
        message: { id: 'msg_1', payload: BODY },
        attempt: 1,
      });

      expect(result.state).toBe('pending');
      expect(result.nextAt).toBeGreaterThanOrEqual(result.at + 5);
      expect(Math.abs(result.at - Date.now() / 1000)).toBeLessThan(2);
    } finally {
      globalThis.fetch = original;
    }
  });
});

describe('randomMessageId', () => {
  it('no tiene puntos ni se repite', () => {
    const id = randomMessageId();

    expect(id).toMatch(/^msg_[0-9a-f]{32}$/);
    expect(randomMessageId()).not.toBe(id);
  });
});
