import type { Verifier } from '../../application/ports';
import { eventKey } from '../../domain/event-key';
import { pickSingles } from '../../domain/fields';
import { fieldValues } from '../../domain/incoming-request';
import { parseTimestamp } from '../../domain/timestamp';
import type { SchemeConfig } from './scheme-verifier';
import { tokenVerifier } from './shared-token';

const MESSAGE_NUMBER_DIGITS = 20;

/**
 * Verifica los avisos de un canal de notificación de Google: Calendar, Drive y otras APIs
 * (sección 5.13).
 *
 * El secreto es el token con el que se creó el canal. El token no cubre el cuerpo ni las demás
 * cabeceras: conviene tratar el aviso como una señal y consultar los cambios a la API.
 */
export function googleChannelScheme(config: SchemeConfig): Verifier {
  return tokenVerifier((request) => {
    const fields = pickSingles({
      token: fieldValues(request.headers, 'x-goog-channel-token'),
      channel: fieldValues(request.headers, 'x-goog-channel-id'),
      number: fieldValues(request.headers, 'x-goog-message-number'),
    });
    if (typeof fields === 'string') return fields;
    const { channel, number } = fields;
    if (parseTimestamp(number, MESSAGE_NUMBER_DIGITS) === null) return 'malformed';

    return {
      timestamp: null,
      received: [fields.token],
      // El número va tal como llegó: es lo que distingue un aviso de otro dentro del canal.
      eventKey: () => eventKey('google-channel', `${channel}:${number}`),
    };
  }, config);
}
