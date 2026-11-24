/**
 * Línea de comandos para depurar una integración sin escribir código: firmar un cuerpo,
 * verificar un pedido guardado y mandar un pedido firmado a una URL.
 *
 * El secreto nunca va en la línea de comandos, donde quedaría en el historial: se lee de la
 * variable de entorno que se indique.
 */
import { readFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { creemScheme } from './adapters/schemes/creem';
import { discordScheme } from './adapters/schemes/discord';
import { githubScheme } from './adapters/schemes/github';
import { hmacBodyScheme } from './adapters/schemes/hmac-body';
import { mercadoPagoScheme } from './adapters/schemes/mercadopago';
import { shopifyScheme } from './adapters/schemes/shopify';
import { slackScheme } from './adapters/schemes/slack';
import { generateStandardKeyPair } from './adapters/schemes/standard/key-signer';
import { standardPublicKeyScheme } from './adapters/schemes/standard/public-key';
import { stripeScheme } from './adapters/schemes/stripe';
import { tiktokScheme } from './adapters/schemes/tiktok';
import type { Verifier } from './application/ports';
import type { IncomingRequest } from './domain/incoming-request';
import { type SignedRequestOptions, type SignedScheme, signedRequest } from './testing';

export interface CliIo {
  readonly env: Readonly<Record<string, string | undefined>>;
  /** Lee un archivo; `-` es la entrada estándar. */
  readonly read: (path: string) => Uint8Array;
  readonly out: (line: string) => void;
  readonly err: (line: string) => void;
  readonly fetch: typeof fetch;
}

const USAGE = `omniwebhook <comando> [opciones]

Comandos:
  sign     Firma un cuerpo y muestra el pedido que mandaría el emisor, en JSON.
  verify   Verifica un pedido guardado. Termina con 0 si el resultado es ok, y con 1 si no.
  send     Firma un cuerpo y lo manda por POST a una URL. Termina con 0 si responde 2xx.
  keygen   Genera un par de claves para la firma asimétrica y lo muestra en JSON.

Opciones:
  --scheme <nombre>      standard, standard-v2a, discord, stripe, slack, shopify, tiktok,
                         mercadopago, github, creem o hmac-body.
  --secret-env <VAR>     La variable de entorno que tiene el secreto. En standard-v2a y discord,
                         la clave privada para sign y send, y la pública para verify.
  --endpoint-id <texto>  El identificador del destino. (standard-v2a)
  --body <archivo>       El cuerpo crudo; - para la entrada estándar. (sign, send)
  --request <archivo>    El pedido en JSON, como lo muestra sign; - para la entrada estándar.
                         (verify)
  --url <url>            A dónde mandar el pedido. (send)
  --timestamp <segundos> La marca de tiempo a firmar. Por defecto, ahora. (sign, send)
  --id <texto>           El identificador que el emisor manda fuera del cuerpo.
  --data-id <texto>      El parámetro data.id. (mercadopago)
  --header, --prefix, --encoding, --id-header
                         La configuración de hmac-body.
  --tolerance <segundos> Cuánto puede alejarse de ahora la marca de tiempo. (verify)

Es una herramienta de desarrollo: send no aplica la política de URLs de destino.`;

class UsageError extends Error {}

interface Options {
  readonly [name: string]: string | undefined;
}

function required(options: Options, name: string): string {
  const value = options[name];
  if (value === undefined || value === '') throw new UsageError(`falta --${name}`);
  return value;
}

function secretOf(options: Options, io: CliIo): string {
  const variable = required(options, 'secret-env');
  const secret = io.env[variable];
  if (secret === undefined || secret === '') {
    throw new UsageError(`la variable de entorno ${variable} está vacía o no existe`);
  }
  return secret;
}

function integer(options: Options, name: string): number | undefined {
  const value = options[name];
  if (value === undefined) return undefined;
  if (!/^[0-9]{1,11}$/.test(value)) throw new UsageError(`--${name} tiene que ser un entero`);
  return Number(value);
}

function encodingOf(options: Options): 'hex' | 'base64' | undefined {
  const { encoding } = options;
  if (encoding === undefined || encoding === 'hex' || encoding === 'base64') return encoding;
  throw new UsageError('--encoding tiene que ser hex o base64');
}

/** Lo mismo, con las claves que pueden faltar como opcionales. */
type Defined<T> = { [K in keyof T as undefined extends T[K] ? never : K]: T[K] } & {
  [K in keyof T as undefined extends T[K] ? K : never]?: Exclude<T[K], undefined>;
};

/** Saca las claves con valor `undefined`, que las opciones exactas no admiten. */
function defined<T extends object>(values: T): Defined<T> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined),
  ) as Defined<T>;
}

async function signed(options: Options, io: CliIo): Promise<IncomingRequest> {
  const request: SignedRequestOptions = defined({
    secret: secretOf(options, io),
    body: io.read(required(options, 'body')),
    timestamp: integer(options, 'timestamp'),
    id: options.id,
    dataId: options['data-id'],
    endpointId: options['endpoint-id'],
    header: options.header,
    prefix: options.prefix,
    encoding: encodingOf(options),
    idHeader: options['id-header'],
  });
  return signedRequest(required(options, 'scheme') as SignedScheme, request);
}

