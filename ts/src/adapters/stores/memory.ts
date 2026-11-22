import type {
  ClaimRequest,
  CompleteRequest,
  IdempotencyStore,
  ReleaseRequest,
} from '../../application/ports';
import type { ClaimOutcome } from '../../domain/reservation';

interface Entry {
  readonly state: 'reserved' | 'completed';
  readonly token: string;
  readonly until: number;
}

/**
 * Almacén de reservas en memoria. Sirve para tests y para un único proceso: no
 * comparte nada entre procesos ni sobrevive a un reinicio.
 */
export class MemoryIdempotencyStore implements IdempotencyStore {
  private readonly entries = new Map<string, Entry>();

  async claim({ key, token, now, leaseSeconds }: ClaimRequest): Promise<ClaimOutcome> {
    const entry = this.entries.get(key);
    if (entry !== undefined && now < entry.until) {
      return entry.state === 'reserved' ? 'in_progress' : 'duplicate';
    }
    this.entries.set(key, { state: 'reserved', token, until: now + leaseSeconds });
    return 'claimed';
  }

  async complete({ key, token, now, retentionSeconds }: CompleteRequest): Promise<boolean> {
    if (!this.reservedBy(key, token)) return false;
    this.entries.set(key, { state: 'completed', token, until: now + retentionSeconds });
    return true;
  }

  async release({ key, token }: ReleaseRequest): Promise<boolean> {
    if (!this.reservedBy(key, token)) return false;
    this.entries.delete(key);
    return true;
  }

  private reservedBy(key: string, token: string): boolean {
    const entry = this.entries.get(key);
    return entry !== undefined && entry.state === 'reserved' && entry.token === token;
  }
}
