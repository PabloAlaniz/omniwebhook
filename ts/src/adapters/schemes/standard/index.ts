import type { Verifier } from '../../../application/ports';
import { eventKey } from '../../../domain/event-key';
import { pickSingles } from '../../../domain/fields';
import { fieldValues } from '../../../domain/incoming-request';
import { parseTimestamp, SECONDS_DIGITS } from '../../../domain/timestamp';
import { type Reading, schemeVerifier, type TimedSchemeConfig } from '../scheme-verifier';
import { referenceSigner } from './reference-signer';
import { standardKey } from './secret';
import type { StandardSigner } from './signer';

export type { StandardSigner } from './signer';

const VERSION = 'v1,';

export interface StandardSchemeConfig extends TimedSchemeConfig {
  /** Quién calcula la firma. Por defecto, la librería de referencia del formato. */
  readonly signer?: StandardSigner;
}

interface StandardReading extends Reading {
  readonly id: string;
  readonly timestamp: number;
}

/** Verifica el formato Standard Webhooks con firma simétrica `v1` (sección 5.1). */
export function standardScheme(config: StandardSchemeConfig): Verifier {
  const signer = config.signer ?? referenceSigner;

  return schemeVerifier<StandardReading>(
    {
      keyOf: standardKey,
      read(request) {
        const fields = pickSingles({
          id: fieldValues(request.headers, 'webhook-id'),
          timestamp: fieldValues(request.headers, 'webhook-timestamp'),
          signature: fieldValues(request.headers, 'webhook-signature'),
        });
        if (typeof fields === 'string') return fields;

        const timestamp = parseTimestamp(fields.timestamp, SECONDS_DIGITS);
        const received = fields.signature.split(' ').filter((token) => token.startsWith(VERSION));
        if (timestamp === null || received.length === 0) return 'malformed';

        return {
          id: fields.id,
          timestamp,
          received,
          eventKey: () => eventKey('standard', fields.id),
        };
      },
      expected: (key, reading, request) =>
        signer.sign(key, reading.id, reading.timestamp, request.body),
    },
    config,
  );
}
