import { describe, expect, it } from 'vitest';
import {
  ConfigurationError,
  creemScheme,
  discordScheme,
  githubScheme,
  hmacBodyScheme,
  mercadoPagoScheme,
  shopifyScheme,
  slackScheme,
  stripeScheme,
  tiktokScheme,
  toIncomingRequest,
  type Verifier,
} from '../../src/index';
import {
  generateStandardKeyPair,
  standardPublicKeyScheme,
  standardScheme,
} from '../../src/standard';
import {
  type SignedRequestOptions,
  type SignedScheme,
  signedRequest,
  tampered,
  toFetchRequest,
} from '../../src/testing';

const NOW = 1_700_000_000;
const clock = { now: () => NOW };
const TEXT = 'secreto-sintetico';
const STANDARD = 'whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE=';
const BODY = '{"id":"evt_1","event_id":"Ev1","ñ":true}';

type Row = readonly [SignedScheme, Verifier, Partial<SignedRequestOptions>, string];
const timed = { secrets: [TEXT], clock };
const SCHEMES: readonly Row[] = [
  ['standard', standardScheme({ secrets: [STANDARD], clock }), { id: 'msg_1' }, 'standard:msg_1'],
  ['stripe', stripeScheme(timed), {}, 'stripe:evt_1'],
  ['slack', slackScheme(timed), {}, 'slack:Ev1'],
  ['tiktok', tiktokScheme(timed), {}, 'tiktok:sha256:'],
  [
    'mercadopago',
    mercadoPagoScheme(timed),
    { id: 'req-1', dataId: 'ABC' },
    'mercadopago:abc:req-1',
  ],
  ['mercadopago', mercadoPagoScheme(timed), {}, `mercadopago:ts:${NOW}`],
  ['github', githubScheme({ secrets: [TEXT] }), { id: 'entrega-1' }, 'github:entrega-1'],
  ['github', githubScheme({ secrets: [TEXT] }), {}, 'github:sha256:'],
  ['creem', creemScheme({ secrets: [TEXT] }), {}, 'creem:evt_1'],
  ['shopify', shopifyScheme({ secrets: [TEXT] }), { id: 'wh-1' }, 'shopify:wh-1'],
  [
    'hmac-body',
    hmacBodyScheme({
      secrets: [TEXT],
      header: 'x-firma',
      prefix: 'v1=',
      encoding: 'base64',
      idHeader: 'x-id',
    }),
    { header: 'x-firma', prefix: 'v1=', encoding: 'base64', idHeader: 'x-id', id: 'e-1' },
    'hmac-body:e-1',
  ],
  [
    'hmac-body',
    hmacBodyScheme({ secrets: [TEXT], header: 'x-firma' }),
    { header: 'x-firma' },
    'hmac-body:sha256:',
  ],
];

