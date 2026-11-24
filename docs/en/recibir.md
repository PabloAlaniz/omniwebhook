# Receiving guide

> **Translation.** This is a translation of the [Spanish original](../recibir.md). If the two disagree, the Spanish text wins.

Receiving a webhook takes four steps, and the package does them in this order:

1. **Verify** the request with the sender's signature scheme.
2. **Reserve** the event in the store, so that nobody else processes it.
3. **Process**: run your function.
4. **Complete** the reservation if it went well, or **release** it if it failed.

Your function only runs if step 1 returned `ok` and step 2 got the reservation.

## The one thing you have to take care of: the raw body

The signature is computed over the bytes of the body exactly as they arrived. If the framework
parses the JSON first and you write it out again, the signature no longer matches. Pass the package
the untouched body:

- **Fetch API**: `toIncomingRequest(request)` reads it for you. Call it before `request.json()`.
- **`node:http` and the frameworks built on top of it**: `nodeIncomingRequest(request)`, from
  `omniwebhook/node`.
- **Starlette and FastAPI**: `await to_incoming_request(request)`, from `omniwebhook.starlette`.
- **Django**: `to_incoming_request(request)`, from `omniwebhook.django`.
- **WSGI**, which includes Flask: `incoming_request_from_environ(environ)`.
- **Another Python framework**: `incoming_request(headers=..., query=..., body=...)`, with the body
  in bytes.

With `node:http`, the adapter reads the stream and `writeNodeResponse` writes the response:

```ts
import { createServer } from 'node:http';
import { nodeIncomingRequest, writeNodeResponse } from 'omniwebhook/node';

createServer(async (request, response) => {
  const reception = await receive.execute(await nodeIncomingRequest(request), procesar);
  writeNodeResponse(response, reception);
});
```

If a middleware has already read the body, pass it in raw. With Express, the webhook route has to
use `express.raw({ type: '*/*' })` instead of `express.json()`, and then `request.body` is the
`Buffer` that arrived:

```ts
const pedidoDeExpress = await nodeIncomingRequest(request, { body: request.body });
```

In Django it is an ordinary view:

```python
from django.http import HttpRequest, HttpResponse
from omniwebhook.django import to_incoming_request, to_response

def webhook(request: HttpRequest) -> HttpResponse:
    return to_response(receive.execute(to_incoming_request(request), procesar))
```

And in any WSGI application, Flask included:

```python
from collections.abc import Iterable
from omniwebhook import incoming_request_from_environ, wsgi_response

def aplicacion(environ: dict[str, Any], start_response: Any) -> Iterable[bytes]:
    pedido = incoming_request_from_environ(environ)
    return wsgi_response(receive.execute(pedido, procesar), start_response)
```

```python
# Flask: the framework has already read the body
pedido = incoming_request_from_environ(request.environ, body=request.get_data())
```

The `node:http` and WSGI adapters read the body themselves and stop once it goes over
`maxBodyBytes` (`max_body_bytes`): the request ends in `too_large` without bringing the rest into
memory.

A repeated header is reported as `ambiguous` only where the environment preserves it: `node:http`,
ASGI and Starlette. The Fetch API, WSGI and Django join repeated headers with commas, so there the
signature simply does not match.

## Signature schemes

| Sender | TypeScript | Python | Timestamp | Event key |
|---|---|---|---|---|
| Standard Webhooks | `standardScheme` | `standard_scheme` | Yes | `webhook-id` |
| Standard Webhooks, with a public key | `standardPublicKeyScheme` | `standard_public_key_scheme` | Yes | `webhook-id` |
| Stripe | `stripeScheme` | `stripe_scheme` | Yes | `id` from the body |
| TikTok | `tiktokScheme` | `tiktok_scheme` | Yes | The body fingerprint |
| Mercado Pago | `mercadoPagoScheme` | `mercadopago_scheme` | Yes | `data.id` and `x-request-id` |
| GitHub | `githubScheme` | `github_scheme` | No | `x-github-delivery` |
| Creem | `creemScheme` | `creem_scheme` | No | `id` from the body |
| Slack | `slackScheme` | `slack_scheme` | Yes | `event_id` from the body, or the fingerprint |
| Shopify | `shopifyScheme` | `shopify_scheme` | No | `x-shopify-webhook-id` |
| Discord | `discordScheme` | `discord_scheme`, in `omniwebhook.discord` | Yes | `id` from the body, or the fingerprint |
| Body signed with HMAC | `hmacBodyScheme` | `hmac_body_scheme` | No | A header, or the body fingerprint |

