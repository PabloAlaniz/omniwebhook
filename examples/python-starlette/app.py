"""Un receptor asincrónico con Starlette. En FastAPI la función de la ruta es la misma."""

import json
import os

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from omniwebhook import AsyncMemoryIdempotencyStore, VerifiedEvent, create_async_receiver, stripe_scheme
from omniwebhook.starlette import to_incoming_request, to_response

receive = create_async_receiver(
    verifier=stripe_scheme(secrets=[os.environ.get("WEBHOOK_SECRET", "")]),
    # En memoria sólo sirve con un proceso. En producción, un almacén compartido.
    store=AsyncMemoryIdempotencyStore(),
)


async def process(event: VerifiedEvent) -> None:
    payload = json.loads(event.request.body)
    print(f"procesado {event.event_key} {payload['type']}", flush=True)


async def webhook(request: Request) -> Response:
    # Lee el cuerpo crudo: la firma se calcula sobre los bytes tal como llegaron.
    return to_response(await receive.execute(await to_incoming_request(request), process))


app = Starlette(routes=[Route("/webhooks", webhook, methods=["POST"])])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "3000")), log_level="warning")
