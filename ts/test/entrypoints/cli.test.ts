import { describe, expect, it, vi } from 'vitest';
import { type CliIo, runCli } from '../../src/cli';

const SECRET = 'secreto-sintetico';
const BODY = '{"id":"evt_1","ñ":true}';

function io(overrides: Partial<CliIo> = {}, files: Record<string, string> = {}) {
  const out: string[] = [];
  const err: string[] = [];
  const all: CliIo = {
    env: { FIRMA: SECRET, VACIA: '' },
    read: (path) => {
      const content = { 'cuerpo.json': BODY, ...files }[path];
      if (content === undefined) throw new Error(`no existe ${path}`);
      return new TextEncoder().encode(content);
    },
    out: (line) => out.push(line),
    err: (line) => err.push(line),
    fetch: vi.fn(async () => new Response(null, { status: 204 })),
    ...overrides,
  };
  return { io: all, out, err };
}

const SIGN = ['--scheme', 'stripe', '--secret-env', 'FIRMA', '--body', 'cuerpo.json'];

describe('la línea de comandos', () => {
  it('sin comando muestra la ayuda y termina con 2', async () => {
    const { io: cli, out } = io();

    expect(await runCli([], cli)).toBe(2);
    expect(await runCli(['--help'], cli)).toBe(0);
    expect(out[0]).toContain('omniwebhook <comando>');
  });

  it('lo que firma sign lo acepta verify', async () => {
    const signing = io();
    expect(await runCli(['sign', ...SIGN], signing.io)).toBe(0);
    const request = signing.out.join('\n');
    expect(JSON.parse(request)).toMatchObject({ body: BODY, query: [] });

    const verifying = io({}, { '-': request });
    const code = await runCli(
      ['verify', '--scheme', 'stripe', '--secret-env', 'FIRMA', '--request', '-'],
      verifying.io,
    );

    expect(code).toBe(0);
    expect(JSON.parse(verifying.out[0] ?? '')).toMatchObject({
      outcome: 'ok',
      eventKey: 'stripe:evt_1',
    });
  });

  it('verify termina con 1 si el pedido no verifica, y dice el resultado', async () => {
    const signing = io();
    await runCli(['sign', ...SIGN, '--timestamp', '1'], signing.io);
    const verifying = io({}, { 'pedido.json': signing.out.join('\n') });

    const code = await runCli(
      ['verify', '--scheme', 'stripe', '--secret-env', 'FIRMA', '--request', 'pedido.json'],
      verifying.io,
    );

    expect(code).toBe(1);
    expect(verifying.out).toEqual(['{"outcome":"stale"}']);
  });

  it.each([
    ['standard', 'ESTANDAR', []],
    ['slack', 'FIRMA', []],
    ['tiktok', 'FIRMA', []],
    ['mercadopago', 'FIRMA', ['--id', 'req-1', '--data-id', 'abc']],
    ['github', 'FIRMA', ['--id', 'entrega-1']],
    ['creem', 'FIRMA', []],
    ['shopify', 'FIRMA', []],
    ['hmac-body', 'FIRMA', ['--header', 'x-firma', '--prefix', 'v1=', '--encoding', 'base64']],
  ])('%s: firma y verifica', async (scheme, variable, extra) => {
    const env = { FIRMA: SECRET, ESTANDAR: 'whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE=' };
    const common = ['--scheme', scheme, '--secret-env', variable, ...extra];
    const signing = io({ env });
    expect(await runCli(['sign', ...common, '--body', 'cuerpo.json'], signing.io)).toBe(0);

    const verifying = io({ env }, { '-': signing.out.join('\n') });
    const verifyOptions = common.filter(
      (_, index) => !['--id', '--data-id'].includes(common[index - (index % 2)] ?? ''),
    );

    expect(await runCli(['verify', ...verifyOptions, '--request', '-'], verifying.io)).toBe(0);
  });

  it('send manda el pedido firmado y termina según el estado', async () => {
    const fetchOk = vi.fn(async (_url: Parameters<typeof fetch>[0], _init?: RequestInit) => {
      return new Response('ignorado', { status: 200 });
    });
    const sending = io({ fetch: fetchOk as typeof fetch });
    const args = ['send', ...SIGN, '--url', 'http://localhost:3000/webhooks?a=1'];

    expect(await runCli(args, sending.io)).toBe(0);
    expect(sending.out).toEqual(['200']);
    const [url, init] = fetchOk.mock.calls[0] ?? [];
    expect(String(url)).toBe('http://localhost:3000/webhooks?a=1');
    expect(new Headers(init?.headers).get('stripe-signature')).toMatch(/^t=\d+,v1=[0-9a-f]{64}$/);
    expect(new TextDecoder().decode(init?.body as Uint8Array)).toBe(BODY);

    const failing = io({
      fetch: (async () => new Response(null, { status: 401 })) as typeof fetch,
    });
    expect(await runCli(args, failing.io)).toBe(1);
    expect(failing.out).toEqual(['401']);
  });

  it('send agrega a la URL los parámetros que firma el emisor', async () => {
    const fetched = vi.fn(
      async (_url: Parameters<typeof fetch>[0]) => new Response(null, { status: 200 }),
    );
    const sending = io({ fetch: fetched as typeof fetch });

    await runCli(
      [
        'send',
        '--scheme',
        'mercadopago',
        '--secret-env',
        'FIRMA',
        '--body',
        'cuerpo.json',
        '--data-id',
        'abc',
        '--url',
        'http://localhost:3000/webhooks',
      ],
      sending.io,
    );

    expect(String(fetched.mock.calls[0]?.[0])).toBe('http://localhost:3000/webhooks?data.id=abc');
  });

  it('un fallo de red en send termina con 1 y lo dice', async () => {
    const failing = io({
      fetch: (async () => {
        throw new Error('conexión rechazada');
      }) as typeof fetch,
    });

    expect(await runCli(['send', ...SIGN, '--url', 'http://localhost:9/'], failing.io)).toBe(1);
    expect(failing.err).toEqual(['omniwebhook: conexión rechazada']);
  });

  it.each([
    ['un comando desconocido', ['otro'], /comando desconocido/],
    ['una opción desconocida', ['sign', ...SIGN, '--otra', 'x'], /otra/],
    ['sin esquema', ['sign', '--secret-env', 'FIRMA', '--body', 'cuerpo.json'], /falta --scheme/],
    ['sin cuerpo', ['sign', '--scheme', 'stripe', '--secret-env', 'FIRMA'], /falta --body/],
    [
      'una variable vacía',
      ['sign', ...SIGN.slice(0, 3), 'VACIA', '--body', 'cuerpo.json'],
      /VACIA/,
    ],
    ['una variable que no existe', ['sign', ...SIGN.slice(0, 3), 'NO', '--body', '-'], /NO está/],
    ['una marca que no es un número', ['sign', ...SIGN, '--timestamp', 'ayer'], /--timestamp/],
    ['una codificación inválida', ['sign', ...SIGN, '--encoding', 'rot13'], /--encoding/],
    ['una URL inválida', ['send', ...SIGN, '--url', 'no es una url'], /URL/i],
    [
      'un esquema desconocido al verificar',
      ['verify', '--scheme', 'otro', '--secret-env', 'FIRMA', '--request', 'cuerpo.json'],
      /esquema desconocido/,
    ],
  ])('con %s termina con 2', async (_what, argv, message) => {
    const { io: cli, err } = io();

    expect(await runCli(argv, cli)).toBe(2);
    expect(err.join('\n')).toMatch(message);
    expect(err.join('\n')).not.toContain(SECRET);
  });

  it.each([
    ['algo que no es JSON', 'no es json', /no es JSON/],
    ['un cuerpo que no es texto', '{"headers":[],"body":7}', /body/],
    ['cabeceras que no son pares', '{"headers":[["a"]],"body":""}', /headers/],
    ['un JSON que no es un objeto', '7', /body/],
  ])('verify rechaza %s', async (_what, saved, message) => {
    const { io: cli, err } = io({}, { 'pedido.json': saved });
    const argv = [
      'verify',
      '--scheme',
      'stripe',
      '--secret-env',
      'FIRMA',
      '--request',
      'pedido.json',
    ];

    expect(await runCli(argv, cli)).toBe(2);
    expect(err.join('\n')).toMatch(message);
  });

  it('un archivo que no se puede leer termina con 1', async () => {
    const { io: cli, err } = io();

    expect(await runCli(['sign', ...SIGN.slice(0, 5), 'no-existe.json'], cli)).toBe(1);
    expect(err).toEqual(['omniwebhook: no existe no-existe.json']);
  });
});
