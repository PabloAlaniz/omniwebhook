# omniwebhook

[![CI](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml/badge.svg)](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/PabloAlaniz/omniwebhook/badge)](https://scorecard.dev/viewer/?uri=github.com/PabloAlaniz/omniwebhook)

[English](README.en.md) · [Español](README.md) · [简体中文](README.zh-CN.md) · Português (Brasil)

Webhooks assinados, enviados e recebidos do mesmo jeito em qualquer stack.

> **Antes da 1.0.** Os dois pacotes estão publicados no npm e no PyPI, completos e cobrindo toda a
> especificação, mas a API ainda pode mudar entre versões menores.

> **Sobre esta tradução.** Esta página é uma tradução; em caso de divergência, vale o
> [original em espanhol](README.md). Os guias e a especificação também têm tradução
> para o inglês, assim como o restante da documentação, e os links abaixo levam a ela.

Quase todo produto acaba recebendo webhooks de um provedor de pagamentos e enviando os seus. E quase
sempre isso é escrito de novo: uma verificação de assinatura por provedor, uma tabela para não
processar duas vezes, uma retentativa feita à mão. O `omniwebhook` separa as regras de todo o
resto:

- **As mesmas regras para receber.** Verificar a assinatura, rejeitar o que é antigo, rejeitar o
  que é ambíguo e processar cada evento uma única vez, com um resultado tipado em vez de exceções.
- **Um formato aberto para enviar.** O que sai é assinado com
  [Standard Webhooks](https://www.standardwebhooks.com/), com retentativas definidas como dados e
  uma política que impede a entrega em endereços internos.
- **Qualquer provedor, qualquer banco, qualquer cliente HTTP.** O núcleo não conhece nenhum deles:
  são portas, e cada uma é resolvida por um adaptador.
- **O mesmo comportamento em cada linguagem.** Existe uma [especificação](spec/SPEC.en.md) e vetores
  de conformidade compartilhados. O pacote de TypeScript e o de Python executam os mesmos casos, e
  um teste de interoperabilidade compara os dois requisição por requisição.

## As duas regras que não se negociam

1. **Nada é processado sem ser verificado.** Se o segredo estiver faltando, a requisição é
   rejeitada: não existe um modo que pule a verificação. Conferir que a mensagem é recente faz
   parte de verificar.
2. **Cada evento produz efeito uma única vez.** O evento é reservado antes de ser processado. Se o
   processamento falhar, a reserva é liberada para que a retentativa do emissor funcione.

## Receber

TypeScript, em qualquer ambiente com a Fetch API:

```ts
import { createReceiver, PostgresIdempotencyStore, stripeScheme, toIncomingRequest, toResponse } from 'omniwebhook';

const receive = createReceiver({
  verifier: stripeScheme({ secrets: [process.env.STRIPE_WEBHOOK_SECRET ?? ''] }),
  store: new PostgresIdempotencyStore(pool),
});

export async function POST(request: Request): Promise<Response> {
  const reception = await receive.execute(await toIncomingRequest(request), async (event) => {
    await recordPayment(JSON.parse(new TextDecoder().decode(event.request.body)));
  });
  return toResponse(reception);
}
```

Python, com FastAPI ou Starlette:

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
    async def process(event: VerifiedEvent) -> None:
        await record_payment(json.loads(event.request.body))

    return to_response(await receive.execute(await to_incoming_request(request), process))
```

A função que processa o evento só é executada se a assinatura for válida, a mensagem for recente e
ninguém a tiver processado antes. Todo o resto termina em um resultado com o status HTTP sugerido:

| Resultado | Status | O que aconteceu |
|---|---|---|
| `ok` | 200 | Foi processado |
| `duplicate` | 200 | Já tinha sido processado |
| `in_progress` | 409 | Outro processo está processando |
| `missing`, `ambiguous`, `malformed`, `invalid`, `stale` | 401 | Não foi possível comprovar a origem |
| `too_large` | 413 | O corpo ultrapassa o tamanho máximo |
| `unprocessable` | 422 | A assinatura é válida, mas o payload não tem o formato esperado |
| `unconfigured` | 500 | Falta um segredo utilizável |
| `failed` | 500 | O processamento falhou e a reserva foi liberada |

Mais no [guia para receber](docs/en/recibir.md) (em inglês).

## Enviar

TypeScript, no Node:

```ts
import { MemoryDeliveryLedger, randomMessageId } from 'omniwebhook';
import { createNodeSender } from 'omniwebhook/node';
import { standardSigner } from 'omniwebhook/standard';

const send = createNodeSender({
  signer: standardSigner({ secrets: [process.env.WEBHOOK_SIGNING_SECRET ?? ''] }),
  ledger: new MemoryDeliveryLedger(),
});

const attempt = await send.execute({
  endpoint: { id: 'ep_42', url: 'https://customer.example/webhooks' },
  message: { id: randomMessageId(), payload: new TextEncoder().encode('{"type":"order.created"}') },
  attempt: 1,
});
// attempt.state: 'delivered', 'pending' (com attempt.nextAt), 'rejected', 'blocked', 'gone' ou 'exhausted'
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
        endpoint=Endpoint(id="ep_42", url="https://customer.example/webhooks"),
        message_id=random_message_id(),
        payload=b'{"type":"order.created"}',
    )
)
# attempt.state: "delivered", "pending" (com attempt.next_at), "rejected", "blocked", "gone" ou "exhausted"
```

Cada chamada é uma tentativa. O pacote diz quando cabe a próxima, mas não a agenda: isso fica com a
fila ou o agendador que você já usa. Se você não quer perder um evento quando o processo cai, a
caixa de saída (outbox) guarda as entregas pendentes e as distribui entre os processos que
despacham. Mais no [guia para enviar](docs/en/emitir.md) (em inglês).

## O que cada pacote traz

| | TypeScript | Python |
|---|---|---|
| Esquemas de assinatura | Standard Webhooks (segredo compartilhado ou chave pública), Stripe, Slack, Shopify, Discord, TikTok, Mercado Pago, GitHub, Creem, os canais do Google e Pub/Sub, e dois genéricos: corpo assinado e token compartilhado | Os mesmos |
| Armazenamento de reservas | Memória, PostgreSQL, Redis, SQLite (também D1), DynamoDB, Workers KV ou qualquer chave-valor | Memória, PostgreSQL, Redis, SQLite, Firestore, DynamoDB ou qualquer chave-valor |
| Transporte HTTP | Módulos de rede do Node, Fetch API | Biblioteca padrão, httpx (assíncrono) |
| Registro de entregas | Memória, PostgreSQL, SQLite (também D1) | Memória, PostgreSQL, SQLite |
| Caixa de saída | Memória, PostgreSQL | Memória, PostgreSQL |
| Entrada | Fetch API (`Request` e `Response`), `node:http` e o que é montado sobre ele | ASGI, Starlette e FastAPI, WSGI, Django, ou qualquer framework |
| Estilo | Assíncrono | Síncrono e assíncrono |
| Dependências obrigatórias | Nenhuma | Nenhuma |

Os armazenamentos de PostgreSQL dos dois pacotes usam a mesma tabela: um evento processado por um
serviço em uma linguagem é reconhecido como duplicado pelo outro. Os de Redis também compartilham
as reservas: executam os mesmos scripts. O mesmo vale para o registro de entregas e a caixa de
saída, e para o SQLite.

## Instalação

```bash
npm install omniwebhook                   # TypeScript
npm install standardwebhooks              # só para omniwebhook/standard

