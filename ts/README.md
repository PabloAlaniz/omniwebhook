# omniwebhook

Webhooks firmados que se emiten y se reciben igual en cualquier stack: verificación, frescura,
idempotencia y reintentos con las mismas reglas en TypeScript y en Python.

- **Recibir**: verifica la firma, rechaza lo viejo y lo ambiguo, y procesa cada evento una sola
  vez. Devuelve un resultado tipado en vez de lanzar.
- **Emitir**: firma con [Standard Webhooks](https://www.standardwebhooks.com/), no entrega a
  direcciones internas y dice cuándo reintentar.
- **Sin dependencias obligatorias.** Usa Web Crypto, así que corre en Node 22 o superior y en
  entornos edge.

```bash
npm install omniwebhook
```

## Recibir

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

Esquemas incluidos: `stripeScheme`, `tiktokScheme`, `mercadoPagoScheme`, `githubScheme`, `creemScheme`,
`slackScheme`, `shopifyScheme`, `hmacBodyScheme` y, en `omniwebhook/standard`, `standardScheme`.

## Emitir

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
```

## Entradas del paquete

| Entrada | Qué trae | Necesita |
|---|---|---|
| `omniwebhook` | Recepción, emisión, esquemas, almacenes y el transporte sobre la API Fetch | Nada |
| `omniwebhook/standard` | El formato Standard Webhooks: verificar y firmar | `npm install standardwebhooks` |
| `omniwebhook/node` | El transporte que se conecta a la dirección validada y la resolución de nombres | Node |

Para emitir desde Node usá `omniwebhook/node`: el transporte sobre la API Fetch no puede elegir a
qué dirección conectarse, así que su protección contra destinos internos es parcial.

## Documentación

- [Guía para recibir](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/recibir.md)
- [Guía para emitir](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/emitir.md)
- [Especificación](https://github.com/PabloAlaniz/omniwebhook/blob/main/spec/SPEC.md)
- [Repositorio](https://github.com/PabloAlaniz/omniwebhook#readme)

## Licencia

MIT
