# Guía para recibir

Recibir un webhook son cuatro pasos, y el paquete los hace en este orden:

1. **Verificar** el pedido con el esquema de firma del emisor.
2. **Reservar** el evento en el almacén, para que nadie más lo procese.
3. **Procesar**: ejecutar tu función.
4. **Completar** la reserva si salió bien, o **liberarla** si falló.

Tu función sólo corre si el paso 1 dio `ok` y el paso 2 consiguió la reserva.

## Lo único que tenés que cuidar: el cuerpo crudo

La firma se calcula sobre los bytes del cuerpo tal como llegaron. Si el framework interpreta el
JSON antes y vos lo volvés a escribir, la firma deja de coincidir. Pasale al paquete el cuerpo sin
tocar:

- **API Fetch**: `toIncomingRequest(request)` lo lee por vos. Llamalo antes de `request.json()`.
- **`node:http` y los frameworks montados encima**: `nodeIncomingRequest(request)`, de
  `omniwebhook/node`.
- **Starlette y FastAPI**: `await to_incoming_request(request)`, de `omniwebhook.starlette`.
- **Django**: `to_incoming_request(request)`, de `omniwebhook.django`.
- **WSGI**, que incluye a Flask: `incoming_request_from_environ(environ)`.
- **Otro framework de Python**: `incoming_request(headers=..., query=..., body=...)`, con el cuerpo en
  bytes.

Con `node:http`, el adaptador lee el flujo y `writeNodeResponse` escribe la respuesta:

```ts
import { createServer } from 'node:http';
import { nodeIncomingRequest, writeNodeResponse } from 'omniwebhook/node';

createServer(async (request, response) => {
  const reception = await receive.execute(await nodeIncomingRequest(request), procesar);
  writeNodeResponse(response, reception);
});
```

Si un middleware ya leyó el cuerpo, pasáselo crudo. Con Express, la ruta del webhook tiene que usar
`express.raw({ type: '*/*' })` en lugar de `express.json()`, y entonces `request.body` es el
`Buffer` que llegó:

```ts
const pedidoDeExpress = await nodeIncomingRequest(request, { body: request.body });
```

En Django es una vista común:

```python
from django.http import HttpRequest, HttpResponse
from omniwebhook.django import to_incoming_request, to_response

def webhook(request: HttpRequest) -> HttpResponse:
    return to_response(receive.execute(to_incoming_request(request), procesar))
```

Y en cualquier aplicación WSGI, Flask incluido:

```python
from collections.abc import Iterable
from omniwebhook import incoming_request_from_environ, wsgi_response

def aplicacion(environ: dict[str, Any], start_response: Any) -> Iterable[bytes]:
    pedido = incoming_request_from_environ(environ)
    return wsgi_response(receive.execute(pedido, procesar), start_response)
```

```python
# Flask: el cuerpo ya lo leyó el framework
pedido = incoming_request_from_environ(request.environ, body=request.get_data())
```

Los adaptadores de `node:http` y de WSGI leen el cuerpo ellos mismos y cortan al pasarse de
`maxBodyBytes` (`max_body_bytes`): el pedido termina en `too_large` sin traer el resto a memoria.

Una cabecera repetida se informa como `ambiguous` sólo donde el entorno la conserva: `node:http`,
ASGI y Starlette. La API Fetch, WSGI y Django unen con comas las cabeceras repetidas, así que ahí
simplemente la firma no coincide.

## Esquemas de firma

| Emisor | TypeScript | Python | Marca de tiempo | Clave del evento |
|---|---|---|---|---|
| Standard Webhooks | `standardScheme` | `standard_scheme` | Sí | `webhook-id` |
| Standard Webhooks, con clave pública | `standardPublicKeyScheme` | `standard_public_key_scheme` | Sí | `webhook-id` |
| Stripe | `stripeScheme` | `stripe_scheme` | Sí | `id` del cuerpo |
| TikTok | `tiktokScheme` | `tiktok_scheme` | Sí | La huella del cuerpo |
| Mercado Pago | `mercadoPagoScheme` | `mercadopago_scheme` | Sí | `data.id` y `x-request-id` |
| GitHub | `githubScheme` | `github_scheme` | No | `x-github-delivery` |
| Creem | `creemScheme` | `creem_scheme` | No | `id` del cuerpo |
| Slack | `slackScheme` | `slack_scheme` | Sí | `event_id` del cuerpo, o la huella |
| Shopify | `shopifyScheme` | `shopify_scheme` | No | `x-shopify-webhook-id` |
| Discord | `discordScheme` | `discord_scheme`, en `omniwebhook.discord` | Sí | `id` del cuerpo, o la huella |
| Cuerpo firmado con HMAC | `hmacBodyScheme` | `hmac_body_scheme` | No | Una cabecera, o la huella del cuerpo |

