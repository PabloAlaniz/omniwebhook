import type { MessageSigner } from '../../../application/ports';
import { messageProblem, type OutgoingMessage, type Signing } from '../../../domain/message';
import {
  concat,
  ed25519PublicKey,
  fromStrictBase64,
  randomEd25519Seed,
  sha256,
  signEd25519,
  toBase64,
  utf8,
} from '../../crypto/web-crypto';

const SECRET_PREFIX = 'whsk_';
const PUBLIC_PREFIX = 'whpk_';
const SEED_BYTES = 32;

export interface StandardKeySignerConfig {
  /** Las claves privadas, con la forma `whsk_…`. Se manda una firma por cada una, en orden. */
  readonly secretKeys: readonly string[];
}

/** La semilla de un texto `whsk_…`, o `null` si no se puede usar (sección 7.1). */
function seedOf(text: string): Uint8Array | null {
  if (typeof text !== 'string' || !text.startsWith(SECRET_PREFIX)) return null;
  const seed = fromStrictBase64(text.slice(SECRET_PREFIX.length));
  return seed !== null && seed.byteLength === SEED_BYTES ? seed : null;
}

/**
 * Firma lo que se emite con la variante asimétrica del formato, `v2a` (sección 7.1). Quien
 * recibe verifica con la clave pública y con el identificador del destino, que es parte de lo
 * que se firma.
 */
export function standardKeySigner(config: StandardKeySignerConfig): MessageSigner {
  const seeds = config.secretKeys.map(seedOf);

  return {
    async sign(message: OutgoingMessage): Promise<Signing> {
      const problem = messageProblem(message);
      if (problem !== null) return { outcome: problem };
      const { endpointId } = message;
      if (typeof endpointId !== 'string' || endpointId === '' || endpointId.includes('.')) {
        return { outcome: 'invalid_endpoint' };
      }
      if (seeds.length === 0) return { outcome: 'unconfigured' };

      const prefix = utf8(`${endpointId}.${message.id}.${message.timestamp}.`);
      const content = await sha256(concat(prefix, message.payload));
      const signatures: string[] = [];
      for (const seed of seeds) {
        if (seed === null) return { outcome: 'unconfigured' };
        signatures.push(`v2a,${toBase64(await signEd25519(seed, content))}`);
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

/** La clave pública `whpk_…` de una clave privada `whsk_…`; `null` si la privada no se puede usar. */
export async function standardPublicKeyOf(secretKey: string): Promise<string | null> {
  const seed = seedOf(secretKey);
  return seed === null ? null : PUBLIC_PREFIX + toBase64(await ed25519PublicKey(seed));
}

/** Un par de claves nuevo. La privada se guarda del lado de quien emite; la pública es la que se comparte. */
export async function generateStandardKeyPair(): Promise<{
  readonly secretKey: string;
  readonly publicKey: string;
}> {
  const seed = randomEd25519Seed();
  return {
    secretKey: SECRET_PREFIX + toBase64(seed),
    publicKey: PUBLIC_PREFIX + toBase64(await ed25519PublicKey(seed)),
  };
}