describe('signedRequest', () => {
  const secretOf = (scheme: SignedScheme) => (scheme === 'standard' ? STANDARD : TEXT);

  it.each(SCHEMES)(
    '%s: lo que arma lo verifica el esquema',
    async (scheme, verifier, extra, key) => {
      const request = await signedRequest(scheme, {
        secret: secretOf(scheme),
        body: BODY,
        timestamp: NOW,
        ...extra,
      });

      const result = await verifier.verify(request);

      expect(result.outcome).toBe('ok');
      expect(result).toMatchObject({ eventKey: expect.stringContaining(key) });
    },
  );

  it.each(SCHEMES)('%s: alterado deja de verificarse', async (scheme, verifier, extra) => {
    const request = await signedRequest(scheme, {
      secret: secretOf(scheme),
      body: BODY,
      timestamp: NOW,
      ...extra,
    });

    expect(await verifier.verify(tampered(request))).toEqual({ outcome: 'invalid' });
  });

  it.each(SCHEMES.filter(([scheme]) => ['standard', 'stripe', 'slack', 'tiktok'].includes(scheme)))(
    '%s: con una marca vieja es stale',
    async (scheme, verifier, extra) => {
      const request = await signedRequest(scheme, {
        secret: secretOf(scheme),
        body: BODY,
        timestamp: NOW - 3600,
        ...extra,
      });

      expect(await verifier.verify(request)).toEqual({ outcome: 'stale' });
    },
  );

  it('por defecto firma con la hora actual y, en standard, genera el identificador', async () => {
    const request = await signedRequest('standard', {
      secret: STANDARD,
      body: new Uint8Array([1]),
    });

    const result = await standardScheme({ secrets: [STANDARD] }).verify(request);

    expect(result).toMatchObject({
      outcome: 'ok',
      eventKey: expect.stringMatching(/^standard:msg_/),
    });
  });

  it.each([
    ['un secreto vacío', 'stripe', { secret: '' }],
    ['un secreto que no es base64 en standard', 'standard', { secret: 'whsec_***' }],
    ['hmac-body sin cabecera', 'hmac-body', {}],
    ['un esquema desconocido', 'otro', {}],
  ] as const)('rechaza %s', async (_what, scheme, extra) => {
    await expect(
      signedRequest(scheme as SignedScheme, { secret: TEXT, body: BODY, ...extra }),
    ).rejects.toThrow(ConfigurationError);
  });
});

describe('toFetchRequest', () => {
  it('conserva cabeceras, parámetros y cuerpo', async () => {
    const signed = await signedRequest('mercadopago', {
      secret: TEXT,
      body: BODY,
      timestamp: NOW,
      id: 'req-1',
      dataId: 'abc',
    });

    const incoming = await toIncomingRequest(toFetchRequest(signed));

    expect(await mercadoPagoScheme(timed).verify(incoming)).toMatchObject({ outcome: 'ok' });
    expect(new TextDecoder().decode(incoming.body)).toBe(BODY);
  });
});

describe('signedRequest con esquemas de clave pública', () => {
  const SEED = '9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60';
  const DISCORD_PUBLIC = 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a';

  it('standard-v2a: lo que arma lo verifica la clave pública, y alterado no', async () => {
    const pair = await generateStandardKeyPair();
    const scheme = standardPublicKeyScheme({
      publicKeys: [pair.publicKey],
      endpointId: 'ep_1',
      clock,
    });

    const request = await signedRequest('standard-v2a', {
      secret: pair.secretKey,
      body: BODY,
      timestamp: NOW,
      id: 'msg_1',
      endpointId: 'ep_1',
    });

    expect(await scheme.verify(request)).toMatchObject({
      outcome: 'ok',
      eventKey: 'standard:msg_1',
    });
    expect(await scheme.verify(tampered(request))).toEqual({ outcome: 'invalid' });
  });

  it('discord: lo que arma lo verifica la clave pública de esa semilla', async () => {
    const scheme = discordScheme({ publicKeys: [DISCORD_PUBLIC], clock });

    const request = await signedRequest('discord', { secret: SEED, body: BODY, timestamp: NOW });

    expect(await scheme.verify(request)).toMatchObject({
      outcome: 'ok',
      eventKey: 'discord:evt_1',
    });
    expect(await scheme.verify(tampered(request))).toEqual({ outcome: 'invalid' });
  });

  it.each([
    ['standard-v2a sin destino', 'standard-v2a', { secret: `whsk_${'A'.repeat(43)}=` }],
    ['standard-v2a con una clave pública', 'standard-v2a', { secret: 'whpk_abc', endpointId: 'e' }],
    [
      'standard-v2a con un destino con punto',
      'standard-v2a',
      { secret: `whsk_${'A'.repeat(43)}=`, endpointId: 'e.1' },
    ],
    ['discord con una semilla corta', 'discord', { secret: 'abcd' }],
  ] as const)('rechaza %s', async (_what, scheme, extra) => {
    await expect(signedRequest(scheme, { body: BODY, ...extra })).rejects.toThrow(
      ConfigurationError,
    );
  });
});
