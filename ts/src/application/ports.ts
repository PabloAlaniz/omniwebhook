import type { DeliveryClass, DeliveryState } from '../domain/delivery';
import type { DestinationProblem } from '../domain/destination';
import type { IncomingRequest } from '../domain/incoming-request';
import type { OutgoingMessage, Signing } from '../domain/message';
import type { ReceptionOutcome } from '../domain/reception';
import type { ClaimOutcome } from '../domain/reservation';
import type { Verification } from '../domain/verification';

/** Comprueba el origen de un pedido entrante. Cada esquema de firma es un adaptador de este puerto. */
export interface Verifier {
  verify(request: IncomingRequest): Promise<Verification>;
}

/** Firma un mensaje a emitir. El formato estándar es un adaptador de este puerto. */
export interface MessageSigner {
  sign(message: OutgoingMessage): Promise<Signing>;
}

/** El tiempo actual, en segundos desde la época Unix. */
export interface Clock {
  now(): number;
}

/** Genera el identificador con el que un proceso marca sus reservas. */
export interface TokenGenerator {
  next(): string;
}

export interface ClaimRequest {
  readonly key: string;
  readonly token: string;
  readonly now: number;
  readonly leaseSeconds: number;
}

export interface CompleteRequest {
  readonly key: string;
  readonly token: string;
  readonly now: number;
  readonly retentionSeconds: number;
}

export interface ReleaseRequest {
  readonly key: string;
  readonly token: string;
}

/** Lo que responde un validador de payload: el valor aceptado, o por qué lo rechaza. */
export type PayloadResult<T> =
  | { readonly value: T; readonly issues?: undefined }
  | { readonly issues: ReadonlyArray<unknown> };

/**
 * Valida el payload de un evento ya verificado (sección 6.2). Tiene la forma de la interfaz
 * común de las librerías de esquemas, así que un esquema de cualquiera de ellas sirve tal cual.
 */
export interface PayloadSchema<T> {
  readonly '~standard': {
    readonly validate: (value: unknown) => PayloadResult<T> | Promise<PayloadResult<T>>;
  };
}

/** Lo que se le informa al observador de cada recepción. Nunca incluye el cuerpo ni un secreto. */
export interface ReceptionObservation {
  readonly outcome: ReceptionOutcome;
  /** La clave del evento; `null` si el pedido no llegó a verificarse. */
  readonly eventKey: string | null;
  /** Cuánto llevó la recepción completa, incluido el procesamiento. */
  readonly durationMs: number;
}

/** Observa las recepciones (sección 6.4). No cambia el resultado: si lanza, el error se descarta. */
export interface ReceptionObserver {
  onReception(observation: ReceptionObservation): void;
}

/** El almacén de reservas (sección 6.1). Las tres operaciones tienen que ser atómicas. */
export interface IdempotencyStore {
  claim(request: ClaimRequest): Promise<ClaimOutcome>;
  /** Devuelve si se aplicó: sólo si la clave sigue reservada con el mismo token. */
  complete(request: CompleteRequest): Promise<boolean>;
  /** Devuelve si se aplicó: sólo si la clave sigue reservada con el mismo token. */
  release(request: ReleaseRequest): Promise<boolean>;
}

/** El tiempo transcurrido, en milisegundos, para medir cuánto tardó un intento. */
export interface Timer {
  nowMs(): number;
}

/** Números en [0, 1) para la variación de los reintentos. */
export interface RandomSource {
  next(): number;
}

/** Resuelve un nombre a direcciones IP. */
export interface DnsResolver {
  /**
   * Devuelve las direcciones del nombre; una lista vacía si el nombre no existe. Si la
   * resolución falla por otro motivo, lanza: el intento cuenta como un error de red.
   */
  resolve(host: string): Promise<readonly string[]>;
}

export interface TransportRequest {
  readonly url: string;
  /** La dirección ya validada a la que hay que conectarse. */
  readonly address: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly body: Uint8Array;
  readonly timeoutSeconds: number;
}

export type TransportResponse =
  | { readonly status: number; readonly retryAfter: string | null }
  | { readonly failure: 'network' | 'timeout' };

/** Hace el POST de un intento. No sigue redirecciones. */
export interface HttpTransport {
  post(request: TransportRequest): Promise<TransportResponse>;
}

/** Lo que queda registrado de cada intento (sección 8.4). Nunca incluye la URL de destino. */
export interface AttemptRecord {
  readonly messageId: string;
  readonly endpointId: string;
  /** El número de intento. El primero es el 1. */
  readonly attempt: number;
  /** Cuándo empezó el intento, en segundos. */
  readonly at: number;
  readonly deliveryClass: DeliveryClass;
  readonly state: DeliveryState;
  /** El estado HTTP, si hubo respuesta. */
  readonly status: number | null;
  /** Por qué la política de URLs rechazó el intento, si lo rechazó. */
  readonly problem: DestinationProblem | null;
  readonly durationMs: number;
  /** Cuándo corresponde el próximo intento; `null` si no hay más. */
  readonly nextAt: number | null;
}

/** El registro de entregas. */
export interface DeliveryLedger {
  record(attempt: AttemptRecord): Promise<void>;
}

/** El estado de una entrada de la bandeja de salida (sección 8.5). */
export type OutboxState = DeliveryState | 'cancelled';

export interface EnqueueRequest {
  readonly messageId: string;
  readonly endpointId: string;
  /** El cuerpo, byte a byte como se va a enviar. */
  readonly payload: Uint8Array;
  readonly now: number;
}

export interface OutboxClaimRequest {
  readonly token: string;
  readonly now: number;
  /** Cuántas entradas tomar, como mucho. */
  readonly limit: number;
  readonly leaseSeconds: number;
}

/** Una entrega tomada de la bandeja: lo que hace falta para hacer el intento. */
export interface OutboxEntry {
  readonly messageId: string;
  readonly endpointId: string;
  readonly payload: Uint8Array;
  /** El número del intento que toca. El primero es el 1. */
  readonly attempt: number;
}

export type SettleRequest = {
  readonly messageId: string;
  readonly endpointId: string;
  readonly token: string;
} & (
  | { readonly state: 'pending'; readonly nextAt: number }
  | { readonly state: Exclude<OutboxState, 'pending'> }
);

/** La bandeja de salida (sección 8.5). Las tres operaciones tienen que ser atómicas. */
export interface Outbox {
  /** Devuelve si se encoló: `false` si ese mensaje ya estaba para ese destino. */
  enqueue(request: EnqueueRequest): Promise<boolean>;
  /** Toma lo pendiente que ya venció, en orden, y lo deja tomado por `token`. */
  claim(request: OutboxClaimRequest): Promise<readonly OutboxEntry[]>;
  /** Devuelve si se aplicó: sólo si la entrada sigue pendiente y la tomó ese mismo token. */
  settle(request: SettleRequest): Promise<boolean>;
}

/** Lo que hace falta saber de un destino para entregarle. */
export interface ResolvedEndpoint {
  readonly url: string;
}

/** Dónde quien integra guarda sus destinos. La bandeja sólo conoce el identificador. */
export interface EndpointDirectory {
  /** El destino, o `null` si no existe o está deshabilitado: su entrega se cancela. */
  resolve(endpointId: string): Promise<ResolvedEndpoint | null>;
}