All of them take a list of secrets. The signature is valid if it matches any of them, so to rotate
a secret it is enough to keep both in the list during the transition.

```ts
stripeScheme({ secrets: [nuevo, anterior], toleranceSeconds: 300 });
```

```python
stripe_scheme(secrets=[nuevo, anterior], tolerance_seconds=300)
```

The tolerance is how far the signed timestamp may be from now, into the past or into the future. It
can be adjusted, but not turned off. In the schemes without a timestamp, what protects against
replay is the event reservation.

The scheme for the standard format lives in a separate entry point (`omniwebhook/standard` in
TypeScript, `omniwebhook.standard` in Python) because it is the only one that uses an external
library.

### Standard Webhooks with a public key

If the sender signs with the asymmetric variant of the format (`v2a`, Ed25519), there is no shared
secret: it gives you a public key, of the form `whpk_…`, and the identifier it assigned to your
endpoint. With that you can verify, but not sign.

```ts
import { standardPublicKeyScheme } from 'omniwebhook/standard';

const verifier = standardPublicKeyScheme({ publicKeys: [secreto], endpointId: 'ep_42' });
```

```python
from omniwebhook.standard import standard_public_key_scheme

verifier = standard_public_key_scheme(public_keys=[secreto], endpoint_id="ep_42")
```

In Python it needs `omniwebhook[ed25519]`. The endpoint identifier is part of what gets signed: it
has to be the one the sender gave you, never one taken from the request. To rotate, pass the new
key and the previous one. A sender that is migrating may send the symmetric signature and the
asymmetric one together; each scheme looks only at its own.

Discord also signs with a public key, your application's, in hexadecimal:
`discordScheme({ publicKeys: [...] })` and `discord_scheme(public_keys=[...])`. In Python it lives
in `omniwebhook.discord` and needs the same extra.

### Several senders on the same URL

If a single route receives webhooks from more than one sender, `routedVerifier` (`routed_verifier`)
picks the scheme by the header that only that sender sends:

```ts
import { githubScheme, routedVerifier, stripeScheme } from 'omniwebhook';

const verifier = routedVerifier([
  { header: 'stripe-signature', verifier: stripeScheme({ secrets: [secreto] }) },
  { header: 'x-hub-signature-256', verifier: githubScheme({ secrets: [nuevo] }) },
]);
```

```python
verifier = routed_verifier(
    [
        VerifierRoute("stripe-signature", stripe_scheme(secrets=[secreto])),
        VerifierRoute("x-hub-signature-256", github_scheme(secrets=[nuevo])),
    ]
)
```

A request with none of those headers is `missing`, and one with more than one is `ambiguous`: one
scheme is never tried after another, because that would let whoever sends the request choose which
rules it is verified with. Event keys do not collide between senders: each one starts with the name
of its scheme.

### A sender that is not on the list

If it signs only the body with HMAC-SHA256 and sends the signature in a header, the generic scheme
is enough:

```ts
hmacBodyScheme({
  secrets: [secreto],
  header: 'x-firma',
  prefix: 'sha256=',
  encoding: 'hex',
  name: 'alertas',
  idHeader: 'x-entrega',
});
```

```python
hmac_body_scheme(
    secrets=[secreto], header="x-firma", prefix="sha256=", encoding="hex", name="alertas", id_header="x-entrega"
)
```

