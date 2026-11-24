import type { Rejection } from './verification';

/** Cómo terminó la recepción de un pedido (sección 6.2). */
export type ReceptionOutcome =
  | 'ok'
  | 'duplicate'
  | 'in_progress'
  | 'failed'
  | 'too_large'
  | 'unprocessable'
  | Rejection;

/** El tamaño máximo del cuerpo de un pedido, en bytes, si no se indica otro (sección 6.2). */
export const DEFAULT_MAX_BODY_BYTES = 1_048_576;

const STATUS: Readonly<Record<ReceptionOutcome, number>> = {
  ok: 200,
  duplicate: 200,
  in_progress: 409,
  missing: 401,
  ambiguous: 401,
  malformed: 401,
  invalid: 401,
  stale: 401,
  too_large: 413,
  unprocessable: 422,
  unconfigured: 500,
  failed: 500,
};

/** El estado HTTP sugerido para cada resultado (sección 6.3). */
export function httpStatusFor(outcome: ReceptionOutcome): number {
  return STATUS[outcome];
}
