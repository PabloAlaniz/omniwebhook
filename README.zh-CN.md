# omniwebhook

[![CI](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml/badge.svg)](https://github.com/PabloAlaniz/omniwebhook/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/PabloAlaniz/omniwebhook/badge)](https://scorecard.dev/viewer/?uri=github.com/PabloAlaniz/omniwebhook)

[English](README.en.md) · [Español](README.md) · 简体中文 · [Português (Brasil)](README.pt-BR.md)

带签名的 webhook：在任何技术栈上，都以同样的方式发送和接收。

> **尚未发布 1.0。** 两个包都已发布到 npm 和 PyPI，功能完整并覆盖了整份规范，但在 1.0 之前，
> API 仍可能在次版本之间发生变化。

> **关于本译文。** 本页是译文，如有出入，以[西班牙语原文](README.md)为准。使用指南、规范以及其余文档另有英文译本，
> 下方的链接指向英文版。

几乎每个产品最终都要接收支付服务商的 webhook，同时也要发出自己的 webhook。而这些逻辑几乎每次都要
重写一遍：每个服务商一套签名校验、一张防止重复处理的表、一段手写的重试。`omniwebhook` 把规则和
其余部分分开：

- **接收时使用同一套规则。** 校验签名、拒绝过期的请求、拒绝有歧义的请求，并且每个事件只处理一次；
  结果是带类型的返回值，而不是异常。
- **发送时使用开放格式。** 发出的消息按 [Standard Webhooks](https://www.standardwebhooks.com/)
  签名，重试策略以数据的形式定义，并且有一项策略禁止向内网地址投递。
- **任意服务商、任意数据库、任意 HTTP 客户端。** 核心对它们一无所知：它们都是端口（port），各自由
  一个适配器实现。
- **每种语言的行为完全一致。** 项目有一份[规范](spec/SPEC.en.md)和一组共享的一致性测试向量。
  TypeScript 包和 Python 包运行相同的用例，并且有互操作测试逐个请求地对比两者。

## 两条不可妥协的规则

1. **未经校验，绝不处理。** 如果没有配置密钥，请求会被拒绝：不存在跳过校验的模式。检查消息是否
   足够新，也是校验的一部分。
2. **每个事件只生效一次。** 事件在处理之前先被预留。如果处理失败，预留会被释放，这样发送方的重试
   才能成功。

## 接收

TypeScript，适用于任何支持 Fetch API 的运行环境：

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

Python，配合 FastAPI 或 Starlette：

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

只有在签名有效、消息足够新、并且此前没有被处理过的情况下，处理函数才会执行。其余情况都会得到一个
结果，并附带建议的 HTTP 状态码：

| 结果 | 状态码 | 含义 |
|---|---|---|
| `ok` | 200 | 已处理 |
| `duplicate` | 200 | 此前已经处理过 |
| `in_progress` | 409 | 另一个进程正在处理 |
| `missing`、`ambiguous`、`malformed`、`invalid`、`stale` | 401 | 无法确认来源 |
| `too_large` | 413 | 请求体超过最大长度 |
| `unprocessable` | 422 | 签名有效，但 payload 不符合预期的结构 |
| `unconfigured` | 500 | 缺少可用的密钥 |
| `failed` | 500 | 处理失败，预留已释放 |

更多内容见[接收指南](docs/en/recibir.md)（英文）。

## 发送

TypeScript，Node 环境：

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
// attempt.state：'delivered'、'pending'（附带 attempt.nextAt）、'rejected'、'blocked'、'gone' 或 'exhausted'
```

Python：

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
# attempt.state："delivered"、"pending"（附带 attempt.next_at）、"rejected"、"blocked"、"gone" 或 "exhausted"
```

每次调用就是一次投递尝试。包会告诉你下一次尝试应该在什么时候进行，但不负责调度：这部分交给你已经
在用的队列或调度器。如果不希望在进程崩溃时丢失事件，可以使用发件箱（outbox）：它保存待投递的消息，
并把它们分配给负责投递的各个进程。更多内容见[发送指南](docs/en/emitir.md)（英文）。

## 每个包包含什么

| | TypeScript | Python |
|---|---|---|
| 签名方案 | Standard Webhooks（共享密钥或公钥）、Stripe、Slack、Shopify、Discord、TikTok、Mercado Pago、GitHub、Creem、Google 通知渠道和 Pub/Sub，以及两个通用方案：请求体签名和共享令牌 | 相同 |
| 幂等存储 | 内存、PostgreSQL、Redis、SQLite（含 D1）、DynamoDB、Workers KV 或任意键值存储 | 内存、PostgreSQL、Redis、SQLite、Firestore、DynamoDB 或任意键值存储 |
| HTTP 传输 | Node 网络模块、Fetch API | 标准库、httpx（异步） |
| 投递记录 | 内存、PostgreSQL、SQLite（含 D1） | 内存、PostgreSQL、SQLite |
| 发件箱 | 内存、PostgreSQL | 内存、PostgreSQL |
| 入口 | Fetch API（`Request` 与 `Response`）、`node:http` 以及构建在其上的框架 | ASGI、Starlette 与 FastAPI、WSGI、Django，或任意框架 |
| 风格 | 异步 | 同步与异步 |
| 必需依赖 | 无 | 无 |

两个包的 PostgreSQL 存储使用同一张表：一种语言的服务处理过的事件，另一种语言的服务会把它识别为
重复。Redis 存储同样共享预留：两边运行的是相同的脚本。投递记录和发件箱也是如此，SQLite 亦然。

## 安装

```bash
npm install omniwebhook                   # TypeScript
npm install standardwebhooks              # 仅 omniwebhook/standard 需要

pip install omniwebhook                   # Python
pip install "omniwebhook[standard]"       # 附带 Standard Webhooks 参考库
```

Python 的其他可选依赖（`httpx`、`starlette`、`django`、`postgres`、`firestore`、`ed25519`、
`otel`）见[包的 README](python/README.en.md)（英文）。

## 文档

以下文档为英文；西班牙语原文位于相同的目录中。

| | |
|---|---|
| [接收指南](docs/en/recibir.md) | 签名方案、存储、事件键和响应 |
| [发送指南](docs/en/emitir.md) | 签名、URL 策略、重试、发件箱和端点健康状况 |
| [遥测](docs/en/telemetria.md) | 基于 OpenTelemetry 的指标和链路追踪 |
| [示例](examples/README.en.md) | 最小化的接收端和一个发件箱示例，均在 CI 中测试 |
| [如何添加签名方案](docs/en/agregar-un-esquema.md) | 从规范到适配器 |
| [规范](spec/SPEC.en.md) | 所有包共同遵循的行为 |
| [架构决策](docs/en/adr/README.md) | 为什么这样设计 |
| [如何发布版本](docs/en/publicar.md) | 发布流程与可信发布 |
| [兼容性](docs/en/compatibilidad.md) | 哪些是稳定的、支持哪些运行环境、变更如何通知 |
| [路线图](docs/en/roadmap.md) | 已完成和尚未完成的内容 |
| [1.0 标准](docs/en/criterios-1.0.md) | 冻结 API 之前必须满足的条件 |

## 仓库结构

| 目录 | 内容 |
|---|---|
| [`spec/`](spec/) | 规范和一致性测试向量 |
| [`ts/`](ts/) | TypeScript 包（npm） |
| [`python/`](python/) | Python 包（PyPI） |
| [`tools/`](tools/) | 测试向量生成器和互操作测试 |
| [`examples/`](examples/) | 每种运行环境一个最小化的接收端，均在 CI 中测试 |
| [`docs/`](docs/) | 使用指南和架构决策 |

## 参与贡献

请参阅 [CONTRIBUTING](CONTRIBUTING.en.md) 和[行为准则](CODE_OF_CONDUCT.en.md)（均为英文）。
报告安全问题请参阅 [SECURITY](SECURITY.en.md)。

## 许可证

[MIT](LICENSE)
