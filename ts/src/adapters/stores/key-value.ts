import type {
  ClaimRequest,
  CompleteRequest,
  IdempotencyStore,
  ReleaseRequest,
} from '../../application/ports';
import { ConfigurationError } from '../../domain/errors';
import type { ClaimOutcome } from '../../domain/reservation';

/** Lo que hay guardado en una clave, con la versión que identifica esa escritura. */
export interface KeyValueRecord {
  readonly value: string;
  /** Cambia en cada escritura. Un cliente sin escritura condicional puede dejarla vacía. */
  readonly version: string;
}

/**
 * Lo mínimo que hace falta de un almacén clave-valor: leer, escribir con vencimiento y borrar.
 * Es el puerto que hay que implementar para usar uno que el paquete no trae.
 *
 * `onlyIf` es la versión que tiene que seguir guardada para que la operación se aplique;
 * `null` significa que la clave no tiene que existir. Un cliente `conditional` DEBE comprobarla
 * y escribir en un solo paso atómico, y devolver `false` si no coincide. Uno que no lo es la
 * ignora y devuelve siempre `true`.
 */
export interface KeyValueClient {
  /** Si `put` y `delete` respetan `onlyIf` de forma atómica. */
  readonly conditional: boolean;
  /** Tiene que ser una lectura consistente: ver lo último que se escribió. */
  get(key: string): Promise<KeyValueRecord | null>;
  put(
    key: string,
    value: string,
    options: { readonly ttlSeconds: number; readonly onlyIf: string | null },
  ): Promise<boolean>;
  delete(key: string, options: { readonly onlyIf: string }): Promise<boolean>;
}

export interface KeyValueStoreOptions {
  /** Lo que va antes de cada clave. Por defecto, `omniwebhook:events:`. */
  readonly prefix?: string;
  /**
   * Cuánto se conserva una reserva después de vencer su plazo, en segundos, antes de que el
   * almacén la borre. Por defecto, un día.
   */
  readonly graceSeconds?: number;
}

export const DEFAULT_KEY_VALUE_PREFIX = 'omniwebhook:events:';
export const DEFAULT_KEY_VALUE_GRACE_SECONDS = 86_400;
// Cuántas veces se vuelve a leer después de perder una escritura condicional.
const CLAIM_ATTEMPTS = 3;

interface Entry {
  readonly state: 'reserved' | 'completed';
  readonly token: string;
  readonly expiresAt: number;
}

/** El valor guardado: el mismo JSON en los dos paquetes, así comparten las reservas. */
function encode(entry: Entry): string {
  return JSON.stringify({ state: entry.state, token: entry.token, expires_at: entry.expiresAt });
}

function decode(value: string): Entry {
  let data: unknown;
  try {
    data = JSON.parse(value);
  } catch {
    data = null;
  }
  const { state, token, expires_at: expiresAt } = (data ?? {}) as Record<string, unknown>;
  if (
    (state !== 'reserved' && state !== 'completed') ||
    typeof token !== 'string' ||
    typeof expiresAt !== 'number'
  ) {
    throw new Error('el almacén clave-valor tiene una entrada que no es de omniwebhook');
  }
  return { state, token, expiresAt };
}

/**
 * Almacén de reservas sobre cualquier almacén clave-valor con vencimiento.
 *
 * Con un cliente `conditional`, cada operación lee y después escribe sólo si nadie escribió en
 * el medio: entre pedidos simultáneos por la misma clave, uno solo la reserva. La garantía es
 * la misma que la de los otros almacenes.
 *
 * Con uno que no lo es, entre la lectura y la escritura puede colarse otro proceso: dos
 * entregas simultáneas del mismo evento pueden reservarlo las dos. Sigue evitando los
 * duplicados que llegan separados en el tiempo, que son los reintentos del emisor. `guarantee`
 * dice cuál de las dos es.
 */
export class KeyValueIdempotencyStore implements IdempotencyStore {
  private readonly prefix: string;
  private readonly graceSeconds: number;

  constructor(
    private readonly client: KeyValueClient,
    options: KeyValueStoreOptions = {},
  ) {
    this.prefix = options.prefix ?? DEFAULT_KEY_VALUE_PREFIX;
    this.graceSeconds = options.graceSeconds ?? DEFAULT_KEY_VALUE_GRACE_SECONDS;
    if (typeof this.prefix !== 'string' || this.prefix === '') {
      throw new ConfigurationError('prefix no puede estar vacío');
    }
    if (!Number.isInteger(this.graceSeconds) || this.graceSeconds < 0) {
      throw new ConfigurationError('graceSeconds tiene que ser un entero mayor o igual que cero');
    }
  }

