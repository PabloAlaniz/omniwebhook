# Examples

> **Translation.** This is a translation of the [Spanish original](README.md). If the two disagree, the Spanish text wins.

A minimal receiver per environment. They all do the same thing: they receive webhooks in Stripe's
format at `/webhooks`, verify the signature, process each event only once and respond with the
suggested status. Changing sender means changing one line: the scheme.

| Folder | Environment | How to run it |
|---|---|---|
| [`node-http/`](node-http/) | `node:http`, no framework | `node examples/node-http/server.mjs` |
| [`python-wsgi/`](python-wsgi/) | WSGI, with the standard library server | `python examples/python-wsgi/app.py` |
| [`python-starlette/`](python-starlette/) | Starlette (the same in FastAPI), asynchronous | `python examples/python-starlette/app.py` |
| [`python-django/`](python-django/) | Django, in a single file | `python examples/python-django/app.py` |

And one for sending: [`python-outbox/`](python-outbox/) records an order and enqueues its webhook
in the same transaction, and then dispatches a batch. It needs a PostgreSQL at `OMNIWEBHOOK_PG_URL`.

Each receiver reads two environment variables: `WEBHOOK_SECRET`, the sender's secret, and `PORT`.

To try one by hand, with the [command line](../docs/en/recibir.md#debugging-from-the-terminal):

```bash
export WEBHOOK_SECRET='un-secreto-de-prueba'
PORT=3000 node examples/node-http/server.mjs &

echo '{"id":"evt_1","type":"invoice.paid"}' > evento.json
omniwebhook send --scheme stripe --secret-env WEBHOOK_SECRET --body evento.json \
  --url http://localhost:3000/webhooks
```

They use the in-memory store so as not to depend on anything. In production you use one shared
between processes: PostgreSQL, Redis, SQLite or Firestore.

`python3 tools/check_examples.py` starts each example and sends it a signed event, the same event
again and one with a different secret. With `OMNIWEBHOOK_PG_URL`, it also runs the outbox one
against a local receiver. Continuous integration runs it on every change.
