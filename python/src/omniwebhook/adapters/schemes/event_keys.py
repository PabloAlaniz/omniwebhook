"""Claves de evento que salen del cuerpo (sección 4.6)."""

import json
from typing import NoReturn

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


def _not_json(constant: str) -> NoReturn:
    raise ValueError(f"{constant} no es JSON")


def _json_id(body: bytes, field: str) -> str | None:
    try:
        # Los números no interesan; leerlos como decimales evita el tope de dígitos de los enteros.
        data = json.loads(body.decode("utf-8"), parse_constant=_not_json, parse_int=float)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    identifier = data.get(field)
    return identifier if isinstance(identifier, str) and identifier else None
