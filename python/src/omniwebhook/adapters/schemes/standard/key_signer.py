"""Firma lo que se emite con la variante asimétrica del formato, `v2a` (sección 7.1).

Necesita `omniwebhook[ed25519]`.
"""

import base64
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from omniwebhook.adapters.ed25519 import ed25519_public_key, random_ed25519_seed, sign_ed25519
from omniwebhook.adapters.schemes.scheme_verifier import checked_secrets, usable_keys
from omniwebhook.application.ports import MessageSigner
from omniwebhook.domain.message import NotSigned, OutgoingMessage, Signed, Signing, message_problem

_SECRET_PREFIX: Final = "whsk_"  # noqa: S105
_PUBLIC_PREFIX: Final = "whpk_"
_SEED_BYTES: Final = 32
_BASE64: Final = re.compile(r"[A-Za-z0-9+/]*={0,2}")


def _seed_of(text: str) -> bytes | None:
    """La semilla de un texto `whsk_…`, o `None` si no se puede usar."""
    if not isinstance(text, str) or not text.startswith(_SECRET_PREFIX):
        return None
    encoded = text.removeprefix(_SECRET_PREFIX)
    if len(encoded) % 4 != 0 or _BASE64.fullmatch(encoded) is None:
        return None
    seed = base64.b64decode(encoded)
    return seed if len(seed) == _SEED_BYTES else None


def _encoded(prefix: str, raw: bytes) -> str:
    return prefix + base64.b64encode(raw).decode("ascii")


class _StandardKeySigner:
    def __init__(self, secret_keys: Sequence[str]) -> None:
        self._seeds = usable_keys(_seed_of, checked_secrets(secret_keys))

    def sign(self, message: OutgoingMessage) -> Signing:
        problem = message_problem(message)
        if problem is not None:
            return NotSigned(problem)
        endpoint_id = message.endpoint_id
        if not isinstance(endpoint_id, str) or endpoint_id == "" or "." in endpoint_id:
            return NotSigned("invalid_endpoint")
        if self._seeds is None:
            return NotSigned("unconfigured")

        prefix = f"{endpoint_id}.{message.id}.{message.timestamp}.".encode()
        content = hashlib.sha256(prefix + message.payload).digest()
        signatures = [_encoded("v2a,", sign_ed25519(seed, content)) for seed in self._seeds]
        return Signed(
            headers={
                "webhook-id": message.id,
                "webhook-timestamp": str(message.timestamp),
                "webhook-signature": " ".join(signatures),
            }
        )


def standard_key_signer(*, secret_keys: Sequence[str]) -> MessageSigner:
    """Arma quien firma los mensajes con una clave privada.

    `secret_keys` son las claves, con la forma `whsk_…`; se manda una firma por cada una, en
    orden. Quien recibe verifica con la clave pública y con el identificador del destino,
    que es parte de lo que se firma.
    """
    return _StandardKeySigner(secret_keys)


def standard_public_key_of(secret_key: str) -> str | None:
    """La clave pública `whpk_…` de una clave privada `whsk_…`; `None` si la privada no se puede usar."""
    seed = _seed_of(secret_key)
    return None if seed is None else _encoded(_PUBLIC_PREFIX, ed25519_public_key(seed))


@dataclass(frozen=True, slots=True)
class StandardKeyPair:
    secret_key: str
    """Se guarda del lado de quien emite. No se le muestra a quien recibe."""
    public_key: str
    """La que se comparte con quien recibe."""

    def __repr__(self) -> str:
        # La clave privada no tiene que terminar en un log por imprimir el par.
        return f"StandardKeyPair(secret_key='whsk_…', public_key={self.public_key!r})"


def generate_standard_key_pair() -> StandardKeyPair:
    """Un par de claves nuevo."""
    seed = random_ed25519_seed()
    return StandardKeyPair(_encoded(_SECRET_PREFIX, seed), _encoded(_PUBLIC_PREFIX, ed25519_public_key(seed)))
