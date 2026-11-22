import { type AttemptOutcome, classifyDelivery, stateAfter } from '../domain/delivery';
import { type DestinationProblem, inspectDestination, selectAddress } from '../domain/destination';
import { ConfigurationError, positiveInteger } from '../domain/errors';
import { checkRetryPolicy, nextAttempt, type RetryPolicy } from '../domain/retry';
import type {
  AttemptRecord,
  Clock,
  DeliveryLedger,
  DnsResolver,
  HttpTransport,
  MessageSigner,
  RandomSource,
  Timer,
} from './ports';

export const DEFAULT_TIMEOUT_SECONDS = 20;
export const DEFAULT_CONTENT_TYPE = 'application/json';

export interface Endpoint {
  /** Cómo llama al destino quien integra. Es lo que queda en el registro, en lugar de la URL. */
  readonly id: string;
  readonly url: string;
}

export interface Delivery {
  readonly endpoint: Endpoint;
  /** El mismo `id` en todos los intentos de un mensaje. */
  readonly message: { readonly id: string; readonly payload: Uint8Array };
  /** El número de este intento. El primero es el 1. */
  readonly attempt: number;
}

export interface SendWebhookDependencies {
  readonly signer: MessageSigner;
  readonly transport: HttpTransport;
  readonly resolver: DnsResolver;
  readonly ledger: DeliveryLedger;
  readonly clock: Clock;
  readonly timer: Timer;
  readonly random: RandomSource;
  readonly retryPolicy?: RetryPolicy;
  /** Permite destinos `http`. Por defecto sólo se entrega a `https`. */
  readonly allowHttp?: boolean;
  readonly timeoutSeconds?: number;
  readonly contentType?: string;
  /** Cabeceras extra. No pueden pisar las de la firma ni el tipo de contenido. */
  readonly headers?: Readonly<Record<string, string>>;
}

/** El resultado de un intento. Es lo mismo que se guarda en el registro. */
export type DeliveryResult = AttemptRecord;

interface Attempted {
  readonly outcome: AttemptOutcome;
  readonly retryAfter: string | null;
  readonly problem: DestinationProblem | null;
}

/**
 * Hacer un intento de entrega (sección 8): firmar, validar el destino, enviar, clasificar
 * y decir cuándo corresponde el próximo intento. No programa el reintento: eso lo hace
 * quien integra, llamando de nuevo con `attempt + 1` cuando llegue `nextAt`.
 */
export class SendWebhook {
  private readonly timeoutSeconds: number;

  constructor(private readonly deps: SendWebhookDependencies) {
    this.timeoutSeconds = positiveInteger(
      'timeoutSeconds',
      deps.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS,
    );
    checkRetryPolicy(deps.retryPolicy ?? {});
  }

  async execute(delivery: Delivery): Promise<DeliveryResult> {
    const { clock, timer, random, ledger } = this.deps;
    const attempt = positiveInteger('attempt', delivery.attempt);

    const at = clock.now();
    const startedMs = timer.nowMs();
    const { outcome, retryAfter, problem } = await this.attempt(delivery, at);
    const durationMs = timer.nowMs() - startedMs;

    const deliveryClass = classifyDelivery(outcome);
    const next =
      deliveryClass === 'retryable'
        ? nextAttempt({
            attempt,
            now: clock.now(),
            random: random.next(),
            retryAfter,
            ...(this.deps.retryPolicy === undefined ? {} : { policy: this.deps.retryPolicy }),
          })
        : null;
    const nextAt = next !== null && !next.exhausted ? next.nextAt : null;

    const record: AttemptRecord = {
      messageId: delivery.message.id,
      endpointId: delivery.endpoint.id,
      attempt,
      at,
      deliveryClass,
      state: stateAfter(deliveryClass, nextAt !== null),
      status: 'status' in outcome ? outcome.status : null,
      problem,
      durationMs,
      nextAt,
    };
    await ledger.record(record);
    return record;
  }

  private async attempt({ endpoint, message }: Delivery, at: number): Promise<Attempted> {
    const { signer, transport, resolver } = this.deps;

    const signing = await signer.sign({ id: message.id, timestamp: at, payload: message.payload });
    if (signing.outcome !== 'signed') {
      throw new ConfigurationError(`no se puede firmar el mensaje: ${signing.outcome}`);
    }

    const blocked = (problem: DestinationProblem): Attempted => ({
      outcome: { failure: 'blocked' },
      retryAfter: null,
      problem,
    });
    const networkFailure: Attempted = {
      outcome: { failure: 'network' },
      retryAfter: null,
      problem: null,
    };

    const inspected = inspectDestination(endpoint.url, { allowHttp: this.deps.allowHttp === true });
    if (typeof inspected === 'string') return blocked(inspected);

    let addresses: readonly string[];
    if (inspected.literalAddress !== null) {
      addresses = [inspected.literalAddress];
    } else {
      try {
        addresses = await resolver.resolve(inspected.host);
      } catch {
        return networkFailure;
      }
    }
    const selected = selectAddress(addresses);
    if (typeof selected === 'string') return blocked(selected);

    try {
      const response = await transport.post({
        url: endpoint.url,
        address: selected.address,
        headers: {
          ...this.deps.headers,
          'content-type': this.deps.contentType ?? DEFAULT_CONTENT_TYPE,
          ...signing.headers,
        },
        body: message.payload,
        timeoutSeconds: this.timeoutSeconds,
      });
      return 'status' in response
        ? { outcome: { status: response.status }, retryAfter: response.retryAfter, problem: null }
        : { outcome: { failure: response.failure }, retryAfter: null, problem: null };
    } catch {
      return networkFailure;
    }
  }
}
