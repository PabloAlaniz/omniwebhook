import type { Clock, Verifier } from '../../../application/ports';
import { ConfigurationError } from '../../../domain/errors';
import { eventKey } from '../../../domain/event-key';
import { pickSingles } from '../../../domain/fields';
import { fieldValues } from '../../../domain/incoming-request';
import { parseTimestamp, SECONDS_DIGITS } from '../../../domain/timestamp';
import { concat, fromStrictBase64, sha256, utf8, verifiesEd25519 } from '../../crypto/web-crypto';
import { type Reading, schemeVerifier } from '../scheme-verifier';

const VERSION = 'v2a,';
const KEY_PREFIX = 'whpk_';
const KEY_BYTES = 32;
const SIGNATURE_BYTES = 64;

export interface StandardPublicKeySchemeConfig {
  /** Las claves públicas aceptadas, con la forma `whpk_…`. Vale cualquiera (rotación). */
  readonly publicKeys: readonly string[];
  /** El identificador que el emisor le asignó a este destino. Es parte de lo que se firma. */
  readonly endpointId: string;
  /** Cuánto puede alejarse de ahora la marca de tiempo, en segundos. Por defecto, 300. */
  readonly toleranceSeconds?: number;
  readonly clock?: Clock;
}

interface PublicKeyReading extends Reading {
  /** `<endpoint_id>.<webhook-id>.<webhook-timestamp>.`: lo que va antes del cuerpo. */
  readonly prefix: Uint8Array;
  /** El contenido firmado, que se calcula una sola vez por pedido. */
  content?: Promise<Uint8Array>;
}

/** La clave pública de un texto `whpk_…`, o `null` si no se puede usar (sección 5.10). */
export function standardPublicKey(text: string): Uint8Array | null {
  if (!text.startsWith(KEY_PREFIX)) return null;
  const key = fromStrictBase64(text.slice(KEY_PREFIX.length));
  return key !== null && key.byteLength === KEY_BYTES ? key : null;
}

/** Verifica el formato Standard Webhooks con firma asimétrica `v2a` (sección 5.10). */
export function standardPublicKeyScheme(config: StandardPublicKeySchemeConfig): Verifier {
  const { endpointId } = config;
  if (typeof endpointId !== 'string' || endpointId === '' || endpointId.includes('.')) {
    throw new ConfigurationError('endpointId no puede estar vacío ni contener un punto');
  }

  return schemeVerifier<PublicKeyReading>(
    {
      keyOf: standardPublicKey,
      read(request) {
        const fields = pickSingles({
          id: fieldValues(request.headers, 'webhook-id'),
          timestamp: fieldValues(request.headers, 'webhook-timestamp'),
          signature: fieldValues(request.headers, 'webhook-signature'),
        });
        if (typeof fields === 'string') return fields;

        const timestamp = parseTimestamp(fields.timestamp, SECONDS_DIGITS);
        const received = fields.signature
          .split(' ')
          .filter((token) => token.startsWith(VERSION))
          .map((token) => token.slice(VERSION.length));
        if (timestamp === null || received.length === 0) return 'malformed';

        return {
          prefix: utf8(`${endpointId}.${fields.id}.${fields.timestamp}.`),
          timestamp,
          received,
          eventKey: () => eventKey('standard', fields.id),
        };
      },
      async verifies(key, received, reading, request) {
        const signature = fromStrictBase64(received);
        if (signature === null || signature.byteLength !== SIGNATURE_BYTES) return false;
        reading.content ??= sha256(concat(reading.prefix, request.body));
        return verifiesEd25519(key, signature, await reading.content);
      },
    },
    {
      secrets: config.publicKeys,
      ...(config.clock === undefined ? {} : { clock: config.clock }),
      ...(config.toleranceSeconds === undefined
        ? {}
        : { toleranceSeconds: config.toleranceSeconds }),
    },
  );
}