If its format is different, see [how to add a scheme](agregar-un-esquema.md).

### Mercado Pago: the signature does not cover the body

Mercado Pago signs the resource identifier, the request identifier and the timestamp, but not the
body. Treat the notification as a signal that something changed and query the resource from its API
before acting.

The default event key comes only from signed data. If you want it to distinguish the notification
type, replace it:

```ts
createReceiver({
  verifier: mercadoPagoScheme({ secrets }),
  store,
  eventKey: (event) => `${event.eventKey}:${tipoDe(event.request)}`,
});
```

```python
create_receiver(
    verifier=mercadopago_scheme(secrets=secrets),
    store=store,
    event_key=lambda event: f"{event.event_key}:{tipo_de(event.request)}",
)
```

## Idempotency stores

The store is what makes an event get processed only once even if the sender sends it twice or two
processes receive it at the same time.

| Store | When to use it |
|---|---|
| Memory | Tests and development. It does not work with more than one process |
| PostgreSQL | Production. Each operation is a single statement |
| Redis | Production, when there is no relational database. Each operation is a script; entries are deleted on their own |
| Key-value | DynamoDB, Workers KV or whichever you have. The guarantee depends on whether it writes conditionally |
| SQLite | Production with Cloudflare D1, libSQL or a single server. Each operation is a single statement |
| Firestore (Python) | Production. Each operation is a transaction |

### PostgreSQL

The table is created once, with the SQL the package returns:

```ts
import { PostgresIdempotencyStore, postgresStoreSchema } from 'omniwebhook';

await pool.query(postgresStoreSchema());
const store = new PostgresIdempotencyStore(pool);
```

```python
from omniwebhook.postgres import PostgresIdempotencyStore, PsycopgClient, postgres_store_schema

with pool.connection() as connection:
    connection.execute(postgres_store_schema())
store = PostgresIdempotencyStore(PsycopgClient(pool.connection))
```

In TypeScript any client works that has a `query(texto, parámetros)` method returning `{ rows }`.
In Python, `PsycopgClient` adapts a psycopg 3 pool; for another client, an object that has
`query(texto, parámetros)`, with `%s` parameters, and returns the rows is enough.

Expired entries do no harm, but they take up space. `purgeExpired(now)` (`purge_expired(now)` in
Python) deletes them; it is a good idea to run it every so often.

### Redis

```ts
import { createClient } from 'redis';
import { nodeRedisClient, RedisIdempotencyStore } from 'omniwebhook';

const redis = createClient({ url });
await redis.connect();
const almacenEnRedis = new RedisIdempotencyStore(nodeRedisClient(redis));
```

```python
import redis
from omniwebhook.redis import RedisIdempotencyStore

almacen_en_redis = RedisIdempotencyStore(redis.Redis.from_url(url))
```

With `ioredis` you use `ioredisClient`. In Python there is also `AsyncRedisIdempotencyStore`, for
`redis.asyncio`. The package does not import any client: it takes yours.

There is nothing to purge: completed entries are deleted when their retention expires. A
reservation whose lease expired is kept for one more day (`graceSeconds`, `grace_seconds`), so that
whoever was delayed can complete it if nobody took it; after that Redis deletes it. This is the
only difference from the other stores, which keep it with no limit.

Keys carry the prefix `omniwebhook:events:`, which is changed with `prefix`.

### Key-value: DynamoDB, Workers KV or your own

`KeyValueIdempotencyStore` works on top of any key-value store with expiry. What changes from one
to another is the client.

```ts
import { dynamoDbClient, KeyValueIdempotencyStore, workersKvClient } from 'omniwebhook';

// DynamoDB: takes the SDK's document client
const enDynamo = new KeyValueIdempotencyStore(dynamoDbClient(db, { table: 'webhooks' }));

// Workers KV: takes the binding
const enWorkersKv = new KeyValueIdempotencyStore(workersKvClient(env.EVENTOS));
```

