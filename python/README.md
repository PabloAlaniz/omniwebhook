# omniwebhook

Webhooks firmados que se emiten y se reciben igual en cualquier stack: verificación, frescura,
idempotencia y reintentos con las mismas reglas en Python y en TypeScript.

- **Recibir**: verifica la firma, rechaza lo viejo y lo ambiguo, y procesa cada evento una sola
  vez. Devuelve un resultado tipado en vez de lanzar.
- **Emitir**: firma con [Standard Webhooks](https://www.standardwebhooks.com/), no entrega a
  direcciones internas y dice cuándo reintentar.
- **Sincrónico y asincrónico**, con tipos completos y sin dependencias obligatorias. Python 3.11 o
  superior.

```bash
pip install omniwebhook
```

## Recibir

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

Esquemas incluidos: `stripe_scheme`, `tiktok_scheme`, `mercadopago_scheme`, `github_scheme`, `creem_scheme`,
`slack_scheme`, `shopify_scheme`, `hmac_body_scheme` y, en `omniwebhook.standard`, `standard_scheme`.

## Emitir

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

## Módulos y extras

| Módulo | Qué trae | Extra |
|---|---|---|
| `omniwebhook` | Recepción, emisión, esquemas, almacén en memoria y transporte de la biblioteca estándar | Ninguno |
| `omniwebhook.standard` | El formato Standard Webhooks: verificar y firmar | `omniwebhook[standard]` |
| `omniwebhook.postgres` | El almacén de reservas sobre PostgreSQL | `omniwebhook[postgres]`, para el pool de psycopg |
| `omniwebhook.sqlite` | El almacén de reservas y el registro de entregas sobre SQLite | Ninguno: usa `sqlite3` |
| `omniwebhook.firestore` | El almacén de reservas sobre Firestore | `omniwebhook[firestore]` |
| `omniwebhook.starlette` | Ayudas para Starlette y FastAPI | `omniwebhook[starlette]` |
| `omniwebhook.django` | Ayudas para Django | `omniwebhook[django]` |
| `omniwebhook.httpx` | Un transporte asincrónico sobre httpx | `omniwebhook[httpx]` |

`omniwebhook.standard` usa por defecto la librería de referencia del formato. Con
`signer=native_signer` firma con la biblioteca estándar y no hace falta el extra:

```python
from omniwebhook.standard import native_signer, standard_scheme

standard_scheme(secrets=[secreto], signer=native_signer)
```

## Documentación

- [Guía para recibir](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/recibir.md)
- [Guía para emitir](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/emitir.md)
- [Especificación](https://github.com/PabloAlaniz/omniwebhook/blob/main/spec/SPEC.md)
- [Repositorio](https://github.com/PabloAlaniz/omniwebhook#readme)

## Licencia

MIT
