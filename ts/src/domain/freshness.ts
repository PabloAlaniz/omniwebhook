export const DEFAULT_TOLERANCE_SECONDS = 300;

/** Un pedido es reciente si su marca no se aleja de ahora más que la tolerancia, en ningún sentido. */
export function isFresh(now: number, timestamp: number, toleranceSeconds: number): boolean {
  return Math.abs(now - timestamp) <= toleranceSeconds;
}
