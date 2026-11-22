/** Las marcas en segundos tienen hasta 11 dígitos. */
export const SECONDS_DIGITS = 11;
/** Un emisor que puede mandar milisegundos usa hasta 15. */
export const SECONDS_OR_MILLIS_DIGITS = 15;

const MILLIS_THRESHOLD = 100_000_000_000;

/** Interpreta un entero decimal sin signo de hasta `maxDigits` dígitos; si no lo es, `null`. */
export function parseTimestamp(text: string, maxDigits: number): number | null {
  if (text.length === 0 || text.length > maxDigits) return null;
  for (const char of text) {
    if (char < '0' || char > '9') return null;
  }
  return Number(text);
}

/** Lleva a segundos una marca que puede venir en milisegundos (sección 5.3). */
export function toSeconds(raw: number): number {
  return raw >= MILLIS_THRESHOLD ? Math.floor(raw / 1000) : raw;
}
