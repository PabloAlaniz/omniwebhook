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

function jsonId(body: Uint8Array, field: string): string | null {
  let data: unknown;
  try {
    // Con `ignoreBOM` la marca de orden de bytes queda en el texto y deja de ser JSON.
    data = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(body));
  } catch {
    return null;
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null;
  if (!Object.hasOwn(data, field)) return null;
  const id = (data as Record<string, unknown>)[field];
  return typeof id === 'string' && id !== '' ? id : null;
}
