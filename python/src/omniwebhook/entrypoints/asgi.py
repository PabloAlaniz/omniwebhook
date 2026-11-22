"""Arma el pedido entrante a partir de un `scope` ASGI. No depende de ningún framework."""

from collections.abc import Mapping
from typing import Any

from omniwebhook.domain.incoming_request import IncomingRequest
from omniwebhook.entrypoints.requests import incoming_request


def incoming_request_from_scope(scope: Mapping[str, Any], body: bytes) -> IncomingRequest:
    """Arma el pedido con las cabeceras y la consulta del `scope` y el cuerpo crudo ya leído.

    Las cabeceras repetidas se conservan, así que se informan como `ambiguous`.
    """
    headers = [(name.decode("latin-1"), value.decode("latin-1")) for name, value in scope.get("headers", [])]
    return incoming_request(
        headers=headers, query=scope.get("query_string", b"").decode("latin-1"), body=body
    )
