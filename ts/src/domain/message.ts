/** Un mensaje a emitir (sección 7). */
export interface OutgoingMessage {
  /** Identifica al mensaje, no al intento: es el mismo en todos los reintentos. */
  readonly id: string;
  /** La hora del intento, en segundos. */
  readonly timestamp: number;
  /** El cuerpo, byte a byte como se va a enviar. */
  readonly payload: Uint8Array;
  /** El identificador del destino. Lo necesita la firma asimétrica (sección 7.1). */
  readonly endpointId?: string;
}

/** El tamaño máximo del payload de un mensaje, en bytes, si no se indica otro (sección 7). */
export const DEFAULT_MAX_PAYLOAD_BYTES = 262_144;

export type SigningProblem =
  | 'invalid_id'
  | 'invalid_timestamp'
  | 'invalid_endpoint'
  | 'unconfigured';

export type Signing =
  | { readonly outcome: 'signed'; readonly headers: Readonly<Record<string, string>> }
  | { readonly outcome: SigningProblem };

/** Lo que impide firmar un mensaje, mirando sólo el mensaje. */
export function messageProblem(
  message: Pick<OutgoingMessage, 'id' | 'timestamp'>,
): Extract<SigningProblem, 'invalid_id' | 'invalid_timestamp'> | null {
  if (message.id === '' || message.id.includes('.')) return 'invalid_id';
  if (!Number.isInteger(message.timestamp) || message.timestamp < 0) return 'invalid_timestamp';
  return null;
}