```python
from omniwebhook.key_value import DynamoDbTableClient, KeyValueIdempotencyStore

en_dynamo = KeyValueIdempotencyStore(DynamoDbTableClient(db))  # the boto3 table resource
```

The DynamoDB table has a string partition key, `pk` (changed with `keyAttribute`,
`key_attribute`), and no sort key. If you enable the table's expiry on the `ttl` attribute, entries
are deleted on their own. In Python there are also `AsyncKeyValueIdempotencyStore` and
`AsyncDynamoDbTableClient`.

**The guarantee is not the same in all of them**, and the store tells you which one it gives in
`guarantee`:

- `atomic`, with DynamoDB: it writes only if nobody changed the entry since it read it. Among
  simultaneous requests for the same event, only one processes it. This is the guarantee of the
  other stores.
- `best-effort`, with Workers KV: it has no conditional write. It avoids duplicates that arrive
  separated in time, which are the sender's retries, but two simultaneous deliveries of the same
  event can both be processed. If you need the full guarantee in a Worker, use D1.

For another store, implement the client: it is three methods.

```ts
import type { KeyValueClient } from 'omniwebhook';

const miCliente: KeyValueClient = {
  conditional: true, // whether put and delete honor onlyIf atomically
  async get(key) {
    const fila = await db.leer(key);
    return fila === null ? null : { value: fila.valor, version: fila.version };
  },
  // Writes only if the stored version is onlyIf; with null, only if the key does not exist.
  put: (key, value, { ttlSeconds, onlyIf }) => db.escribirSi(key, value, ttlSeconds, onlyIf),
  delete: (key, { onlyIf }) => db.borrarSi(key, onlyIf),
};
```

In Python it is the same, with `ttl_seconds` and `only_if`. `MemoryKeyValueClient` is the reference
for what it has to satisfy. As in Redis, an expired reservation is kept for one more day before the
store deletes it.

### SQLite and D1

For SQLite (and for D1, which is also SQLite) the package ships its own variant of the SQL, with
`?` parameters and the same columns as the PostgreSQL table.

In a Cloudflare Worker, `d1Client` adapts the D1 binding. It is a good idea to create the table in
a D1 migration with the SQL from `sqliteStoreSchema()`, copied as is:

```ts
import { createReceiver, d1Client, SqliteIdempotencyStore } from 'omniwebhook';
import { standardScheme } from 'omniwebhook/standard';

const receive = createReceiver({
  verifier: standardScheme({ secrets: [env.WEBHOOK_SECRET] }),
  store: new SqliteIdempotencyStore(d1Client(env.DB)),
});
```

With a synchronous SQLite database (`node:sqlite`, `better-sqlite3` or `bun:sqlite`),
`sqliteClient` adapts it:

```ts
import { DatabaseSync } from 'node:sqlite';
import { SqliteIdempotencyStore, sqliteClient, sqliteStoreSchema } from 'omniwebhook';

const db = new DatabaseSync('webhooks.db');
db.exec(sqliteStoreSchema());
const store = new SqliteIdempotencyStore(sqliteClient(db));
```

In Python, `Sqlite3Client` adapts a `sqlite3` connection, from the standard library. It commits
each statement and runs them one at a time, so the same connection works for several threads if it
is opened with `check_same_thread=False`:

```python
import sqlite3

from omniwebhook.sqlite import Sqlite3Client, SqliteIdempotencyStore, sqlite_store_schema

conexion = sqlite3.connect("webhooks.db", check_same_thread=False)
conexion.executescript(sqlite_store_schema())
store = SqliteIdempotencyStore(Sqlite3Client(conexion))
```

For another client, in both languages an object that runs a statement with `?` parameters, commits
it and returns the rows is enough: `all(sql, parámetros)` in TypeScript and
`query(texto, parámetros)` in Python. In Python there is only a synchronous variant, because
`sqlite3` is not asynchronous; from asynchronous code it can be run in a thread with
`asyncio.to_thread`.

