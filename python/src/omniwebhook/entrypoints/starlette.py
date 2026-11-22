"""Ayudas para Starlette y los frameworks que se apoyan en él."""

from starlette.requests import Request
from starlette.responses import Response

from omniwebhook.application.receive_webhook import Reception
from omniwebhook.domain.incoming_request import IncomingRequest
from omniwebhook.domain.reception import http_status_for
from omniwebhook.entrypoints.asgi import incoming_request_from_scope


async def to_incoming_request(request: Request) -> IncomingRequest:
    """Convierte el pedido del framework en el que entiende el núcleo. Lee el cuerpo crudo."""
    return incoming_request_from_scope(request.scope, await request.body())


def to_response(reception: Reception) -> Response:
    """La respuesta sugerida para un resultado (sección 6.3). El cuerpo no dice qué falló."""
    return Response(status_code=http_status_for(reception.outcome))