Todos reciben una lista de secretos. La firma vale si coincide con cualquiera, así que para rotar un
secreto alcanza con tener los dos en la lista durante la transición.

```ts
stripeScheme({ secrets: [nuevo, anterior], toleranceSeconds: 300 });
```

```python
stripe_scheme(secrets=[nuevo, anterior], tolerance_seconds=300)
```

La tolerancia es cuánto puede alejarse de ahora la marca de tiempo firmada, hacia el pasado o hacia
el futuro. Se puede ajustar, pero no apagar. En los esquemas sin marca de tiempo, lo que protege de
la repetición es la reserva del evento.

El esquema del formato estándar vive en una entrada aparte (`omniwebhook/standard` en TypeScript,
`omniwebhook.standard` en Python) porque es el único que usa una librería externa.

### Standard Webhooks con clave pública

Si el emisor firma con la variante asimétrica del formato (`v2a`, Ed25519), no hay secreto
compartido: te da una clave pública, con la forma `whpk_…`, y el identificador que le asignó a tu
destino. Con eso podés verificar, pero no firmar.

```ts
import { standardPublicKeyScheme } from 'omniwebhook/standard';

const verifier = standardPublicKeyScheme({ publicKeys: [secreto], endpointId: 'ep_42' });
```

```python
from omniwebhook.standard import standard_public_key_scheme

verifier = standard_public_key_scheme(public_keys=[secreto], endpoint_id="ep_42")
```

En Python necesita `omniwebhook[ed25519]`. El identificador del destino es parte de lo que se
firma: tiene que ser el que te dio el emisor, nunca uno sacado del pedido. Para rotar, pasá la
clave nueva y la anterior. Un emisor que está migrando puede mandar la firma simétrica y la
asimétrica juntas; cada esquema mira sólo la suya.

Discord también firma con clave pública, la de tu aplicación, en hexadecimal:
`discordScheme({ publicKeys: [...] })` y `discord_scheme(public_keys=[...])`. En Python vive en
`omniwebhook.discord` y necesita el mismo extra.

### Varios emisores en la misma URL

Si una misma ruta recibe webhooks de más de un emisor, `routedVerifier` (`routed_verifier`) elige
el esquema por la cabecera que sólo ese emisor manda:

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

Un pedido sin ninguna de esas cabeceras es `missing`, y uno con más de una es `ambiguous`: nunca se
prueba un esquema después de otro, porque eso le dejaría elegir a quien manda el pedido con qué
reglas se lo verifica. Las claves de evento no se pisan entre emisores: cada una empieza con el
nombre de su esquema.

### Un emisor que no está en la lista

Si firma sólo el cuerpo con HMAC-SHA256 y manda la firma en una cabecera, alcanza con el esquema
genérico:

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

Si su formato es otro, mirá [cómo agregar un esquema](agregar-un-esquema.md).

### Mercado Pago: la firma no cubre el cuerpo

Mercado Pago firma el identificador del recurso, el identificador del pedido y la marca de tiempo,
pero no el cuerpo. Tratá el aviso como una señal de que algo cambió y consultá el recurso a su API
antes de actuar.

La clave del evento por defecto sale sólo de datos firmados. Si querés que distinga el tipo de
aviso, reemplazala:

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

## Almacenes de reservas

El almacén es lo que hace que un evento se procese una sola vez aunque el emisor lo mande dos veces
o lo reciban dos procesos a la vez.

| Almacén | Cuándo usarlo |
|---|---|
| Memoria | Tests y desarrollo. No sirve con más de un proceso |
| PostgreSQL | Producción. Cada operación es una sola sentencia |
| Redis | Producción, cuando no hay base relacional. Cada operación es un script; las entradas se borran solas |
| Clave-valor | DynamoDB, Workers KV o el que tengas. La garantía depende de si escribe con condición |
| SQLite | Producción con D1 de Cloudflare, libSQL o un solo servidor. Cada operación es una sola sentencia |
| Firestore (Python) | Producción. Cada operación es una transacción |

### PostgreSQL

La tabla se crea una vez, con el SQL que devuelve el paquete:

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

En TypeScript sirve cualquier cliente con un método `query(texto, parámetros)` que devuelva
`{ rows }`. En Python, `PsycopgClient` adapta un pool de psycopg 3; para otro cliente alcanza con un
objeto que tenga `query(texto, parámetros)`, con parámetros `%s`, y devuelva las filas.

