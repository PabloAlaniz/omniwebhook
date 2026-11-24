/** Primitivas criptográficas sobre Web Crypto: corre igual en Node y en entornos edge. */

const encoder = new TextEncoder();

export function utf8(text: string): Uint8Array {
  return encoder.encode(text);
}

export function concat(...parts: readonly Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

/** Copia a un búfer propio: Web Crypto no acepta vistas sobre memoria compartida. */
function owned(bytes: Uint8Array): Uint8Array<ArrayBuffer> {
  return new Uint8Array(bytes);
}

export async function hmacSha256(key: Uint8Array, message: Uint8Array): Promise<Uint8Array> {
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    owned(key),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  return new Uint8Array(await crypto.subtle.sign('HMAC', cryptoKey, owned(message)));
}

export async function sha256Hex(message: Uint8Array): Promise<string> {
  return toHex(new Uint8Array(await crypto.subtle.digest('SHA-256', owned(message))));
}

export function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function toBase64(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes));
}

export function fromBase64(text: string): Uint8Array {
  return Uint8Array.from(atob(text), (char) => char.charCodeAt(0));
}

/** Compara dos textos sin cortar en la primera diferencia (sección 4.3). */
export function equalInConstantTime(a: string, b: string): boolean {
  const x = utf8(a);
  const y = utf8(b);
  let difference = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    difference |= (x[i] ?? 0) ^ (y[i] ?? 0);
  }
  return difference === 0;
}

export async function sha256(message: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', owned(message)));
}

/**
 * Si `signature` es la firma Ed25519 de `message` para la clave pública cruda `publicKey`.
 * Un error de la plataforma al cargar la clave o al verificar cuenta como que no verifica.
 */
export async function verifiesEd25519(
  publicKey: Uint8Array,
  signature: Uint8Array,
  message: Uint8Array,
): Promise<boolean> {
  try {
    const key = await crypto.subtle.importKey('raw', owned(publicKey), { name: 'Ed25519' }, false, [
      'verify',
    ]);
    return await crypto.subtle.verify({ name: 'Ed25519' }, key, owned(signature), owned(message));
  } catch {
    return false;
  }
}

const STRICT_BASE64 = /^[A-Za-z0-9+/]*={0,2}$/;

/** Decodifica base64 estándar con relleno; `null` si el texto no lo es. */
export function fromStrictBase64(text: string): Uint8Array | null {
  if (text.length % 4 !== 0 || !STRICT_BASE64.test(text)) return null;
  try {
    return fromBase64(text);
  } catch {
    return null;
  }
}

const HEX = /^(?:[0-9A-Fa-f]{2})*$/;

/** Decodifica hexadecimal, en mayúsculas o minúsculas; `null` si el texto no lo es. */
export function fromHex(text: string): Uint8Array | null {
  if (!HEX.test(text)) return null;
  const bytes = new Uint8Array(text.length / 2);
  for (let index = 0; index < bytes.length; index++) {
    bytes[index] = Number.parseInt(text.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}
