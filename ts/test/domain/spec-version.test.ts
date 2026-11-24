import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PACKAGE_VERSION, SPEC_VERSION, USER_AGENT } from '../../src/index';

describe('SPEC_VERSION', () => {
  it('coincide con spec/VERSION', () => {
    const declarada = readFileSync(new URL('../../../spec/VERSION', import.meta.url), 'utf8');

    expect(SPEC_VERSION).toBe(declarada.trim());
  });
});

describe('PACKAGE_VERSION', () => {
  it('coincide con package.json', () => {
    const manifest = JSON.parse(
      readFileSync(new URL('../../package.json', import.meta.url), 'utf8'),
    ) as { version: string };

    expect(PACKAGE_VERSION).toBe(manifest.version);
    expect(USER_AGENT).toBe(`omniwebhook/${manifest.version} (typescript)`);
  });
});
