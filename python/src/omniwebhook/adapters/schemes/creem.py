"""El formato de firma de Creem (sección 5.5)."""

from collections.abc import Sequence

from omniwebhook.adapters.schemes.body_signature import BodySignatureFormat, body_signature_verifier
from omniwebhook.application.ports import Verifier

_FORMAT = BodySignatureFormat(name="creem", header="creem-signature", fallback_key="json-id")


def creem_scheme(*, secrets: Sequence[str]) -> Verifier:
    """Verifica el formato de firma de Creem."""
    return body_signature_verifier(_FORMAT, secrets=secrets)
