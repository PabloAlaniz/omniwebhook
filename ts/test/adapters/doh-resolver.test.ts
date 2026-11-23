import { describe, expect, it } from 'vitest';
import { createSender, dohResolver, MemoryDeliveryLedger } from '../../src/index';

type Answers = Record<string, unknown>;

/** Un servicio de DNS sobre HTTPS de mentira: responde según el tipo que se pide. */
function fakeDoh(byType: Answers, status = 200) {
  const asked: string[] = [];
  const fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input));
    asked.push(url.toString());
    expect(new Headers(init?.headers).get('accept')).toBe('application/dns-json');
    const body = byType[url.searchParams.get('type') ?? ''];
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
  }) as typeof globalThis.fetch;
  return { fetch, asked };
}

const A = { Status: 0, Answer: [{ name: 'hooks.ejemplo.test', type: 1, data: '93.184.216.34' }] };
const AAAA = {
  Status: 0,
  Answer: [
    { name: 'hooks.ejemplo.test', type: 5, data: 'otro.ejemplo.test.' },
    { name: 'otro.ejemplo.test', type: 28, data: '2606:2800:220:1::1' },
  ],
};

describe('dohResolver', () => {
  it('devuelve las direcciones IPv4 e IPv6, sin los alias', async () => {
    const { fetch, asked } = fakeDoh({ '1': A, '28': AAAA });

    const addresses = await dohResolver({ fetch }).resolve('hooks.ejemplo.test');

    expect(addresses).toEqual(['93.184.216.34', '2606:2800:220:1::1']);
    expect(asked).toEqual([
      'https://cloudflare-dns.com/dns-query?name=hooks.ejemplo.test&type=1',
      'https://cloudflare-dns.com/dns-query?name=hooks.ejemplo.test&type=28',
    ]);
  });

  it('usa el servicio indicado, conservando sus parámetros', async () => {
    const { fetch, asked } = fakeDoh({ '1': A, '28': { Status: 0 } });

    await dohResolver({ fetch, endpoint: 'https://dns.ejemplo.test/resolve?ct=x' }).resolve(
      'hooks.ejemplo.test',
    );

    expect(asked[0]).toBe('https://dns.ejemplo.test/resolve?ct=x&name=hooks.ejemplo.test&type=1');
  });

  it('un nombre que no existe da una lista vacía', async () => {
    const { fetch } = fakeDoh({ '1': { Status: 3 }, '28': { Status: 3 } });

    expect(await dohResolver({ fetch }).resolve('no-existe.invalid')).toEqual([]);
  });

  it('un nombre sin direcciones de un tipo devuelve las del otro', async () => {
    const { fetch } = fakeDoh({ '1': A, '28': { Status: 0 } });

    expect(await dohResolver({ fetch }).resolve('hooks.ejemplo.test')).toEqual(['93.184.216.34']);
  });

  it('un error del servidor de nombres lanza', async () => {
    const { fetch } = fakeDoh({ '1': { Status: 2 }, '28': { Status: 2 } });

    await expect(dohResolver({ fetch }).resolve('hooks.ejemplo.test')).rejects.toThrow('código 2');
  });

  it('un error HTTP del servicio lanza', async () => {
    const { fetch } = fakeDoh({ '1': A, '28': AAAA }, 503);

    await expect(dohResolver({ fetch }).resolve('hooks.ejemplo.test')).rejects.toThrow('503');
  });

  it.each([
    ['un cuerpo que no es JSON', 'no es json'],
    ['respuestas que no son una lista', { Status: 0, Answer: 'x' }],
  ])('%s lanza', async (_name, body) => {
    const { fetch } = fakeDoh({ '1': body, '28': body });

    await expect(dohResolver({ fetch }).resolve('hooks.ejemplo.test')).rejects.toThrow();
  });

  it('descarta las respuestas sin texto', async () => {
    const { fetch } = fakeDoh({
      '1': { Status: 0, Answer: [{ type: 1, data: 42 }, { type: 1 }] },
      '28': { Status: 3 },
    });

    expect(await dohResolver({ fetch }).resolve('hooks.ejemplo.test')).toEqual([]);
  });

  it('una consulta que tarda más que el plazo lanza', async () => {
    const fetch = ((_input: string, init?: RequestInit) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason));
      })) as typeof globalThis.fetch;

    await expect(
      dohResolver({ fetch, timeoutSeconds: 0.01 }).resolve('hooks.ejemplo.test'),
    ).rejects.toThrow();
  });
});

describe('createSender con dohResolver', () => {
  it('un nombre que resuelve a una dirección interna queda bloqueado sin enviar nada', async () => {
    const { fetch } = fakeDoh({
      '1': { Status: 0, Answer: [{ type: 1, data: '10.0.0.7' }] },
      '28': { Status: 0 },
    });
    let posted = false;
    const send = createSender({
      signer: { sign: async () => ({ outcome: 'signed', headers: {} }) },
      ledger: new MemoryDeliveryLedger(),
      resolver: dohResolver({ fetch }),
      transport: {
        post: async () => {
          posted = true;
          return { status: 200, retryAfter: null };
        },
      },
    });

    const result = await send.execute({
      endpoint: { id: 'ep_1', url: 'https://interno.ejemplo.test/hook' },
      message: { id: 'msg_1', payload: new Uint8Array() },
      attempt: 1,
    });

    expect(result).toMatchObject({ state: 'blocked', problem: 'blocked_address' });
    expect(posted).toBe(false);
  });
});
