# omniwebhook

[![CI](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml/badge.svg)](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/PabloAlaniz/omniwebhook/badge)](https://scorecard.dev/viewer/?uri=github.com/PabloAlaniz/omniwebhook)

English · [Español](README.md) · [简体中文](README.zh-CN.md) · [Português (Brasil)](README.pt-BR.md)

Signed webhooks, sent and received the same way on any stack.

> **Pre-1.0.** Both packages are published on npm and PyPI, complete and covering the whole
> specification, but the API can still change between minor versions.

> **About this translation.** This page is a translation; if it disagrees with the
> [Spanish original](README.md), the original wins. The rest of the documentation is translated
> too, and the links below lead to the English versions.

Almost every product ends up receiving webhooks from a payment provider and sending its own. And
it almost always gets written again from scratch: one signature check per provider, a table to
avoid processing twice, a hand-rolled retry. `omniwebhook` separates the rules from everything
else:

- **The same rules for receiving.** Verify the signature, reject what is stale, reject what is
  ambiguous and process each event exactly once, with a typed result instead of exceptions.
- **An open format for sending.** Outgoing messages are signed with
  [Standard Webhooks](https://www.standardwebhooks.com/), with retries defined as data and a
  policy that refuses to deliver to internal addresses.
- **Any provider, any database, any HTTP client.** The core knows none of them: they are ports,
  and each one is filled in by an adapter.
- **The same behaviour in every language.** There is a [specification](spec/SPEC.en.md) and shared
  conformance vectors. The TypeScript and Python packages run the same cases, and an
  interoperability test compares them request by request.

## The two rules that are not negotiable

1. **Nothing is processed without being verified.** If the secret is missing, the request is
   rejected: there is no mode that skips verification. Checking that the message is recent is
   part of verifying it.
2. **Each event takes effect exactly once.** The event is reserved before it is processed. If
   processing fails, the reservation is released so that the sender's retry works.

## Receiving

TypeScript, in any runtime with the Fetch API:

```ts
import { createReceiver, PostgresIdempotencyStore, stripeScheme, toIncomingRequest, toResponse } from 'omniwebhook';

const receive = createReceiver({
  verifier: stripeScheme({ secrets: [process.env.STRIPE_WEBHOOK_SECRET ?? ''] }),
  store: new PostgresIdempotencyStore(pool),
});

export async function POST(request: Request): Promise<Response> {
  const reception = await receive.execute(await toIncomingRequest(request), async (event) => {
    await recordPayment(JSON.parse(new TextDecoder().decode(event.request.body)));
  });
  return toResponse(reception);
}
```

Python, with FastAPI or Starlette:

```python
from omniwebhook import create_async_receiver, stripe_scheme
from omniwebhook.postgres import AsyncPostgresIdempotencyStore, AsyncPsycopgClient
from omniwebhook.starlette import to_incoming_request, to_response

receive = create_async_receiver(
    verifier=stripe_scheme(secrets=[os.environ.get("STRIPE_WEBHOOK_SECRET", "")]),
    store=AsyncPostgresIdempotencyStore(AsyncPsycopgClient(pool.connection)),
)

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> Response:
    async def process(event: VerifiedEvent) -> None:
        await record_payment(json.loads(event.request.body))

    return to_response(await receive.execute(await to_incoming_request(request), process))
```

The handler only runs if the signature is valid, the message is recent and nobody has processed
it before. Everything else ends in a result with a suggested HTTP status:

| Result | Status | What happened |
|---|---|---|
| `ok` | 200 | It was processed |
| `duplicate` | 200 | It had already been processed |
| `in_progress` | 409 | Another process is handling it |
| `missing`, `ambiguous`, `malformed`, `invalid`, `stale` | 401 | The origin could not be established |
| `too_large` | 413 | The body exceeds the maximum size |
| `unprocessable` | 422 | The signature is valid but the payload does not have the expected shape |
| `unconfigured` | 500 | A usable secret is missing |
| `failed` | 500 | Processing failed and the reservation was released |

More in the [receiving guide](docs/en/recibir.md).

## Sending

TypeScript, on Node:

```ts
import { MemoryDeliveryLedger, randomMessageId } from 'omniwebhook';
import { createNodeSender } from 'omniwebhook/node';
import { standardSigner } from 'omniwebhook/standard';

const send = createNodeSender({
  signer: standardSigner({ secrets: [process.env.WEBHOOK_SIGNING_SECRET ?? ''] }),
  ledger: new MemoryDeliveryLedger(),
});

const attempt = await send.execute({
  endpoint: { id: 'ep_42', url: 'https://customer.example/webhooks' },
  message: { id: randomMessageId(), payload: new TextEncoder().encode('{"type":"order.created"}') },
  attempt: 1,
});
// attempt.state: 'delivered', 'pending' (with attempt.nextAt), 'rejected', 'blocked', 'gone' or 'exhausted'
```

Python:

```python
from omniwebhook import Delivery, Endpoint, MemoryDeliveryLedger, create_sender, random_message_id
from omniwebhook.standard import standard_signer

send = create_sender(
    signer=standard_signer(secrets=[os.environ.get("WEBHOOK_SIGNING_SECRET", "")]),
    ledger=MemoryDeliveryLedger(),
)

attempt = send.execute(
    Delivery(
        endpoint=Endpoint(id="ep_42", url="https://customer.example/webhooks"),
        message_id=random_message_id(),
        payload=b'{"type":"order.created"}',
    )
)
# attempt.state: "delivered", "pending" (with attempt.next_at), "rejected", "blocked", "gone" or "exhausted"
```

Each call is one attempt. The package tells you when the next one is due, but it does not
schedule it: that stays with the queue or scheduler you already use. If you do not want to lose
an event when the process dies, the outbox stores pending deliveries and hands them out to the
processes that dispatch. More in the [sending guide](docs/en/emitir.md).

## What each package includes

| | TypeScript | Python |
|---|---|---|
| Signature schemes | Standard Webhooks (shared secret or public key), Stripe, Slack, Shopify, Discord, TikTok, Mercado Pago, GitHub, Creem and a generic signed-body scheme | The same |
| Idempotency store | Memory, PostgreSQL, Redis, SQLite (also D1), DynamoDB, Workers KV or any key-value store | Memory, PostgreSQL, Redis, SQLite, Firestore, DynamoDB or any key-value store |
| HTTP transport | Node networking modules, Fetch API | Standard library, httpx (async) |
| Delivery ledger | Memory, PostgreSQL, SQLite (also D1) | Memory, PostgreSQL, SQLite |
| Outbox | Memory, PostgreSQL | Memory, PostgreSQL |
| Entry points | Fetch API (`Request` and `Response`), `node:http` and whatever is built on it | ASGI, Starlette and FastAPI, WSGI, Django, or any framework |
| Style | Async | Sync and async |
| Required dependencies | None | None |

The PostgreSQL stores of both packages use the same table: an event processed by a service in
one language is recognised as a duplicate by the other. The Redis stores share reservations too:
they run the same scripts. The same holds for the delivery ledger and the outbox, and for SQLite.

## Installation

```bash
npm install omniwebhook                   # TypeScript
npm install standardwebhooks              # only for omniwebhook/standard

pip install omniwebhook                   # Python
pip install "omniwebhook[standard]"       # with the Standard Webhooks reference library
```

The other Python extras (`httpx`, `starlette`, `django`, `postgres`, `firestore`, `ed25519`,
`otel`) are described in the [package README](python/README.en.md).

## Documentation

| | |
|---|---|
| [Receiving guide](docs/en/recibir.md) | Schemes, stores, event keys and responses |
| [Sending guide](docs/en/emitir.md) | Signing, URL policy, retries, outbox and endpoint health |
| [Telemetry](docs/en/telemetria.md) | Metrics and traces with OpenTelemetry |
| [Examples](examples/README.en.md) | Minimal receivers and an outbox, tested in CI |
| [How to add a signature scheme](docs/en/agregar-un-esquema.md) | From the specification to the adapter |
| [Specification](spec/SPEC.en.md) | The behaviour every package shares |
| [Architecture decisions](docs/en/adr/README.md) | Why it is built this way |
| [How a version is published](docs/en/publicar.md) | The release flow and trusted publishing |
| [Compatibility](docs/en/compatibilidad.md) | What is stable, which runtimes are supported and how changes are announced |
| [Roadmap](docs/en/roadmap.md) | What is done and what is missing |
| [1.0 criteria](docs/en/criterios-1.0.md) | What has to be true before the API is frozen |

## Repository layout

| Folder | Contents |
|---|---|
| [`spec/`](spec/) | The specification and the conformance vectors |
| [`ts/`](ts/) | The TypeScript package (npm) |
| [`python/`](python/) | The Python package (PyPI) |
| [`tools/`](tools/) | The vector generator and the interoperability test |
| [`examples/`](examples/) | A minimal receiver per runtime, tested in CI |
| [`docs/`](docs/) | The guides and the architecture decisions |

## Contributing

See [CONTRIBUTING](CONTRIBUTING.en.md) and the [code of conduct](CODE_OF_CONDUCT.en.md). To report
a security issue, see [SECURITY](SECURITY.en.md).

## License

[MIT](LICENSE)
