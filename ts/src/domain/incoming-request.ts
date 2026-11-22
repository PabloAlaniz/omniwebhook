import { trim } from './blanks';

/** Un par nombre-valor. Un mismo nombre puede aparecer en más de un par. */
export type Field = readonly [name: string, value: string];

/** El pedido entrante tal como llegó (sección 3 de la especificación). */
export interface IncomingRequest {
  /** Cabeceras. Los nombres no distinguen mayúsculas. */
  readonly headers: readonly Field[];
  /** Parámetros de la URL. */
  readonly query: readonly Field[];
  /** El cuerpo crudo, antes de interpretarlo. */
  readonly body: Uint8Array;
}

/**
 * Los valores de un campo, recortados y sin los vacíos: un valor vacío equivale a
 * que el campo no esté.
 */
export function fieldValues(fields: readonly Field[], name: string): readonly string[] {
  const wanted = name.toLowerCase();
  return fields
    .filter(([candidate]) => candidate.toLowerCase() === wanted)
    .map(([, value]) => trim(value))
    .filter((value) => value !== '');
}
