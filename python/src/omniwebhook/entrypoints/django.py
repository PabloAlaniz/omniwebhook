"""Ayudas para Django."""

from django.http import HttpRequest, HttpResponse

from omniwebhook.application.receive_webhook import Reception
from omniwebhook.domain.incoming_request import IncomingRequest
from omniwebhook.domain.reception import http_status_for
from omniwebhook.entrypoints.requests import incoming_request


def to_incoming_request(request: HttpRequest) -> IncomingRequest:
    """Convierte el pedido del framework en el que entiende el núcleo. Lee el cuerpo crudo.

    Hay que llamarla antes de leer `request.POST` o `request.data`. El tamaño lo acota
    `DATA_UPLOAD_MAX_MEMORY_SIZE`: si el cuerpo lo supera, Django corta antes de llegar acá.

    Django une con comas las cabeceras repetidas, así que una cabecera repetida no se
    informa como `ambiguous` sino que deja de coincidir con la firma.
    """
    return incoming_request(
        headers=list(request.headers.items()),
        query=request.META.get("QUERY_STRING", ""),
        body=request.body,
    )


def to_response(reception: Reception) -> HttpResponse:
    """La respuesta sugerida para un resultado (sección 6.3). El cuerpo no dice qué falló."""
    return HttpResponse(status=http_status_for(reception.outcome))
