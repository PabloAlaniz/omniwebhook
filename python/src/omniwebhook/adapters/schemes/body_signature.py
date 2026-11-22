"""Esquemas que firman sólo el cuerpo y mandan la firma en una cabecera."""

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from omniwebhook.adapters.crypto import hmac_sha256
from omniwebhook.adapters.schemes.event_keys import body_fingerprint, json_id_key
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier, text_key
from omniwebhook.application.ports import Verifier
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.event_key import event_key
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.incoming_request import IncomingRequest, field_values

SignatureEncoding = Literal["hex", "base64"]


@dataclass(frozen=True, slots=True, kw_only=True)
class BodySignatureFormat:
    name: str
    """El nombre del esquema en la clave del evento."""
    header: str
    """La cabecera que trae la firma."""
    prefix: str = ""
    """Un texto fijo antes de la firma."""
    encoding: SignatureEncoding = "hex"
    id_header: str | None = None
    """La cabecera que identifica el evento, si el emisor manda una."""
    fallback_key: Literal["json-id", "fingerprint"] = "fingerprint"
    """De dónde sale la clave del evento cuando no hay cabecera que lo identifique."""

    def __post_init__(self) -> None:
        for option, value in (("name", self.name), ("header", self.header)):
            if not isinstance(value, str) or value.strip() == "":
                raise ConfigurationError(f"{option} no puede estar vacío")
        if self.encoding not in ("hex", "base64"):
            raise ConfigurationError('encoding tiene que ser "hex" o "base64"')


@dataclass(frozen=True, slots=True)
class _BodySignature:
    format: BodySignatureFormat

    def key_of(self, secret: str) -> bytes | None:
        return text_key(secret)

    def read(self, request: IncomingRequest) -> Reading | ReadProblem:
        fmt = self.format
        fields = pick_singles(
            {"signature": field_values(request.headers, fmt.header)},
            {"id": [] if fmt.id_header is None else field_values(request.headers, fmt.id_header)},
        )
        if isinstance(fields, str):
            return fields
        signature = fields.required["signature"]
        if not signature.startswith(fmt.prefix):
            return "malformed"

        received = signature[len(fmt.prefix) :]
        identifier = fields.optional["id"]

        def key() -> str:
            if identifier is not None:
                return event_key(fmt.name, identifier)
            derive = json_id_key if fmt.fallback_key == "json-id" else body_fingerprint
            return derive(fmt.name, request.body)

        return Reading(
            timestamp=None,
            received=[received.lower() if fmt.encoding == "hex" else received],
            event_key=key,
        )

    def expected(self, key: bytes, reading: Reading, request: IncomingRequest) -> str:
        mac = hmac_sha256(key, request.body)
        return mac.hex() if self.format.encoding == "hex" else base64.b64encode(mac).decode("ascii")


def body_signature_verifier(fmt: BodySignatureFormat, *, secrets: Sequence[str]) -> Verifier:
    """Arma el verificador de un formato que firma sólo el cuerpo. No lleva marca de tiempo."""
    return scheme_verifier(_BodySignature(fmt), secrets=secrets)
