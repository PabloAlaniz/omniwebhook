# Telemetría

Con [OpenTelemetry](https://opentelemetry.io/) se puede ver cuántos webhooks se reciben y con qué
resultado, cuántos intentos de entrega fallan y por qué, y seguir una entrega como parte de la
operación que la originó. Son tres piezas opcionales, que se enchufan en puntos que ya existen.

En TypeScript viven en `omniwebhook/otel` y necesitan `@opentelemetry/api`. En Python, en
`omniwebhook.otel`, con `omniwebhook[otel]`. Reciben tu `Meter` y tu `Tracer`: configurar a dónde
se exporta sigue siendo tuyo.

## Recibir: métricas por resultado

```ts
import { createReceiver, stripeScheme } from 'omniwebhook';
import { otelReceptionObserver } from 'omniwebhook/otel';

const receptor = createReceiver({
  verifier: stripeScheme({ secrets: [secreto] }),
  store,
  observer: otelReceptionObserver({ meter }),
});
```

```python
from omniwebhook.otel import OtelReceptionObserver

receptor = create_receiver(
    verifier=stripe_scheme(secrets=[secreto]), store=store, observer=OtelReceptionObserver(meter=meter)
)
```

| Métrica | Tipo | Unidad | Atributos |
|---|---|---|---|
| `omniwebhook.receptions` | Contador | `{reception}` | `omniwebhook.reception.outcome` |
| `omniwebhook.reception.duration` | Histograma | `s` | `omniwebhook.reception.outcome` |

Sirve para alertar si suben los `invalid` (alguien probando firmas, o un secreto mal rotado), los
`failed` (tu función está fallando) o los `stale` (un reloj corrido).

## Emitir: métricas por intento

El registro de entregas ya recibe cada intento. Se lo envuelve:

```ts
import { otelDeliveryLedger } from 'omniwebhook/otel';

const registro = otelDeliveryLedger(ledger, { meter });
```

```python
from omniwebhook.otel import OtelDeliveryLedger

registro = OtelDeliveryLedger(ledger, meter=meter)
```

Guarda el intento en el registro de adentro y, si eso salió bien, lo cuenta. Va donde iba el
registro: en `ledger`, y también en `health`, porque sigue dando el resumen de fallos.

| Métrica | Tipo | Unidad | Atributos |
|---|---|---|---|
| `omniwebhook.delivery.attempts` | Contador | `{attempt}` | `omniwebhook.delivery.class`, `omniwebhook.delivery.state`, `http.response.status_code` |
| `omniwebhook.delivery.attempt.duration` | Histograma | `s` | Los mismos |

Las entregas agotadas son los intentos con `omniwebhook.delivery.state` igual a `exhausted`.

## Emitir: un tramo por intento

```ts
import { createNodeSender, nodeTransport } from 'omniwebhook/node';
import { otelTransport } from 'omniwebhook/otel';

const envio = createNodeSender({
  signer,
  ledger,
  transport: otelTransport(nodeTransport(), { tracer }),
});
```

```python
from omniwebhook import HttpClientTransport
from omniwebhook.otel import OtelTransport

envio = create_sender(signer=signer, ledger=ledger, transport=OtelTransport(HttpClientTransport(), tracer=tracer))
```

Cada intento es un tramo de cliente HTTP, con los nombres de las convenciones semánticas:

| Atributo | Contenido |
|---|---|
| `http.request.method` | `POST` |
| `server.address`, `server.port`, `url.scheme` | El host, el puerto y el esquema del destino |
| `http.response.status_code` | El estado, si hubo respuesta |
| `error.type` | El estado si es 400 o más, o `timeout` o `network` si no hubo respuesta |
| `omniwebhook.message.id` | El identificador del mensaje |

El pedido sale además con la cabecera `traceparent`. Si quien recibe también usa OpenTelemetry,
ve la entrega como continuación de la operación que la originó. Esa cabecera no está firmada.

## Lo que nunca sale

- **La URL completa del destino.** Suele llevar un token en la ruta o en la consulta: del destino
  sólo van el host, el puerto y el esquema.
- **El cuerpo, la firma y los secretos.**
- **La clave del evento, el destino y el mensaje como atributos de una métrica.** Hay uno distinto
  por evento o por cliente, y una métrica así no se puede agregar. El identificador del mensaje
  va en el tramo, que es donde sirve para buscar.

Los nombres de las métricas y de los atributos son los mismos en los dos paquetes: un panel o una
alerta sirve para un servicio en cualquiera de los dos lenguajes. En Python, los que hacen
entrada/salida tienen su variante asincrónica: `AsyncOtelDeliveryLedger` y `AsyncOtelTransport`.
