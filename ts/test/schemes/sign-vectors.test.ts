import { describe, expect, it } from 'vitest';
import { standardScheme, standardSigner } from '../../src/standard';
import { loadVector } from '../support/vectors';

interface SignCase {
  readonly name: string;
  readonly secrets: string[];
  readonly id: string;
  readonly timestamp: number;
  readonly payload: string;
  readonly expected: { headers?: Record<string, string>; error?: string };
}

describe('vectores de firmar/standard', () => {
  const vector = loadVector<SignCase>('firmar/standard');

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', async (_name, c) => {
    const signer = standardSigner({ secrets: c.secrets });
    const payload = new TextEncoder().encode(c.payload);

    const result = await signer.sign({ id: c.id, timestamp: c.timestamp, payload });

    if (c.expected.headers !== undefined) {
      expect(result).toEqual({ outcome: 'signed', headers: c.expected.headers });
    } else {
      expect(result).toEqual({ outcome: c.expected.error });
    }
  });

  it('lo que se firma se verifica con el mismo secreto', async () => {
    const secrets = ['whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE='];
    const payload = new TextEncoder().encode('{"hola":"mundo"}');

    const signed = await standardSigner({ secrets }).sign({
      id: 'msg_1',
      timestamp: 1000,
      payload,
    });
    if (signed.outcome !== 'signed') throw new Error('no firmó');
    const verified = await standardScheme({ secrets, clock: { now: () => 1000 } }).verify({
      headers: Object.entries(signed.headers),
      query: [],
      body: payload,
    });

    expect(verified).toEqual({ outcome: 'ok', eventKey: 'standard:msg_1', timestamp: 1000 });
  });
});
