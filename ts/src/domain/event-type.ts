import { ConfigurationError } from './errors';

const SEGMENT = '[A-Za-z0-9_-]+';
const TYPE = new RegExp(`^${SEGMENT}(\\.${SEGMENT})*$`);
const PATTERN = new RegExp(`^(\\*|${SEGMENT}(\\.${SEGMENT})*(\\.\\*)?)$`);
const MAX_LENGTH = 256;

/** Si el texto es un tipo de evento (sección 8.6): `pedido.creado`, `pedido.item.agregado`. */
export function isEventType(text: string): boolean {
  return typeof text === 'string' && text.length <= MAX_LENGTH && TYPE.test(text);
}

/** Si el texto es un patrón de tipos: un tipo exacto, `grupo.*` o `*`. */
export function isEventPattern(text: string): boolean {
  return typeof text === 'string' && text.length <= MAX_LENGTH && PATTERN.test(text);
}

function matches(pattern: string, type: string): boolean {
  if (pattern === '*') return true;
  // `pedido.*` coincide con lo que empieza con `pedido.`, a cualquier profundidad.
  if (pattern.endsWith('.*')) return type.startsWith(pattern.slice(0, -1));
  return pattern === type;
}

/**
 * Si un destino que declaró esos patrones recibe un evento de ese tipo. Sin lista (`null` o
 * `undefined`) recibe todos; con una lista vacía, ninguno.
 *
 * Un tipo o un patrón que no cumple la gramática lanza `ConfigurationError`: es un error de
 * quien integra, no un evento que no coincide.
 */
export function subscribes(patterns: readonly string[] | null | undefined, type: string): boolean {
  if (!isEventType(type)) throw new ConfigurationError('el tipo de evento no es válido');
  if (patterns === null || patterns === undefined) return true;
  for (const pattern of patterns) {
    if (!isEventPattern(pattern)) {
      throw new ConfigurationError('un patrón de tipos de evento no es válido');
    }
  }
  return patterns.some((pattern) => matches(pattern, type));
}
