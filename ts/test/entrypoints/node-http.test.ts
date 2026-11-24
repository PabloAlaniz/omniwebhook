import { createHmac } from 'node:crypto';
import { createServer, request as httpRequest, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  createReceiver,
  hmacBodyScheme,
  type IncomingRequest,
  MemoryIdempotencyStore,
} from '../../src/index';
import { nodeIncomingRequest, writeNodeResponse } from '../../src/node';

const SECRET = 'secreto-de-prueba';
const BODY = '{"id":"evt_1","ñ":1}';
const firma = (body: string) => createHmac('sha256', SECRET).update(body).digest('hex');

describe('el adaptador de node:http', () => {
  let server: Server;
  let port: number;
  let seen: IncomingRequest | undefined;
  let processed = 0;

  beforeAll(async () => {
    const receive = createReceiver({
      verifier: hmacBodyScheme({ secrets: [SECRET], header: 'x-firma' }),
      store: new MemoryIdempotencyStore(),
      maxBodyBytes: 64,
    });
    server = createServer(async (request, response) => {
      seen = await nodeIncomingRequest(request, { maxBodyBytes: 64 });
      const reception = await receive.execute(seen, () => {
        processed += 1;
      });
      writeNodeResponse(response, reception);
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    port = (server.address() as AddressInfo).port;
  });

  afterAll(async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  });

  /** Manda las cabeceras como pares, para poder repetir una. */
  function post(headers: readonly string[], body: string, path = '/hooks'): Promise<number> {
    return new Promise((resolve, reject) => {
      const outgoing = httpRequest(
        {
          host: '127.0.0.1',
          port,
          path,
          method: 'POST',
          // Con las cabeceras como lista, Node no agrega ninguna por su cuenta.
          headers: [
            'Host',
            `127.0.0.1:${port}`,
            'Content-Length',
            String(Buffer.byteLength(body)),
            ...headers,
          ],
        },
        (response) => {
          response.resume();
          resolve(response.statusCode ?? 0);
        },
      );
      outgoing.on('error', reject);
      outgoing.end(body);
    });
  }

  it('recibe, verifica contra el cuerpo crudo y responde', async () => {
    expect(await post(['X-Firma', firma(BODY)], BODY, '/hooks?tipo=pago&tipo=alta')).toBe(200);
    expect(await post(['X-Firma', firma(BODY)], BODY)).toBe(200);

    expect(processed).toBe(1);
    expect(seen?.query).toEqual([]);
    expect(new TextDecoder().decode(seen?.body)).toBe(BODY);
  });

  it('conserva los parámetros repetidos de la URL', async () => {
    await post(['X-Firma', 'x'], BODY, '/hooks?tipo=pago&tipo=alta');

    expect(seen?.query).toEqual([
      ['tipo', 'pago'],
      ['tipo', 'alta'],
    ]);
  });

  it('una cabecera repetida se informa como ambigua', async () => {
    expect(await post(['X-Firma', firma(BODY), 'X-Firma', firma(BODY)], BODY)).toBe(401);
    expect(seen?.headers.filter(([name]) => name.toLowerCase() === 'x-firma')).toHaveLength(2);
  });

  it('deja de leer al pasarse del máximo y responde 413', async () => {
    const enorme = 'x'.repeat(4096);

    expect(await post(['X-Firma', firma(enorme)], enorme)).toBe(413);
    expect(seen?.body.byteLength).toBe(65);
  });

  it('un cuerpo del tamaño máximo se lee entero', async () => {
    const justo = 'y'.repeat(64);

    expect(await post(['X-Firma', firma(justo)], justo)).toBe(200);
  });
});

describe('nodeIncomingRequest con el cuerpo ya leído', () => {
  const request = { rawHeaders: ['X-Firma', 'abc'], url: undefined } as never;

  it('usa el cuerpo que leyó un middleware y no toca el flujo', async () => {
    const body = Buffer.from(BODY);

    const incoming = await nodeIncomingRequest(request, { body });

    expect(incoming).toEqual({ headers: [['X-Firma', 'abc']], query: [], body });
  });

  it('rechaza un cuerpo que ya fue interpretado', async () => {
    await expect(nodeIncomingRequest(request, { body: { id: 1 } as never })).rejects.toThrow(
      TypeError,
    );
  });

  it('rechaza un máximo inválido', async () => {
    await expect(nodeIncomingRequest(request, { maxBodyBytes: 0 })).rejects.toThrow(/maxBodyBytes/);
  });
});
