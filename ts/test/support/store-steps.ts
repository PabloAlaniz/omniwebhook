import { expect } from 'vitest';
import type { IdempotencyStore } from '../../src/index';
import type { StoreStep } from './vectors';

/** Ejecuta los pasos de un vector contra un almacén y comprueba cada resultado. */
export async function playSteps(
  store: IdempotencyStore,
  steps: readonly StoreStep[],
): Promise<void> {
  for (const [index, step] of steps.entries()) {
    const etiqueta = `paso ${index + 1} (${step.op})`;
    if (step.op === 'claim') {
      const result = await store.claim({
        key: step.key,
        token: step.token,
        now: step.now,
        leaseSeconds: step.lease_seconds,
      });
      expect(result, etiqueta).toBe(step.expected);
    } else if (step.op === 'complete') {
      const applied = await store.complete({
        key: step.key,
        token: step.token,
        now: step.now,
        retentionSeconds: step.retention_seconds,
      });
      expect(applied, etiqueta).toBe(step.expected);
    } else {
      const applied = await store.release({ key: step.key, token: step.token });
      expect(applied, etiqueta).toBe(step.expected);
    }
  }
}
