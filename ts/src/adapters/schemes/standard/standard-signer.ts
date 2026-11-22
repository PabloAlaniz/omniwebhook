import type { MessageSigner } from '../../../application/ports';
import { messageProblem, type OutgoingMessage, type Signing } from '../../../domain/message';
import { referenceSigner } from './reference-signer';
import { standardKey } from './secret';
import type { StandardSigner } from './signer';

export interface StandardSignerConfig {
  /** Con más de un secreto se manda una firma por cada uno, en este orden (rotación). */
  readonly secrets: readonly string[];
  /** Quién calcula la firma. Por defecto, la librería de referencia del formato. */
  readonly signer?: StandardSigner;
}

/** Firma lo que se emite con el formato Standard Webhooks (sección 7). */
export function standardSigner(config: StandardSignerConfig): MessageSigner {
  const signer = config.signer ?? referenceSigner;
  const keys = config.secrets.map((secret) => (secret === '' ? null : standardKey(secret)));

  return {
    async sign(message: OutgoingMessage): Promise<Signing> {
      const problem = messageProblem(message);
      if (problem !== null) return { outcome: problem };
      if (keys.length === 0) return { outcome: 'unconfigured' };

      const signatures: string[] = [];
      for (const key of keys) {
        if (key === null) return { outcome: 'unconfigured' };
        signatures.push(await signer.sign(key, message.id, message.timestamp, message.payload));
      }
      return {
        outcome: 'signed',
        headers: {
          'webhook-id': message.id,
          'webhook-timestamp': String(message.timestamp),
          'webhook-signature': signatures.join(' '),
        },
      };
    },
  };
}
