# Telemetry

> **Translation.** This is a translation of the [Spanish original](../telemetria.md). If the two disagree, the Spanish text wins.

With [OpenTelemetry](https://opentelemetry.io/) you can see how many webhooks are received and with
what outcome, how many delivery attempts fail and why, and follow a delivery as part of the
operation that caused it. There are three optional pieces, which plug into points that already exist.

In TypeScript they live in `omniwebhook/otel` and need `@opentelemetry/api`. In Python, in
`omniwebhook.otel`, with `omniwebhook[otel]`. They take your `Meter` and your `Tracer`: configuring
where it is exported to is still up to you.

## Receiving: metrics by outcome

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

| Metric | Type | Unit | Attributes |
|---|---|---|---|
| `omniwebhook.receptions` | Counter | `{reception}` | `omniwebhook.reception.outcome` |
| `omniwebhook.reception.duration` | Histogram | `s` | `omniwebhook.reception.outcome` |

It is useful for alerting when there is a rise in `invalid` (someone trying out signatures, or a
badly rotated secret), in `failed` (your function is failing) or in `stale` (a clock that is off).

## Sending: metrics by attempt

The delivery ledger already receives every attempt. You wrap it:

```ts
import { otelDeliveryLedger } from 'omniwebhook/otel';

const registro = otelDeliveryLedger(ledger, { meter });
```

```python
from omniwebhook.otel import OtelDeliveryLedger

registro = OtelDeliveryLedger(ledger, meter=meter)
```

It stores the attempt in the inner ledger and, if that went well, counts it. It goes where the
ledger went: in `ledger`, and also in `health`, because it still provides the failure summary.

| Metric | Type | Unit | Attributes |
|---|---|---|---|
| `omniwebhook.delivery.attempts` | Counter | `{attempt}` | `omniwebhook.delivery.class`, `omniwebhook.delivery.state`, `http.response.status_code` |
| `omniwebhook.delivery.attempt.duration` | Histogram | `s` | The same ones |

Exhausted deliveries are the attempts with `omniwebhook.delivery.state` equal to `exhausted`.

## Sending: one span per attempt

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

Each attempt is an HTTP client span, with the names from the semantic conventions:

| Attribute | Content |
|---|---|
| `http.request.method` | `POST` |
| `server.address`, `server.port`, `url.scheme` | The host, the port and the scheme of the endpoint |
| `http.response.status_code` | The status, if there was a response |
| `error.type` | The status if it is 400 or more, or `timeout` or `network` if there was no response |
| `omniwebhook.message.id` | The message identifier |

The request also goes out with the `traceparent` header. If the receiver uses OpenTelemetry too,
it sees the delivery as a continuation of the operation that caused it. That header is not signed.

## What never goes out

- **The full URL of the endpoint.** It usually carries a token in the path or in the query: of the
  endpoint, only the host, the port and the scheme are included.
- **The body, the signature and the secrets.**
- **The event key, the endpoint and the message as attributes of a metric.** There is a different
  one per event or per customer, and a metric like that cannot be aggregated. The message identifier
  goes in the span, which is where it is useful for searching.

The names of the metrics and of the attributes are the same in both packages: a dashboard or an
alert works for a service in either of the two languages. In Python, the ones that do
input/output have an asynchronous variant: `AsyncOtelDeliveryLedger` and `AsyncOtelTransport`.
