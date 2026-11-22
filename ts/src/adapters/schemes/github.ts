import type { Verifier } from '../../application/ports';
import { bodySignatureVerifier } from './body-signature';
import type { SchemeConfig } from './scheme-verifier';

/** Verifica el formato de firma de GitHub (sección 5.4). */
export function githubScheme(config: SchemeConfig): Verifier {
  return bodySignatureVerifier(
    {
      name: 'github',
      header: 'x-hub-signature-256',
      prefix: 'sha256=',
      encoding: 'hex',
      idHeader: 'x-github-delivery',
      fallbackKey: 'fingerprint',
    },
    config,
  );
}
