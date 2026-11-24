import { describe, expect, it } from 'vitest';
import type { Outbox, OutboxState } from '../../src/index';
import { loadVector } from '../support/vectors';

type OutboxStep =
  | {
      readonly op: 'enqueue';
      readonly message_id: string;
      readonly endpoint_id: string;
      readonly payload: string;
      readonly now: number;
      readonly expected: boolean;
    }
  | {
      readonly op: 'claim';
      readonly token: string;
      readonly now: number;
      readonly limit: number;
      readonly lease_seconds: number;
      readonly expected: ReadonlyArray<{
        readonly message_id: string;
        readonly endpoint_id: string;
        readonly payload: string;
        readonly attempt: number;
      }>;
    }
  | {
      readonly op: 'requeue';
      readonly endpoint_id: string;
      readonly from: number;
      readonly to: number;
      readonly now: number;
      readonly expected: number;
    }
  | {
      readonly op: 'settle';
      readonly message_id: string;
      readonly endpoint_id: string;
      readonly token: string;
      readonly state: OutboxState;
      readonly next_at?: number;
      readonly expected: boolean;
    };

interface OutboxCase {
  readonly name: string;
  readonly steps: readonly OutboxStep[];
}

/** Ejecuta los pasos de un vector contra una bandeja y comprueba cada resultado. */
export async function playOutboxSteps(outbox: Outbox, steps: readonly OutboxStep[]): Promise<void> {
  for (const [index, step] of steps.entries()) {
    const etiqueta = `paso ${index + 1} (${step.op})`;
    if (step.op === 'enqueue') {
      const enqueued = await outbox.enqueue({
        messageId: step.message_id,
        endpointId: step.endpoint_id,
        payload: new TextEncoder().encode(step.payload),
        now: step.now,
      });
      expect(enqueued, etiqueta).toBe(step.expected);
    } else if (step.op === 'claim') {
      const entries = await outbox.claim({
        token: step.token,
        now: step.now,
        limit: step.limit,
        leaseSeconds: step.lease_seconds,
      });
      const seen = entries.map((entry) => ({
        message_id: entry.messageId,
        endpoint_id: entry.endpointId,
        payload: new TextDecoder().decode(entry.payload),
        attempt: entry.attempt,
      }));
      expect(seen, etiqueta).toEqual(step.expected);
    } else if (step.op === 'requeue') {
      const requeued = await outbox.requeue({
        endpointId: step.endpoint_id,
        from: step.from,
        to: step.to,
        now: step.now,
      });
      expect(requeued, etiqueta).toBe(step.expected);
    } else {
      const pair = { messageId: step.message_id, endpointId: step.endpoint_id, token: step.token };
      const applied = await outbox.settle(
        step.state === 'pending'
          ? { ...pair, state: 'pending', nextAt: step.next_at ?? 0 }
          : { ...pair, state: step.state },
      );
      expect(applied, etiqueta).toBe(step.expected);
    }
  }
}

/**
 * Contrato del puerto `Outbox`. Todo adaptador corre esta misma batería: `factory` devuelve
 * una bandeja vacía para cada caso.
 */
export function describeOutbox(name: string, factory: () => Outbox | Promise<Outbox>): void {
  const vector = loadVector<OutboxCase>('entregar/bandeja');

  describe(`${name}: contrato de Outbox`, () => {
    it.each(vector.cases.map((c) => [c.name, c] as const))('%s', async (_name, testCase) => {
      await playOutboxSteps(await factory(), testCase.steps);
    });
  });
}
