import type { Verifier } from '../../application/ports';
import { bodySignatureVerifier } from './body-signature';
import type { SchemeConfig } from './scheme-verifier';

/** Verifica el formato de firma de Creem (sección 5.5). */
export function creemScheme(config: SchemeConfig): Verifier {
  return bodySignatureVerifier(
    {
      name: 'creem',
      header: 'creem-signature',
      prefix: '',
      encoding: 'hex',
      fallbackKey: 'json-id',
    },
    config,
  );
}
