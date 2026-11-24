# omniwebhook

[![CI](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml/badge.svg)](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/PabloAlaniz/omniwebhook/badge)](https://scorecard.dev/viewer/?uri=github.com/PabloAlaniz/omniwebhook)

Webhooks firmados que se emiten y se reciben igual en cualquier stack.

> **Antes de la 1.0.** Los dos paquetes están publicados en npm y PyPI, completos y con la
> especificación cubierta, pero la API todavía puede cambiar entre versiones menores.

Casi todo producto termina recibiendo webhooks de un proveedor de pagos y emitiendo los suyos. Y
casi siempre se escribe de nuevo: una verificación de firma por proveedor, una tabla para no
procesar dos veces, un reintento a mano. `omniwebhook` separa las reglas de todo lo demás:

- **Las mismas reglas para recibir.** Verificar la firma, rechazar lo viejo, rechazar lo ambiguo y
  procesar cada evento una sola vez, con un resultado tipado en vez de excepciones.
- **Un formato abierto para emitir.** Lo que sale se firma con
  [Standard Webhooks](https://www.standardwebhooks.com/), con reintentos definidos como datos y una
  política que impide entregar a direcciones internas.
- **Cualquier proveedor, cualquier base, cualquier cliente HTTP.** El núcleo no los conoce: son
  puertos, y cada uno se resuelve con un adaptador.
- **El mismo comportamiento en cada lenguaje.** Hay una [especificación](spec/SPEC.md) y vectores de
  conformidad compartidos. El paquete de TypeScript y el de Python corren los mismos casos, y una
  prueba de interoperabilidad los compara pedido por pedido.

## Las dos reglas que no se negocian

1. **Nada se procesa sin verificar.** Si falta el secreto, se rechaza: no hay un modo que saltee
   la verificación. Comprobar que el aviso es reciente es parte de verificar.
2. **Cada evento produce efecto una sola vez.** El evento se reserva antes de procesarlo. Si el
   procesamiento falla, la reserva se libera para que el reintento del emisor funcione.

## Recibir

TypeScript, en cualquier entorno con la API Fetch:

```ts
import { createReceiver, PostgresIdempotencyStore, stripeScheme, toIncomingRequest, toResponse } from 'omniwebhook';

const receive = createReceiver({
  verifier: stripeScheme({ secrets: [process.env.STRIPE_WEBHOOK_SECRET ?? ''] }),
  store: new PostgresIdempotencyStore(pool),
});

export async function POST(request: Request): Promise<Response> {
  const reception = await receive.execute(await toIncomingRequest(request), async (event) => {
    await registrarPago(JSON.parse(new TextDecoder().decode(event.request.body)));
  });
  return toResponse(reception);
}
```

Python, con FastAPI o Starlette:

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
    async def procesar(event: VerifiedEvent) -> None:
        await registrar_pago(json.loads(event.request.body))

    return to_response(await receive.execute(await to_incoming_request(request), procesar))
```

La función que procesa el evento sólo se ejecuta si la firma es válida, el aviso es reciente y nadie
lo procesó antes. Todo lo demás termina en un resultado con su estado HTTP sugerido:

| Resultado | Estado | Qué pasó |
|---|---|---|
| `ok` | 200 | Se procesó |
| `duplicate` | 200 | Ya se había procesado |
| `in_progress` | 409 | Otro proceso lo está procesando |
| `missing`, `ambiguous`, `malformed`, `invalid`, `stale` | 401 | No se pudo comprobar el origen |
| `too_large` | 413 | El cuerpo supera el tamaño máximo |
| `unprocessable` | 422 | La firma es válida pero el payload no tiene la forma esperada |
| `unconfigured` | 500 | Falta un secreto utilizable |
| `failed` | 500 | Falló el procesamiento y la reserva quedó libre |

Más en la [guía para recibir](docs/recibir.md).

## Emitir

TypeScript, en Node:

```ts
import { MemoryDeliveryLedger, randomMessageId } from 'omniwebhook';
import { createNodeSender } from 'omniwebhook/node';
import { standardSigner } from 'omniwebhook/standard';

const send = createNodeSender({
  signer: standardSigner({ secrets: [process.env.WEBHOOK_SIGNING_SECRET ?? ''] }),
  ledger: new MemoryDeliveryLedger(),
});

const attempt = await send.execute({
  endpoint: { id: 'ep_42', url: 'https://cliente.example/webhooks' },
  message: { id: randomMessageId(), payload: new TextEncoder().encode('{"type":"pedido.creado"}') },
  attempt: 1,
});
// attempt.state: 'delivered', 'pending' (con attempt.nextAt), 'rejected', 'blocked', 'gone' o 'exhausted'
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
        endpoint=Endpoint(id="ep_42", url="https://cliente.example/webhooks"),
        message_id=random_message_id(),
        payload=b'{"type":"pedido.creado"}',
    )
)
# attempt.state: "delivered", "pending" (con attempt.next_at), "rejected", "blocked", "gone" o "exhausted"
```

Cada llamada es un intento. El paquete dice cuándo corresponde el siguiente, pero no lo programa:
eso queda del lado de la cola o el planificador que ya uses. Más en la
[guía para emitir](docs/emitir.md).

## Qué trae cada paquete

| | TypeScript | Python |
|---|---|---|
| Esquemas de firma | Standard Webhooks (con secreto compartido o con clave pública), Stripe, Slack, Shopify, Discord, TikTok, Mercado Pago, GitHub, Creem y uno genérico de cuerpo firmado | Los mismos |
| Almacén de reservas | Memoria, PostgreSQL, Redis, SQLite (también D1), DynamoDB, Workers KV o cualquier clave-valor | Memoria, PostgreSQL, Redis, SQLite, Firestore, DynamoDB o cualquier clave-valor |
| Transporte HTTP | Módulos de red de Node, API Fetch | Biblioteca estándar, httpx (asincrónico) |
| Registro de entregas | Memoria, PostgreSQL, SQLite (también D1) | Memoria, PostgreSQL, SQLite |
| Entrada | API Fetch (`Request` y `Response`), `node:http` y lo que se monta encima | ASGI, Starlette y FastAPI, WSGI, Django, o cualquier framework |
| Estilo | Asincrónico | Sincrónico y asincrónico |
| Dependencias obligatorias | Ninguna | Ninguna |

Los almacenes de PostgreSQL de los dos paquetes usan la misma tabla: un evento que procesó un
servicio en un lenguaje, el otro lo reconoce como duplicado.
Los de Redis también comparten las reservas: corren los mismos scripts.
Lo mismo pasa con el registro de entregas: los intentos que registra uno los lee el otro. Y lo
mismo con SQLite.

## Instalación

```bash
npm install omniwebhook                   # TypeScript
npm install standardwebhooks              # sólo para omniwebhook/standard

