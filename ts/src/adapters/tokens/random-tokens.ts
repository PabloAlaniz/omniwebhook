import type { TokenGenerator } from '../../application/ports';

/** Tokens de reserva aleatorios (UUID v4). */
export const randomTokens: TokenGenerator = {
  next: () => crypto.randomUUID(),
};
