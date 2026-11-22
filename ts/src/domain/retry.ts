import { ConfigurationError, positiveInteger } from './errors';

/** Las esperas entre intentos, en segundos. Con esta lista hay diez intentos (sección 8.3). */
export const DEFAULT_RETRY_SCHEDULE: readonly number[] = [
  5, 300, 1800, 7200, 18_000, 36_000, 50_400, 72_000, 86_400,
];
export const DEFAULT_MAX_DELAY_SECONDS = 86_400;
export const DEFAULT_JITTER_RATIO = 0.1;

/** La política de reintentos es un dato. Lo que no se indica toma el valor por defecto. */
export interface RetryPolicy {
  readonly schedule?: readonly number[];
  readonly maxDelaySeconds?: number;
  readonly jitterRatio?: number;
}

export interface NextAttemptInput {
  /** El número del intento que acaba de fallar. El primero es el 1. */
  readonly attempt: number;
  readonly now: number;
  /** Un número en [0, 1) para la variación. */
  readonly random: number;
  /** El valor de la cabecera `retry-after` de la respuesta, si la hubo. */
  readonly retryAfter?: string | null;
  readonly policy?: RetryPolicy;
}

export type NextAttempt =
  | { readonly exhausted: true }
  | { readonly exhausted: false; readonly delaySeconds: number; readonly nextAt: number };

/** Comprueba una política al configurarla, para no descubrir el error en un reintento. */
export function checkRetryPolicy(policy: RetryPolicy): void {
  for (const delay of policy.schedule ?? []) {
    if (!Number.isInteger(delay) || delay < 0) {
      throw new ConfigurationError('schedule tiene que ser una lista de enteros no negativos');
    }
  }
  if (policy.maxDelaySeconds !== undefined)
    positiveInteger('maxDelaySeconds', policy.maxDelaySeconds);
  if (policy.jitterRatio !== undefined && !(policy.jitterRatio >= 0)) {
    throw new ConfigurationError('jitterRatio no puede ser negativo');
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const HTTP_DATE =
  /^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), ([0-9]{2}) ([A-Z][a-z]{2}) ([0-9]{4}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) GMT$/;
const WHOLE_SECONDS = /^[0-9]+$/;

/** La época Unix de una fecha HTTP como `Sun, 06 Nov 1994 08:49:37 GMT`; `null` si no lo es. */
function parseHttpDate(text: string): number | null {
  const match = HTTP_DATE.exec(text);
  if (match === null) return null;
  const [, day, monthName, year, hour, minute, second] = match;
  const month = MONTHS.indexOf(monthName ?? '');
  const date = new Date(
    Date.UTC(Number(year), month, Number(day), Number(hour), Number(minute), Number(second)),
  );
  const real =
    month !== -1 &&
    date.getUTCDate() === Number(day) &&
    date.getUTCHours() === Number(hour) &&
    date.getUTCMinutes() === Number(minute) &&
    date.getUTCSeconds() === Number(second);
  return real ? date.getTime() / 1000 : null;
}

/** Los segundos que pide `retry-after`; `null` si falta, no se entiende o ya pasó. */
export function retryAfterSeconds(value: string | null | undefined, now: number): number | null {
  if (value === null || value === undefined) return null;
  if (WHOLE_SECONDS.test(value)) return Number(value);
  const at = parseHttpDate(value);
  return at === null || at < now ? null : at - now;
}

/** Cuándo corresponde el próximo intento después de uno que falló y se puede reintentar. */
export function nextAttempt(input: NextAttemptInput): NextAttempt {
  const schedule = input.policy?.schedule ?? DEFAULT_RETRY_SCHEDULE;
  const maxDelaySeconds = input.policy?.maxDelaySeconds ?? DEFAULT_MAX_DELAY_SECONDS;
  const jitterRatio = input.policy?.jitterRatio ?? DEFAULT_JITTER_RATIO;

  const base = schedule[input.attempt - 1];
  if (base === undefined) return { exhausted: true };

  const requested = retryAfterSeconds(input.retryAfter, input.now);
  const capped = Math.min(Math.max(base, requested ?? 0), maxDelaySeconds);
  const delaySeconds = capped + Math.floor(capped * jitterRatio * input.random);
  return { exhausted: false, delaySeconds, nextAt: input.now + delaySeconds };
}
