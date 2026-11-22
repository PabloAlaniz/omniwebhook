import type { Verifier } from '../../application/ports';
import { ConfigurationError } from '../../domain/errors';
import { eventKey } from '../../domain/event-key';
import { pickSingles } from '../../domain/fields';
import { fieldValues } from '../../domain/incoming-request';
import { hmacSha256, toBase64, toHex, utf8 } from '../crypto/web-crypto';
import { bodyFingerprint, jsonIdKey } from './event-keys';
import { type Reading, type SchemeConfig, schemeVerifier } from './scheme-verifier';

export type SignatureEncoding = 'hex' | 'base64';

/** Un emisor que firma sólo el cuerpo y manda la firma en una cabecera. */
export interface BodySignatureFormat {
  /** El nombre del esquema en la clave del evento. */
  readonly name: string;
  /** La cabecera que trae la firma. */
  readonly header: string;
  /** Un texto fijo antes de la firma. */
  readonly prefix: string;
  readonly encoding: SignatureEncoding;
  /** La cabecera que identifica el evento, si el emisor manda una. */
  readonly idHeader?: string;
  /** De dónde sale la clave del evento cuando no hay cabecera que lo identifique. */
  readonly fallbackKey: 'json-id' | 'fingerprint';
}

/** Arma el verificador de un formato que firma sólo el cuerpo. No lleva marca de tiempo. */
export function bodySignatureVerifier(format: BodySignatureFormat, config: SchemeConfig): Verifier {
  for (const [option, value] of [
    ['name', format.name],
    ['header', format.header],
  ] as const) {
    if (value.trim() === '') throw new ConfigurationError(`${option} no puede estar vacío`);
  }
  if (format.encoding !== 'hex' && format.encoding !== 'base64') {
    throw new ConfigurationError('encoding tiene que ser "hex" o "base64"');
  }

  return schemeVerifier<Reading>(
    {
      keyOf: utf8,
      read(request) {
        const fields = pickSingles(
          { signature: fieldValues(request.headers, format.header) },
          {
            id: format.idHeader === undefined ? [] : fieldValues(request.headers, format.idHeader),
          },
        );
        if (typeof fields === 'string') return fields;
        if (!fields.signature.startsWith(format.prefix)) return 'malformed';

        const received = fields.signature.slice(format.prefix.length);
        const { id } = fields;
        return {
          timestamp: null,
          received: [format.encoding === 'hex' ? received.toLowerCase() : received],
          eventKey: () => {
            if (id !== undefined) return eventKey(format.name, id);
            return format.fallbackKey === 'json-id'
              ? jsonIdKey(format.name, request.body)
              : bodyFingerprint(format.name, request.body);
          },
        };
      },
      async expected(key, _reading, request) {
        const mac = await hmacSha256(key, request.body);
        return format.encoding === 'hex' ? toHex(mac) : toBase64(mac);
      },
    },
    config,
  );
}