Las entradas vencidas no molestan, pero ocupan lugar. `purgeExpired(now)` (`purge_expired(now)` en
Python) las borra; conviene correrlo cada tanto.

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

Con `ioredis` se usa `ioredisClient`. En Python también está `AsyncRedisIdempotencyStore`, para
`redis.asyncio`. El paquete no importa ningún cliente: recibe el tuyo.

No hay nada que purgar: lo completado se borra al vencer su retención. Una reserva cuyo plazo
venció se conserva un día más (`graceSeconds`, `grace_seconds`), para que quien se demoró pueda
completarla si nadie la tomó; después Redis la borra. Es la única diferencia con los otros
almacenes, que la conservan sin límite.

Las claves llevan el prefijo `omniwebhook:events:`, que se cambia con `prefix`.

### Clave-valor: DynamoDB, Workers KV o el tuyo

`KeyValueIdempotencyStore` funciona sobre cualquier almacén clave-valor con vencimiento. Lo que
cambia de uno a otro es el cliente.

```ts
import { dynamoDbClient, KeyValueIdempotencyStore, workersKvClient } from 'omniwebhook';

// DynamoDB: recibe el cliente de documentos del SDK
const enDynamo = new KeyValueIdempotencyStore(dynamoDbClient(db, { table: 'webhooks' }));

// Workers KV: recibe el binding
const enWorkersKv = new KeyValueIdempotencyStore(workersKvClient(env.EVENTOS));
```

```python
from omniwebhook.key_value import DynamoDbTableClient, KeyValueIdempotencyStore

en_dynamo = KeyValueIdempotencyStore(DynamoDbTableClient(db))  # el recurso de tabla de boto3
```

La tabla de DynamoDB tiene una clave de partición de texto, `pk` (se cambia con `keyAttribute`,
`key_attribute`), y ninguna de ordenamiento. Si activás el vencimiento de la tabla sobre el
atributo `ttl`, las entradas se borran solas. En Python también están
`AsyncKeyValueIdempotencyStore` y `AsyncDynamoDbTableClient`.

**La garantía no es la misma en todos**, y el almacén te la dice en `guarantee`:

- `atomic`, con DynamoDB: escribe sólo si nadie cambió la entrada desde que la leyó. Entre
  pedidos simultáneos por el mismo evento, uno solo lo procesa. Es la garantía de los otros
  almacenes.
- `best-effort`, con Workers KV: no tiene escritura condicional. Evita los duplicados que llegan
  separados en el tiempo, que son los reintentos del emisor, pero dos entregas simultáneas del
  mismo evento pueden procesarse las dos. Si en un Worker necesitás la garantía completa, usá D1.

Para otro almacén, implementá el cliente: son tres métodos.

```ts
import type { KeyValueClient } from 'omniwebhook';

const miCliente: KeyValueClient = {
  conditional: true, // si put y delete respetan onlyIf de forma atómica
  async get(key) {
    const fila = await db.leer(key);
    return fila === null ? null : { value: fila.valor, version: fila.version };
  },
  // Escribe sólo si la versión guardada es onlyIf; con null, sólo si la clave no existe.
  put: (key, value, { ttlSeconds, onlyIf }) => db.escribirSi(key, value, ttlSeconds, onlyIf),
  delete: (key, { onlyIf }) => db.borrarSi(key, onlyIf),
};
```

En Python es lo mismo, con `ttl_seconds` y `only_if`. `MemoryKeyValueClient` es la referencia de
lo que tiene que cumplir. Como en Redis, una reserva vencida se conserva un día más antes de que
el almacén la borre.

### SQLite y D1

Para SQLite (y para D1, que también es SQLite) el paquete trae su propia variante del SQL, con
parámetros `?` y las mismas columnas que la tabla de PostgreSQL.

En un Worker de Cloudflare, `d1Client` adapta el binding de D1. Conviene crear la tabla en una
migración de D1 con el SQL de `sqliteStoreSchema()`, copiado tal cual:

```ts
import { createReceiver, d1Client, SqliteIdempotencyStore } from 'omniwebhook';
import { standardScheme } from 'omniwebhook/standard';

const receive = createReceiver({
  verifier: standardScheme({ secrets: [env.WEBHOOK_SECRET] }),
  store: new SqliteIdempotencyStore(d1Client(env.DB)),
});
```

Con una base SQLite sincrónica (`node:sqlite`, `better-sqlite3` o `bun:sqlite`), `sqliteClient`
la adapta:

