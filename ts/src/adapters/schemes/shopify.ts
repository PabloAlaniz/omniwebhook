import type { Verifier } from '../../application/ports';
import { bodySignatureVerifier } from './body-signature';
import type { SchemeConfig } from './scheme-verifier';

/** Verifica el formato de firma de Shopify (sección 5.9). */
export function shopifyScheme(config: SchemeConfig): Verifier {
  return bodySignatureVerifier(
    {
      name: 'shopify',
      header: 'x-shopify-hmac-sha256',
      prefix: '',
      encoding: 'base64',
      idHeader: 'x-shopify-webhook-id',
      fallbackKey: 'fingerprint',
    },
    config,
  );
}
