import { fromBase64 } from '../../crypto/web-crypto';

const PREFIX = 'whsec_';
const BASE64 = /^[A-Za-z0-9+/]*={0,2}$/;

/** La clave de un secreto del formato estándar, o `null` si no se puede usar (sección 5.1). */
export function standardKey(secret: string): Uint8Array | null {
  const encoded = secret.startsWith(PREFIX) ? secret.slice(PREFIX.length) : secret;
  if (encoded === '' || encoded.length % 4 !== 0 || !BASE64.test(encoded)) return null;
  return fromBase64(encoded);
}
