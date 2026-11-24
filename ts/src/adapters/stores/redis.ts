import type {
  ClaimRequest,
  CompleteRequest,
  IdempotencyStore,
  ReleaseRequest,
} from '../../application/ports';
import { ConfigurationError } from '../../domain/errors';
import type { ClaimOutcome } from '../../domain/reservation';

/** Lo mínimo que hace falta de un cliente de Redis: correr un script con claves y argumentos. */
export interface RedisClient {
  eval(script: string, keys: readonly string[], args: readonly string[]): Promise<unknown>;
}

/** Adapta un cliente de `redis` (node-redis), que recibe las claves y los argumentos en un objeto. */
export function nodeRedisClient(client: {
  eval(script: string, options: { keys: string[]; arguments: string[] }): Promise<unknown>;
}): RedisClient {
  return {
    eval: (script, keys, args) => client.eval(script, { keys: [...keys], arguments: [...args] }),
  };
}

/** Adapta un cliente de `ioredis`, que recibe la cantidad de claves y después todo junto. */
export function ioredisClient(client: {
  eval(script: string, numKeys: number, ...rest: string[]): Promise<unknown>;
}): RedisClient {
  return { eval: (script, keys, args) => client.eval(script, keys.length, ...keys, ...args) };
}

export interface RedisStoreOptions {
  /** Lo que va antes de cada clave. Por defecto, `omniwebhook:events:`. */
  readonly prefix?: string;
  /**
   * Cuánto se conserva una reserva después de vencer su plazo, en segundos, antes de que
   * Redis la borre. Por defecto, un día.
   */
  readonly graceSeconds?: number;
}

export const DEFAULT_REDIS_PREFIX = 'omniwebhook:events:';
export const DEFAULT_REDIS_GRACE_SECONDS = 86_400;

// Cada entrada es un hash con `state`, `token` y `expires_at`. Los dos paquetes usan estos
// mismos scripts, así que comparten las reservas.
//
// El vencimiento se decide comparando con el `now` que llega, igual que en los otros
// almacenes. El TTL de Redis sólo limpia: nunca vence antes que la entrada.
const CLAIM = `
local entry = redis.call('HMGET', KEYS[1], 'state', 'expires_at')
if entry[1] and tonumber(entry[2]) > tonumber(ARGV[2]) then
  if entry[1] == 'completed' then return 'duplicate' end
  return 'in_progress'
end
redis.call('HSET', KEYS[1], 'state', 'reserved', 'token', ARGV[1], 'expires_at', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 'claimed'`;

const COMPLETE = `
local entry = redis.call('HMGET', KEYS[1], 'state', 'token')
if entry[1] ~= 'reserved' or entry[2] ~= ARGV[1] then return 0 end
redis.call('HSET', KEYS[1], 'state', 'completed', 'expires_at', ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1`;

const RELEASE = `
local entry = redis.call('HMGET', KEYS[1], 'state', 'token')
if entry[1] ~= 'reserved' or entry[2] ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
return 1`;

/** Los scripts, para el paquete de Python y para quien quiera cargarlos con `SCRIPT LOAD`. */
export const REDIS_STORE_SCRIPTS = { claim: CLAIM, complete: COMPLETE, release: RELEASE } as const;

/**
 * Almacén de reservas sobre Redis. Cada operación es un script, así que es atómica y sirve
 * con varios procesos a la vez. Las entradas se borran solas: no hace falta purgar.
 *
 * Una diferencia con los otros almacenes: una reserva cuyo plazo venció se puede completar
 * mientras nadie la haya tomado, pero sólo durante `graceSeconds`. Después Redis la borra.
 */
export class RedisIdempotencyStore implements IdempotencyStore {
  private readonly prefix: string;
  private readonly graceSeconds: number;

  constructor(
    private readonly client: RedisClient,
    options: RedisStoreOptions = {},
  ) {
    this.prefix = options.prefix ?? DEFAULT_REDIS_PREFIX;
    this.graceSeconds = options.graceSeconds ?? DEFAULT_REDIS_GRACE_SECONDS;
    if (typeof this.prefix !== 'string' || this.prefix === '') {
      throw new ConfigurationError('prefix no puede estar vacío');
    }
    if (!Number.isInteger(this.graceSeconds) || this.graceSeconds < 0) {
      throw new ConfigurationError('graceSeconds tiene que ser un entero mayor o igual que cero');
    }
  }

  async claim({ key, token, now, leaseSeconds }: ClaimRequest): Promise<ClaimOutcome> {
    const outcome = await this.client.eval(
      CLAIM,
      [this.prefix + key],
      [token, String(now), String(now + leaseSeconds), String(leaseSeconds + this.graceSeconds)],
    );
    if (outcome === 'claimed' || outcome === 'duplicate' || outcome === 'in_progress') {
      return outcome;
    }
    throw new Error('el almacén de Redis devolvió una respuesta inesperada');
  }

  async complete({ key, token, now, retentionSeconds }: CompleteRequest): Promise<boolean> {
    const applied = await this.client.eval(
      COMPLETE,
      [this.prefix + key],
      [token, String(now + retentionSeconds), String(retentionSeconds)],
    );
    return Number(applied) === 1;
  }

  async release({ key, token }: ReleaseRequest): Promise<boolean> {
    return Number(await this.client.eval(RELEASE, [this.prefix + key], [token])) === 1;
  }
}
