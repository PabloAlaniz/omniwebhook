"""Claves de evento que salen del cuerpo (sección 4.6)."""

import json
from typing import Any, NoReturn

from omniwebhook.adapters.crypto import sha256_hex
from omniwebhook.domain.event_key import event_key, fingerprint_key


def body_fingerprint(scheme: str, body: bytes) -> str:
    """La clave de un evento sin identificador: la huella de su cuerpo."""
    return fingerprint_key(scheme, sha256_hex(body))


def json_id_key(scheme: str, body: bytes, field: str = "id") -> str:
    """La clave de un evento cuyo identificador viaja en un campo del cuerpo, `id` si no se indica otro.

    Si el cuerpo no es un objeto JSON con ese campo como texto no vacío, se usa la huella.
    """
    identifier = _json_id(body, field)
    return body_fingerprint(scheme, body) if identifier is None else event_key(scheme, identifier)


def pubsub_message_key(scheme: str, body: bytes) -> str:
    """La clave de un aviso de Pub/Sub: el identificador del mensaje que envuelve (sección 5.14).

    Se lee `message.messageId` y, si no sirve, `message.message_id`. Si ninguno es un texto
    no vacío, se usa la huella.
    """
    data = _json_object(body)
    message = None if data is None else data.get("message")
    if isinstance(message, dict):
        for field in ("messageId", "message_id"):
            identifier = message.get(field)
            if isinstance(identifier, str) and identifier:
                return event_key(scheme, identifier)
    return body_fingerprint(scheme, body)


def _not_json(constant: str) -> NoReturn:
    raise ValueError(f"{constant} no es JSON")


def _json_object(body: bytes) -> dict[str, Any] | None:
    """El cuerpo como objeto JSON estricto en UTF-8; `None` si no lo es."""
    try:
        # Los números no interesan; leerlos como decimales evita el tope de dígitos de los enteros.
        data = json.loads(body.decode("utf-8"), parse_constant=_not_json, parse_int=float)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _json_id(body: bytes, field: str) -> str | None:
    data = _json_object(body)
    identifier = None if data is None else data.get(field)
    return identifier if isinstance(identifier, str) and identifier else None
