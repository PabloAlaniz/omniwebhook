import type { Field } from './incoming-request';

/**
 * Parte una cabecera con pares `clave=valor` separados por comas (sección 4.5.1).
 * Una parte sin `=`, con la clave vacía o con el valor vacío se ignora.
 */
export function parsePairs(
  text: string,
  options: { lowercaseKeys?: boolean } = {},
): readonly Field[] {
  const pairs: Field[] = [];
  for (const piece of text.split(',')) {
    const cut = piece.indexOf('=');
    if (cut === -1) continue;
    const key = piece.slice(0, cut).trim();
    const value = piece.slice(cut + 1).trim();
    if (key === '' || value === '') continue;
    pairs.push([options.lowercaseKeys ? key.toLowerCase() : key, value]);
  }
  return pairs;
}

/** Los valores de una clave, comparada tal cual. */
export function pairValues(pairs: readonly Field[], key: string): readonly string[] {
  return pairs.filter(([candidate]) => candidate === key).map(([, value]) => value);
}