async function verifierOf(options: Options, io: CliIo): Promise<Verifier> {
  const scheme = required(options, 'scheme');
  const secrets = [secretOf(options, io)];
  const timed = defined({ secrets, toleranceSeconds: integer(options, 'tolerance') });
  switch (scheme) {
    case 'standard': {
      // Se carga recién acá: es el único esquema que necesita la librería de referencia.
      const { standardScheme } = await import('./adapters/schemes/standard/index');
      return standardScheme(timed);
    }
    case 'standard-v2a':
      return standardPublicKeyScheme(
        defined({
          publicKeys: secrets,
          endpointId: required(options, 'endpoint-id'),
          toleranceSeconds: integer(options, 'tolerance'),
        }),
      );
    case 'discord':
      return discordScheme(
        defined({ publicKeys: secrets, toleranceSeconds: integer(options, 'tolerance') }),
      );
    case 'stripe':
      return stripeScheme(timed);
    case 'slack':
      return slackScheme(timed);
    case 'tiktok':
      return tiktokScheme(timed);
    case 'mercadopago':
      return mercadoPagoScheme(timed);
    case 'github':
      return githubScheme({ secrets });
    case 'creem':
      return creemScheme({ secrets });
    case 'shopify':
      return shopifyScheme({ secrets });
    case 'hmac-body':
      return hmacBodyScheme(
        defined({
          secrets,
          header: required(options, 'header'),
          prefix: options.prefix,
          encoding: encodingOf(options),
          idHeader: options['id-header'],
        }),
      );
    default:
      throw new UsageError(`esquema desconocido: ${scheme}`);
  }
}

type Pairs = ReadonlyArray<readonly [string, string]>;

function pairs(value: unknown, name: string): Pairs {
  const valid =
    Array.isArray(value) &&
    value.every(
      (pair) =>
        Array.isArray(pair) &&
        pair.length === 2 &&
        typeof pair[0] === 'string' &&
        typeof pair[1] === 'string',
    );
  if (!valid) throw new UsageError(`${name} tiene que ser una lista de pares de texto`);
  return value as Pairs;
}

function savedRequest(text: string): IncomingRequest {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new UsageError('el pedido no es JSON');
  }
  const saved = (typeof data === 'object' && data !== null ? data : {}) as Record<string, unknown>;
  if (typeof saved.body !== 'string') throw new UsageError('body tiene que ser un texto');
  return {
    headers: pairs(saved.headers, 'headers'),
    query: pairs(saved.query ?? [], 'query'),
    body: new TextEncoder().encode(saved.body),
  };
}

function shown(request: IncomingRequest): string {
  const body = new TextDecoder().decode(request.body);
  return JSON.stringify({ headers: request.headers, query: request.query, body }, null, 2);
}

/** Corre un comando y devuelve el código de salida. */
export async function runCli(argv: readonly string[], io: CliIo): Promise<number> {
  const [command, ...rest] = argv;
  if (command === undefined || command === 'help' || command === '--help' || command === '-h') {
    io.out(USAGE);
    return command === undefined ? 2 : 0;
  }

  try {
    const { values } = parseArgs({
      args: [...rest],
      strict: true,
      options: Object.fromEntries(
        [
          'scheme',
          'secret-env',
          'body',
          'request',
          'url',
          'timestamp',
          'id',
          'data-id',
          'endpoint-id',
          'header',
          'prefix',
          'encoding',
          'id-header',
          'tolerance',
        ].map((name) => [name, { type: 'string' as const }]),
      ),
    });
    const options = values as Options;

    if (command === 'keygen') {
      // La clave privada sale por la salida estándar porque se la pidió: guardala en un gestor
      // de secretos y compartí sólo la pública.
      io.out(JSON.stringify(await generateStandardKeyPair(), null, 2));
      return 0;
    }
    if (command === 'sign') {
      io.out(shown(await signed(options, io)));
      return 0;
    }
    if (command === 'verify') {
      const text = new TextDecoder().decode(io.read(required(options, 'request')));
      const verifier = await verifierOf(options, io);
      const result = await verifier.verify(savedRequest(text));
      io.out(JSON.stringify(result));
      return result.outcome === 'ok' ? 0 : 1;
    }
    if (command === 'send') {
      const url = new URL(required(options, 'url'));
      const request = await signed(options, io);
      for (const [name, value] of request.query) url.searchParams.append(name, value);
      const headers = new Headers({ 'content-type': 'application/json' });
      for (const [name, value] of request.headers) headers.append(name, value);
      const response = await io.fetch(url, {
        method: 'POST',
        headers,
        body: new Uint8Array(request.body),
        redirect: 'manual',
      });
      await response.body?.cancel();
      io.out(String(response.status));
      return response.ok ? 0 : 1;
    }
    throw new UsageError(`comando desconocido: ${command}`);
  } catch (error) {
    // El mensaje nunca incluye el secreto: sólo el nombre de la variable que lo tiene.
    const message = error instanceof Error ? error.message : String(error);
    io.err(`omniwebhook: ${message}`);
    return error instanceof UsageError || error instanceof TypeError ? 2 : 1;
  }
}

/** La entrada del ejecutable. */
export async function main(): Promise<void> {
  process.exitCode = await runCli(process.argv.slice(2), {
    env: process.env,
    read: (path) => readFileSync(path === '-' ? 0 : path),
    out: (line) => console.log(line),
    err: (line) => console.error(line),
    fetch,
  });
}
