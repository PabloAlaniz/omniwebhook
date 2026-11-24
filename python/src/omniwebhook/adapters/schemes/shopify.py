"""El formato de firma de Shopify (sección 5.9)."""

from collections.abc import Sequence

from omniwebhook.adapters.schemes.body_signature import BodySignatureFormat, body_signature_verifier
from omniwebhook.application.ports import Verifier

_FORMAT = BodySignatureFormat(
    name="shopify", header="x-shopify-hmac-sha256", encoding="base64", id_header="x-shopify-webhook-id"
)


def shopify_scheme(*, secrets: Sequence[str]) -> Verifier:
    """Verifica el formato de firma de Shopify."""
    return body_signature_verifier(_FORMAT, secrets=secrets)
