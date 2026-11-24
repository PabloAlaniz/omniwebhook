# omniwebhook

> **Translation.** This is a translation of the [Spanish original](README.md). If the two disagree, the Spanish text wins.

Signed webhooks that are sent and received the same way in any stack: verification, freshness,
idempotency and retries with the same rules in Python and in TypeScript.

- **Receive**: verifies the signature, rejects what is stale and what is ambiguous, and processes
  each event only once. It returns a typed result instead of throwing.
- **Send**: signs with [Standard Webhooks](https://www.standardwebhooks.com/), does not deliver to
  internal addresses and tells you when to retry.
- **Synchronous and asynchronous**, fully typed and with no required dependencies. Python 3.11 or
  later.

```bash
pip install omniwebhook
```

## Receive

```python
import json
import os

from omniwebhook import VerifiedEvent, create_async_receiver, stripe_scheme
from omniwebhook.postgres import AsyncPostgresIdempotencyStore, AsyncPsycopgClient
from omniwebhook.starlette import to_incoming_request, to_response

receive = create_async_receiver(
    verifier=stripe_scheme(secrets=[os.environ.get("STRIPE_WEBHOOK_SECRET", "")]),
    store=AsyncPostgresIdempotencyStore(AsyncPsycopgClient(pool.connection)),
)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> Response:
    async def procesar(event: VerifiedEvent) -> None:
        await registrar_pago(json.loads(event.request.body))

    return to_response(await receive.execute(await to_incoming_request(request), procesar))
```

Included schemes: `stripe_scheme`, `tiktok_scheme`, `mercadopago_scheme`, `github_scheme`, `creem_scheme`,
`slack_scheme`, `shopify_scheme`, `hmac_body_scheme` and, in `omniwebhook.standard`, `standard_scheme`.

## Send

```python
import os

from omniwebhook import Delivery, Endpoint, MemoryDeliveryLedger, create_sender, random_message_id
from omniwebhook.standard import standard_signer

send = create_sender(
    signer=standard_signer(secrets=[os.environ.get("WEBHOOK_SIGNING_SECRET", "")]),
    ledger=MemoryDeliveryLedger(),
)

attempt = send.execute(
    Delivery(
        endpoint=Endpoint(id="ep_42", url="https://cliente.example/webhooks"),
        message_id=random_message_id(),
        payload=b'{"type":"pedido.creado"}',
    )
)
```

## Modules and extras

| Module | What it provides | Extra |
|---|---|---|
| `omniwebhook` | Receiving, sending, schemes, in-memory store and standard library transport | None |
| `omniwebhook.standard` | The Standard Webhooks format: verifying and signing | `omniwebhook[standard]`; `omniwebhook[ed25519]` for asymmetric signatures |
| `omniwebhook.postgres` | The idempotency store on PostgreSQL | `omniwebhook[postgres]`, for the psycopg pool |
| `omniwebhook.redis` | The idempotency store on Redis | None: it takes your `redis` client |
| `omniwebhook.key_value` | The idempotency store on DynamoDB or any key-value store | None: it takes your client |
| `omniwebhook.sqlite` | The idempotency store and the delivery ledger on SQLite | None: it uses `sqlite3` |
| `omniwebhook.firestore` | The idempotency store on Firestore | `omniwebhook[firestore]` |
| `omniwebhook.starlette` | Helpers for Starlette and FastAPI | `omniwebhook[starlette]` |
| `omniwebhook.discord` | The Discord signature scheme | `omniwebhook[ed25519]` |
| `omniwebhook.django` | Helpers for Django | `omniwebhook[django]` |
| `omniwebhook.otel` | Metrics and traces with OpenTelemetry | `omniwebhook[otel]` |
| `omniwebhook.testing` | Signed requests for testing your integration | None |
| `omniwebhook.httpx` | An asynchronous transport over httpx | `omniwebhook[httpx]` |

`omniwebhook.standard` uses the format's reference library by default. With
`signer=native_signer` it signs with the standard library and the extra is not needed:

```python
from omniwebhook.standard import native_signer, standard_scheme

standard_scheme(secrets=[secreto], signer=native_signer)
```

## Documentation

- [Receiving guide](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/en/recibir.md)
- [Sending guide](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/en/emitir.md)
- [Specification](https://github.com/PabloAlaniz/omniwebhook/blob/main/spec/SPEC.en.md)
- [Repository](https://github.com/PabloAlaniz/omniwebhook#readme)

## License

MIT
