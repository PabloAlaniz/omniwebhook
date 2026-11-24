/**
 * Ayudas para probar una integración: arman el pedido que mandaría cada emisor, firmado
 * con el secreto que se indique. Viven en una entrada aparte porque no son para producción.
 */
import { concat, hmacSha256, toBase64, toHex, utf8 } from './adapters/crypto/web-crypto';
import { standardKey } from './adapters/schemes/standard/secret';
import { ConfigurationError } from './domain/errors';
import type { Field, IncomingRequest } from './domain/incoming-request';

export type SignedScheme =
  | 'standard'
  | 'stripe'
  | 'slack'
  | 'shopify'
  | 'tiktok'
  | 'mercadopago'
  | 'github'
  | 'creem'
  | 'hmac-body';

export interface SignedRequestOptions {
  /** El secreto con el que firma el emisor: el mismo que recibe el esquema. */
  readonly secret: string;
  /** El cuerpo crudo. Un texto se codifica en UTF-8. */
  readonly body: string | Uint8Array;
  /** La marca de tiempo firmada, en segundos. Por defecto, ahora. Para probar `stale`, una vieja. */
  readonly timestamp?: number;
  /**
   * El identificador que manda el emisor fuera del cuerpo: `webhook-id` en `standard`,
   * `x-github-delivery`, `x-shopify-webhook-id`, `x-request-id` en `mercadopago` o la cabecera
   * `idHeader` de `hmac-body`. En `standard` es obligatorio para el formato y, si falta, se
   * genera uno.
   */
  readonly id?: string;
  /** Sólo `mercadopago`: el parámetro `data.id` de la URL. */
  readonly dataId?: string;
  /** Sólo `hmac-body`: la misma configuración que recibe `hmacBodyScheme`. */
  readonly header?: string;
  readonly prefix?: string;
  readonly encoding?: 'hex' | 'base64';
  readonly idHeader?: string;
}

/**
 * Arma el pedido que mandaría el emisor, con una firma válida: lo verifica el esquema del
 * mismo nombre configurado con el mismo secreto.
 */
export async function signedRequest(
  scheme: SignedScheme,
  options: SignedRequestOptions,
): Promise<IncomingRequest> {
  const body = typeof options.body === 'string' ? utf8(options.body) : options.body;
  const timestamp = String(options.timestamp ?? Math.floor(Date.now() / 1000));
  const key = scheme === 'standard' ? standardKey(options.secret) : utf8(options.secret);
  if (key === null || options.secret === '') {
    throw new ConfigurationError('secret no se puede usar con este esquema');
  }
  const hex = async (...parts: Uint8Array[]) => toHex(await hmacSha256(key, concat(...parts)));
  const base64 = async (...parts: Uint8Array[]) =>
    toBase64(await hmacSha256(key, concat(...parts)));
  const optional = (name: string, value: string | undefined): Field[] =>
    value === undefined ? [] : [[name, value]];

  let headers: Field[];
  let query: Field[] = [];
  switch (scheme) {
    case 'standard': {
      const id = options.id ?? `msg_${crypto.randomUUID().replaceAll('-', '')}`;
      headers = [
        ['webhook-id', id],
        ['webhook-timestamp', timestamp],
        ['webhook-signature', `v1,${await base64(utf8(`${id}.${timestamp}.`), body)}`],
      ];
      break;
    }
    case 'stripe':
      headers = [
        ['stripe-signature', `t=${timestamp},v1=${await hex(utf8(`${timestamp}.`), body)}`],
      ];
      break;
    case 'tiktok':
      headers = [
        ['tiktok-signature', `t=${timestamp},s=${await hex(utf8(`${timestamp}.`), body)}`],
      ];
      break;
    case 'slack':
      headers = [
        ['x-slack-signature', `v0=${await hex(utf8(`v0:${timestamp}:`), body)}`],
        ['x-slack-request-timestamp', timestamp],
      ];
      break;
    case 'mercadopago': {
      const dataId = options.dataId?.toLowerCase();
      const manifest = [
        dataId === undefined ? '' : `id:${dataId};`,
        options.id === undefined ? '' : `request-id:${options.id};`,
        `ts:${timestamp};`,
      ].join('');
      headers = [
        ['x-signature', `ts=${timestamp},v1=${await hex(utf8(manifest))}`],
        ...optional('x-request-id', options.id),
      ];
      query = optional('data.id', options.dataId);
      break;
    }
    case 'github':
      headers = [
        ['x-hub-signature-256', `sha256=${await hex(body)}`],
        ...optional('x-github-delivery', options.id),
      ];
      break;
    case 'creem':
      headers = [['creem-signature', await hex(body)]];
      break;
    case 'shopify':
      headers = [
        ['x-shopify-hmac-sha256', await base64(body)],
        ...optional('x-shopify-webhook-id', options.id),
      ];
      break;
    case 'hmac-body': {
      if (options.header === undefined || options.header.trim() === '') {
        throw new ConfigurationError('header no puede estar vacío');
      }
      const signature = options.encoding === 'base64' ? await base64(body) : await hex(body);
      headers = [
        [options.header, `${options.prefix ?? ''}${signature}`],
        ...(options.idHeader === undefined ? [] : optional(options.idHeader, options.id)),
      ];
      break;
    }
    default:
      throw new ConfigurationError(`esquema desconocido: ${String(scheme)}`);
  }
  return { headers, query, body };
}

/**
 * El mismo pedido con un byte del cuerpo cambiado después de firmar: tiene que terminar en
 * `invalid`. En `mercadopago`, cuya firma no cubre el cuerpo, lo que cambia es la firma.
 */
export function tampered(request: IncomingRequest): IncomingRequest {
  const signature = request.headers.findIndex(([name]) => name === 'x-signature');
  if (signature !== -1) {
    const headers = request.headers.map(([name, value], index): Field => {
      if (index !== signature) return [name, value];
      const last = value.slice(-1) === '0' ? '1' : '0';
      return [name, value.slice(0, -1) + last];
    });
    return { ...request, headers };
  }
  const body = new Uint8Array(request.body.byteLength + 1);
  body.set(request.body);
  body[request.body.byteLength] = 0x20;
  return { ...request, body };
}

/** Convierte el pedido en un `Request` de la API Fetch, para pasárselo a una ruta. */
export function toFetchRequest(
  request: IncomingRequest,
  url = 'https://receptor.test/webhooks',
): Request {
  const target = new URL(url);
  for (const [name, value] of request.query) target.searchParams.append(name, value);
  const headers = new Headers();
  for (const [name, value] of request.headers) headers.append(name, value);
  return new Request(target, { method: 'POST', headers, body: new Uint8Array(request.body) });
}
