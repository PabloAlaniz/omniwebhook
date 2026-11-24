import { systemClock } from '../adapters/clock/system-clock';
import { randomTokens } from '../adapters/tokens/random-tokens';
import type { Clock, Timer, TokenGenerator } from '../application/ports';
import { ReceiveWebhook, type ReceiveWebhookDependencies } from '../application/receive-webhook';

export interface ReceiverOptions<T = never>
  extends Omit<ReceiveWebhookDependencies<T>, 'clock' | 'tokens' | 'timer'> {
  readonly timer?: Timer;
  readonly clock?: Clock;
  readonly tokens?: TokenGenerator;
}

/** Arma el caso de uso de recepción con el reloj del sistema y tokens aleatorios por defecto. */
export function createReceiver<T = never>(options: ReceiverOptions<T>): ReceiveWebhook<T> {
  return new ReceiveWebhook<T>({
    ...options,
    clock: options.clock ?? systemClock,
    tokens: options.tokens ?? randomTokens,
    timer: options.timer ?? { nowMs: () => Date.now() },
  });
}
