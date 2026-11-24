import { systemClock } from '../adapters/clock/system-clock';
import { randomTokens } from '../adapters/tokens/random-tokens';
import type { Clock, Timer, TokenGenerator } from '../application/ports';
import { ReceiveWebhook, type ReceiveWebhookDependencies } from '../application/receive-webhook';

export interface ReceiverOptions
  extends Omit<ReceiveWebhookDependencies, 'clock' | 'tokens' | 'timer'> {
  readonly timer?: Timer;
  readonly clock?: Clock;
  readonly tokens?: TokenGenerator;
}

/** Arma el caso de uso de recepción con el reloj del sistema y tokens aleatorios por defecto. */
export function createReceiver(options: ReceiverOptions): ReceiveWebhook {
  return new ReceiveWebhook({
    ...options,
    clock: options.clock ?? systemClock,
    tokens: options.tokens ?? randomTokens,
    timer: options.timer ?? { nowMs: () => Date.now() },
  });
}
