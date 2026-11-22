"""El formato de firma de GitHub (sección 5.4)."""

from collections.abc import Sequence

from omniwebhook.adapters.schemes.body_signature import BodySignatureFormat, body_signature_verifier
from omniwebhook.application.ports import Verifier

_FORMAT = BodySignatureFormat(
    name="github", header="x-hub-signature-256", prefix="sha256=", id_header="x-github-delivery"
)


def github_scheme(*, secrets: Sequence[str]) -> Verifier:
    """Verifica el formato de firma de GitHub."""
    return body_signature_verifier(_FORMAT, secrets=secrets)
