import type {
  EnqueueRequest,
  Outbox,
  OutboxClaimRequest,
  OutboxEntry,
  OutboxState,
  RequeueRequest,
  SettleRequest,
} from '../../application/ports';

interface Row {
  readonly messageId: string;
  readonly endpointId: string;
  readonly payload: Uint8Array;
  readonly seq: number;
  attempt: number;
  availableAt: number;
  state: OutboxState;
  token: string | null;
  leaseExpiresAt: number | null;
}

/** Bandeja de salida en memoria, para tests y desarrollo. No sirve con más de un proceso. */
export class MemoryOutbox implements Outbox {
  private readonly rows: Row[] = [];

  async enqueue({ messageId, endpointId, payload, now }: EnqueueRequest): Promise<boolean> {
    if (this.find(messageId, endpointId) !== undefined) return false;
    this.rows.push({
      messageId,
      endpointId,
      payload: Uint8Array.from(payload),
      seq: this.rows.length,
      attempt: 1,
      availableAt: now,
      state: 'pending',
      token: null,
      leaseExpiresAt: null,
    });
    return true;
  }

  async claim({ token, now, limit, leaseSeconds }: OutboxClaimRequest): Promise<OutboxEntry[]> {
    const taken = this.rows
      .filter(
        (row) =>
          row.state === 'pending' &&
          row.availableAt <= now &&
          (row.leaseExpiresAt === null || row.leaseExpiresAt <= now),
      )
      .sort((a, b) => a.availableAt - b.availableAt || a.seq - b.seq)
      .slice(0, limit);
    for (const row of taken) {
      row.token = token;
      row.leaseExpiresAt = now + leaseSeconds;
    }
    return taken.map(({ messageId, endpointId, payload, attempt }) => ({
      messageId,
      endpointId,
      payload: Uint8Array.from(payload),
      attempt,
    }));
  }

  async settle(request: SettleRequest): Promise<boolean> {
    const row = this.find(request.messageId, request.endpointId);
    if (row === undefined || row.state !== 'pending' || row.token !== request.token) return false;
    if (request.state === 'pending') {
      row.attempt += 1;
      row.availableAt = request.nextAt;
    } else {
      row.state = request.state;
    }
    row.token = null;
    row.leaseExpiresAt = null;
    return true;
  }

  async requeue({ endpointId, from, to, now }: RequeueRequest): Promise<number> {
    const again = this.rows.filter(
      (row) =>
        row.endpointId === endpointId &&
        row.state !== 'pending' &&
        row.state !== 'delivered' &&
        row.availableAt >= from &&
        row.availableAt <= to,
    );
    for (const row of again) {
      row.state = 'pending';
      row.attempt = 1;
      row.availableAt = now;
      row.token = null;
      row.leaseExpiresAt = null;
    }
    return again.length;
  }

  /** El estado de una entrada, para comprobarlo en tests. */
  stateOf(messageId: string, endpointId: string): OutboxState | undefined {
    return this.find(messageId, endpointId)?.state;
  }

  private find(messageId: string, endpointId: string): Row | undefined {
    return this.rows.find((row) => row.messageId === messageId && row.endpointId === endpointId);
  }
}
