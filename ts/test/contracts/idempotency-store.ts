import { describe, it } from 'vitest';
import type { IdempotencyStore } from '../../src/index';
import { playSteps } from '../support/store-steps';
import { loadVector, type StoreStep } from '../support/vectors';

interface StoreCase {
  readonly name: string;
  readonly steps: readonly StoreStep[];
}

/**
 * Contrato del puerto `IdempotencyStore`. Todo adaptador corre esta misma batería:
 * `factory` devuelve un almacén vacío para cada caso.
 */
export function describeIdempotencyStore(
  name: string,
  factory: () => IdempotencyStore | Promise<IdempotencyStore>,
): void {
  const vector = loadVector<StoreCase>('reservas/almacen');

  describe(`${name}: contrato de IdempotencyStore`, () => {
    it.each(vector.cases.map((c) => [c.name, c] as const))('%s', async (_name, testCase) => {
      await playSteps(await factory(), testCase.steps);
    });
  });
}