  /** `atomic` si el cliente escribe con condición; `best-effort` si no. */
  get guarantee(): 'atomic' | 'best-effort' {
    return this.client.conditional ? 'atomic' : 'best-effort';
  }

  async claim({ key, token, now, leaseSeconds }: ClaimRequest): Promise<ClaimOutcome> {
    const name = this.prefix + key;
    const reserved = encode({ state: 'reserved', token, expiresAt: now + leaseSeconds });

    for (let attempt = 0; attempt < CLAIM_ATTEMPTS; attempt++) {
      const record = await this.client.get(name);
      const entry = record === null ? null : decode(record.value);
      if (entry !== null && entry.expiresAt > now) {
        return entry.state === 'completed' ? 'duplicate' : 'in_progress';
      }
      const written = await this.client.put(name, reserved, {
        ttlSeconds: leaseSeconds + this.graceSeconds,
        onlyIf: record?.version ?? null,
      });
      if (written) return 'claimed';
      // Otro proceso escribió entre la lectura y la escritura: se vuelve a mirar qué dejó.
    }
    return 'in_progress';
  }

  async complete({ key, token, now, retentionSeconds }: CompleteRequest): Promise<boolean> {
    const name = this.prefix + key;
    const record = await this.ownReservation(name, token);
    if (record === null) return false;
    return this.client.put(
      name,
      encode({ state: 'completed', token, expiresAt: now + retentionSeconds }),
      { ttlSeconds: retentionSeconds, onlyIf: record.version },
    );
  }

  async release({ key, token }: ReleaseRequest): Promise<boolean> {
    const name = this.prefix + key;
    const record = await this.ownReservation(name, token);
    if (record === null) return false;
    return this.client.delete(name, { onlyIf: record.version });
  }

  /** Lo guardado, sólo si es una reserva hecha con este token. */
  private async ownReservation(name: string, token: string): Promise<KeyValueRecord | null> {
    const record = await this.client.get(name);
    if (record === null) return null;
    const entry = decode(record.value);
    return entry.state === 'reserved' && entry.token === token ? record : null;
  }
}

/**
 * Un cliente clave-valor en memoria, con escritura condicional. Sirve para tests y como
 * referencia de lo que tiene que cumplir uno propio. No vence nada: el vencimiento del
 * almacén sólo limpia.
 */
export class MemoryKeyValueClient implements KeyValueClient {
  readonly conditional = true;
  private readonly records = new Map<string, KeyValueRecord>();
  private writes = 0;

  async get(key: string): Promise<KeyValueRecord | null> {
    return this.records.get(key) ?? null;
  }

  async put(
    key: string,
    value: string,
    options: { readonly ttlSeconds: number; readonly onlyIf: string | null },
  ): Promise<boolean> {
    if ((this.records.get(key)?.version ?? null) !== options.onlyIf) return false;
    this.writes += 1;
    this.records.set(key, { value, version: String(this.writes) });
    return true;
  }

  async delete(key: string, options: { readonly onlyIf: string }): Promise<boolean> {
    if (this.records.get(key)?.version !== options.onlyIf) return false;
    return this.records.delete(key);
  }
}

/** Lo que se usa de un espacio de nombres de Workers KV. */
export interface WorkersKvNamespace {
  get(key: string): Promise<string | null>;
  put(key: string, value: string, options: { expirationTtl: number }): Promise<unknown>;
  delete(key: string): Promise<unknown>;
}

// Workers KV no acepta un vencimiento menor.
const WORKERS_KV_MIN_TTL_SECONDS = 60;

/**
 * Adapta un espacio de nombres de Workers KV. No tiene escritura condicional y sus lecturas
 * pueden tardar en ver una escritura reciente, así que la garantía es `best-effort`. Si hace
 * falta la garantía completa en un Worker, conviene el almacén sobre D1.
 */
