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
- **Starlette y FastAPI**: `await to_incoming_request(request)`.
- **Otro framework de Python**: `incoming_request(headers=..., query=..., body=...)`, con el cuerpo en
  bytes.

```python
# Flask
from omniwebhook import incoming_request

pedido = incoming_request(
    headers=request.headers.items(),
    query=request.query_string.decode(),
    body=request.get_data(),
)
```

Pasar las cabeceras como pares, y no como diccionario, permite detectar una cabecera repetida. La
API Fetch une con comas las cabeceras repetidas, así que ahí una cabecera repetida no se informa
como `ambiguous`: simplemente la firma no coincide.

## Esquemas de firma

| Emisor | TypeScript | Python | Marca de tiempo | Clave del evento |
|---|---|---|---|---|
| Standard Webhooks | `standardScheme` | `standard_scheme` | Sí | `webhook-id` |
| Stripe | `stripeScheme` | `stripe_scheme` | Sí | `id` del cuerpo |
| TikTok | `tiktokScheme` | `tiktok_scheme` | Sí | La huella del cuerpo |
| Mercado Pago | `mercadoPagoScheme` | `mercadopago_scheme` | Sí | `data.id` y `x-request-id` |
| GitHub | `githubScheme` | `github_scheme` | No | `x-github-delivery` |
| Creem | `creemScheme` | `creem_scheme` | No | `id` del cuerpo |
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

## Qué responder

`toResponse` y `to_response` arman la respuesta con el estado sugerido y sin cuerpo: la respuesta no
le dice a quien llama cuál de las comprobaciones falló. Si armás la respuesta a mano,
`httpStatusFor(outcome)` (`http_status_for(outcome)`) da el estado.

Dos casos que conviene entender:

- **`duplicate` responde 200.** El evento ya se procesó; un error haría que el emisor siga
  reintentando.
- **`failed` responde 500 y libera la reserva.** El emisor reintenta y el reintento se procesa. El
  error de tu función viene adjunto en el resultado, para que lo registres.

```ts
const reception = await receive.execute(pedido, procesar);
if (reception.outcome === 'failed') logger.error(reception.error);
```

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
