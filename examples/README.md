# Ejemplos

Un receptor mínimo por entorno. Todos hacen lo mismo: reciben webhooks con el formato de Stripe en
`/webhooks`, verifican la firma, procesan cada evento una sola vez y responden con el estado
sugerido. Cambiar de emisor es cambiar una línea: el esquema.

| Carpeta | Entorno | Cómo se corre |
|---|---|---|
| [`node-http/`](node-http/) | `node:http`, sin framework | `node examples/node-http/server.mjs` |
| [`python-wsgi/`](python-wsgi/) | WSGI, con el servidor de la biblioteca estándar | `python examples/python-wsgi/app.py` |
| [`python-starlette/`](python-starlette/) | Starlette (igual en FastAPI), asincrónico | `python examples/python-starlette/app.py` |
| [`python-django/`](python-django/) | Django, en un solo archivo | `python examples/python-django/app.py` |

Cada uno lee dos variables de entorno: `WEBHOOK_SECRET`, el secreto del emisor, y `PORT`.

Para probar uno a mano, con la [línea de comandos](../docs/recibir.md#depurar-desde-la-terminal):

```bash
export WEBHOOK_SECRET='un-secreto-de-prueba'
PORT=3000 node examples/node-http/server.mjs &

echo '{"id":"evt_1","type":"invoice.paid"}' > evento.json
omniwebhook send --scheme stripe --secret-env WEBHOOK_SECRET --body evento.json \
  --url http://localhost:3000/webhooks
```

Usan el almacén en memoria para no depender de nada. En producción va uno compartido entre
procesos: PostgreSQL, Redis, SQLite o Firestore.

`python3 tools/check_examples.py` levanta cada ejemplo y le manda un evento firmado, el mismo
evento repetido y uno con otro secreto. La integración continua lo corre en cada cambio.
