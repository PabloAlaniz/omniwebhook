"""Un receptor WSGI, con el servidor de la biblioteca estándar. En Flask es igual."""

import json
import os
from collections.abc import Callable, Iterable
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

from omniwebhook import (
    MemoryIdempotencyStore,
    VerifiedEvent,
    create_receiver,
    incoming_request_from_environ,
    stripe_scheme,
    wsgi_response,
)

receive = create_receiver(
    verifier=stripe_scheme(secrets=[os.environ.get("WEBHOOK_SECRET", "")]),
    # En memoria sólo sirve con un proceso. En producción, un almacén compartido.
    store=MemoryIdempotencyStore(),
)


def process(event: VerifiedEvent) -> None:
    payload = json.loads(event.request.body)
    print(f"procesado {event.event_key} {payload['type']}", flush=True)


def application(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
    if environ["REQUEST_METHOD"] != "POST" or not environ["PATH_INFO"].startswith("/webhooks"):
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]
    # Lee el cuerpo crudo: la firma se calcula sobre los bytes tal como llegaron.
    return wsgi_response(receive.execute(incoming_request_from_environ(environ), process), start_response)


class _Silent(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


if __name__ == "__main__":
    make_server(
        "127.0.0.1", int(os.environ.get("PORT", "3000")), application, handler_class=_Silent
    ).serve_forever()
