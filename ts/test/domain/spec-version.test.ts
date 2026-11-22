import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { SPEC_VERSION } from '../../src/index';

describe('SPEC_VERSION', () => {
  it('coincide con spec/VERSION', () => {
    const declarada = readFileSync(new URL('../../../spec/VERSION', import.meta.url), 'utf8');

    expect(SPEC_VERSION).toBe(declarada.trim());
  });
});
