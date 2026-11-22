import type { AttemptRecord, DeliveryLedger } from '../../application/ports';

/** Registro de entregas en memoria. Sirve para tests y para un único proceso. */
export class MemoryDeliveryLedger implements DeliveryLedger {
  private readonly records: AttemptRecord[] = [];

  async record(attempt: AttemptRecord): Promise<void> {
    this.records.push(attempt);
  }

  /** Todos los intentos, en el orden en que se registraron. */
  attempts(): readonly AttemptRecord[] {
    return [...this.records];
  }

  /** Los intentos de un mensaje hacia un destino. */
  attemptsOf(messageId: string, endpointId: string): readonly AttemptRecord[] {
    return this.records.filter((r) => r.messageId === messageId && r.endpointId === endpointId);
  }
}
