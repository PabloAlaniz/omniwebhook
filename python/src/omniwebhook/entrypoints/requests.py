"""Arma el pedido entrante a partir de lo que entrega cualquier framework."""

from collections.abc import Iterable, Mapping
from urllib.parse import parse_qsl

from omniwebhook.domain.incoming_request import Field, IncomingRequest

Fields = Mapping[str, str] | Iterable[Field]


def _pairs(fields: Fields) -> list[Field]:
    items = fields.items() if isinstance(fields, Mapping) else fields
    return [(str(name), str(value)) for name, value in items]


def incoming_request(*, headers: Fields, query: Fields | str = "", body: bytes) -> IncomingRequest:
    """Arma el pedido que entiende el núcleo.

    `headers` y `query` pueden ser un diccionario o una lista de pares; con pares, un
    nombre repetido se informa como `ambiguous` en lugar de perderse. `query` también
    puede ser el texto de la consulta de la URL. `body` es el cuerpo crudo: los bytes tal
    como llegaron, antes de interpretarlos.
    """
    if not isinstance(body, bytes | bytearray | memoryview):
        raise TypeError("body tiene que ser el cuerpo crudo, en bytes")
    parsed = parse_qsl(query, keep_blank_values=True) if isinstance(query, str) else _pairs(query)
    return IncomingRequest(headers=_pairs(headers), query=parsed, body=bytes(body))
