"""Firma lo que se emite con el formato Standard Webhooks (sección 7)."""

from collections.abc import Sequence

from omniwebhook.adapters.schemes.scheme_verifier import checked_secrets, usable_keys
from omniwebhook.adapters.schemes.standard.secret import default_signer, standard_key
from omniwebhook.adapters.schemes.standard.signer import StandardSigner
from omniwebhook.application.ports import MessageSigner
from omniwebhook.domain.message import NotSigned, OutgoingMessage, Signed, Signing, message_problem


class _StandardMessageSigner:
    def __init__(self, secrets: Sequence[str], signer: StandardSigner | None) -> None:
        self._keys = usable_keys(standard_key, checked_secrets(secrets))
        self._signer = signer or default_signer()

    def sign(self, message: OutgoingMessage) -> Signing:
        problem = message_problem(message)
        if problem is not None:
            return NotSigned(problem)
        if self._keys is None:
            return NotSigned("unconfigured")

        signatures = [
            self._signer.sign(key, message.id, message.timestamp, message.payload) for key in self._keys
        ]
        return Signed(
            headers={
                "webhook-id": message.id,
                "webhook-timestamp": str(message.timestamp),
                "webhook-signature": " ".join(signatures),
            }
        )


def standard_signer(*, secrets: Sequence[str], signer: StandardSigner | None = None) -> MessageSigner:
    """Arma quien firma los mensajes a emitir.

    Con más de un secreto se manda una firma por cada uno, en el orden de la lista
    (rotación). `signer` es quien calcula la firma; por defecto, la librería de referencia.
    """
    return _StandardMessageSigner(secrets, signer)
