import type { Rejection } from './verification';

/** Cómo terminó la recepción de un pedido (sección 6.2). */
export type ReceptionOutcome = 'ok' | 'duplicate' | 'in_progress' | 'failed' | Rejection;

const STATUS: Readonly<Record<ReceptionOutcome, number>> = {
  ok: 200,
  duplicate: 200,
  in_progress: 409,
  missing: 401,
  ambiguous: 401,
  malformed: 401,
  invalid: 401,
  stale: 401,
  unconfigured: 500,
  failed: 500,
};

/** El estado HTTP sugerido para cada resultado (sección 6.3). */
export function httpStatusFor(outcome: ReceptionOutcome): number {
  return STATUS[outcome];
}
