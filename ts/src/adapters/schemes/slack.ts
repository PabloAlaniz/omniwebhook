import type { Verifier } from '../../application/ports';
import { pickSingles } from '../../domain/fields';
import { fieldValues } from '../../domain/incoming-request';
import { parseTimestamp, SECONDS_DIGITS } from '../../domain/timestamp';
import { concat, hmacSha256, toHex, utf8 } from '../crypto/web-crypto';
import { jsonIdKey } from './event-keys';
import { type Reading, schemeVerifier, type TimedSchemeConfig } from './scheme-verifier';

const VERSION = 'v0';

interface SlackReading extends Reading {
  /** La marca tal como llegó: es parte de lo que se firma. */
  readonly rawTimestamp: string;
}

/** Verifica el formato de firma de Slack (sección 5.8). */
export function slackScheme(config: TimedSchemeConfig): Verifier {
  return schemeVerifier<SlackReading>(
    {
      keyOf: utf8,
      read(request) {
        const fields = pickSingles({
          signature: fieldValues(request.headers, 'x-slack-signature'),
          timestamp: fieldValues(request.headers, 'x-slack-request-timestamp'),
        });
        if (typeof fields === 'string') return fields;

        const timestamp = parseTimestamp(fields.timestamp, SECONDS_DIGITS);
        if (timestamp === null || !fields.signature.startsWith(`${VERSION}=`)) return 'malformed';

        return {
          rawTimestamp: fields.timestamp,
          timestamp,
          received: [fields.signature.slice(VERSION.length + 1).toLowerCase()],
          eventKey: () => jsonIdKey('slack', request.body, 'event_id'),
        };
      },
      async expected(key, reading, request) {
        const prefix = utf8(`${VERSION}:${reading.rawTimestamp}:`);
        return toHex(await hmacSha256(key, concat(prefix, request.body)));
      },
    },
    config,
  );
}