```ts
import { DatabaseSync } from 'node:sqlite';
import { SqliteIdempotencyStore, sqliteClient, sqliteStoreSchema } from 'omniwebhook';

const db = new DatabaseSync('webhooks.db');
db.exec(sqliteStoreSchema());
const store = new SqliteIdempotencyStore(sqliteClient(db));
```

En Python, `Sqlite3Client` adapta una conexión de `sqlite3`, de la biblioteca estándar. Confirma
cada sentencia y las ejecuta de a una, así que la misma conexión sirve para varios hilos si se abre
con `check_same_thread=False`:

```python
import sqlite3

from omniwebhook.sqlite import Sqlite3Client, SqliteIdempotencyStore, sqlite_store_schema

conexion = sqlite3.connect("webhooks.db", check_same_thread=False)
conexion.executescript(sqlite_store_schema())
store = SqliteIdempotencyStore(Sqlite3Client(conexion))
```

Para otro cliente, en los dos lenguajes alcanza con un objeto que ejecute una sentencia con
parámetros `?`, la confirme y devuelva las filas: `all(sql, parámetros)` en TypeScript y
`query(texto, parámetros)` en Python. En Python sólo hay variante sincrónica, porque `sqlite3` no es
asincrónico; desde código asincrónico se puede correr en un hilo con `asyncio.to_thread`.

Un archivo SQLite lo pueden compartir los dos paquetes: lo que reserva uno lo ve el otro.

### Firestore

```python
from omniwebhook.firestore import FirestoreIdempotencyStore

store = FirestoreIdempotencyStore(firestore.Client(), collection="omniwebhook_events")
```

Cada entrada guarda el campo `expire_time`. Con una política de TTL sobre ese campo, Firestore borra
solo lo vencido.

### Plazos

- **`leaseSeconds` / `lease_seconds`** (300 por defecto): cuánto dura una reserva. Si tu función
  tarda más que eso, otro proceso puede tomar el evento. Poné un plazo mayor que tu peor caso.
- **`retentionSeconds` / `retention_seconds`** (siete días por defecto): cuánto se recuerda un
  evento ya procesado. Tiene que cubrir la ventana en la que el emisor reintenta.

### Tamaño del cuerpo

- **`maxBodyBytes` / `max_body_bytes`** (1 MiB por defecto): un cuerpo más grande termina en
  `too_large`, con estado 413, antes de mirar la firma. Si tu emisor manda eventos más grandes,
  subilo.

Este límite evita calcular una firma sobre un cuerpo enorme, pero cuando llega al paquete el
cuerpo ya está en memoria. El límite que protege la memoria es el de tu servidor o tu framework:
configuralo igual o más bajo.

## Qué responder

`toResponse` y `to_response` arman la respuesta con el estado sugerido y sin cuerpo: la respuesta no
le dice a quien llama cuál de las comprobaciones falló. Si armás la respuesta a mano,
`httpStatusFor(outcome)` (`http_status_for(outcome)`) da el estado.

Cuatro casos que conviene entender:

- **`unprocessable` responde 422.** La firma era válida pero el payload no pasó tu validador.
  Reintentar no lo arregla; lo que conviene es registrar el motivo.
- **`too_large` responde 413.** No es un problema de origen sino de tamaño, y reintentar no lo
  arregla: la mayoría de los emisores deja de intentar ante un 4xx.
- **`duplicate` responde 200.** El evento ya se procesó; un error haría que el emisor siga
  reintentando.
- **`failed` responde 500 y libera la reserva.** El emisor reintenta y el reintento se procesa. El
  error de tu función viene adjunto en el resultado, para que lo registres.

```ts
const reception = await receive.execute(pedido, procesar);
if (reception.outcome === 'failed') logger.error(reception.error);
```

## Validar el payload

Una firma válida dice quién mandó el evento, no que tenga la forma que tu código espera. Con
`payload` le pasás un validador, y tu función recibe el payload ya validado en lugar de
interpretar el cuerpo a mano.

En TypeScript sirve tal cual el esquema de cualquier librería que implemente la interfaz común de
esquemas (la propiedad `~standard`), y el tipo del payload sale de ahí:

```ts
const receptorDePedidos = createReceiver({
  verifier: stripeScheme({ secrets: [secreto] }),
  store,
  payload: esquemaDePedido, // un esquema de la librería que uses
});

await receptorDePedidos.execute(pedido, async (event) => {
  await registrarPago(event.payload); // ya validado y con su tipo
});
```

En Python es cualquier función que reciba el cuerpo interpretado y devuelva el valor validado, o
lance si no sirve. El validador de una librería de modelos se pasa directo:

