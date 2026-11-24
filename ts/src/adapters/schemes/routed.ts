import type { Verifier } from '../../application/ports';
import { ConfigurationError } from '../../domain/errors';
import { fieldValues } from '../../domain/incoming-request';
import { rejected } from '../../domain/verification';

/** Un emisor de los que atiende una misma URL. */
export interface VerifierRoute {
  /** La cabecera que sólo manda este emisor: su presencia decide que el pedido es suyo. */
  readonly header: string;
  readonly verifier: Verifier;
}

/**
 * Atiende a varios emisores en una misma URL (sección 4.7). El pedido se verifica con la
 * única ruta cuya cabecera llegó: sin ninguna es `missing` y con más de una, `ambiguous`.
 * Nunca prueba un esquema después de otro.
 */
export function routedVerifier(routes: readonly VerifierRoute[]): Verifier {
  if (routes.length === 0) throw new ConfigurationError('routes no puede estar vacío');
  const seen = new Set<string>();
  for (const { header } of routes) {
    const name = typeof header === 'string' ? header.trim().toLowerCase() : '';
    if (name === '') throw new ConfigurationError('header no puede estar vacío');
    if (seen.has(name)) throw new ConfigurationError(`header está repetido entre rutas: ${name}`);
    seen.add(name);
  }

  return {
    async verify(request) {
      const matching = routes.filter(
        ({ header }) => fieldValues(request.headers, header.trim()).length > 0,
      );
      const [route] = matching;
      if (route === undefined) return rejected('missing');
      if (matching.length > 1) return rejected('ambiguous');
      return route.verifier.verify(request);
    },
  };
}
