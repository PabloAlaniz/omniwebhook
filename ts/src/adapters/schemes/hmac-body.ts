import type { Verifier } from '../../application/ports';
import { bodySignatureVerifier, type SignatureEncoding } from './body-signature';
import type { SchemeConfig } from './scheme-verifier';

export interface HmacBodyOptions extends SchemeConfig {
  /** La cabecera que trae la firma. */
  readonly header: string;
  /** Un texto fijo antes de la firma. Por defecto, ninguno. */
  readonly prefix?: string;
  /** Por defecto, `hex`. */
  readonly encoding?: SignatureEncoding;
  /** El nombre del esquema en la clave del evento. Por defecto, `hmac-body`. */
  readonly name?: string;
  /** La cabecera que identifica el evento. Sin ella, la clave es la huella del cuerpo. */
  readonly idHeader?: string;
}

/** Verifica a un emisor que firma sólo el cuerpo con HMAC-SHA256 (sección 5.6). */
export function hmacBodyScheme(options: HmacBodyOptions): Verifier {
  return bodySignatureVerifier(
    {
      name: options.name ?? 'hmac-body',
      header: options.header,
      prefix: options.prefix ?? '',
      encoding: options.encoding ?? 'hex',
      fallbackKey: 'fingerprint',
      ...(options.idHeader === undefined ? {} : { idHeader: options.idHeader }),
    },
    options,
  );
}
