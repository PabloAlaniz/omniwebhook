import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { inspectDestination } from '../../src/domain/destination';
import { parsePairs } from '../../src/domain/signature-pairs';
import {
  creemScheme,
  DEFAULT_MAX_DELAY_SECONDS,
  githubScheme,
  hmacBodyScheme,
  type IncomingRequest,
  isBlockedAddress,
  mercadoPagoScheme,
  nextAttempt,
  shopifyScheme,
  slackScheme,
  stripeScheme,
  tiktokScheme,
  type Verifier,
} from '../../src/index';
import { standardScheme, standardSigner } from '../../src/standard';

// Lo que interpreta entrada ajena no puede lanzar: cualquier cosa que llegue termina en uno
// de los resultados definidos. Los vectores cubren los casos pensados; esto, los que no.

const NOW = 1_700_000_000;
const clock = { now: () => NOW };
const SECRET = 'whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE=';
const OUTCOMES = ['ok', 'unconfigured', 'missing', 'ambiguous', 'malformed', 'invalid', 'stale'];

const SCHEMES: ReadonlyArray<readonly [string, Verifier]> = [
  ['standard', standardScheme({ secrets: [SECRET], clock })],
  ['stripe', stripeScheme({ secrets: ['secreto-sintetico'], clock })],
  ['tiktok', tiktokScheme({ secrets: ['secreto-sintetico'], clock })],
  ['mercadopago', mercadoPagoScheme({ secrets: ['secreto-sintetico'], clock })],
  ['github', githubScheme({ secrets: ['secreto-sintetico'] })],
  ['creem', creemScheme({ secrets: ['secreto-sintetico'] })],
  ['slack', slackScheme({ secrets: ['secreto-sintetico'], clock })],
  ['shopify', shopifyScheme({ secrets: ['secreto-sintetico'] })],
  ['hmac-body', hmacBodyScheme({ secrets: ['secreto-sintetico'], header: 'x-firma' })],
];

// Los nombres que algún esquema lee, para que la entrada al azar llegue más allá de `missing`.
const KNOWN_NAMES = [
  'webhook-id',
  'webhook-timestamp',
  'webhook-signature',
  'stripe-signature',
  'tiktok-signature',
  'x-signature',
  'x-request-id',
  'x-hub-signature-256',
  'creem-signature',
  'x-slack-signature',
  'x-slack-request-timestamp',
  'x-shopify-hmac-sha256',
  'x-shopify-webhook-id',
  'x-firma',
  'data.id',
];
// Valores con la forma de los que los esquemas esperan, mezclados con cualquier cosa.
const shaped = fc.oneof(
  fc.string(),
  fc.string({ unit: 'binary' }),
  fc.stringMatching(/^(t|ts|v1|s|sha256)=[0-9a-f]{0,64}(,(t|ts|v1|s)=[0-9a-f]{0,64}){0,3}$/),
  fc.stringMatching(/^v1,[A-Za-z0-9+/]{0,44}={0,2}( v1,[A-Za-z0-9+/]{0,44})?$/),
  fc.stringMatching(/^[0-9]{1,16}$/),
  fc.constant(String(NOW)),
);
const field = fc.tuple(fc.oneof(fc.constantFrom(...KNOWN_NAMES), fc.string()), shaped);
const request: fc.Arbitrary<IncomingRequest> = fc.record({
  headers: fc.array(field, { maxLength: 8 }),
  query: fc.array(field, { maxLength: 4 }),
  body: fc.oneof(
    fc.uint8Array({ maxLength: 256 }),
    fc.json().map((text) => new TextEncoder().encode(text)),
  ),
});

describe('propiedades de la verificación', () => {
  it.each(SCHEMES)('%s: cualquier pedido termina en un resultado definido', async (_name, v) => {
    await fc.assert(
      fc.asyncProperty(request, async (incoming) => {
        const result = await v.verify(incoming);
        expect(OUTCOMES).toContain(result.outcome);
      }),
      { numRuns: 300 },
    );
  });

  it('lo que se firma se verifica, y con un byte cambiado deja de verificarse', async () => {
    const signer = standardSigner({ secrets: [SECRET] });
    const verifier = standardScheme({ secrets: [SECRET], clock });

    await fc.assert(
      fc.asyncProperty(
        fc.stringMatching(/^[A-Za-z0-9_-]{1,40}$/),
        fc.uint8Array({ minLength: 1, maxLength: 512 }),
        fc.nat(),
        async (id, payload, position) => {
          const signing = await signer.sign({ id, timestamp: NOW, payload });
          if (signing.outcome !== 'signed') throw new Error(signing.outcome);
          const headers = Object.entries(signing.headers);

          expect(await verifier.verify({ headers, query: [], body: payload })).toEqual({
            outcome: 'ok',
            eventKey: `standard:${id}`,
            timestamp: NOW,
          });

          const altered = Uint8Array.from(payload);
          const index = position % altered.length;
          altered[index] = (altered[index] ?? 0) ^ 1;
          expect(await verifier.verify({ headers, query: [], body: altered })).toEqual({
            outcome: 'invalid',
          });
        },
      ),
      { numRuns: 200 },
    );
  });
});

