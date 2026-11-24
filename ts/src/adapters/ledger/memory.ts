import type { AttemptRecord, DeliveryLedger, EndpointFailureSource } from '../../application/ports';
import { type FailureSummary, summarizeFailures } from '../../domain/endpoint-health';

/** Registro de entregas en memoria. Sirve para tests y para un único proceso. */
export class MemoryDeliveryLedger implements DeliveryLedger, EndpointFailureSource {
  private readonly records: AttemptRecord[] = [];

  async record(attempt: AttemptRecord): Promise<void> {
    this.records.push(attempt);
  }

  /** Todos los intentos, en el orden en que se registraron. */
  attempts(): readonly AttemptRecord[] {
    return [...this.records];
  }

  /** El resumen de fallos de un destino desde `since` (sección 8.5). */
  async failuresOf(endpointId: string, since: number): Promise<FailureSummary> {
    return summarizeFailures(
      this.records.filter((r) => r.endpointId === endpointId),
      since,
    );
  }

  /** Los intentos de un mensaje hacia un destino. */
  attemptsOf(messageId: string, endpointId: string): readonly AttemptRecord[] {
    return this.records.filter((r) => r.messageId === messageId && r.endpointId === endpointId);
  }
}