```python
receptor_de_pedidos = create_receiver(
    verifier=stripe_scheme(secrets=[secreto]),
    store=store,
    payload=Pedido.model_validate,
)

def procesar_pedido(event: VerifiedEvent) -> None:
    registrar_pago(event.payload)  # una instancia de Pedido
```

Un cuerpo que no es JSON, o que el validador rechaza, termina en `unprocessable`, con estado 422.
El resultado trae el motivo: `issues` en TypeScript y `error` en Python.

El validador corre después de verificar la firma, así que un cuerpo sin autenticar nunca se
interpreta, y antes de reservar el evento, así que un payload inválido no escribe nada en el
almacén. Si el emisor reintenta, el reintento vuelve a dar `unprocessable`.

## Medir lo que pasa

Con `observer`, cada recepción te informa su resultado, la clave del evento y cuánto tardó. Sirve
para contar rechazos por motivo o para alertar si suben los `failed`, sin tocar tu función:

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

El observador no recibe el cuerpo, las cabeceras ni ningún secreto, y no puede cambiar el
resultado: si lanza, el error se descarta. Para la emisión no hace falta: el registro de entregas
ya recibe cada intento.

## Probar tu integración

`omniwebhook/testing` (`omniwebhook.testing`) arma el pedido que mandaría cada emisor, firmado con
el secreto que le pases, para que tus tests recorran el camino real en lugar de saltear la
verificación:

```ts
import { stripeScheme } from 'omniwebhook';
import { signedRequest, tampered, toFetchRequest } from 'omniwebhook/testing';

const firmado = await signedRequest('stripe', { secret: secreto, body: '{"id":"evt_1"}' });

await stripeScheme({ secrets: [secreto] }).verify(firmado); // ok
await stripeScheme({ secrets: [secreto] }).verify(tampered(firmado)); // invalid

const viejo = await signedRequest('stripe', { secret: secreto, body: '{}', timestamp: 1 }); // stale
const paraLaRuta = toFetchRequest(firmado); // un Request, para llamar a tu ruta
```

```python
from omniwebhook.testing import signed_request, tampered

firmado = signed_request("stripe", secret=secreto, body='{"id":"evt_1"}')

stripe_scheme(secrets=[secreto]).verify(firmado)  # ok
stripe_scheme(secrets=[secreto]).verify(tampered(firmado))  # invalid
```

Para probar que un evento repetido no se procesa dos veces, mandá el mismo pedido firmado dos
veces. Sirve para todos los esquemas incluidos; con `hmac-body` recibe la misma configuración que
el esquema.

## Depurar desde la terminal

Los dos paquetes instalan el mismo comando, `omniwebhook`, para probar una integración sin escribir
código. Con npm se corre con `npx omniwebhook`; con Python, `omniwebhook` o `python -m omniwebhook`.

```bash
export FIRMA='el secreto del emisor'

# Mandar un evento firmado a tu servidor local
omniwebhook send --scheme stripe --secret-env FIRMA --body evento.json \
  --url http://localhost:3000/webhooks

# Ver el pedido que mandaría el emisor, y guardarlo
omniwebhook sign --scheme stripe --secret-env FIRMA --body evento.json > pedido.json

# Verificar un pedido guardado: dice el resultado y termina con 0 sólo si es ok
omniwebhook verify --scheme stripe --secret-env FIRMA --request pedido.json
```

El secreto se lee de una variable de entorno y nunca va como argumento, para que no quede en el
historial de la terminal. `--timestamp` firma con otra hora, para provocar un `stale`; `--body -` y
`--request -` leen de la entrada estándar. Sirve para los esquemas de secreto compartido; los de
clave pública no se pueden firmar desde acá.

Es una herramienta de desarrollo: `send` manda a la URL que le digas, sin la política de URLs de
destino que aplica la emisión.

## Sincrónico o asincrónico, en Python

Cada pieza que hace entrada/salida tiene las dos variantes. La asincrónica lleva el prefijo
`Async` o `async`:

| Sincrónico | Asincrónico |
|---|---|
| `create_receiver` | `create_async_receiver` |
| `MemoryIdempotencyStore` | `AsyncMemoryIdempotencyStore` |
| `PostgresIdempotencyStore` | `AsyncPostgresIdempotencyStore` |
| `FirestoreIdempotencyStore` | `AsyncFirestoreIdempotencyStore` |
| `SqliteIdempotencyStore` | No hay: `sqlite3` no es asincrónico |

Los esquemas de firma son los mismos en los dos casos: verificar es sólo cálculo.

En la variante asincrónica, si la tarea se cancela mientras tu función corre, la reserva se libera
antes de que la cancelación siga su camino.
