import type { Verifier } from '../../application/ports';
import { pickSingles } from '../../domain/fields';
import { fieldValues } from '../../domain/incoming-request';
import { pairValues, parsePairs } from '../../domain/signature-pairs';
import { parseTimestamp, SECONDS_DIGITS } from '../../domain/timestamp';
import { concat, hmacSha256, toHex, utf8 } from '../crypto/web-crypto';
import { jsonIdKey } from './event-keys';
import { type Reading, schemeVerifier, type TimedSchemeConfig } from './scheme-verifier';

interface StripeReading extends Reading {
  /** La marca tal como llegó: es parte de lo que se firma. */
  readonly rawTimestamp: string;
}

/** Verifica el formato de firma de Stripe (sección 5.2). */
export function stripeScheme(config: TimedSchemeConfig): Verifier {
  return schemeVerifier<StripeReading>(
    {
      keyOf: utf8,
      read(request) {
        const fields = pickSingles({ header: fieldValues(request.headers, 'stripe-signature') });
        if (typeof fields === 'string') return fields;

        const pairs = parsePairs(fields.header);
        const times = pairValues(pairs, 't');
        const signatures = pairValues(pairs, 'v1');
        if (times.length > 1) return 'ambiguous';

        const rawTimestamp = times[0];
        const timestamp =
          rawTimestamp === undefined ? null : parseTimestamp(rawTimestamp, SECONDS_DIGITS);
        if (rawTimestamp === undefined || timestamp === null || signatures.length === 0)
          return 'malformed';

        return {
          rawTimestamp,
          timestamp,
          received: signatures.map((signature) => signature.toLowerCase()),
          eventKey: () => jsonIdKey('stripe', request.body),
        };
      },
      async expected(key, reading, request) {
        return toHex(await hmacSha256(key, concat(utf8(`${reading.rawTimestamp}.`), request.body)));
      },
    },
    config,
  );
}
