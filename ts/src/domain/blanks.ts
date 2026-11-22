/** Qué es un espacio (sección 3): el carácter de espacio o la tabulación, y nada más. */
const BLANK = /^[ \t]+|[ \t]+$/g;

/** El texto sin espacios al principio ni al final. */
export function trim(text: string): string {
  return text.replace(BLANK, '');
}
