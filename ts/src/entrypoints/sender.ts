import { systemClock } from '../adapters/clock/system-clock';
import { fetchTransport } from '../adapters/transport/fetch';
import type { Clock, HttpTransport, RandomSource, Timer } from '../application/ports';
import { SendWebhook, type SendWebhookDependencies } from '../application/send-webhook';

export interface SenderOptions
  extends Omit<SendWebhookDependencies, 'clock' | 'timer' | 'random' | 'transport'> {
  readonly transport?: HttpTransport;
  readonly clock?: Clock;
  readonly timer?: Timer;
  readonly random?: RandomSource;
}

/**
 * Arma el caso de uso de envío con el reloj del sistema y, si no se indica otro, el
 * transporte sobre la API Fetch.
 */
export function createSender(options: SenderOptions): SendWebhook {
  return new SendWebhook({
    ...options,
    transport: options.transport ?? fetchTransport(),
    clock: options.clock ?? systemClock,
    timer: options.timer ?? { nowMs: () => Date.now() },
    random: options.random ?? { next: () => Math.random() },
  });
}