pip install omniwebhook                   # Python
pip install "omniwebhook[standard]"       # com a biblioteca de referência do Standard Webhooks
```

Os demais extras de Python (`httpx`, `starlette`, `django`, `postgres`, `firestore`, `ed25519`,
`otel`) estão descritos no [README do pacote](python/README.en.md) (em inglês).

## Documentação

Os documentos abaixo estão em inglês; os originais em espanhol ficam nas mesmas pastas.

| | |
|---|---|
| [Guia para receber](docs/en/recibir.md) | Esquemas, armazenamentos, chaves de evento e respostas |
| [Guia para enviar](docs/en/emitir.md) | Assinatura, política de URLs, retentativas, caixa de saída e saúde dos destinos |
| [Telemetria](docs/en/telemetria.md) | Métricas e traces com OpenTelemetry |
| [Exemplos](examples/README.en.md) | Receptores mínimos e uma caixa de saída, testados na integração contínua |
| [Como adicionar um esquema de assinatura](docs/en/agregar-un-esquema.md) | Da especificação ao adaptador |
| [Especificação](spec/SPEC.en.md) | O comportamento que todos os pacotes compartilham |
| [Decisões de arquitetura](docs/en/adr/README.md) | Por que foi feito assim |
| [Como uma versão é publicada](docs/en/publicar.md) | O fluxo de versões e a publicação confiável |
| [Compatibilidade](docs/en/compatibilidad.md) | O que é estável, quais ambientes são suportados e como uma mudança é avisada |
| [Roadmap](docs/en/roadmap.md) | O que está feito e o que falta |
| [Critérios da 1.0](docs/en/criterios-1.0.md) | O que precisa acontecer para congelar a API |

## Estrutura do repositório

| Pasta | O que tem |
|---|---|
| [`spec/`](spec/) | A especificação e os vetores de conformidade |
| [`ts/`](ts/) | O pacote de TypeScript (npm) |
| [`python/`](python/) | O pacote de Python (PyPI) |
| [`tools/`](tools/) | O gerador de vetores e o teste de interoperabilidade |
| [`examples/`](examples/) | Um receptor mínimo por ambiente, testado na integração contínua |
| [`docs/`](docs/) | Os guias e as decisões de arquitetura |

## Contribuir

Veja o [CONTRIBUTING](CONTRIBUTING.en.md) e o [código de conduta](CODE_OF_CONDUCT.en.md), ambos em
inglês. Para reportar um problema de segurança, veja o [SECURITY](SECURITY.en.md).

## Licença

[MIT](LICENSE)
