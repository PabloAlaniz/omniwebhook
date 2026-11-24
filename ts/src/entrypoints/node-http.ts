import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Reception } from '../application/receive-webhook';
import { positiveInteger } from '../domain/errors';
import type { Field, IncomingRequest } from '../domain/incoming-request';
import { DEFAULT_MAX_BODY_BYTES, httpStatusFor } from '../domain/reception';

export interface NodeIncomingRequestOptions {
  /**
   * El cuerpo crudo, si un middleware ya lo leyó (por ejemplo, `express.raw()`). Tiene que
   * ser el `Buffer` tal como llegó: un cuerpo ya interpretado como JSON no sirve.
   */
  readonly body?: Uint8Array;
  /**
   * Cuánto se lee del cuerpo, como mucho. Al pasarse se deja de leer y el pedido termina en
   * `too_large`. Tiene que ser igual o mayor que el `maxBodyBytes` del receptor.
   */
  readonly maxBodyBytes?: number;
}

/**
 * Convierte un pedido de `node:http` en el que entiende el núcleo. Sirve tal cual para los
 * frameworks montados sobre `node:http`, que exponen el mismo objeto.
 *
 * Lee el cuerpo crudo del flujo, así que hay que llamarla antes de que otra cosa lo consuma;
 * si un middleware ya lo leyó, se pasa en `body`. Las cabeceras repetidas se conservan, así
 * que se informan como `ambiguous`.
 */
export async function nodeIncomingRequest(
  request: IncomingMessage,
  options: NodeIncomingRequestOptions = {},
): Promise<IncomingRequest> {
  const maxBodyBytes = positiveInteger(
    'maxBodyBytes',
    options.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES,
  );
  if (options.body !== undefined && !(options.body instanceof Uint8Array)) {
    throw new TypeError('body tiene que ser el cuerpo crudo, en bytes');
  }

  const headers: Field[] = [];
  for (let index = 0; index + 1 < request.rawHeaders.length; index += 2) {
    headers.push([request.rawHeaders[index] ?? '', request.rawHeaders[index + 1] ?? '']);
  }
  const query = new URL(request.url ?? '/', 'http://localhost').searchParams;

  return {
    headers,
    query: [...query.entries()],
    body: options.body ?? (await readBody(request, maxBodyBytes)),
  };
}

/** Lee hasta un byte más que el máximo: alcanza para saber que se pasó, sin leer el resto. */
async function readBody(request: IncomingMessage, maxBodyBytes: number): Promise<Uint8Array> {
  const chunks: Uint8Array[] = [];
  let total = 0;
  for await (const chunk of request as AsyncIterable<Uint8Array>) {
    chunks.push(chunk);
    total += chunk.byteLength;
    if (total > maxBodyBytes) break;
  }
  const body = new Uint8Array(Math.min(total, maxBodyBytes + 1));
  let offset = 0;
  for (const chunk of chunks) {
    const part = chunk.subarray(0, body.byteLength - offset);
    body.set(part, offset);
    offset += part.byteLength;
  }
  return body;
}

/** Escribe la respuesta sugerida para un resultado (sección 6.3). El cuerpo no dice qué falló. */
export function writeNodeResponse(
  response: ServerResponse,
  reception: Pick<Reception, 'outcome'>,
): void {
  // Si quedó cuerpo sin leer, la conexión no se reutiliza: el resto no se va a consumir.
  if (reception.outcome === 'too_large') response.setHeader('connection', 'close');
  response.writeHead(httpStatusFor(reception.outcome)).end();
}
