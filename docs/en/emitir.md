# Sending guide

> **Translation.** This is a translation of the [Spanish original](../emitir.md). If the two disagree, the Spanish text wins.

Sending a webhook means making **attempts**. Each call to the package makes one:

1. **Signs** the message in the [Standard Webhooks](https://www.standardwebhooks.com/) format.
2. **Validates the endpoint**: the shape of the URL and the addresses it resolves to.
3. **Sends** the POST to the address it validated.
4. **Classifies** what happened and says when the next attempt is due.
5. **Records** the attempt.

The package does not schedule the retry. It returns `nextAt` (`next_at` in Python) and you schedule
it in the queue or scheduler you already use, calling again with the next attempt number.

## One attempt

```ts
import { randomMessageId } from 'omniwebhook';
import { createNodeSender } from 'omniwebhook/node';
import { standardSigner } from 'omniwebhook/standard';

const send = createNodeSender({ signer: standardSigner({ secrets: [secreto] }), ledger });

const attempt = await send.execute({
  endpoint: { id: 'ep_42', url: 'https://cliente.example/webhooks' },
  message: { id: randomMessageId(), payload },
  attempt: 1,
});

if (attempt.state === 'pending') await cola.agendar({ ...entrega, attempt: 2 }, attempt.nextAt);
```

```python
from omniwebhook import Delivery, Endpoint, create_sender, random_message_id
from omniwebhook.standard import standard_signer

send = create_sender(signer=standard_signer(secrets=[secreto]), ledger=ledger)

attempt = send.execute(
    Delivery(endpoint=Endpoint("ep_42", "https://cliente.example/webhooks"), message_id=identificador, payload=payload)
)

if attempt.state == "pending":
    cola.agendar(entrega, intento=2, cuando=attempt.next_at)
```

Three things to keep in mind:

- **The message identifier is the same in every attempt.** It is what lets the receiver recognize
  a retry. Store it together with the message; do not generate it on each attempt.
- **The body is bytes** and is sent exactly as it was signed. Serialize it once and store those
  bytes.
- **Each attempt is signed again** with the current time, so a late retry does not arrive with an
  old timestamp.

## Without losing events: the outbox

The example above has a gap: if the process crashes between the attempt and `cola.agendar`, the
retry is lost. And before that, if the change that causes the webhook is saved but the send
fails, the event never goes out. The outbox closes both.

**Enqueuing** goes in the same transaction as the business change. If the transaction does not
commit, the webhook does not exist; if it commits, it is not lost:

```ts
import { PostgresOutbox, randomMessageId } from 'omniwebhook';

const conexion = await pool.connect();
try {
  await conexion.query('BEGIN');
  await conexion.query('INSERT INTO pedidos (id) VALUES ($1)', ['pedido-1']);
  await new PostgresOutbox(conexion).enqueue({
    messageId: randomMessageId(),
    endpointId: 'ep_42',
    payload,
    now: Math.floor(Date.now() / 1000),
  });
  await conexion.query('COMMIT');
} finally {
  conexion.release();
}
```

```python
from omniwebhook import EnqueueRequest
from omniwebhook.postgres import PostgresOutbox, PsycopgConnectionClient

with pool.connection() as conexion:  # commits on exit, or rolls back if anything raises
    conexion.execute("INSERT INTO pedidos (id) VALUES (%s)", ("pedido-1",))
    PostgresOutbox(PsycopgConnectionClient(conexion)).enqueue(
        EnqueueRequest(message_id=identificador, endpoint_id="ep_42", payload=payload, now=ahora)
    )
```

**Dispatching** runs separately. Each call claims a batch of the pending deliveries that are
already due, makes one attempt per delivery and settles it with the result; what has to be retried
goes out again when it is due:

```ts
import { createDispatcher, PostgresOutbox } from 'omniwebhook';

const despacho = createDispatcher({
  outbox: new PostgresOutbox(pool),
  // Your endpoints: the outbox stores only the identifier, never the URL.
  endpoints: { resolve: async (id) => db.destinoHabilitado(id) }, // { url } or null
  sender: send, // the createNodeSender from above
});

const tanda = await despacho.execute();
// tanda.dispatched: what was attempted and how it ended up. tanda.failures: what never got attempted.
```

```python
from omniwebhook import create_dispatcher
from omniwebhook.postgres import PostgresOutbox, PsycopgClient

despacho = create_dispatcher(
    outbox=PostgresOutbox(PsycopgClient(pool.connection)), endpoints=destinos, sender=send
)
tanda = despacho.execute()
```

It does not come with a scheduler: call it every few seconds from a cron, a job in your queue or a
loop. Several processes can dispatch at the same time without delivering the same thing twice.

What is worth knowing:

- **At least once.** If the process crashes after delivering and before settling, the message
  goes out again, with the same identifier. The receiver recognizes it as a repeat.
- **No ordering.** Two messages for the same endpoint can arrive in any order.
- **An endpoint that does not exist or is disabled** (`resolve` returns `null`, `None`) cancels
  the delivery without attempting it.
- **One secret per endpoint.** `sender` is anything with `execute`: if each endpoint has its own
  secret, pass an object that picks the sender based on `delivery.endpoint.id`.
- **`leaseSeconds` (`lease_seconds`) has to last longer than a whole batch**: the limit times the
  timeout of one attempt. The defaults, 10 deliveries and 300 seconds, are enough.
- **Enqueuing the same message twice for the same endpoint does not duplicate it.**

There is an in-memory outbox (`MemoryOutbox`), for tests, and one on PostgreSQL. The table is
created with `postgresOutboxSchema()` (`postgres_outbox_schema()`) and is the same in both
packages: one service can enqueue in one language and another can dispatch in the other. In Python
there are also `AsyncPostgresOutbox` and `create_async_dispatcher`. There is a
[complete example](../../examples/python-outbox/app.py).

## Each endpoint receives only what it asked for

An event type names what happened, from the general to the particular: `pedido.creado`,
`pedido.item.agregado`. Each endpoint declares which ones it receives with a list of patterns, and
`subscribes` says whether an event is meant for it:

```ts
import { subscribes } from 'omniwebhook';

subscribes(['pedido.*', 'pago.aprobado'], 'pedido.creado'); // true
subscribes(['pedido.*'], 'pago.aprobado'); // false
subscribes(null, 'pago.aprobado'); // true: with no list, it receives everything
```

```python
from omniwebhook import subscribes

subscribes(["pedido.*", "pago.aprobado"], "pedido.creado")  # True
```

| Pattern | Matches |
|---|---|
| `*` | Any type |
| `pedido.*` | Whatever starts with `pedido.`, at any depth. Not `pedido` on its own |
| `pedido.creado` | That exact type |

The wildcard only goes at the end, and matching is case-sensitive. An empty list receives nothing.
A badly written type or pattern raises a configuration error instead of silently not matching: it
is worth validating the patterns with `isEventPattern` (`is_event_pattern`) when the endpoint's
owner saves them.

It is used when enqueuing: for each subscribed endpoint, one entry in the outbox with the same
message identifier. Where the type goes inside the payload is up to you; the usual choice is a
`type` field.

## Endpoints that are down

An endpoint that has not responded for days keeps consuming attempts. With `health`, the
dispatcher computes the health of each endpoint after an attempt that failed and tells you which
ones are worth disabling:

```ts
import { createDispatcher, PostgresOutbox } from 'omniwebhook';

const despachoConSalud = createDispatcher({
  outbox: new PostgresOutbox(pool),
  endpoints: { resolve: async (id) => db.destinoHabilitado(id) },
  sender: send,
  health: { failures: ledger }, // the same delivery ledger that send uses
});

const resultado = await despachoConSalud.execute();
for (const { endpointId, health } of resultado.disabled) {
  await db.deshabilitar(endpointId, health.reason); // 'failing' or 'gone'
}
```

```python
from omniwebhook.postgres import PostgresOutbox, PsycopgClient

despacho_con_salud = create_dispatcher(
    outbox=PostgresOutbox(PsycopgClient(pool.connection)), endpoints=destinos, sender=send, health=ledger
)
for caido in despacho_con_salud.execute().disabled:
    db.deshabilitar(caido.endpoint_id, caido.health.reason)
```

An endpoint is reported for disabling in two cases: it responded 410, or it failed at least 5
times in a row and has gone 5 days without a single delivery. Both conditions are needed: many
failures in a short while are an outage that recovers. They are changed with
`policy: { windowSeconds, minFailures }` (`health_policy=HealthPolicy(...)`).

**The package reports, it does not disable.** Storing that state and notifying the endpoint's
owner is up to you. As long as `resolve` keeps returning the endpoint, deliveries to it continue;
when it returns `null` (`None`), its pending deliveries are cancelled.

**To re-enable it**, make `resolve` return `enabledAt` (`enabled_at`) with the moment it was
re-enabled: health counts from there, and what failed before does not take it down again. What
was cancelled or failed while it was down is requeued by time range:

```ts
import { PostgresOutbox } from 'omniwebhook';

const reenviadas = await new PostgresOutbox(pool).requeue({
  endpointId: 'ep_42',
  from: 1_700_000_000, // since when it was down
  to: 1_700_400_000,
  now: Math.floor(Date.now() / 1000),
});
```

```python
from omniwebhook.postgres import PostgresOutbox, PsycopgClient

reenviadas = PostgresOutbox(PsycopgClient(pool.connection)).requeue(
    RequeueRequest(endpoint_id="ep_42", since=1_700_000_000, until=1_700_400_000, now=ahora)
)
```

They go out again from attempt 1 and with the same message identifier. What was already delivered
is not resent. If you do not use the outbox, `endpointHealth` and `summarizeFailures`
(`endpoint_health`, `summarize_failures`) are standalone functions, and the delivery ledgers have
`failuresOf` (`failures_of`).

## What state the delivery ends up in

| State | When | What to do |
|---|---|---|
| `delivered` | The endpoint responded 2xx | Nothing else |
| `pending` | It failed but can be retried | Schedule the next attempt for `nextAt` |
| `exhausted` | It failed and no attempts are left | Notify; it can be resent by hand |
| `rejected` | The endpoint responded with something that is not retried, redirects included | Check the endpoint |
| `gone` | The endpoint responded 410 | Disable the endpoint |
| `blocked` | The URL policy rejected the endpoint | Check the URL; `problem` says why |

A retry happens on 408, 409, 425, 429, any 5xx, a network error and a timeout.

Resending a delivery by hand means calling again from attempt 1 with the same message
identifier.

## The retry policy

It is data: the list of waits, in seconds, between one attempt and the next. By default there are
ten attempts spread over a little more than three days.

```ts
createNodeSender({ signer, ledger, retryPolicy: { schedule: [10, 60, 600, 3600], maxDelaySeconds: 3600 } });
```

```python
create_sender(signer=signer, ledger=ledger, retry_policy=RetryPolicy(schedule=[10, 60, 600, 3600]))
```

- If the endpoint responds with `retry-after`, the wait is what it asks for when that is more than
  what was due, without going over the cap.
- A random variation of up to 10 % is added to each wait, so that the retries of many messages do
  not all land together.

## The destination URL policy

A destination URL is written by a third party. Without care, someone can register one that points
to your cloud's metadata service or to an internal service. Before each attempt the package
checks:

- that the URL is `https` (or `http`, only if you allow it explicitly);
- that it carries no user or password;
- that it has a strict shape: no backslashes, no spaces or control characters, no abbreviated
  forms of an IP address;
- that **none** of the addresses the name resolves to is in a private, local or reserved range.

It then connects to the address it validated and does not resolve the name again. Redirects are
not followed.

It is worth checking the URL also when the customer registers it, to tell them right away:

```ts
import { inspectDestination } from 'omniwebhook';

const revisada = inspectDestination(url);
if (typeof revisada === 'string') throw new Error(`URL no válida: ${revisada}`);
```

```python
from omniwebhook import inspect_destination

revisada = inspect_destination(url)
if isinstance(revisada, str):
    raise ValueError(f"URL no válida: {revisada}")
```

That check looks only at the URL. The check on the addresses is done on each attempt, because a
name can change address after it is registered.

A name with characters outside ASCII has to come in its ASCII form (`xn--…`).

### Delivering to your own network

If the sender runs in your infrastructure and has to deliver to services on the same network
(another container, a machine on the local network, a VPN), you can allow those networks
explicitly. An address in an allowed network is accepted even if it is in a blocked range:

```ts
const send = createNodeSender({
  signer,
  ledger,
  allowedNetworks: ['192.168.0.0/16', 'fd00::/8'],
});
```

```python
send = create_sender(signer=signer, ledger=ledger, allowed_networks=["192.168.0.0/16", "fd00::/8"])
```

- Each network is written `address/prefix`, with the bits outside the prefix set to zero:
  `10.0.0.0/8` yes, `10.0.0.1/8` no. A badly written network is a configuration error when the
  sender is built.
- The clouds' metadata services (`169.254.0.0/16`, `100.100.100.200`, `fd00:ec2::254`) are never
  allowed, even if a network in the list includes them.
- The rest of the policy does not change: strict shape, no credentials, `https` unless explicitly
  allowed, and connection to the validated address.

Allow only what you need. If the endpoints are registered by third parties, any network in the
list is within their reach.

### Which transport to use

| Transport | Connects to the validated address |
|---|---|
| `createNodeSender` (`omniwebhook/node`) | Yes |
| `createSender` with the Fetch API | **No**: the Fetch API does not let you choose the address |
| `create_sender` and `create_async_sender` (Python) | Yes |
| `AsyncHttpxTransport` (`omniwebhook.httpx`) | Yes |

With the Fetch API, between the validation and the connection the name could resolve to another
address. Use that transport only where there is no other, and knowing that the protection is
partial.

### No system DNS: Workers and edge functions

`createSender` needs a resolver to validate the addresses. Where there is no system DNS
(Cloudflare Workers, Deno Deploy, edge functions), `dohResolver` resolves with DNS over HTTPS:

```ts
import { createSender, dohResolver } from 'omniwebhook';
import { standardSigner } from 'omniwebhook/standard';

const send = createSender({
  signer: standardSigner({ secrets: [secreto] }),
  ledger,
  resolver: dohResolver(),
});
```

By default it asks Cloudflare's service; `endpoint` picks another one that speaks the JSON format,
such as `https://dns.google/resolve`. The names of the endpoints travel to that service. A name
that does not exist leaves the attempt `blocked` with `unresolved`; if the service does not
respond, the attempt counts as a network error and is retried.

The connection still cannot be pinned to the validated address, because the transport is the Fetch
API. On Cloudflare Workers it is worth adding the `global_fetch_strictly_public` option in
`wrangler.toml`, which prevents `fetch` from reaching internal addresses.

The timeout (`timeoutSeconds`, `timeout_seconds`; 20 seconds by default) is the deadline for the
whole attempt in every transport: a server that responds one byte at a time does not stretch it.

## The delivery ledger

Each attempt is stored in the ledger, which is a port with a single method. The package comes with
one in memory, for tests, and one on PostgreSQL and another on SQLite, for production. The tables
are the same in both packages: what one records, the other reads.

```ts
import { PostgresDeliveryLedger, postgresLedgerSchema } from 'omniwebhook';

await pool.query(postgresLedgerSchema());
const ledger = new PostgresDeliveryLedger(pool);

const intentos = await ledger.attemptsOf('msg_…', 'ep_42');
await ledger.purgeBefore(Math.floor(Date.now() / 1000) - 30 * 86_400);
```

```python
from omniwebhook.postgres import PostgresDeliveryLedger, PsycopgClient, postgres_ledger_schema

with pool.connection() as connection:
    connection.execute(postgres_ledger_schema())
ledger = PostgresDeliveryLedger(PsycopgClient(pool.connection))
```

The schema's SQL is several statements (the table and two indexes): it is run without parameters.
In Python there is also `AsyncPostgresDeliveryLedger`.

On SQLite or D1 it is the same, with `SqliteDeliveryLedger` and `sqliteLedgerSchema()`
(`sqlite_ledger_schema()` in Python). In a Cloudflare Worker, the schema goes in a D1 migration
and the ledger uses the binding:

```ts
import { d1Client, SqliteDeliveryLedger } from 'omniwebhook';

const ledger = new SqliteDeliveryLedger(d1Client(db));
```

A resend starts again from attempt 1, so the table can have two rows with the same attempt
number; `attemptsOf` (`attempts_of`) returns them in the order in which they were recorded. Old
attempts are not deleted on their own: `purgeBefore(at)` (`purge_before(at)`) deletes the ones
that started before `at`.

For another database, write your own ledger:

```ts
import type { AttemptRecord, DeliveryLedger } from 'omniwebhook';

const ledger: DeliveryLedger = {
  async record(attempt: AttemptRecord) {
    await db.insert('webhook_attempts', attempt);
  },
};
```

```python
class Registro:
    def record(self, attempt: AttemptRecord) -> None:
        db.insert("webhook_attempts", dataclasses.asdict(attempt))
```

The ledger stores the identifier you use to refer to the endpoint, never its URL: a webhook URL
usually carries a token and must not end up in a log.

## Rotating the signing secret

With more than one secret, each message goes out with one signature per secret. The receiver
accepts any of them, so you can move from the old secret to the new one without coordinating the
exact moment:

```ts
standardSigner({ secrets: [nuevo, anterior] });
```

## Signing with a private key

With a shared secret, the receiver could sign just as you do. With the asymmetric variant of the
format, you sign with a private key and the receiver verifies with the public one: if it leaks
from them, nobody can impersonate you.

```ts
import { generateStandardKeyPair, standardKeySigner } from 'omniwebhook/standard';

const par = await generateStandardKeyPair(); // { secretKey: 'whsk_…', publicKey: 'whpk_…' }
const firmante = standardKeySigner({ secretKeys: [par.secretKey] });
```

```python
from omniwebhook.standard import generate_standard_key_pair, standard_key_signer

par = generate_standard_key_pair()
firmante = standard_key_signer(secret_keys=[par.secret_key])
```

It is used like any signer, in `signer`. In Python it needs `omniwebhook[ed25519]`. The private
key goes to your secrets manager; you give the receiver the public key and the identifier of
their endpoint, which is part of what is signed. That is why that identifier cannot contain dots,
and changing it invalidates the receiver's verifications.

To rotate, pass the new key and the previous one: one signature goes out for each. To migrate from
the shared secret without coordinating the moment with each receiver, send both signatures
together:

```ts
import { combinedSigner, standardKeySigner, standardSigner } from 'omniwebhook/standard';

const lasDos = combinedSigner([
  standardSigner({ secrets: [secreto] }),
  standardKeySigner({ secretKeys: [nuevo] }),
]);
```

`combined_signer` in Python. Each receiver looks only at the signature of its variant.

## Custom headers

You can add headers to each send with `headers`. They cannot replace the signature headers, the
content type header, which is changed with `contentType` (`content_type`), or `user-agent`.

Each send identifies itself with `user-agent: omniwebhook/<versión> (<lenguaje>)`. The receiver
can use it to recognize the traffic in their logs; to check the origin there is the signature.

## Payload size

A payload of more than 256 KiB is not sent: `execute` raises a configuration error, as with an
invalid `id`. It is changed with `maxPayloadBytes` (`max_payload_bytes`), but it is better not to:
a small webhook that says what happened and where to look up the detail lets the receiver decide
what to fetch, and does not depend on their server's size limit.

## The endpoint's response

Only the status and the `retry-after` header of the response are used. The body is not read: an
endpoint cannot make you spend memory by responding with a huge one.

## What you tell the receiver

The receiver can verify your webhooks with any implementation of Standard Webhooks, or with this
same package:

```ts
standardScheme({ secrets: [secretoCompartido] });
```
