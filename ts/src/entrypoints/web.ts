import type { Reception } from '../application/receive-webhook';
import type { IncomingRequest } from '../domain/incoming-request';
import { httpStatusFor } from '../domain/reception';

/**
 * Convierte un `Request` de la API Fetch en el pedido que entiende el núcleo.
 *
 * Lee el cuerpo crudo: hay que llamarla antes de que otra cosa lo consuma. La API
 * Fetch une con comas las cabeceras repetidas, así que una cabecera repetida no se
 * informa como `ambiguous` sino que deja de coincidir con la firma.
 */
export async function toIncomingRequest(request: Request): Promise<IncomingRequest> {
  return {
    headers: [...request.headers.entries()],
    query: [...new URL(request.url).searchParams.entries()],
    body: new Uint8Array(await request.arrayBuffer()),
  };
}

/** La respuesta sugerida para un resultado (sección 6.3). El cuerpo no dice qué falló. */
export function toResponse(reception: Pick<Reception, 'outcome'>): Response {
  return new Response(null, { status: httpStatusFor(reception.outcome) });
}