describe('propiedades de las cabeceras con pares', () => {
  it('nunca devuelve una clave o un valor vacíos ni con blancos en los bordes', () => {
    fc.assert(
      fc.property(fc.oneof(fc.string(), fc.string({ unit: 'binary' })), (text) => {
        for (const [key, value] of parsePairs(text)) {
          for (const part of [key, value]) {
            expect(part).not.toBe('');
            expect(part).not.toMatch(/^[ \t]|[ \t]$/);
          }
          expect(key).not.toContain(',');
          expect(value).not.toContain(',');
        }
      }),
    );
  });
});

describe('propiedades de la política de URLs', () => {
  const PROBLEMS = ['invalid_url', 'scheme', 'credentials'];
  // URLs casi válidas: es donde un analizador estricto y uno tolerante pueden no coincidir.
  const piece = fc.oneof(
    fc.constantFrom('a', 'A', 'z', '0', '1', '9', '-', '_', '.', '..', 'xn--', 'example', 'test'),
    fc.constantFrom(':', '/', '//', '@', '?', '#', '[', ']', '%', '%2e', '%00', '\\', ' ', '\t'),
    fc.constantFrom(
      '127.0.0.1',
      '0x7f',
      '0177',
      '2130706433',
      '::1',
      '::ffff:10.0.0.1',
      '。',
      'ａ',
    ),
    fc.string({ maxLength: 3 }),
  );
  const almostUrl = fc
    .tuple(
      fc.constantFrom('https://', 'http://', 'HTTPS://', 'https:/', 'https:', 'ftp://', ''),
      fc.array(piece, { maxLength: 8 }),
    )
    .map(([scheme, pieces]) => scheme + pieces.join(''));
  const anyUrl = fc.oneof(almostUrl, fc.webUrl(), fc.string());

  it('cualquier texto termina en un destino o en un motivo definido', () => {
    fc.assert(
      fc.property(anyUrl, fc.boolean(), (url, allowHttp) => {
        const inspected = inspectDestination(url, { allowHttp });
        if (typeof inspected === 'string') expect(PROBLEMS).toContain(inspected);
      }),
      { numRuns: 2000 },
    );
  });

  it('si acepta una URL, el analizador de la plataforma lee el mismo host', () => {
    fc.assert(
      fc.property(anyUrl, (url) => {
        const inspected = inspectDestination(url, { allowHttp: true });
        if (typeof inspected === 'string') return;

        // La conexión la hace el analizador de la plataforma: si leyera otro host, la
        // política habría validado un destino y el pedido saldría hacia otro.
        // Que la plataforma rechace una URL que la política aceptó no es un problema: el
        // intento falla sin salir hacia ningún lado.
        if (!URL.canParse(url)) return;
        const parsed = new URL(url);
        const host = parsed.hostname.replace(/^\[|\]$/g, '');
        expect(parsed.username + parsed.password).toBe('');
        if (inspected.literalAddress === null) {
          expect(host).toBe(inspected.host);
        } else {
          expect(isBlockedAddress(host)).toBe(isBlockedAddress(inspected.literalAddress));
        }
      }),
      { numRuns: 5000 },
    );
  });

  it('cualquier texto es una dirección bloqueada o una permitida, sin lanzar', () => {
    fc.assert(
      fc.property(fc.oneof(fc.string(), fc.ipV4(), fc.ipV4Extended(), fc.ipV6()), (text) => {
        expect(typeof isBlockedAddress(text)).toBe('boolean');
      }),
      { numRuns: 2000 },
    );
  });
});

describe('propiedades de los reintentos', () => {
  const retryAfter = fc.oneof(
    fc.constant(null),
    fc.string(),
    fc.stringMatching(/^[0-9]{1,20}$/),
    fc.date({ noInvalidDate: true }).map((date) => date.toUTCString()),
  );

  it('la espera nunca es negativa ni supera el tope más su variación', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 30 }),
        fc.double({ min: 0, max: 1, maxExcluded: true, noNaN: true }),
        retryAfter,
        (attempt, random, header) => {
          const next = nextAttempt({ attempt, now: NOW, random, retryAfter: header });
          if (next.exhausted) return;

          expect(Number.isInteger(next.delaySeconds)).toBe(true);
          expect(next.delaySeconds).toBeGreaterThanOrEqual(0);
          expect(next.delaySeconds).toBeLessThan(DEFAULT_MAX_DELAY_SECONDS * 1.1);
          expect(next.nextAt).toBe(NOW + next.delaySeconds);
        },
      ),
      { numRuns: 2000 },
    );
  });
});
