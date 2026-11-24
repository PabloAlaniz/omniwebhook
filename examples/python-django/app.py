"""Un receptor con Django, en un solo archivo. En un proyecto real, `webhook` va en `views.py`."""

import json
import os
from wsgiref.simple_server import WSGIRequestHandler, make_server

import django
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.http import HttpRequest, HttpResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from omniwebhook import MemoryIdempotencyStore, VerifiedEvent, create_receiver, stripe_scheme
from omniwebhook.django import to_incoming_request, to_response

settings.configure(
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["localhost", "127.0.0.1"],
    SECRET_KEY=os.environ.get("DJANGO_SECRET_KEY", "sólo-para-el-ejemplo"),
)
django.setup()

receive = create_receiver(
    verifier=stripe_scheme(secrets=[os.environ.get("WEBHOOK_SECRET", "")]),
    # En memoria sólo sirve con un proceso. En producción, un almacén compartido.
    store=MemoryIdempotencyStore(),
)


def process(event: VerifiedEvent) -> None:
    payload = json.loads(event.request.body)
    print(f"procesado {event.event_key} {payload['type']}", flush=True)


# Sin la protección de CSRF: un webhook no trae ese token. Lo que lo autentica es la firma.
@csrf_exempt
@require_POST
def webhook(request: HttpRequest) -> HttpResponse:
    # Lee el cuerpo crudo: hay que llamarla antes de tocar `request.POST`.
    return to_response(receive.execute(to_incoming_request(request), process))


urlpatterns = [path("webhooks", webhook)]


class _Silent(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    make_server("127.0.0.1", port, get_wsgi_application(), handler_class=_Silent).serve_forever()
