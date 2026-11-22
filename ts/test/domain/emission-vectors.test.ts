import { describe, expect, it } from 'vitest';
import {
  classifyDelivery,
  type DeliveryFailure,
  evaluateDestination,
  isBlockedAddress,
  nextAttempt,
  type RetryPolicy,
} from '../../src/index';
import { loadVector } from '../support/vectors';

describe('vectores de entregar/direcciones', () => {
  const vector = loadVector<{ name: string; address: string; expected: { blocked: boolean } }>(
    'entregar/direcciones',
  );

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    expect(isBlockedAddress(c.address)).toBe(c.expected.blocked);
  });
});

describe('vectores de entregar/url', () => {
  const vector = loadVector<{
    name: string;
    url: string;
    allow_http: boolean;
    resolved: string[];
    expected: { result: string };
  }>('entregar/url');

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    expect(evaluateDestination(c.url, { allowHttp: c.allow_http, resolved: c.resolved })).toBe(
      c.expected.result,
    );
  });
});

describe('vectores de entregar/clasificacion', () => {
  const vector = loadVector<{
    name: string;
    status: number | null;
    failure: DeliveryFailure | null;
    expected: { class: string };
  }>('entregar/clasificacion');

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    const attempt = c.failure === null ? { status: c.status as number } : { failure: c.failure };

    expect(classifyDelivery(attempt)).toBe(c.expected.class);
  });
});

describe('vectores de entregar/reintentos', () => {
  const vector = loadVector<{
    name: string;
    attempt: number;
    now: number;
    random: number;
    retry_after: string | null;
    schedule?: number[];
    max_delay_seconds?: number;
    jitter_ratio?: number;
    expected: { exhausted: boolean; delay_seconds?: number; next_at?: number };
  }>('entregar/reintentos');

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    const policy: RetryPolicy = {
      ...(c.schedule === undefined ? {} : { schedule: c.schedule }),
      ...(c.max_delay_seconds === undefined ? {} : { maxDelaySeconds: c.max_delay_seconds }),
      ...(c.jitter_ratio === undefined ? {} : { jitterRatio: c.jitter_ratio }),
    };

    const result = nextAttempt({
      attempt: c.attempt,
      now: c.now,
      random: c.random,
      retryAfter: c.retry_after,
      policy,
    });

    expect(result).toEqual(
      c.expected.exhausted
        ? { exhausted: true }
        : { exhausted: false, delaySeconds: c.expected.delay_seconds, nextAt: c.expected.next_at },
    );
  });
});
