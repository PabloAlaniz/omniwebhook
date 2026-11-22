import type { Verifier } from '../../application/ports';
import { eventKey } from '../../domain/event-key';
import { pickSingles } from '../../domain/fields';
import { fieldValues } from '../../domain/incoming-request';
import { pairValues, parsePairs } from '../../domain/signature-pairs';
import { parseTimestamp, SECONDS_OR_MILLIS_DIGITS, toSeconds } from '../../domain/timestamp';
import { hmacSha256, toHex, utf8 } from '../crypto/web-crypto';
import { type Reading, schemeVerifier, type TimedSchemeConfig } from './scheme-verifier';

interface MercadoPagoReading extends Reading {
  /** Lo que se firma: `id:…;request-id:…;ts:…;`, sin las partes que falten. */
  readonly manifest: string;
}

/**
 * Verifica el formato de firma de Mercado Pago (sección 5.3).
 *
 * La firma no cubre el cuerpo: conviene tratar el aviso como una señal de cambio y
 * consultar el recurso al emisor antes de actuar.
 */
export function mercadoPagoScheme(config: TimedSchemeConfig): Verifier {
  return schemeVerifier<MercadoPagoReading>(
    {
      keyOf: utf8,
      read(request) {
        const fields = pickSingles(
          { signature: fieldValues(request.headers, 'x-signature') },
          {
            requestId: fieldValues(request.headers, 'x-request-id'),
            dataId: fieldValues(request.query, 'data.id'),
          },
        );
        if (typeof fields === 'string') return fields;

        const pairs = parsePairs(fields.signature, { lowercaseKeys: true });
        const times = pairValues(pairs, 'ts');
        const signatures = pairValues(pairs, 'v1');
        if (times.length > 1 || signatures.length > 1) return 'ambiguous';

        const [rawTimestamp] = times;
        const [signature] = signatures;
        const raw =
          rawTimestamp === undefined
            ? null
            : parseTimestamp(rawTimestamp, SECONDS_OR_MILLIS_DIGITS);
        if (rawTimestamp === undefined || raw === null || signature === undefined)
          return 'malformed';

        const dataId = fields.dataId?.toLowerCase();
        const { requestId } = fields;
        const parts = [
          dataId === undefined ? '' : `id:${dataId};`,
          requestId === undefined ? '' : `request-id:${requestId};`,
          `ts:${rawTimestamp};`,
        ];

        return {
          manifest: parts.join(''),
          timestamp: toSeconds(raw),
          received: [signature.toLowerCase()],
          eventKey: () =>
            dataId === undefined && requestId === undefined
              ? eventKey('mercadopago', `ts:${rawTimestamp}`)
              : eventKey('mercadopago', `${dataId ?? ''}:${requestId ?? ''}`),
        };
      },
      async expected(key, reading) {
        return toHex(await hmacSha256(key, utf8(reading.manifest)));
      },
    },
    config,
  );
}
