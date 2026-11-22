import type { IncomingRequest } from '../domain/incoming-request';
import type { ClaimOutcome } from '../domain/reservation';
import type { Verification } from '../domain/verification';

/** Comprueba el origen de un pedido entrante. Cada esquema de firma es un adaptador de este puerto. */
export interface Verifier {
  verify(request: IncomingRequest): Promise<Verification>;
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

/** El almacén de reservas (sección 6.1). Las tres operaciones tienen que ser atómicas. */
export interface IdempotencyStore {
  claim(request: ClaimRequest): Promise<ClaimOutcome>;
  /** Devuelve si se aplicó: sólo si la clave sigue reservada con el mismo token. */
  complete(request: CompleteRequest): Promise<boolean>;
  /** Devuelve si se aplicó: sólo si la clave sigue reservada con el mismo token. */
  release(request: ReleaseRequest): Promise<boolean>;
}
