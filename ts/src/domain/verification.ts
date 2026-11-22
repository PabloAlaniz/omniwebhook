/** Por qué se rechazó un pedido (sección 4). El orden es el de las comprobaciones. */
export type Rejection =
  | 'unconfigured'
  | 'missing'
  | 'ambiguous'
  | 'malformed'
  | 'invalid'
  | 'stale';

export interface Verified {
  readonly outcome: 'ok';
  /** La clave que identifica al evento para no procesarlo dos veces. */
  readonly eventKey: string;
  /** La marca de tiempo firmada, en segundos; `null` si el esquema no lleva una. */
  readonly timestamp: number | null;
}

export interface Rejected {
  readonly outcome: Rejection;
}

export type Verification = Verified | Rejected;

export function rejected(outcome: Rejection): Rejected {
  return { outcome };
}
