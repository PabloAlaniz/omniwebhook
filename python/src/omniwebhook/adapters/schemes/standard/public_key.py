"""El formato Standard Webhooks con firma asimétrica `v2a` (sección 5.10).

Es el único módulo que importa `cryptography`: la biblioteca estándar no trae Ed25519.
"""

import base64
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from omniwebhook.adapters.crypto import utf8
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, public_key_scheme_verifier
from omniwebhook.application.ports import Clock, Verifier
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.event_key import event_key
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.freshness import DEFAULT_TOLERANCE_SECONDS
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.timestamp import SECONDS_DIGITS, parse_timestamp

_VERSION: Final = "v2a,"
_KEY_PREFIX: Final = "whpk_"
_KEY_BYTES: Final = 32
_SIGNATURE_BYTES: Final = 64
_BASE64: Final = re.compile(r"[A-Za-z0-9+/]*={0,2}")


def _strict_base64(text: str) -> bytes | None:
    if len(text) % 4 != 0 or _BASE64.fullmatch(text) is None:
        return None
    return base64.b64decode(text)


def standard_public_key(text: str) -> bytes | None:
    """La clave pública de un texto `whpk_…`, o `None` si no se puede usar."""
    if not text.startswith(_KEY_PREFIX):
        return None
    key = _strict_base64(text.removeprefix(_KEY_PREFIX))
    return key if key is not None and len(key) == _KEY_BYTES else None


@dataclass(frozen=True, slots=True, kw_only=True)
class _PublicKeyReading(Reading):
    prefix: bytes
    """`<endpoint_id>.<webhook-id>.<webhook-timestamp>.`: lo que va antes del cuerpo."""


@dataclass(frozen=True, slots=True)
class _StandardPublicKey:
    endpoint_id: str

    def key_of(self, secret: str) -> bytes | None:
        return standard_public_key(secret)

    def read(self, request: IncomingRequest) -> _PublicKeyReading | ReadProblem:
        fields = pick_singles(
            {
                "id": field_values(request.headers, "webhook-id"),
                "timestamp": field_values(request.headers, "webhook-timestamp"),
                "signature": field_values(request.headers, "webhook-signature"),
            }
        )
        if isinstance(fields, str):
            return fields

        identifier, raw_timestamp = fields.required["id"], fields.required["timestamp"]
        timestamp = parse_timestamp(raw_timestamp, SECONDS_DIGITS)
        received = [
            token.removeprefix(_VERSION)
            for token in fields.required["signature"].split(" ")
            if token.startswith(_VERSION)
        ]
        prefix = utf8(f"{self.endpoint_id}.{identifier}.{raw_timestamp}.")
        # Un identificador que no se puede pasar a bytes no se puede haber firmado.
        if timestamp is None or not received or prefix is None:
            return "malformed"

        return _PublicKeyReading(
            prefix=prefix,
            timestamp=timestamp,
            received=received,
            event_key=lambda: event_key("standard", identifier),
        )

    def verifies(
        self, key: bytes, received: str, reading: _PublicKeyReading, request: IncomingRequest
    ) -> bool:
        signature = _strict_base64(received)
        if signature is None or len(signature) != _SIGNATURE_BYTES:
            return False
        content = hashlib.sha256(reading.prefix + request.body).digest()
        try:
            Ed25519PublicKey.from_public_bytes(key).verify(signature, content)
        except (InvalidSignature, ValueError):
            # Una clave que la plataforma no puede cargar cuenta como que no verifica.
            return False
        return True


def standard_public_key_scheme(
    *,
    public_keys: Sequence[str],
    endpoint_id: str,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    clock: Clock | None = None,
) -> Verifier:
    """Verifica el formato Standard Webhooks con firma asimétrica `v2a`.

    `public_keys` son las claves aceptadas, con la forma `whpk_…`; vale cualquiera, así se
    rotan. `endpoint_id` es el identificador que el emisor le asignó a este destino: es
    parte de lo que se firma y nunca se toma del pedido.
    """
    if not isinstance(endpoint_id, str) or endpoint_id == "" or "." in endpoint_id:
        raise ConfigurationError("endpoint_id no puede estar vacío ni contener un punto")
    return public_key_scheme_verifier(
        _StandardPublicKey(endpoint_id), keys=public_keys, clock=clock, tolerance_seconds=tolerance_seconds
    )
