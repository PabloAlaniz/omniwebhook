import {
  checkHealthPolicy,
  type EndpointHealth,
  endpointHealth,
  type FailureSummary,
  type HealthPolicy,
} from '../domain/endpoint-health';
import { positiveInteger } from '../domain/errors';
import type {
  AttemptRecord,
  Clock,
  EndpointDirectory,
  EndpointFailureSource,
  Outbox,
  OutboxEntry,
  OutboxState,
  TokenGenerator,
} from './ports';

export const DEFAULT_DISPATCH_LIMIT = 10;
export const DEFAULT_DISPATCH_LEASE_SECONDS = 300;

/** Quien hace el intento: `SendWebhook`, o algo que elija cuál usar según el destino. */
export interface AttemptSender {
  execute(delivery: {
    readonly endpoint: { readonly id: string; readonly url: string };
    readonly message: { readonly id: string; readonly payload: Uint8Array };
    readonly attempt: number;
  }): Promise<AttemptRecord>;
}

export interface DispatchDueDependencies {
  readonly outbox: Outbox;
  readonly endpoints: EndpointDirectory;
  readonly sender: AttemptSender;
  readonly clock: Clock;
  readonly tokens: TokenGenerator;
  /** Cuántas entregas toma cada tanda, como mucho. Por defecto, 10. */
  readonly limit?: number;
  /**
   * Cuánto dura la toma, en segundos. Tiene que ser más de lo que puede tardar una tanda
   * entera: el límite por el tiempo de espera de un intento. Por defecto, 300.
   */
  readonly leaseSeconds?: number;
  /**
   * Con esto, después de cada intento que no se entregó se calcula la salud del destino, y los
   * que haya que deshabilitar salen en el resultado de la tanda. `failures` es el registro de
   * entregas que usa `sender`.
   */
  readonly health?: {
    readonly failures: EndpointFailureSource;
    readonly policy?: HealthPolicy;
  };
}

/** Un destino que conviene deshabilitar. El paquete no lo hace: avisa. */
export interface DisabledEndpoint {
  readonly endpointId: string;
  readonly health: Extract<EndpointHealth, { status: 'disabled' }>;
  readonly summary: FailureSummary;
}

/** Cómo terminó una entrega de la tanda. */
export interface Dispatched {
  readonly messageId: string;
  readonly endpointId: string;
  readonly attempt: number;
  /** El estado en que quedó la entrada. */
  readonly state: OutboxState;
  /** `false` si otro proceso tomó la entrada mientras tanto: su resultado es el que vale. */
  readonly settled: boolean;
}

/** Una entrega que no llegó a intentarse. Sigue tomada hasta que venza el plazo. */
export interface DispatchFailure {
  readonly messageId: string;
  readonly endpointId: string;
  readonly error: unknown;
}

export interface DispatchResult {
  readonly dispatched: readonly Dispatched[];
  readonly failures: readonly DispatchFailure[];
  /** Los destinos que quedaron para deshabilitar, una vez cada uno. Vacío sin `health`. */
  readonly disabled: readonly DisabledEndpoint[];
}

/**
 * Despachar una tanda (sección 8.5): tomar lo pendiente que ya venció, hacer un intento por
 * cada entrega y cerrarla con el resultado. No tiene bucle ni planificador: se llama desde un
 * cron, una cola o un bucle propio, tan seguido como haga falta.
 */
export class DispatchDue {
  private readonly limit: number;
  private readonly leaseSeconds: number;

  constructor(private readonly deps: DispatchDueDependencies) {
    this.limit = positiveInteger('limit', deps.limit ?? DEFAULT_DISPATCH_LIMIT);
    this.leaseSeconds = positiveInteger(
      'leaseSeconds',
      deps.leaseSeconds ?? DEFAULT_DISPATCH_LEASE_SECONDS,
    );
    checkHealthPolicy(deps.health?.policy ?? {});
  }

  async execute(): Promise<DispatchResult> {
    const { outbox, clock, tokens } = this.deps;
    const token = tokens.next();
    const entries = await outbox.claim({
      token,
      now: clock.now(),
      limit: this.limit,
      leaseSeconds: this.leaseSeconds,
    });

    const dispatched: Dispatched[] = [];
    const failures: DispatchFailure[] = [];
    const disabled = new Map<string, DisabledEndpoint>();
    for (const entry of entries) {
      const { messageId, endpointId } = entry;
      try {
        dispatched.push(await this.dispatch(entry, token, disabled));
      } catch (error) {
        // No se cierra: la entrada vuelve a salir cuando venza la toma.
        failures.push({ messageId, endpointId, error });
      }
    }
    return { dispatched, failures, disabled: [...disabled.values()] };
  }

  /** Anota el destino si, después de este intento, quedó para deshabilitar. */
  private async assess(
    endpointId: string,
    since: number,
    disabled: Map<string, DisabledEndpoint>,
  ): Promise<void> {
    const { health, clock } = this.deps;
    if (health === undefined || disabled.has(endpointId)) return;
    const summary = await health.failures.failuresOf(endpointId, since);
    const verdict = endpointHealth(summary, clock.now(), health.policy);
    if (verdict.status === 'disabled')
      disabled.set(endpointId, { endpointId, health: verdict, summary });
  }

  private async dispatch(
    entry: OutboxEntry,
    token: string,
    disabled: Map<string, DisabledEndpoint>,
  ): Promise<Dispatched> {
    const { outbox, endpoints, sender } = this.deps;
    const { messageId, endpointId, attempt } = entry;
    const pair = { messageId, endpointId, token };

    const endpoint = await endpoints.resolve(endpointId);
    if (endpoint === null) {
      const settled = await outbox.settle({ ...pair, state: 'cancelled' });
      return { messageId, endpointId, attempt, state: 'cancelled', settled };
    }

    const record = await sender.execute({
      endpoint: { id: endpointId, url: endpoint.url },
      message: { id: messageId, payload: entry.payload },
      attempt,
    });
    if (record.state === 'pending' && record.nextAt === null) {
      throw new Error('el intento quedó pendiente pero sin próximo intento');
    }
    const settled = await outbox.settle(
      record.state === 'pending' && record.nextAt !== null
        ? { ...pair, state: 'pending', nextAt: record.nextAt }
        : { ...pair, state: record.state as Exclude<OutboxState, 'pending'> },
    );
    // Después de cerrar: si esto falla, la entrega ya quedó como corresponde.
    if (record.deliveryClass !== 'delivered') {
      await this.assess(endpointId, endpoint.enabledAt ?? 0, disabled);
    }
    return { messageId, endpointId, attempt, state: record.state, settled };
  }
}
