import { ConfigurationError, positiveInteger } from '../domain/errors';
import type { IncomingRequest } from '../domain/incoming-request';
import { DEFAULT_MAX_BODY_BYTES } from '../domain/reception';
import { DEFAULT_LEASE_SECONDS, DEFAULT_RETENTION_SECONDS } from '../domain/reservation';
import type { Rejected } from '../domain/verification';
import type {
  Clock,
  IdempotencyStore,
  ReceptionObserver,
  Timer,
  TokenGenerator,
  Verifier,
} from './ports';

/** Lo que recibe la función que procesa el evento: sólo existe si el pedido se verificó. */
export interface VerifiedEvent {
  readonly eventKey: string;
  readonly timestamp: number | null;
  readonly request: IncomingRequest;
}

export type EventHandler = (event: VerifiedEvent) => void | Promise<void>;

export type Reception =
  | { readonly outcome: 'ok' | 'duplicate' | 'in_progress'; readonly eventKey: string }
  | { readonly outcome: 'failed'; readonly eventKey: string; readonly error: unknown }
  | { readonly outcome: 'too_large' }
  | Rejected;

export interface ReceiveWebhookDependencies {
  readonly verifier: Verifier;
  readonly store: IdempotencyStore;
  readonly clock: Clock;
  readonly tokens: TokenGenerator;
  readonly leaseSeconds?: number;
  readonly retentionSeconds?: number;
  /** El tamaño máximo del cuerpo, en bytes. Uno más grande termina en `too_large` sin verificarse. */
  readonly maxBodyBytes?: number;
  /** Reemplaza la clave del evento por una propia, calculada del pedido ya verificado. */
  readonly eventKey?: (event: VerifiedEvent) => string;
  /** Recibe el resultado y la duración de cada recepción (sección 6.4). Necesita `timer`. */
  readonly observer?: ReceptionObserver;
  readonly timer?: Timer;
}

/**
 * Recibir un webhook (sección 6.2): acotar el tamaño, verificar, reservar, procesar y completar. Si el
 * procesamiento falla, la reserva se libera para que el reintento del emisor funcione.
 */
export class ReceiveWebhook {
  private readonly leaseSeconds: number;
  private readonly retentionSeconds: number;
  private readonly maxBodyBytes: number;

  constructor(private readonly deps: ReceiveWebhookDependencies) {
    this.leaseSeconds = positiveInteger('leaseSeconds', deps.leaseSeconds ?? DEFAULT_LEASE_SECONDS);
    this.retentionSeconds = positiveInteger(
      'retentionSeconds',
      deps.retentionSeconds ?? DEFAULT_RETENTION_SECONDS,
    );
    this.maxBodyBytes = positiveInteger(
      'maxBodyBytes',
      deps.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES,
    );
    if (deps.observer !== undefined && deps.timer === undefined) {
      throw new ConfigurationError('observer necesita timer para medir la duración');
    }
  }

  async execute(request: IncomingRequest, handler: EventHandler): Promise<Reception> {
    const { observer, timer } = this.deps;
    if (observer === undefined || timer === undefined) return this.receive(request, handler);

    const startedMs = timer.nowMs();
    const reception = await this.receive(request, handler);
    try {
      observer.onReception({
        outcome: reception.outcome,
        eventKey: 'eventKey' in reception ? reception.eventKey : null,
        durationMs: timer.nowMs() - startedMs,
      });
    } catch {
      // Una falla al medir no cambia el resultado de la recepción.
    }
    return reception;
  }

  private async receive(request: IncomingRequest, handler: EventHandler): Promise<Reception> {
    const { verifier, store, clock, tokens } = this.deps;

    // Antes que la firma: un pedido sin autenticar no elige cuánto trabajo cuesta rechazarlo.
    if (request.body.byteLength > this.maxBodyBytes) return { outcome: 'too_large' };

    const verification = await verifier.verify(request);
    if (verification.outcome !== 'ok') return verification;

    const event = this.eventOf(request, verification.eventKey, verification.timestamp);
    const key = event.eventKey;
    const token = tokens.next();

    const claim = await store.claim({
      key,
      token,
      now: clock.now(),
      leaseSeconds: this.leaseSeconds,
    });
    if (claim !== 'claimed') return { outcome: claim, eventKey: key };

    try {
      await handler(event);
    } catch (error) {
      await store.release({ key, token });
      return { outcome: 'failed', eventKey: key, error };
    }

    await store.complete({ key, token, now: clock.now(), retentionSeconds: this.retentionSeconds });
    return { outcome: 'ok', eventKey: key };
  }

  private eventOf(
    request: IncomingRequest,
    eventKey: string,
    timestamp: number | null,
  ): VerifiedEvent {
    const event = { eventKey, timestamp, request };
    return this.deps.eventKey ? { ...event, eventKey: this.deps.eventKey(event) } : event;
  }
}
