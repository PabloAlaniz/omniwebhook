// Agente de interoperabilidad del paquete de TypeScript.
//
// Lee un pedido JSON por línea de la entrada estándar y responde un JSON por línea. Usa el
// paquete ya compilado (`pnpm build`), igual que lo usaría quien lo instala.
import { createInterface } from 'node:readline';
import { DatabaseSync } from 'node:sqlite';
import pg from 'pg';
import { Webhook } from 'standardwebhooks';
import {
  classifyDelivery,
  creemScheme,
  evaluateDestination,
  discordScheme,
  endpointHealth,
  githubScheme,
  hmacBodyScheme,
  httpStatusFor,
  inspectDestination,
  allowedNetworks,
  isBlockedAddress,
  isEventPattern,
  isEventType,
  mercadoPagoScheme,
  nextAttempt,
  PostgresDeliveryLedger,
  PostgresIdempotencyStore,
  PostgresOutbox,
  postgresLedgerSchema,
  postgresOutboxSchema,
  postgresStoreSchema,
  SqliteDeliveryLedger,
  SqliteIdempotencyStore,
  sqliteClient,
  sqliteLedgerSchema,
  sqliteStoreSchema,
  shopifyScheme,
  slackScheme,
  stripeScheme,
  subscribes,
  summarizeFailures,
  tiktokScheme,
} from '../dist/index.js';
import { standardPublicKeyScheme, standardScheme, standardSigner } from '../dist/standard.js';

const bytes = (base64) => new Uint8Array(Buffer.from(base64, 'base64'));
const defined = (entries) => Object.fromEntries(entries.filter(([, value]) => value !== undefined));

function verifier({ scheme, secrets, now, options = {} }) {
  const clock = { now: () => now };
  const timed = defined([
    ['secrets', secrets],
    ['clock', clock],
    ['toleranceSeconds', options.tolerance_seconds],
  ]);
  if (scheme === 'standard') return standardScheme(timed);
  if (scheme === 'standard-v2a') {
    return standardPublicKeyScheme(
      defined([
        ['publicKeys', secrets],
        ['endpointId', options.endpoint_id],
        ['clock', clock],
        ['toleranceSeconds', options.tolerance_seconds],
      ]),
    );
  }
  if (scheme === 'discord') {
    return discordScheme(
      defined([
        ['publicKeys', secrets],
        ['clock', clock],
        ['toleranceSeconds', options.tolerance_seconds],
      ]),
    );
  }
  if (scheme === 'stripe') return stripeScheme(timed);
  if (scheme === 'tiktok') return tiktokScheme(timed);
  if (scheme === 'mercadopago') return mercadoPagoScheme(timed);
  if (scheme === 'github') return githubScheme({ secrets });
  if (scheme === 'creem') return creemScheme({ secrets });
  if (scheme === 'shopify') return shopifyScheme({ secrets });
  if (scheme === 'slack') return slackScheme(timed);
  if (scheme === 'hmac-body') {
    return hmacBodyScheme(
      defined([
        ['secrets', secrets],
        ['header', options.header],
        ['prefix', options.prefix],
        ['encoding', options.encoding],
        ['name', options.name],
        ['idHeader', options.id_header],
      ]),
    );
  }
  throw new Error(`esquema desconocido: ${scheme}`);
}

let database = null;
let store = null;
let ledger = null;
let outbox = null;

// `sqlite:<archivo>` abre un archivo SQLite; cualquier otra URL, un PostgreSQL.
function openDatabase(url) {
  if (url.startsWith('sqlite:')) {
    const db = new DatabaseSync(url.slice('sqlite:'.length), { timeout: 10_000 });
    return {
      kind: 'sqlite',
      client: sqliteClient(db),
      exec: async (sql) => db.exec(sql),
      close: async () => db.close(),
    };
  }
  const pool = new pg.Pool({ connectionString: url });
  return {
    kind: 'postgres',
    client: pool,
    exec: async (sql) => pool.query(sql),
    close: async () => pool.end(),
  };
}

