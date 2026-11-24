import { describe, expect, it } from 'vitest';
import {
  type Clock,
  ConfigurationError,
  githubScheme,
  routedVerifier,
  stripeScheme,
  type Verifier,
} from '../../src/index';
import { standardScheme } from '../../src/standard';
import { loadVector, type RequestVector, toRequest } from '../support/vectors';

interface RouteCase {
  readonly name: string;
  readonly routes: ReadonlyArray<{
    readonly header: string;
    readonly scheme: 'stripe' | 'github' | 'standard';
    readonly secrets: readonly string[];
  }>;
  readonly now: number;
  readonly request: RequestVector;
  readonly expected: {
    readonly outcome: string;
    readonly event_key?: string;
    readonly timestamp?: number | null;
  };
}

function build(scheme: string, secrets: readonly string[], clock: Clock): Verifier {
  if (scheme === 'stripe') return stripeScheme({ secrets, clock });
  if (scheme === 'github') return githubScheme({ secrets });
  return standardScheme({ secrets, clock });
}

describe('vectores de verificar/varios', () => {
  const vector = loadVector<RouteCase>('verificar/varios');

  it.each(vector.cases.map((c) => [c.name, c] as const))('%s', async (_name, c) => {
    const clock = { now: () => c.now };
    const verifier = routedVerifier(
      c.routes.map((route) => ({
        header: route.header,
        verifier: build(route.scheme, route.secrets, clock),
      })),
    );

    const result = await verifier.verify(toRequest(c.request));

    expect(result).toEqual(
      c.expected.outcome === 'ok'
        ? { outcome: 'ok', eventKey: c.expected.event_key, timestamp: c.expected.timestamp }
        : { outcome: c.expected.outcome },
    );
  });
});

describe('routedVerifier', () => {
  const never: Verifier = {
    verify: async () => {
      throw new Error('no se tenía que verificar');
    },
  };
  const request = { headers: [['x-a', '1']], query: [], body: new Uint8Array() } as const;

  it('sólo le pasa el pedido al verificador de la ruta que coincide', async () => {
    const verifier = routedVerifier([
      { header: 'x-b', verifier: never },
      { header: ' X-A ', verifier: { verify: async () => ({ outcome: 'invalid' }) } },
    ]);

    expect(await verifier.verify(request)).toEqual({ outcome: 'invalid' });
  });

  it('con dos rutas que coinciden no verifica con ninguna', async () => {
    const verifier = routedVerifier([
      { header: 'x-a', verifier: never },
      { header: 'x-b', verifier: never },
    ]);

    expect(
      await verifier.verify({ ...request, headers: [...request.headers, ['x-b', '2']] }),
    ).toEqual({
      outcome: 'ambiguous',
    });
  });

  it.each([
    ['sin rutas', []],
    ['una cabecera vacía', [{ header: ' ', verifier: never }]],
    ['una cabecera que no es texto', [{ header: undefined as never, verifier: never }]],
    [
      'una cabecera repetida',
      [
        { header: 'x-a', verifier: never },
        { header: 'X-A', verifier: never },
      ],
    ],
  ])('rechaza %s al construirse', (_what, routes) => {
    expect(() => routedVerifier(routes)).toThrow(ConfigurationError);
  });
});
