import { describe, expect, it } from 'vitest';
import {
  ConfigurationError,
  endpointHealth,
  MemoryDeliveryLedger,
  summarizeFailures,
} from '../../src/index';
import { expectedSummary, healthCases, policyOf, recordOf } from '../support/health';

describe('vectores de entregar/salud', () => {
  it.each(healthCases.map((c) => [c.name, c] as const))('%s', async (_name, c) => {
    const attempts = c.attempts.map((a) => ({ at: a.at, deliveryClass: a.delivery_class }));

    const summary = summarizeFailures(attempts, c.since);

    expect(summary).toEqual(expectedSummary(c));
    expect(endpointHealth(summary, c.now, policyOf(c))).toEqual(c.expected.health);
  });

  it.each(healthCases.map((c) => [c.name, c] as const))(
    'el registro en memoria da el mismo resumen: %s',
    async (_name, c) => {
      const ledger = new MemoryDeliveryLedger();
      for (const [index, attempt] of c.attempts.entries()) {
        // Otro destino en el medio, que no tiene que contar.
        await ledger.record(recordOf('ep_otro', index, { at: attempt.at, delivery_class: 'gone' }));
        await ledger.record(recordOf('ep_1', index, attempt));
      }

      expect(await ledger.failuresOf('ep_1', c.since)).toEqual(expectedSummary(c));
    },
  );
});

describe('endpointHealth', () => {
  it.each([
    ['windowSeconds', { windowSeconds: 0 }],
    ['minFailures', { minFailures: 1.5 }],
  ])('rechaza un %s inválido', (name, policy) => {
    expect(() =>
      endpointHealth({ failures: 0, failingSince: null, gone: false }, 0, policy),
    ).toThrow(ConfigurationError);
    expect(() =>
      endpointHealth({ failures: 0, failingSince: null, gone: false }, 0, policy),
    ).toThrow(new RegExp(name));
  });
});
