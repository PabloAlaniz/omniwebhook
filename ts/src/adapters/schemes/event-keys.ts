import { eventKey, fingerprintKey } from '../../domain/event-key';
import { sha256Hex } from '../crypto/web-crypto';

/** La clave de un evento sin identificador: la huella de su cuerpo (sección 4.6). */
export async function bodyFingerprint(scheme: string, body: Uint8Array): Promise<string> {
  return fingerprintKey(scheme, await sha256Hex(body));
}

/**
 * La clave de un evento cuyo identificador viaja en un campo del cuerpo, `id` si no se indica
 * otro. Si el cuerpo no es un objeto JSON con ese campo como texto no vacío, se usa la huella.
 */
export async function jsonIdKey(scheme: string, body: Uint8Array, field = 'id'): Promise<string> {
  const id = jsonId(body, field);
  return id === null ? bodyFingerprint(scheme, body) : eventKey(scheme, id);
}

/**
 * La clave de un aviso de Pub/Sub: el identificador del mensaje que envuelve (sección 5.14).
 * Se lee `message.messageId` y, si no sirve, `message.message_id`. Si ninguno es un texto no
 * vacío, se usa la huella.
 */
export async function pubsubMessageKey(scheme: string, body: Uint8Array): Promise<string> {
  const message = jsonObject(body)?.message;
  if (isObject(message)) {
    for (const field of ['messageId', 'message_id']) {
      const id = ownValue(message, field);
      if (typeof id === 'string' && id !== '') return eventKey(scheme, id);
    }
  }
  return bodyFingerprint(scheme, body);
}

function isObject(data: unknown): data is Record<string, unknown> {
  return typeof data === 'object' && data !== null && !Array.isArray(data);
}

/** El valor de un campo propio del objeto: lo heredado del prototipo no vino en el cuerpo. */
function ownValue(data: Record<string, unknown>, field: string): unknown {
  return Object.hasOwn(data, field) ? data[field] : undefined;
}

/** El cuerpo como objeto JSON estricto en UTF-8; `null` si no lo es. */
function jsonObject(body: Uint8Array): Record<string, unknown> | null {
  let data: unknown;
  try {
    // Con `ignoreBOM` la marca de orden de bytes queda en el texto y deja de ser JSON.
    data = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(body));
  } catch {
    return null;
  }
  return isObject(data) ? data : null;
}

function jsonId(body: Uint8Array, field: string): string | null {
  const data = jsonObject(body);
  const id = data === null ? undefined : ownValue(data, field);
  return typeof id === 'string' && id !== '' ? id : null;
}
