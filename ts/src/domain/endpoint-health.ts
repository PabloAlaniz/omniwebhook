import { positiveInteger } from './errors';

/** Los fallos de un destino desde su última entrega (sección 8.5). */
export interface FailureSummary {
  /** Cuántos intentos fallaron desde la última entrega. */
  readonly failures: number;
  /** El menor `at` entre ellos; `null` si no hay ninguno. */
  readonly failingSince: number | null;
  /** Si alguno fue un 410. */
  readonly gone: boolean;
}

export interface HealthPolicy {
  /** Cuánto tiene que llevar fallando para darlo por caído, en segundos. Por defecto, cinco días. */
  readonly windowSeconds?: number;
  /** Cuántos fallos hacen falta, como mínimo. Por defecto, 5. */
  readonly minFailures?: number;
}

export const DEFAULT_HEALTH_WINDOW_SECONDS = 432_000;
export const DEFAULT_HEALTH_MIN_FAILURES = 5;

export type EndpointHealth =
  | { readonly status: 'healthy' | 'failing'; readonly reason: null }
  | { readonly status: 'disabled'; readonly reason: 'gone' | 'failing' };

/** Comprueba una política al configurarla, para no descubrir el error al despachar. */
export function checkHealthPolicy(policy: HealthPolicy): Required<HealthPolicy> {
  return {
    windowSeconds: positiveInteger(
      'windowSeconds',
      policy.windowSeconds ?? DEFAULT_HEALTH_WINDOW_SECONDS,
    ),
    minFailures: positiveInteger('minFailures', policy.minFailures ?? DEFAULT_HEALTH_MIN_FAILURES),
  };
}

/**
 * El resumen de fallos de un destino a partir de sus intentos, en el orden en que se
 * registraron. Sólo cuentan los de `since` en adelante y posteriores a la última entrega.
 */
export function summarizeFailures(
  attempts: ReadonlyArray<{ readonly at: number; readonly deliveryClass: string }>,
  since = 0,
): FailureSummary {
  let failures = 0;
  let failingSince: number | null = null;
  let gone = false;
  for (const attempt of attempts) {
    if (attempt.at < since) continue;
    if (attempt.deliveryClass === 'delivered') {
      failures = 0;
      failingSince = null;
      gone = false;
      continue;
    }
    failures += 1;
    failingSince = failingSince === null ? attempt.at : Math.min(failingSince, attempt.at);
    gone ||= attempt.deliveryClass === 'gone';
  }
  return { failures, failingSince, gone };
}

/** La salud de un destino: hacen falta cantidad y tiempo para darlo por caído. */
export function endpointHealth(
  summary: FailureSummary,
  now: number,
  policy: HealthPolicy = {},
): EndpointHealth {
  const { windowSeconds, minFailures } = checkHealthPolicy(policy);
  if (summary.gone) return { status: 'disabled', reason: 'gone' };
  if (summary.failingSince === null || summary.failures === 0) {
    return { status: 'healthy', reason: null };
  }
  return summary.failures >= minFailures && now - summary.failingSince >= windowSeconds
    ? { status: 'disabled', reason: 'failing' }
    : { status: 'failing', reason: null };
}
