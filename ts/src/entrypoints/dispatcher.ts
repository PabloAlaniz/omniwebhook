import { systemClock } from '../adapters/clock/system-clock';
import { randomTokens } from '../adapters/tokens/random-tokens';
import { DispatchDue, type DispatchDueDependencies } from '../application/dispatch-due';
import type { Clock, TokenGenerator } from '../application/ports';

export interface DispatcherOptions extends Omit<DispatchDueDependencies, 'clock' | 'tokens'> {
  readonly clock?: Clock;
  readonly tokens?: TokenGenerator;
}

/** Arma el despacho de una tanda con el reloj del sistema y tokens aleatorios por defecto. */
export function createDispatcher(options: DispatcherOptions): DispatchDue {
  return new DispatchDue({
    ...options,
    clock: options.clock ?? systemClock,
    tokens: options.tokens ?? randomTokens,
  });
}
