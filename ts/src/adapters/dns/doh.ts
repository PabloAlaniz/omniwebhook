import type { DnsResolver } from '../../application/ports';

export interface DohResolverOptions {
  /**
   * El servicio de DNS sobre HTTPS, con el formato JSON (`application/dns-json`). Por defecto,
   * el de Cloudflare: `https://cloudflare-dns.com/dns-query`. El de Google es
   * `https://dns.google/resolve`.
   */
  readonly endpoint?: string;
  /** La función `fetch` a usar. Por defecto, la global. */
  readonly fetch?: typeof fetch;
  /** Cuánto esperar cada consulta, en segundos. Por defecto, 5. */
  readonly timeoutSeconds?: number;
}

const DEFAULT_ENDPOINT = 'https://cloudflare-dns.com/dns-query';
const DEFAULT_TIMEOUT_SECONDS = 5;

// Los códigos de respuesta de DNS (RFC 1035) y los tipos de registro que interesan.
const NOERROR = 0;
const NXDOMAIN = 3;
const TYPE_A = 1;
const TYPE_AAAA = 28;

interface DnsJsonAnswer {
  readonly type?: unknown;
  readonly data?: unknown;
}

interface DnsJsonResponse {
  readonly Status?: unknown;
  readonly Answer?: unknown;
}

/**
 * Resuelve nombres con DNS sobre HTTPS, para entornos sin acceso al DNS del sistema:
 * Cloudflare Workers, Deno Deploy, funciones edge. Pregunta por A y AAAA y devuelve las
 * direcciones de las dos respuestas; los alias (CNAME) los sigue el servicio.
 *
 * Un nombre que no existe da una lista vacía. Cualquier otra falla (el servicio no
 * responde, responde un error o algo que no se puede leer) lanza, y el intento cuenta como
 * un error de red.
 *
 * Los nombres de los destinos viajan al servicio elegido: elegí uno en el que confíes.
 */
export function dohResolver(options: DohResolverOptions = {}): DnsResolver {
  const endpoint = new URL(options.endpoint ?? DEFAULT_ENDPOINT);
  const send = options.fetch ?? fetch;
  const timeoutMs = (options.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS) * 1000;

  async function ask(host: string, type: number): Promise<readonly string[]> {
    const url = new URL(endpoint);
    url.searchParams.set('name', host);
    url.searchParams.set('type', String(type));
    const response = await send(url.toString(), {
      headers: { accept: 'application/dns-json' },
      redirect: 'error',
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) {
      await response.body?.cancel();
      throw new Error(`el servicio de DNS respondió ${response.status}`);
    }
    const body = (await response.json()) as DnsJsonResponse;
    if (body.Status === NXDOMAIN) return [];
    if (body.Status !== NOERROR) {
      throw new Error(`el servicio de DNS respondió el código ${String(body.Status)}`);
    }
    if (body.Answer === undefined) return [];
    if (!Array.isArray(body.Answer)) throw new Error('el servicio de DNS respondió algo ilegible');
    return (body.Answer as DnsJsonAnswer[])
      .filter((answer) => answer.type === type && typeof answer.data === 'string')
      .map((answer) => answer.data as string);
  }

  return {
    async resolve(host: string): Promise<readonly string[]> {
      const [v4, v6] = await Promise.all([ask(host, TYPE_A), ask(host, TYPE_AAAA)]);
      return [...v4, ...v6];
    },
  };
}
