import { describe, expect, it } from 'vitest';
import {
  combinedSigner,
  generateStandardKeyPair,
  standardKeySigner,
  standardPublicKeyOf,
  standardPublicKeyScheme,
  standardScheme,
  standardSigner,
} from '../../src/standard';
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

interface KeySignCase extends SignCase {
  readonly endpoint_id: string | null;
  readonly expected: SignCase['expected'] & { readonly public_keys?: readonly string[] };
}

describe('vectores de firmar/standard-v2a', () => {
  const vector = loadVector<KeySignCase>('firmar/standard-v2a');
  const messageOf = (c: KeySignCase) => ({
    id: c.id,
    timestamp: c.timestamp,
    payload: new TextEncoder().encode(c.payload),
    ...(c.endpoint_id === null ? {} : { endpointId: c.endpoint_id }),
  });

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', async (_name, c) => {
    const result = await standardKeySigner({ secretKeys: c.secrets }).sign(messageOf(c));

    if (c.expected.headers !== undefined) {
      expect(result).toEqual({ outcome: 'signed', headers: c.expected.headers });
      expect(await Promise.all(c.secrets.map(standardPublicKeyOf))).toEqual(c.expected.public_keys);
    } else {
      expect(result).toEqual({ outcome: c.expected.error });
    }
  });

  it.each(
    vector.cases.filter((c) => c.expected.headers !== undefined).map((c) => [c.name, c] as const),
  )('lo firmado lo verifica la clave pública: %s', async (_name, c) => {
    const message = messageOf(c);
    const signed = await standardKeySigner({ secretKeys: c.secrets }).sign(message);
    if (signed.outcome !== 'signed') throw new Error('no firmó');

    const verified = await standardPublicKeyScheme({
      publicKeys: [c.expected.public_keys?.at(-1) ?? ''],
      endpointId: c.endpoint_id ?? '',
      clock: { now: () => c.timestamp },
    }).verify({ headers: Object.entries(signed.headers), query: [], body: message.payload });

    expect(verified).toMatchObject({ outcome: 'ok', eventKey: `standard:${c.id}` });
  });
});

describe('las claves del formato estándar', () => {
  it('un par nuevo firma y verifica, y no se repite', async () => {
    const pair = await generateStandardKeyPair();
    const other = await generateStandardKeyPair();
    const payload = new TextEncoder().encode('{}');

    const signed = await standardKeySigner({ secretKeys: [pair.secretKey] }).sign({
      id: 'msg_1',
      timestamp: 1000,
      payload,
      endpointId: 'ep_1',
    });
    if (signed.outcome !== 'signed') throw new Error('no firmó');
    const request = { headers: Object.entries(signed.headers), query: [], body: payload };
    const scheme = (publicKey: string) =>
      standardPublicKeyScheme({
        publicKeys: [publicKey],
        endpointId: 'ep_1',
        clock: { now: () => 1000 },
      });

    expect(pair.secretKey).toMatch(/^whsk_[A-Za-z0-9+/]{43}=$/);
    expect(await standardPublicKeyOf(pair.secretKey)).toBe(pair.publicKey);
    expect(await scheme(pair.publicKey).verify(request)).toMatchObject({ outcome: 'ok' });
    expect(await scheme(other.publicKey).verify(request)).toEqual({ outcome: 'invalid' });
  });

  it('una clave privada inutilizable no tiene clave pública', async () => {
    expect(await standardPublicKeyOf('whsk_***')).toBeNull();
    expect(await standardPublicKeyOf(7 as never)).toBeNull();
  });
});

describe('combinedSigner', () => {
  const SECRET = 'whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE=';
  const payload = new TextEncoder().encode('{"hola":"mundo"}');
  const message = { id: 'msg_1', timestamp: 1000, payload, endpointId: 'ep_1' };
  const clock = { now: () => 1000 };

  it('junta las dos firmas en una cabecera y cada receptor verifica con la suya', async () => {
    const pair = await generateStandardKeyPair();
    const signer = combinedSigner([
      standardSigner({ secrets: [SECRET] }),
      standardKeySigner({ secretKeys: [pair.secretKey] }),
    ]);

    const signed = await signer.sign(message);
    if (signed.outcome !== 'signed') throw new Error('no firmó');
    const request = { headers: Object.entries(signed.headers), query: [], body: payload };

    expect(signed.headers['webhook-signature']).toMatch(/^v1,\S+ v2a,\S+$/);
    expect(Object.keys(signed.headers).sort()).toEqual([
      'webhook-id',
      'webhook-signature',
      'webhook-timestamp',
    ]);
    expect(await standardScheme({ secrets: [SECRET], clock }).verify(request)).toMatchObject({
      outcome: 'ok',
    });
    expect(
      await standardPublicKeyScheme({
        publicKeys: [pair.publicKey],
        endpointId: 'ep_1',
        clock,
      }).verify(request),
    ).toMatchObject({ outcome: 'ok' });
  });

  it('si uno no puede firmar, el mensaje no se firma', async () => {
    const signer = combinedSigner([
      standardSigner({ secrets: [SECRET] }),
      standardKeySigner({ secretKeys: [] }),
    ]);

    expect(await signer.sign(message)).toEqual({ outcome: 'unconfigured' });
  });

  it('rechaza una lista vacía', () => {
    expect(() => combinedSigner([])).toThrow(/signers/);
  });
});
