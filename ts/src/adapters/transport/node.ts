import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { isIP, type LookupFunction } from 'node:net';
import type { HttpTransport, TransportRequest, TransportResponse } from '../../application/ports';

/** Una función de resolución que siempre responde la dirección ya validada. */
export function pinnedTo(address: string): LookupFunction {
  const family = isIP(address);
  return (_hostname, options, callback) => {
    if (typeof options === 'object' && options.all === true) {
      callback(null, [{ address, family }]);
    } else {
      callback(null, address, family);
    }
  };
}

/**
 * Transporte sobre los módulos de red de Node. Se conecta a la dirección validada y no
 * vuelve a resolver el nombre; el certificado se comprueba contra el nombre de la URL.
 */
export function nodeTransport(): HttpTransport {
  return {
    post(request: TransportRequest): Promise<TransportResponse> {
      return new Promise((resolve) => {
        const url = new URL(request.url);
        const send = url.protocol === 'https:' ? httpsRequest : httpRequest;
        const body = Buffer.from(request.body);

        const outgoing = send(
          url,
          {
            method: 'POST',
            headers: { ...request.headers, 'content-length': String(body.length) },
            lookup: pinnedTo(request.address),
            timeout: request.timeoutSeconds * 1000,
          },
          (response) => {
            response.resume();
            const header = response.headers['retry-after'];
            resolve({ status: response.statusCode ?? 0, retryAfter: header ?? null });
          },
        );
        outgoing.on('timeout', () => {
          resolve({ failure: 'timeout' });
          outgoing.destroy();
        });
        outgoing.on('error', () => resolve({ failure: 'network' }));
        outgoing.end(body);
      });
    },
  };
}
