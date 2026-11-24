import { describe, expect, it } from 'vitest';
import { ConfigurationError, isEventPattern, isEventType, subscribes } from '../../src/index';
import { loadVector } from '../support/vectors';

interface EventCase {
  readonly name: string;
  readonly type: string;
  readonly patterns: readonly string[] | null;
  readonly expected: {
    readonly valid_type: boolean;
    readonly valid_patterns: readonly boolean[] | null;
    readonly subscribed: boolean | null;
  };
}

describe('vectores de entregar/tipos', () => {
  const vector = loadVector<EventCase>('entregar/tipos');

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    expect(isEventType(c.type)).toBe(c.expected.valid_type);
    expect(c.patterns?.map(isEventPattern) ?? null).toEqual(c.expected.valid_patterns);
    if (c.expected.subscribed === null) {
      expect(() => subscribes(c.patterns, c.type)).toThrow(ConfigurationError);
    } else {
      expect(subscribes(c.patterns, c.type)).toBe(c.expected.subscribed);
    }
  });
});

describe('subscribes', () => {
  it('sin lista recibe todo, también con undefined', () => {
    expect(subscribes(undefined, 'pedido.creado')).toBe(true);
  });

  it('lo que no es texto no es un tipo ni un patrón', () => {
    expect(isEventType(7 as never)).toBe(false);
    expect(isEventPattern(null as never)).toBe(false);
  });
});
