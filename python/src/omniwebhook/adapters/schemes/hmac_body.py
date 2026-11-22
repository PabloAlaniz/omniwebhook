"""Un esquema genérico para emisores que firman sólo el cuerpo (sección 5.6)."""

from collections.abc import Sequence

from omniwebhook.adapters.schemes.body_signature import (
    BodySignatureFormat,
    SignatureEncoding,
    body_signature_verifier,
)
from omniwebhook.application.ports import Verifier


def hmac_body_scheme(
    *,
    secrets: Sequence[str],
    header: str,
    prefix: str = "",
    encoding: SignatureEncoding = "hex",
    name: str = "hmac-body",
    id_header: str | None = None,
) -> Verifier:
    """Verifica a un emisor que firma sólo el cuerpo con HMAC-SHA256.

    `header` es la cabecera que trae la firma y `prefix` un texto fijo antes de ella.
    `name` es el nombre del esquema en la clave del evento. Sin `id_header`, la clave es
    la huella del cuerpo.
    """
    fmt = BodySignatureFormat(name=name, header=header, prefix=prefix, encoding=encoding, id_header=id_header)
    return body_signature_verifier(fmt, secrets=secrets)
