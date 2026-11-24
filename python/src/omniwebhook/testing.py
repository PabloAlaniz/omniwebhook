"""Ayudas para probar una integración.

Arman el pedido que mandaría cada emisor, firmado con el secreto que se indique. No son
para producción.
"""

import base64
import time
import uuid
from dataclasses import replace
from typing import Literal

from omniwebhook.adapters.crypto import hmac_sha256
from omniwebhook.adapters.schemes.standard.secret import standard_key
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.incoming_request import Field, IncomingRequest

__all__ = ["SignedScheme", "signed_request", "tampered"]

SignedScheme = Literal[
    "standard", "stripe", "slack", "shopify", "tiktok", "mercadopago", "github", "creem", "hmac-body"
]


def signed_request(
    scheme: SignedScheme,
    *,
    secret: str,
    body: str | bytes,
    timestamp: int | None = None,
    id: str | None = None,
    data_id: str | None = None,
    header: str | None = None,
    prefix: str = "",
    encoding: Literal["hex", "base64"] = "hex",
    id_header: str | None = None,
) -> IncomingRequest:
    """Arma el pedido que mandaría el emisor, con una firma válida.

    Lo verifica el esquema del mismo nombre configurado con el mismo secreto.

    - `timestamp`: la marca de tiempo firmada, en segundos. Por defecto, ahora. Para probar
      `stale`, una vieja.
    - `id`: el identificador que manda el emisor fuera del cuerpo: `webhook-id` en
      `standard`, `x-github-delivery`, `x-shopify-webhook-id`, `x-request-id` en
      `mercadopago` o la cabecera `id_header` de `hmac-body`. En `standard`, si falta, se
      genera uno.
    - `data_id`: sólo `mercadopago`, el parámetro `data.id` de la URL.
    - `header`, `prefix`, `encoding`, `id_header`: sólo `hmac-body`, la misma configuración
      que recibe `hmac_body_scheme`.
    """
    raw = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    key = standard_key(secret) if scheme == "standard" else secret.encode("utf-8")
    if not secret or key is None:
        raise ConfigurationError("secret no se puede usar con este esquema")

    def in_hex(message: bytes) -> str:
        return hmac_sha256(key, message).hex()

    def in_base64(message: bytes) -> str:
        return base64.b64encode(hmac_sha256(key, message)).decode("ascii")

    def optional(name: str, value: str | None) -> list[Field]:
        return [] if value is None else [(name, value)]

    headers: list[Field]
    query: list[Field] = []
    if scheme == "standard":
        identifier = id or f"msg_{uuid.uuid4().hex}"
        signature = in_base64(f"{identifier}.{stamp}.".encode() + raw)
        headers = [
            ("webhook-id", identifier),
            ("webhook-timestamp", stamp),
            ("webhook-signature", f"v1,{signature}"),
        ]
    elif scheme == "stripe":
        headers = [("stripe-signature", f"t={stamp},v1={in_hex(f'{stamp}.'.encode() + raw)}")]
    elif scheme == "tiktok":
        headers = [("tiktok-signature", f"t={stamp},s={in_hex(f'{stamp}.'.encode() + raw)}")]
    elif scheme == "slack":
        headers = [
            ("x-slack-signature", f"v0={in_hex(f'v0:{stamp}:'.encode() + raw)}"),
            ("x-slack-request-timestamp", stamp),
        ]
    elif scheme == "mercadopago":
        manifest = "".join(
            [
                "" if data_id is None else f"id:{data_id.lower()};",
                "" if id is None else f"request-id:{id};",
                f"ts:{stamp};",
            ]
        )
        headers = [
            ("x-signature", f"ts={stamp},v1={in_hex(manifest.encode())}"),
            *optional("x-request-id", id),
        ]
        query = optional("data.id", data_id)
    elif scheme == "github":
        headers = [("x-hub-signature-256", f"sha256={in_hex(raw)}"), *optional("x-github-delivery", id)]
    elif scheme == "creem":
        headers = [("creem-signature", in_hex(raw))]
    elif scheme == "shopify":
        headers = [("x-shopify-hmac-sha256", in_base64(raw)), *optional("x-shopify-webhook-id", id)]
    elif scheme == "hmac-body":
        if header is None or header.strip() == "":
            raise ConfigurationError("header no puede estar vacío")
        signature = in_base64(raw) if encoding == "base64" else in_hex(raw)
        headers = [(header, prefix + signature)]
        if id_header is not None:
            headers += optional(id_header, id)
    else:
        raise ConfigurationError(f"esquema desconocido: {scheme}")
    return IncomingRequest(headers=headers, query=query, body=raw)


def tampered(request: IncomingRequest) -> IncomingRequest:
    """El mismo pedido alterado después de firmar: tiene que terminar en `invalid`.

    Cambia el cuerpo. En `mercadopago`, cuya firma no cubre el cuerpo, cambia la firma.
    """
    if any(name == "x-signature" for name, _ in request.headers):
        headers = [
            (name, value[:-1] + ("1" if value[-1] == "0" else "0"))
            if name == "x-signature"
            else (name, value)
            for name, value in request.headers
        ]
        return replace(request, headers=headers)
    return replace(request, body=request.body + b" ")
