import type { AttemptRecord } from '../../application/ports';

/** Las columnas de la tabla de intentos, en el orden de `attemptParams`. */
export const LEDGER_COLUMNS =
  'message_id, endpoint_id, attempt, at, delivery_class, state, status, problem, duration_ms, next_at';

export interface LedgerRow {
  readonly message_id: string;
  readonly endpoint_id: string;
  readonly attempt: number | string;
  readonly at: number | string | bigint;
  readonly delivery_class: AttemptRecord['deliveryClass'];
  readonly state: AttemptRecord['state'];
  readonly status: number | string | null;
  readonly problem: AttemptRecord['problem'];
  readonly duration_ms: number | string | bigint;
  readonly next_at: number | string | bigint | null;
}

/** Los valores de un intento, en el orden de `LEDGER_COLUMNS`. */
export function attemptParams(attempt: AttemptRecord): unknown[] {
  return [
    attempt.messageId,
    attempt.endpointId,
    attempt.attempt,
    attempt.at,
    attempt.deliveryClass,
    attempt.state,
    attempt.status,
    attempt.problem,
    attempt.durationMs,
    attempt.nextAt,
  ];
}

// Algunos clientes devuelven los enteros grandes como texto o `bigint` para no perder
// precisión. Los valores de acá (segundos y milisegundos) entran en un número.
export function toAttemptRecord(row: LedgerRow): AttemptRecord {
  return {
    messageId: row.message_id,
    endpointId: row.endpoint_id,
    attempt: Number(row.attempt),
    at: Number(row.at),
    deliveryClass: row.delivery_class,
    state: row.state,
    status: row.status === null ? null : Number(row.status),
    problem: row.problem,
    durationMs: Number(row.duration_ms),
    nextAt: row.next_at === null ? null : Number(row.next_at),
  };
}
