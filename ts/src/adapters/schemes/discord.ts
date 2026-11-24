import type { Clock, Verifier } from '../../application/ports';
import { pickSingles } from '../../domain/fields';
import { fieldValues } from '../../domain/incoming-request';
import { parseTimestamp, SECONDS_DIGITS } from '../../domain/timestamp';
import { concat, fromHex, utf8, verifiesEd25519 } from '../crypto/web-crypto';
import { jsonIdKey } from './event-keys';
import { type Reading, schemeVerifier } from './scheme-verifier';

const KEY_BYTES = 32;
const SIGNATURE_BYTES = 64;

export interface DiscordSchemeConfig {
  /** Las claves públicas aceptadas, en hexadecimal: la de la aplicación. Vale cualquiera. */
  readonly publicKeys: readonly string[];
  /** Cuánto puede alejarse de ahora la marca de tiempo, en segundos. Por defecto, 300. */
  readonly toleranceSeconds?: number;
  readonly clock?: Clock;
}

interface DiscordReading extends Reading {
  /** La marca tal como llegó: es parte de lo que se firma. */
  readonly rawTimestamp: string;
}

function bytesOf(text: string, length: number): Uint8Array | null {
  const bytes = fromHex(text);
  return bytes !== null && bytes.byteLength === length ? bytes : null;
}

/** Verifica el formato de firma de Discord (sección 5.11). */
export function discordScheme(config: DiscordSchemeConfig): Verifier {
  return schemeVerifier<DiscordReading>(
    {
      keyOf: (text) => bytesOf(text, KEY_BYTES),
      read(request) {
        const fields = pickSingles({
          signature: fieldValues(request.headers, 'x-signature-ed25519'),
          timestamp: fieldValues(request.headers, 'x-signature-timestamp'),
        });
        if (typeof fields === 'string') return fields;

        const timestamp = parseTimestamp(fields.timestamp, SECONDS_DIGITS);
        if (timestamp === null) return 'malformed';

        return {
          rawTimestamp: fields.timestamp,
          timestamp,
          received: [fields.signature],
          eventKey: () => jsonIdKey('discord', request.body),
        };
      },
      async verifies(key, received, reading, request) {
        const signature = bytesOf(received, SIGNATURE_BYTES);
        if (signature === null) return false;
        return verifiesEd25519(key, signature, concat(utf8(reading.rawTimestamp), request.body));
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
