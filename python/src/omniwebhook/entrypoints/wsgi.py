"""Arma el pedido entrante a partir de un `environ` WSGI. No depende de ningún framework."""

from collections.abc import Callable, Iterable, Mapping
from http import HTTPStatus
from typing import Any

from omniwebhook.application.receive_webhook import Reception
from omniwebhook.domain.errors import positive_integer
from omniwebhook.domain.incoming_request import IncomingRequest
from omniwebhook.domain.reception import DEFAULT_MAX_BODY_BYTES, http_status_for
from omniwebhook.entrypoints.requests import incoming_request

StartResponse = Callable[[str, list[tuple[str, str]]], Any]

# Las dos cabeceras que WSGI entrega sin el prefijo `HTTP_`.
_UNPREFIXED = {"CONTENT_TYPE": "content-type", "CONTENT_LENGTH": "content-length"}


def _content_length(environ: Mapping[str, Any]) -> int:
    try:
        return max(int(environ.get("CONTENT_LENGTH") or 0), 0)
    except ValueError:
        return 0


def incoming_request_from_environ(
    environ: Mapping[str, Any], *, body: bytes | None = None, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
) -> IncomingRequest:
    """Arma el pedido con las cabeceras y la consulta del `environ` y el cuerpo crudo.

    Lee el cuerpo de `wsgi.input`, así que hay que llamarla antes de que otra cosa lo
    consuma; si el framework ya lo leyó, se pasa en `body`. Como mucho lee
    `max_body_bytes` más un byte: alcanza para que el pedido termine en `too_large` sin
    traer el resto a memoria. Tiene que ser igual o mayor que el `max_body_bytes` del
    receptor.

    WSGI une con comas las cabeceras repetidas, así que una cabecera repetida no se
    informa como `ambiguous` sino que deja de coincidir con la firma.
    """
    limit = positive_integer("max_body_bytes", max_body_bytes)
    headers = [
        (name[5:].replace("_", "-").lower(), str(value))
        for name, value in environ.items()
        if name.startswith("HTTP_")
    ]
    headers += [(header, str(environ[name])) for name, header in _UNPREFIXED.items() if environ.get(name)]

    if body is None:
        # Sin `CONTENT_LENGTH` no se lee: WSGI no garantiza que el flujo termine solo.
        wanted = min(_content_length(environ), limit + 1)
        body = environ["wsgi.input"].read(wanted) if wanted else b""
    return incoming_request(headers=headers, query=str(environ.get("QUERY_STRING", "")), body=body)


def wsgi_response(reception: Reception, start_response: StartResponse) -> Iterable[bytes]:
    """Responde con el estado sugerido (sección 6.3) y sin cuerpo: no dice qué falló."""
    status = HTTPStatus(http_status_for(reception.outcome))
    start_response(f"{status.value} {status.phrase}", [("Content-Length", "0")])
    return [b""]
