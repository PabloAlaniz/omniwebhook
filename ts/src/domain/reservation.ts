/** Qué devolvió el almacén al pedir la reserva de un evento (sección 6.1). */
export type ClaimOutcome = 'claimed' | 'in_progress' | 'duplicate';

export const DEFAULT_LEASE_SECONDS = 300;
export const DEFAULT_RETENTION_SECONDS = 604_800;
