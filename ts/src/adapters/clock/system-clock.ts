import type { Clock } from '../../application/ports';

/** El reloj del sistema, en segundos. */
export const systemClock: Clock = {
  now: () => Math.floor(Date.now() / 1000),
};
