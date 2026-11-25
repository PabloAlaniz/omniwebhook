import type { Verifier } from '../../application/ports';
import { pickSingles } from '../../domain/fields';
import { fieldValues } from '../../domain/incoming-request';
import { pubsubMessageKey } from './event-keys';
import type { SchemeConfig } from './scheme-verifier';
import { checkedName, tokenVerifier } from './shared-token';

export interface GooglePubSubOptions extends SchemeConfig {
  /** El parámetro de la URL de entrega que trae el token. Por defecto, `token`. */
  readonly query?: string;
}

/**
 * Verifica los avisos de una suscripción de entrega de Pub/Sub, como los de Gmail
 * (sección 5.14).
 *
 * El secreto es el token que va en la URL de entrega de la suscripción. No se verifica el token
 * de identidad (JWT) de la cabecera `authorization`. El token no cubre el cuerpo: conviene
 * tratar el aviso como una señal y consultar los cambios a la API. Un token en la URL suele
 * quedar en los logs de acceso.
 */
export function googlePubSubScheme(options: GooglePubSubOptions): Verifier {
  const query = checkedName('query', options.query ?? 'token');

  return tokenVerifier((request) => {
    const fields = pickSingles({ token: fieldValues(request.query, query) });
    if (typeof fields === 'string') return fields;
    return {
      timestamp: null,
      received: [fields.token],
      eventKey: () => pubsubMessageKey('google-pubsub', request.body),
    };
  }, options);
}
