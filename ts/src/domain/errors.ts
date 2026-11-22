/**
 * Error de configuración: lo lanza un constructor cuando recibe una opción inválida.
 * Nunca lo provoca un pedido entrante; eso siempre termina en un resultado tipado.
 */
export class ConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigurationError';
  }
}

/** Devuelve `value` si es un entero mayor que cero; si no, lanza `ConfigurationError`. */
export function positiveInteger(name: string, value: number): number {
  if (!Number.isInteger(value) || value <= 0) {
    throw new ConfigurationError(`${name} tiene que ser un entero mayor que cero`);
  }
  return value;
}