export function workersKvClient(namespace: WorkersKvNamespace): KeyValueClient {
  return {
    conditional: false,
    async get(key) {
      const value = await namespace.get(key);
      return value === null ? null : { value, version: '' };
    },
    async put(key, value, { ttlSeconds }) {
      const expirationTtl = Math.max(ttlSeconds, WORKERS_KV_MIN_TTL_SECONDS);
      await namespace.put(key, value, { expirationTtl });
      return true;
    },
    async delete(key) {
      await namespace.delete(key);
      return true;
    },
  };
}

/**
 * Lo que se usa de un cliente de documentos de DynamoDB: los métodos `get`, `put` y `delete`
 * que tiene `DynamoDBDocument` de `@aws-sdk/lib-dynamodb`.
 */
export interface DynamoDbDocumentClient {
  get(input: {
    TableName: string;
    Key: Record<string, string>;
    ConsistentRead: boolean;
  }): Promise<{ Item?: Record<string, unknown> | undefined }>;
  put(input: {
    TableName: string;
    Item: Record<string, unknown>;
    ConditionExpression: string;
    ExpressionAttributeNames: Record<string, string>;
    ExpressionAttributeValues?: Record<string, unknown>;
  }): Promise<unknown>;
  delete(input: {
    TableName: string;
    Key: Record<string, string>;
    ConditionExpression: string;
    ExpressionAttributeNames: Record<string, string>;
    ExpressionAttributeValues: Record<string, unknown>;
  }): Promise<unknown>;
}

export interface DynamoDbClientOptions {
  readonly table: string;
  /** El atributo de la clave de partición de la tabla. Por defecto, `pk`. */
  readonly keyAttribute?: string;
  /** El reloj para el atributo de vencimiento, en segundos. Por defecto, el del sistema. */
  readonly now?: () => number;
}

const CONDITION_FAILED = 'ConditionalCheckFailedException';

/**
 * Adapta una tabla de DynamoDB, con escritura condicional: la garantía es `atomic`.
 *
 * La tabla tiene una clave de partición de texto (`pk` si no se indica otra) y ninguna de
 * ordenamiento. Cada ítem lleva `value`, `version` y `ttl`; activando el vencimiento de la
 * tabla sobre el atributo `ttl`, las entradas se borran solas.
 */
export function dynamoDbClient(
  document: DynamoDbDocumentClient,
  options: DynamoDbClientOptions,
): KeyValueClient {
  const { table } = options;
  const keyAttribute = options.keyAttribute ?? 'pk';
  const now = options.now ?? (() => Math.floor(Date.now() / 1000));
  for (const [name, value] of [
    ['table', table],
    ['keyAttribute', keyAttribute],
  ] as const) {
    if (typeof value !== 'string' || value === '') {
      throw new ConfigurationError(`${name} no puede estar vacío`);
    }
  }

  /** `true` si se aplicó; `false` si la condición no se cumplió. Otro error se propaga. */
  async function applied(operation: Promise<unknown>): Promise<boolean> {
    try {
      await operation;
      return true;
    } catch (error) {
      if ((error as { name?: unknown } | null)?.name === CONDITION_FAILED) return false;
      throw error;
    }
  }

  return {
    conditional: true,
    async get(key) {
      const { Item } = await document.get({
        TableName: table,
        Key: { [keyAttribute]: key },
        ConsistentRead: true,
      });
      if (Item === undefined) return null;
      return { value: String(Item.value), version: String(Item.version) };
    },
    put(key, value, { ttlSeconds, onlyIf }) {
      const Item = {
        [keyAttribute]: key,
        value,
        version: crypto.randomUUID(),
        ttl: now() + ttlSeconds,
      };
      return applied(
        onlyIf === null
          ? document.put({
              TableName: table,
              Item,
              ConditionExpression: 'attribute_not_exists(#k)',
              ExpressionAttributeNames: { '#k': keyAttribute },
            })
          : document.put({
              TableName: table,
              Item,
              ConditionExpression: '#v = :expected',
              ExpressionAttributeNames: { '#v': 'version' },
              ExpressionAttributeValues: { ':expected': onlyIf },
            }),
      );
    },
    delete(key, { onlyIf }) {
      return applied(
        document.delete({
          TableName: table,
          Key: { [keyAttribute]: key },
          ConditionExpression: '#v = :expected',
          ExpressionAttributeNames: { '#v': 'version' },
          ExpressionAttributeValues: { ':expected': onlyIf },
        }),
      );
    },
  };
}
