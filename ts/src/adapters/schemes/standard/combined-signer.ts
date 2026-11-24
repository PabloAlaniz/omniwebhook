import type { MessageSigner } from '../../../application/ports';
import { ConfigurationError } from '../../../domain/errors';
import type { OutgoingMessage, Signing } from '../../../domain/message';

const SIGNATURE = 'webhook-signature';

/**
 * Firma un mismo mensaje con varios firmantes del formato estándar y junta sus firmas en una
 * sola cabecera. Sirve para migrar de la firma simétrica a la asimétrica: cada receptor mira
 * sólo las de su variante (sección 7.1).
 *
 * Si alguno no puede firmar, el mensaje no se firma: el resultado es el problema del primero.
 */
export function combinedSigner(signers: readonly MessageSigner[]): MessageSigner {
  if (signers.length === 0) throw new ConfigurationError('signers no puede estar vacío');

  return {
    async sign(message: OutgoingMessage): Promise<Signing> {
      let headers: Record<string, string> = {};
      const signatures: string[] = [];
      for (const signer of signers) {
        const signing = await signer.sign(message);
        if (signing.outcome !== 'signed') return signing;
        headers = { ...headers, ...signing.headers };
        const signature = signing.headers[SIGNATURE];
        if (signature !== undefined) signatures.push(signature);
      }
      return { outcome: 'signed', headers: { ...headers, [SIGNATURE]: signatures.join(' ') } };
    },
  };
}
