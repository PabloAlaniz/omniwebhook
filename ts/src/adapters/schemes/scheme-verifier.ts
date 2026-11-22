import type { Clock, Verifier } from '../../application/ports';
import { positiveInteger } from '../../domain/errors';
import { DEFAULT_TOLERANCE_SECONDS, isFresh } from '../../domain/freshness';
import type { IncomingRequest } from '../../domain/incoming-request';
import { type Rejection, rejected, type Verification } from '../../domain/verification';
import { systemClock } from '../clock/system-clock';
import { equalInConstantTime } from '../crypto/web-crypto';

/** Lo que un esquema saca de un pedido bien formado. */
export interface Reading {
  /** La marca de tiempo firmada, en segundos; `null` si el esquema no lleva una. */
  readonly timestamp: number | null;
  /** Las firmas recibidas, ya normalizadas para compararlas como texto. */
  readonly received: readonly string[];
  /** La clave del evento. Sólo se calcula si la firma resulta válida. */
  eventKey(): string | Promise<string>;
}

/** Lo que distingue a un esquema de otro. El recorrido de la sección 4.1 es común a todos. */
export interface SchemeDefinition<R extends Reading> {
  /** Convierte un secreto en la clave del HMAC; `null` si no se puede usar. */
  keyOf(secret: string): Uint8Array | null;
  /** Lee el pedido, o dice por qué no se puede: `missing`, `ambiguous` o `malformed`. */
  read(request: IncomingRequest): R | Extract<Rejection, 'missing' | 'ambiguous' | 'malformed'>;
  /** La firma que debería haber llegado para esta clave, como texto. */
  expected(key: Uint8Array, reading: R, request: IncomingRequest): string | Promise<string>;
}

export interface SchemeConfig {
  /** Los secretos aceptados. La firma vale si coincide con cualquiera (rotación). */
  readonly secrets: readonly string[];
  readonly clock?: Clock;
}

export interface TimedSchemeConfig extends SchemeConfig {
  /** Cuánto puede alejarse de ahora la marca de tiempo, en segundos. Por defecto, 300. */
  readonly toleranceSeconds?: number;
}

/** Arma el verificador de un esquema aplicando las comprobaciones en el orden de la sección 4.1. */
export function schemeVerifier<R extends Reading>(
  definition: SchemeDefinition<R>,
  config: TimedSchemeConfig,
): Verifier {
  const toleranceSeconds = positiveInteger(
    'toleranceSeconds',
    config.toleranceSeconds ?? DEFAULT_TOLERANCE_SECONDS,
  );
  const clock = config.clock ?? systemClock;
  const keys = usableKeys(definition, config.secrets);

  return {
    async verify(request: IncomingRequest): Promise<Verification> {
      if (keys === null) return rejected('unconfigured');

      const reading = definition.read(request);
      if (typeof reading === 'string') return rejected(reading);

      let valid = false;
      for (const key of keys) {
        const expected = await definition.expected(key, reading, request);
        for (const received of reading.received) {
          if (equalInConstantTime(expected, received)) valid = true;
        }
      }
      if (!valid) return rejected('invalid');

      const { timestamp } = reading;
      if (timestamp !== null && !isFresh(clock.now(), timestamp, toleranceSeconds)) {
        return rejected('stale');
      }
      return { outcome: 'ok', eventKey: await reading.eventKey(), timestamp };
    },
  };
}

/** Las claves de todos los secretos, o `null` si no hay ninguno o alguno no se puede usar. */
function usableKeys<R extends Reading>(
  definition: SchemeDefinition<R>,
  secrets: readonly string[],
): readonly Uint8Array[] | null {
  if (secrets.length === 0) return null;
  const keys: Uint8Array[] = [];
  for (const secret of secrets) {
    const key = secret === '' ? null : definition.keyOf(secret);
    if (key === null) return null;
    keys.push(key);
  }
  return keys;
}
