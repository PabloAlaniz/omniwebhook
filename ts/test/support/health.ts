import type { DeliveryClass } from '../../src/index';
import { loadVector } from './vectors';

export interface HealthCase {
  readonly name: string;
  readonly attempts: ReadonlyArray<{ readonly at: number; readonly delivery_class: DeliveryClass }>;
  readonly since: number;
  readonly now: number;
  readonly policy?: { readonly window_seconds: number; readonly min_failures: number };
  readonly expected: {
    readonly summary: { failures: number; failing_since: number | null; gone: boolean };
    readonly health: { status: string; reason: string | null };
  };
}

export const healthCases = loadVector<HealthCase>('entregar/salud').cases;

export function policyOf(c: HealthCase) {
  return c.policy === undefined
    ? {}
    : { windowSeconds: c.policy.window_seconds, minFailures: c.policy.min_failures };
}

export function expectedSummary(c: HealthCase) {
  const { failures, failing_since: failingSince, gone } = c.expected.summary;
  return { failures, failingSince, gone };
}

export function recordOf(
  endpointId: string,
  index: number,
  attempt: { readonly at: number; readonly delivery_class: DeliveryClass },
) {
  return {
    messageId: `msg_${index}`,
    endpointId,
    attempt: 1,
    at: attempt.at,
    deliveryClass: attempt.delivery_class,
    state: attempt.delivery_class === 'retryable' ? ('pending' as const) : attempt.delivery_class,
    status: null,
    problem: null,
    durationMs: 1,
    nextAt: attempt.delivery_class === 'retryable' ? attempt.at + 5 : null,
  };
}
