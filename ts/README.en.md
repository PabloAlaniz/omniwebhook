# omniwebhook

> **Translation.** This is a translation of the [Spanish original](README.md). If the two disagree, the Spanish text wins.

Signed webhooks that are sent and received the same way in any stack: verification, freshness,
idempotency and retries with the same rules in TypeScript and in Python.

- **Receive**: verifies the signature, rejects what is stale and what is ambiguous, and processes
  each event only once. It returns a typed result instead of throwing.
- **Send**: signs with [Standard Webhooks](https://www.standardwebhooks.com/), does not deliver to
  internal addresses and tells you when to retry.
- **No required dependencies.** It uses Web Crypto, so it runs on Node 22 or later and in edge
  environments.

```bash
npm install omniwebhook
```

## Receive

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

Included schemes: `stripeScheme`, `tiktokScheme`, `mercadoPagoScheme`, `githubScheme`, `creemScheme`,
`slackScheme`, `shopifyScheme`, `discordScheme`, `hmacBodyScheme` and, in `omniwebhook/standard`, `standardScheme`.

## Send

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

## Package entry points

| Entry point | What it provides | Requires |
|---|---|---|
| `omniwebhook` | Receiving, sending, schemes, stores and the transport over the Fetch API | Nothing |
| `omniwebhook/standard` | The Standard Webhooks format: verifying and signing | `npm install standardwebhooks` |
| `omniwebhook/node` | The transport that connects to the validated address, and name resolution | Node |

To send from Node, use `omniwebhook/node`: the transport over the Fetch API cannot choose which
address to connect to, so its protection against internal destinations is partial.

## Documentation

- [Receiving guide](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/en/recibir.md)
- [Sending guide](https://github.com/PabloAlaniz/omniwebhook/blob/main/docs/en/emitir.md)
- [Specification](https://github.com/PabloAlaniz/omniwebhook/blob/main/spec/SPEC.en.md)
- [Repository](https://github.com/PabloAlaniz/omniwebhook#readme)

## License

MIT