A SQLite file can be shared by the two packages: what one reserves, the other sees.

### Firestore

```python
from omniwebhook.firestore import FirestoreIdempotencyStore

store = FirestoreIdempotencyStore(firestore.Client(), collection="omniwebhook_events")
```

Each entry stores the `expire_time` field. With a TTL policy on that field, Firestore deletes
expired entries on its own.

### Durations

- **`leaseSeconds` / `lease_seconds`** (300 by default): how long a reservation lasts. If your
  function takes longer than that, another process can take the event. Set a lease longer than your
  worst case.
- **`retentionSeconds` / `retention_seconds`** (seven days by default): how long an already
  processed event is remembered. It has to cover the window in which the sender retries.

### Body size

- **`maxBodyBytes` / `max_body_bytes`** (1 MiB by default): a larger body ends in `too_large`, with
  status 413, before the signature is looked at. If your sender sends larger events, raise it.

This limit avoids computing a signature over a huge body, but by the time it reaches the package
the body is already in memory. The limit that protects memory is the one in your server or your
framework: set it to the same value or lower.

## What to respond

`toResponse` and `to_response` build the response with the suggested status and no body: the
response does not tell the caller which of the checks failed. If you build the response by hand,
`httpStatusFor(outcome)` (`http_status_for(outcome)`) gives the status.

Four cases worth understanding:

- **`unprocessable` responds 422.** The signature was valid but the payload did not pass your
  validator. Retrying does not fix it; the thing to do is log the reason.
- **`too_large` responds 413.** It is not a problem of origin but of size, and retrying does not
  fix it: most senders stop trying on a 4xx.
- **`duplicate` responds 200.** The event was already processed; an error would make the sender
  keep retrying.
- **`failed` responds 500 and releases the reservation.** The sender retries and the retry gets
  processed. The error from your function comes attached to the result, so that you can log it.

```ts
const reception = await receive.execute(pedido, procesar);
if (reception.outcome === 'failed') logger.error(reception.error);
```

## Validating the payload

A valid signature says who sent the event, not that it has the shape your code expects. With
`payload` you pass it a validator, and your function receives the already validated payload instead
of parsing the body by hand.

In TypeScript the schema of any library that implements the common schema interface (the
`~standard` property) works as is, and the payload type comes from there:

```ts
const receptorDePedidos = createReceiver({
  verifier: stripeScheme({ secrets: [secreto] }),
  store,
  payload: esquemaDePedido, // a schema from the library you use
});

await receptorDePedidos.execute(pedido, async (event) => {
  await registrarPago(event.payload); // already validated and typed
});
```

In Python it is any function that takes the parsed body and returns the validated value, or raises
if it is no good. The validator of a model library is passed directly:

```python
receptor_de_pedidos = create_receiver(
    verifier=stripe_scheme(secrets=[secreto]),
    store=store,
    payload=Pedido.model_validate,
)

def procesar_pedido(event: VerifiedEvent) -> None:
    registrar_pago(event.payload)  # an instance of Pedido
```

A body that is not JSON, or that the validator rejects, ends in `unprocessable`, with status 422.
The result carries the reason: `issues` in TypeScript and `error` in Python.

The validator runs after the signature is verified, so an unauthenticated body is never parsed, and
before the event is reserved, so an invalid payload writes nothing to the store. If the sender
retries, the retry gives `unprocessable` again.

## Measuring what happens

With `observer`, each reception reports its outcome, the event key and how long it took. It is
useful for counting rejections by reason or for alerting if the `failed` ones go up, without
touching your function:

```ts
const receptor = createReceiver({
  verifier: stripeScheme({ secrets: [secreto] }),
  store,
  observer: {
    onReception: ({ outcome, eventKey, durationMs }) => logger.info({ outcome, eventKey, durationMs }),
  },
});
```

