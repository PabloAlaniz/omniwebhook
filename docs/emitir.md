# Guía para emitir

Emitir un webhook es hacer **intentos**. Cada llamada al paquete hace uno:

1. **Firma** el mensaje con el formato [Standard Webhooks](https://www.standardwebhooks.com/).
2. **Valida el destino**: la forma de la URL y las direcciones a las que resuelve.
3. **Envía** el POST a la dirección que validó.
4. **Clasifica** lo que pasó y dice cuándo corresponde el próximo intento.
5. **Registra** el intento.

El paquete no programa el reintento. Devuelve `nextAt` (`next_at` en Python) y vos lo agendás en la
cola o el planificador que ya uses, llamando de nuevo con el número de intento siguiente.

## Un intento

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

Tres cosas a tener en cuenta:

- **El identificador del mensaje es el mismo en todos los intentos.** Es lo que le permite al
  receptor reconocer un reintento. Guardalo junto con el mensaje; no lo generes en cada intento.
- **El cuerpo va en bytes** y se envía tal cual se firmó. Serializalo una vez y guardá esos bytes.
- **Cada intento se firma de nuevo** con la hora actual, así que un reintento tardío no llega con
  una marca vieja.

## En qué estado queda la entrega

| Estado | Cuándo | Qué hacer |
|---|---|---|
| `delivered` | El destino respondió 2xx | Nada más |
| `pending` | Falló pero se puede reintentar | Agendar el próximo intento para `nextAt` |
| `exhausted` | Falló y no quedan intentos | Avisar; se puede reenviar a mano |
| `rejected` | El destino respondió algo que no se reintenta, incluidas las redirecciones | Revisar el destino |
| `gone` | El destino respondió 410 | Deshabilitar el destino |
| `blocked` | La política de URLs rechazó el destino | Revisar la URL; `problem` dice por qué |

Se reintenta ante 408, 409, 425, 429, cualquier 5xx, un error de red y un tiempo de espera agotado.

Reenviar a mano una entrega es llamar de nuevo desde el intento 1 con el mismo identificador de
mensaje.

## La política de reintentos

Es un dato: la lista de esperas, en segundos, entre un intento y el siguiente. Por defecto hay diez
intentos repartidos en algo más de tres días.

```ts
createNodeSender({ signer, ledger, retryPolicy: { schedule: [10, 60, 600, 3600], maxDelaySeconds: 3600 } });
```

```python
create_sender(signer=signer, ledger=ledger, retry_policy=RetryPolicy(schedule=[10, 60, 600, 3600]))
```

- Si el destino responde con `retry-after`, se espera lo que pide cuando es más que lo que tocaba,
  sin pasar del tope.
- A cada espera se le suma una variación al azar de hasta el 10 %, para que los reintentos de
  muchos mensajes no caigan todos juntos.

## La política de URLs de destino

Una URL de destino la escribe un tercero. Sin cuidado, alguien puede registrar una que apunte al
servicio de metadatos de tu nube o a un servicio interno. Antes de cada intento el paquete
comprueba:

- que la URL sea `https` (o `http`, sólo si lo permitís expresamente);
- que no traiga usuario ni contraseña;
- que tenga una forma estricta: sin barras invertidas, sin espacios ni caracteres de control, sin
  formas abreviadas de una dirección IP;
- que **ninguna** de las direcciones a las que resuelve el nombre esté en un rango privado, local o
  reservado.

Después se conecta a la dirección que validó y no vuelve a resolver el nombre. Las redirecciones no
se siguen.

Conviene revisar la URL también cuando el cliente la registra, para avisarle en el momento:

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

Esa revisión mira sólo la URL. La de las direcciones se hace en cada intento, porque un nombre
puede cambiar de dirección después de registrado.

Un nombre con caracteres fuera de ASCII tiene que venir en su forma ASCII (`xn--…`).

### Entregar a una red propia

Si el emisor corre en tu infraestructura y tiene que entregar a servicios de la misma red (otro
contenedor, una máquina de la red local, una VPN), podés permitir esas redes de forma explícita.
Una dirección de una red permitida se acepta aunque esté en un rango bloqueado:

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

- Cada red se escribe `dirección/prefijo`, con los bits fuera del prefijo en cero: `10.0.0.0/8`
  sí, `10.0.0.1/8` no. Una red mal escrita es un error de configuración al armar el emisor.
- Los servicios de metadatos de las nubes (`169.254.0.0/16`, `100.100.100.200`,
  `fd00:ec2::254`) no se permiten nunca, aunque una red de la lista los incluya.
- El resto de la política no cambia: forma estricta, sin credenciales, `https` salvo permiso
  expreso y conexión a la dirección validada.

Permití sólo lo que necesitás. Si los destinos los registran terceros, cualquier red de la lista
queda a su alcance.

### Qué transporte usar

| Transporte | Se conecta a la dirección validada |
|---|---|
| `createNodeSender` (`omniwebhook/node`) | Sí |
| `createSender` con la API Fetch | **No**: la API Fetch no deja elegir la dirección |
| `create_sender` y `create_async_sender` (Python) | Sí |
| `AsyncHttpxTransport` (`omniwebhook.httpx`) | Sí |

Con la API Fetch, entre la validación y la conexión el nombre podría resolver a otra dirección. Usá
ese transporte sólo donde no haya otro, y sabiendo que la protección es parcial.

### Sin DNS del sistema: Workers y funciones edge

`createSender` necesita un resolver para validar las direcciones. Donde no hay DNS del sistema
(Cloudflare Workers, Deno Deploy, funciones edge), `dohResolver` resuelve con DNS sobre HTTPS:

```ts
import { createSender, dohResolver } from 'omniwebhook';
import { standardSigner } from 'omniwebhook/standard';

const send = createSender({
  signer: standardSigner({ secrets: [secreto] }),
  ledger,
  resolver: dohResolver(),
});
```

Por defecto pregunta al servicio de Cloudflare; `endpoint` elige otro que hable el formato JSON,
como `https://dns.google/resolve`. Los nombres de los destinos viajan a ese servicio. Un nombre que
no existe deja el intento `blocked` con `unresolved`; si el servicio no responde, el intento cuenta
como un error de red y se reintenta.

La conexión sigue sin poder fijarse a la dirección validada, porque el transporte es la API Fetch.
En Cloudflare Workers conviene sumar la opción `global_fetch_strictly_public` en `wrangler.toml`,
que impide que `fetch` llegue a direcciones internas.

El tiempo de espera (`timeoutSeconds`, `timeout_seconds`; 20 segundos por defecto) es el plazo del
intento completo en todos los transportes: un servidor que responde de a un byte no lo estira.

## El registro de entregas

Cada intento se guarda en el registro, que es un puerto con un solo método. El paquete trae uno en
memoria, para tests, y uno sobre PostgreSQL y otro sobre SQLite, para producción. Las tablas son
las mismas en los dos paquetes: lo que registra uno lo lee el otro.

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

El SQL del esquema son varias sentencias (la tabla y dos índices): se corre sin parámetros. En
Python también está `AsyncPostgresDeliveryLedger`.

Sobre SQLite o D1 es igual, con `SqliteDeliveryLedger` y `sqliteLedgerSchema()`
(`sqlite_ledger_schema()` en Python). En un Worker de Cloudflare, el esquema va en una migración de
D1 y el registro usa el binding:

```ts
import { d1Client, SqliteDeliveryLedger } from 'omniwebhook';

const ledger = new SqliteDeliveryLedger(d1Client(db));
```

Un reenvío vuelve a empezar desde el intento 1, así que en la tabla puede haber dos filas con el
mismo número de intento; `attemptsOf` (`attempts_of`) las devuelve en el orden en que se
registraron. Los intentos viejos no se borran solos: `purgeBefore(at)` (`purge_before(at)`) borra
los que empezaron antes de `at`.

Para otra base, escribí tu propio registro:

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

El registro guarda el identificador con el que vos llamás al destino, nunca su URL: una URL de
webhook suele llevar un token y no tiene que terminar en un log.

## Rotar el secreto de firma

Con más de un secreto, cada mensaje sale con una firma por secreto. El receptor acepta cualquiera,
así que podés pasar del secreto viejo al nuevo sin coordinar el momento exacto:

```ts
standardSigner({ secrets: [nuevo, anterior] });
```

## Cabeceras propias

Podés agregar cabeceras a cada envío con `headers`. No pueden reemplazar las de la firma, la del
tipo de contenido, que se cambia con `contentType` (`content_type`), ni `user-agent`.

Cada envío se identifica con `user-agent: omniwebhook/<versión> (<lenguaje>)`. Quien recibe lo
puede usar para reconocer el tráfico en sus logs; para comprobar el origen está la firma.

## Tamaño del payload

Un payload de más de 256 KiB no se envía: `execute` lanza un error de configuración, como con un
`id` inválido. Se cambia con `maxPayloadBytes` (`max_payload_bytes`), pero conviene no hacerlo: un
webhook chico que dice qué pasó y dónde consultar el detalle le deja a quien recibe decidir qué
traer, y no depende del límite de tamaño de su servidor.

## La respuesta del destino

De la respuesta sólo se usan el estado y la cabecera `retry-after`. El cuerpo no se lee: un
destino no puede hacerte gastar memoria respondiendo con uno enorme.

## Qué le decís a quien recibe

Quien recibe puede verificar tus webhooks con cualquier implementación de Standard Webhooks, o con
este mismo paquete:

```ts
standardScheme({ secrets: [secretoCompartido] });
```