pip install omniwebhook                   # Python
pip install "omniwebhook[standard]"       # con la librería de referencia de Standard Webhooks
```

Los demás extras de Python (`httpx`, `starlette`, `postgres`, `firestore`) están descritos en el
[README del paquete](python/README.md).

## Documentación

| | |
|---|---|
| [Guía para recibir](docs/recibir.md) | Esquemas, almacenes, claves de evento y respuestas |
| [Ejemplos](examples/README.md) | Un receptor mínimo en `node:http`, WSGI, Starlette y Django |
| [Guía para emitir](docs/emitir.md) | Firma, política de URLs, reintentos y registro |
| [Cómo agregar un esquema de firma](docs/agregar-un-esquema.md) | De la especificación al adaptador |
| [Especificación](spec/SPEC.md) | El comportamiento que comparten todos los paquetes |
| [Decisiones de arquitectura](docs/adr/README.md) | Por qué está hecho así |
| [Cómo se publica una versión](docs/publicar.md) | El circuito de versiones y la publicación de confianza |
| [Compatibilidad](docs/compatibilidad.md) | Qué es estable, qué entornos se soportan y cómo se avisa un cambio |
| [Hoja de ruta](docs/roadmap.md) | Lo que viene en los próximos tres sprints |

## Estructura del repositorio

| Carpeta | Qué hay |
|---|---|
| [`spec/`](spec/) | La especificación y los vectores de conformidad |
| [`ts/`](ts/) | El paquete de TypeScript (npm) |
| [`python/`](python/) | El paquete de Python (PyPI) |
| [`tools/`](tools/) | El generador de vectores y la prueba de interoperabilidad |
| [`examples/`](examples/) | Un receptor mínimo por entorno, probado en la integración continua |
| [`docs/`](docs/) | Las guías y las decisiones de arquitectura |

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md) y el [código de conducta](CODE_OF_CONDUCT.md). Para reportar un problema de seguridad, ver
[SECURITY.md](SECURITY.md).

## Licencia

[MIT](LICENSE)