```python
class Metricas:
    def on_reception(self, observation: ReceptionObservation) -> None:
        print(observation.outcome, observation.event_key, observation.duration_ms)

receptor = create_receiver(verifier=stripe_scheme(secrets=[secreto]), store=store, observer=Metricas())
```

The observer does not receive the body, the headers or any secret, and it cannot change the
outcome: if it throws, the error is discarded. For sending it is not needed: the delivery ledger
already receives every attempt.

## Testing your integration

`omniwebhook/testing` (`omniwebhook.testing`) builds the request each sender would send, signed
with the secret you pass it, so that your tests go through the real path instead of skipping
verification:

```ts
import { stripeScheme } from 'omniwebhook';
import { signedRequest, tampered, toFetchRequest } from 'omniwebhook/testing';

const firmado = await signedRequest('stripe', { secret: secreto, body: '{"id":"evt_1"}' });

await stripeScheme({ secrets: [secreto] }).verify(firmado); // ok
await stripeScheme({ secrets: [secreto] }).verify(tampered(firmado)); // invalid

const viejo = await signedRequest('stripe', { secret: secreto, body: '{}', timestamp: 1 }); // stale
const paraLaRuta = toFetchRequest(firmado); // a Request, for calling your route
```

```python
from omniwebhook.testing import signed_request, tampered

firmado = signed_request("stripe", secret=secreto, body='{"id":"evt_1"}')

stripe_scheme(secrets=[secreto]).verify(firmado)  # ok
stripe_scheme(secrets=[secreto]).verify(tampered(firmado))  # invalid
```

The public key schemes take the private key in `secret`: `whsk_…` and `endpointId` (`endpoint_id`)
in `standard-v2a`, and the seed in hexadecimal in `discord`.

To test that a repeated event is not processed twice, send the same signed request twice. It works
for all the included schemes; with `hmac-body` it takes the same configuration as the scheme.

## Debugging from the terminal

Both packages install the same command, `omniwebhook`, for testing an integration without writing
code. With npm you run it with `npx omniwebhook`; with Python, `omniwebhook` or
`python -m omniwebhook`.

```bash
export FIRMA='el secreto del emisor'

# Send a signed event to your local server
omniwebhook send --scheme stripe --secret-env FIRMA --body evento.json \
  --url http://localhost:3000/webhooks

# See the request the sender would send, and save it
omniwebhook sign --scheme stripe --secret-env FIRMA --body evento.json > pedido.json

# Verify a saved request: it prints the outcome and exits with 0 only if it is ok
omniwebhook verify --scheme stripe --secret-env FIRMA --request pedido.json
```

The secret is read from an environment variable and never goes as an argument, so that it does not
end up in the terminal history. `--timestamp` signs with a different time, to provoke a `stale`;
`--body -` and `--request -` read from standard input. It works for the shared-secret schemes; the
public key ones are signed with the private key in the environment variable and verified with the
public one; `standard-v2a` also requires `--endpoint-id`. `omniwebhook keygen` generates a new
pair.

It is a development tool: `send` sends to whatever URL you give it, without the destination URL policy
that sending applies.

## Synchronous or asynchronous, in Python

Every piece that does input/output has both variants. The asynchronous one carries the prefix
`Async` or `async`:

| Synchronous | Asynchronous |
|---|---|
| `create_receiver` | `create_async_receiver` |
| `MemoryIdempotencyStore` | `AsyncMemoryIdempotencyStore` |
| `PostgresIdempotencyStore` | `AsyncPostgresIdempotencyStore` |
| `FirestoreIdempotencyStore` | `AsyncFirestoreIdempotencyStore` |
| `SqliteIdempotencyStore` | None: `sqlite3` is not asynchronous |

The signature schemes are the same in both cases: verifying is just computation.

In the asynchronous variant, if the task is cancelled while your function is running, the
reservation is released before the cancellation continues on its way.
