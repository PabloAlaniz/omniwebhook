import type { HttpTransport, TransportRequest, TransportResponse } from '../../application/ports';

export interface FetchTransportOptions {
  /** La función `fetch` a usar. Por defecto, la global. */
  readonly fetch?: typeof fetch;
}

/**
 * Transporte sobre la API Fetch, para entornos sin acceso a sockets.
 *
 * `fetch` no permite elegir a qué dirección conectarse, así que este transporte no
 * puede fijar la dirección validada: entre la validación y la conexión el nombre
 * podría resolver a otra cosa. Donde haya sockets conviene `nodeTransport`.
 */
export function fetchTransport(options: FetchTransportOptions = {}): HttpTransport {
  const send = options.fetch ?? fetch;

  return {
    async post(request: TransportRequest): Promise<TransportResponse> {
      try {
        const response = await send(request.url, {
          method: 'POST',
          headers: request.headers,
          body: new Uint8Array(request.body),
          redirect: 'manual',
          signal: AbortSignal.timeout(request.timeoutSeconds * 1000),
        });
        await response.body?.cancel();
        return { status: response.status, retryAfter: response.headers.get('retry-after') };
      } catch (error) {
        const name = error instanceof Error ? error.name : '';
        return {
          failure: name === 'TimeoutError' || name === 'AbortError' ? 'timeout' : 'network',
        };
      }
    },
  };
}
