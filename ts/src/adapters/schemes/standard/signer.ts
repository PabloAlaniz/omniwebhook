/**
 * Calcula la firma `v1` del formato estándar. Es la única costura por la que entra la
 * librería de referencia: cualquier implementación que pase los vectores sirve.
 */
export interface StandardSigner {
  /** Devuelve la firma con su versión: `v1,<base64>`. */
  sign(
    key: Uint8Array,
    id: string,
    timestamp: number,
    payload: Uint8Array,
  ): string | Promise<string>;
}
