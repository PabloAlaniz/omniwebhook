import { Webhook } from 'standardwebhooks';
import type { StandardSigner } from './signer';

/** Firma con la librería de referencia del formato estándar. */
export const referenceSigner: StandardSigner = {
  sign(key, id, timestamp, payload) {
    return new Webhook(key, { format: 'raw' }).sign(id, new Date(timestamp * 1000), payload);
  },
};
