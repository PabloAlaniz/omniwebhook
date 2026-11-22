/** Por qué un intento no llegó a tener respuesta. */
export type DeliveryFailure = 'network' | 'timeout' | 'blocked';

/** Qué pasó en un intento: hubo respuesta, o no la hubo y por qué. */
export type AttemptOutcome = { readonly status: number } | { readonly failure: DeliveryFailure };

/** La clase de un intento (sección 8.2). */
export type DeliveryClass = 'delivered' | 'gone' | 'retryable' | 'rejected' | 'blocked';

/** El estado de una entrega después de un intento (sección 8.4). */
export type DeliveryState = 'pending' | 'delivered' | 'rejected' | 'blocked' | 'gone' | 'exhausted';

const RETRYABLE_STATUSES: ReadonlySet<number> = new Set([408, 409, 425, 429]);

export function classifyDelivery(outcome: AttemptOutcome): DeliveryClass {
  if ('failure' in outcome) return outcome.failure === 'blocked' ? 'blocked' : 'retryable';

  const { status } = outcome;
  if (status >= 200 && status <= 299) return 'delivered';
  if (status === 410) return 'gone';
  if (RETRYABLE_STATUSES.has(status) || (status >= 500 && status <= 599)) return 'retryable';
  return 'rejected';
}

/** El estado en que queda la entrega: `retryable` sigue pendiente sólo si hay un próximo intento. */
export function stateAfter(deliveryClass: DeliveryClass, hasNextAttempt: boolean): DeliveryState {
  if (deliveryClass !== 'retryable') return deliveryClass;
  return hasNextAttempt ? 'pending' : 'exhausted';
}