const commands = {
  async verify(input) {
    const { headers, query, body } = input.request;
    const result = await verifier(input).verify({ headers, query, body: bytes(body) });
    return result.outcome === 'ok'
      ? { outcome: 'ok', event_key: result.eventKey, timestamp: result.timestamp }
      : { outcome: result.outcome };
  },
  async sign({ secrets, id, timestamp, payload }) {
    return standardSigner({ secrets }).sign({ id, timestamp, payload: bytes(payload) });
  },
  // Lo que firmó el otro paquete, verificado con la librería de referencia del formato.
  async reference_verify({ secret, headers, body }) {
    try {
      new Webhook(secret).verify(Buffer.from(body, 'base64'), headers, { jsonParse: false });
      return { valid: true };
    } catch {
      return { valid: false };
    }
  },
  async address({ address }) {
    return { blocked: isBlockedAddress(address) };
  },
  async network({ network }) {
    try {
      allowedNetworks([network]);
      return { valid: true };
    } catch {
      return { valid: false };
    }
  },
  async url({ url, allow_http, allowed_networks = [], resolved }) {
    const result = evaluateDestination(url, {
      allowHttp: allow_http,
      allowedNetworks: allowed_networks,
      resolved,
    });
    const inspected = inspectDestination(url, { allowHttp: allow_http });
    if (typeof inspected === 'string') return { result };
    // Lo que entiende el analizador de la plataforma, que es el que usa el transporte.
    let platform = null;
    try {
      const parsed = new URL(url);
      platform = {
        host: parsed.hostname.replace(/^\[|\]$/g, ''),
        port: parsed.port === '' ? null : Number(parsed.port),
        scheme: parsed.protocol,
      };
    } catch {}
    return { result, host: inspected.host, literal: inspected.literalAddress, platform };
  },
  async classify({ status, failure }) {
    return { class: classifyDelivery(status === null ? { failure } : { status }) };
  },
  async health({ attempts, since, now, policy }) {
    const summary = summarizeFailures(
      attempts.map((a) => ({ at: a.at, deliveryClass: a.delivery_class })),
      since,
    );
    const health = endpointHealth(
      summary,
      now,
      policy ? { windowSeconds: policy.window_seconds, minFailures: policy.min_failures } : {},
    );
    return {
      summary: { failures: summary.failures, failing_since: summary.failingSince, gone: summary.gone },
      health,
    };
  },
  async event({ type, patterns }) {
    const valid_type = isEventType(type);
    const valid_patterns = patterns === null ? null : patterns.map(isEventPattern);
    let subscribed = null;
    try {
      subscribed = subscribes(patterns, type);
    } catch {}
    return { valid_type, valid_patterns, subscribed };
  },
  async status({ outcome }) {
    return { status: httpStatusFor(outcome) };
  },
  async retry(input) {
    const policy = defined([
      ['schedule', input.schedule],
      ['maxDelaySeconds', input.max_delay_seconds],
      ['jitterRatio', input.jitter_ratio],
    ]);
    const next = nextAttempt({
      attempt: input.attempt,
      now: input.now,
      random: input.random,
      retryAfter: input.retry_after,
      policy,
    });
    return next.exhausted
      ? { exhausted: true }
      : { exhausted: false, delay_seconds: next.delaySeconds, next_at: next.nextAt };
  },
  async store_open({ url, table, create }) {
    database = openDatabase(url);
    const sqlite = database.kind === 'sqlite';
    if (create) {
      await database.exec(`DROP TABLE IF EXISTS ${table}`);
      await database.exec(sqlite ? sqliteStoreSchema(table) : postgresStoreSchema(table));
    }
    store = sqlite
      ? new SqliteIdempotencyStore(database.client, { table })
      : new PostgresIdempotencyStore(database.client, { table });
    return { ready: true };
  },
  async store_step(step) {
    if (step.op === 'claim') {
      return {
        result: await store.claim({
          key: step.key,
          token: step.token,
          now: step.now,
          leaseSeconds: step.lease_seconds,
        }),
      };
    }
    if (step.op === 'complete') {
      return {
        result: await store.complete({
          key: step.key,
          token: step.token,
          now: step.now,
          retentionSeconds: step.retention_seconds,
        }),
      };
    }
    return { result: await store.release({ key: step.key, token: step.token }) };
  },
  async store_close({ table, drop }) {
    if (drop) await database.exec(`DROP TABLE IF EXISTS ${table}`);
    await database.close();
    return { closed: true };
  },
  async outbox_open({ url, table, create }) {
    database = openDatabase(url);
    if (create) {
      await database.exec(`DROP TABLE IF EXISTS ${table}`);
      await database.exec(postgresOutboxSchema(table));
    }
    outbox = new PostgresOutbox(database.client, { table });
    return { ready: true };
  },
  async outbox_reset({ table }) {
    await database.exec(`TRUNCATE ${table} RESTART IDENTITY`);
    return { reset: true };
  },
  async outbox_step(step) {
    if (step.op === 'enqueue') {
      return {
        result: await outbox.enqueue({
          messageId: step.message_id,
          endpointId: step.endpoint_id,
          payload: new TextEncoder().encode(step.payload),
          now: step.now,
        }),
      };
    }
    if (step.op === 'claim') {
      const entries = await outbox.claim({
        token: step.token,
        now: step.now,
        limit: step.limit,
        leaseSeconds: step.lease_seconds,
      });
      return {
        result: entries.map((entry) => ({
          message_id: entry.messageId,
          endpoint_id: entry.endpointId,
          payload: new TextDecoder().decode(entry.payload),
          attempt: entry.attempt,
        })),
      };
    }
    if (step.op === 'requeue') {
      return {
        result: await outbox.requeue({
          endpointId: step.endpoint_id,
          from: step.from,
          to: step.to,
          now: step.now,
        }),
      };
    }
    const pair = { messageId: step.message_id, endpointId: step.endpoint_id, token: step.token };
    return {
      result: await outbox.settle(
        step.state === 'pending'
          ? { ...pair, state: 'pending', nextAt: step.next_at }
          : { ...pair, state: step.state },
      ),
    };
  },
  async outbox_close({ table, drop }) {
    if (drop) await database.exec(`DROP TABLE IF EXISTS ${table}`);
    await database.close();
    return { closed: true };
  },
  async ledger_open({ url, table, create }) {
    database = openDatabase(url);
    const sqlite = database.kind === 'sqlite';
    if (create) {
      await database.exec(`DROP TABLE IF EXISTS ${table}`);
      await database.exec(sqlite ? sqliteLedgerSchema(table) : postgresLedgerSchema(table));
    }
    ledger = sqlite
      ? new SqliteDeliveryLedger(database.client, { table })
      : new PostgresDeliveryLedger(database.client, { table });
    return { ready: true };
  },
  async ledger_record({ record }) {
    await ledger.record({
      messageId: record.message_id,
      endpointId: record.endpoint_id,
      attempt: record.attempt,
      at: record.at,
      deliveryClass: record.delivery_class,
      state: record.state,
      status: record.status,
      problem: record.problem,
      durationMs: record.duration_ms,
      nextAt: record.next_at,
    });
    return { recorded: true };
  },
  async ledger_read({ message_id, endpoint_id }) {
    const attempts = await ledger.attemptsOf(message_id, endpoint_id);
    return {
      attempts: attempts.map((a) => ({
        message_id: a.messageId,
        endpoint_id: a.endpointId,
        attempt: a.attempt,
        at: a.at,
        delivery_class: a.deliveryClass,
        state: a.state,
        status: a.status,
        problem: a.problem,
        duration_ms: a.durationMs,
        next_at: a.nextAt,
      })),
    };
  },
  async ledger_close({ table, drop }) {
    if (drop) await database.exec(`DROP TABLE IF EXISTS ${table}`);
    await database.close();
    return { closed: true };
  },
};

for await (const line of createInterface({ input: process.stdin })) {
  if (line.trim() === '') continue;
  let reply;
  try {
    const { command, ...input } = JSON.parse(line);
    reply = await commands[command](input);
  } catch (error) {
    reply = { crashed: String(error) };
  }
  process.stdout.write(`${JSON.stringify(reply)}\n`);
}
