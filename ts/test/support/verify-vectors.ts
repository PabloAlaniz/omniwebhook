import { describe, expect, it } from 'vitest';
import type { Clock, Verifier } from '../../src/index';
import { loadVector, toRequest, type VerifyCase } from './vectors';

export type VerifierFactory = (testCase: VerifyCase, clock: Clock) => Verifier;

/** Corre todos los casos de `verificar/<esquema>` contra el verificador que arma `factory`. */
export function describeVerifyVectors(scheme: string, factory: VerifierFactory): void {
  const vector = loadVector<VerifyCase>(`verificar/${scheme}`);

  describe(`vectores de ${vector.id}`, () => {
    it.each(vector.cases.map((testCase) => [testCase.name, testCase] as const))(
      '%s',
      async (_name, testCase) => {
        const verifier = factory(testCase, { now: () => testCase.now });

        const result = await verifier.verify(toRequest(testCase.request));

        if (testCase.expected.outcome === 'ok') {
          expect(result).toEqual({
            outcome: 'ok',
            eventKey: testCase.expected.event_key,
            timestamp: testCase.expected.timestamp,
          });
        } else {
          expect(result).toEqual({ outcome: testCase.expected.outcome });
        }
      },
    );
  });
}

export function toleranceOf(testCase: VerifyCase): { toleranceSeconds?: number } {
  const value = testCase.options?.tolerance_seconds;
  return typeof value === 'number' ? { toleranceSeconds: value } : {};
}
