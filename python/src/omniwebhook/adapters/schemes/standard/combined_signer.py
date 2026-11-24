"""Varias firmas del formato estándar en un mismo mensaje (sección 7.1)."""

from collections.abc import Sequence

from omniwebhook.application.ports import MessageSigner
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.message import OutgoingMessage, Signed, Signing

_SIGNATURE = "webhook-signature"


class _CombinedSigner:
    def __init__(self, signers: Sequence[MessageSigner]) -> None:
        self._signers = tuple(signers)

    def sign(self, message: OutgoingMessage) -> Signing:
        headers: dict[str, str] = {}
        signatures: list[str] = []
        for signer in self._signers:
            signing = signer.sign(message)
            if not isinstance(signing, Signed):
                return signing
            headers.update(signing.headers)
            if _SIGNATURE in signing.headers:
                signatures.append(signing.headers[_SIGNATURE])
        return Signed(headers={**headers, _SIGNATURE: " ".join(signatures)})


def combined_signer(signers: Sequence[MessageSigner]) -> MessageSigner:
    """Firma un mismo mensaje con varios firmantes y junta sus firmas en una sola cabecera.

    Sirve para migrar de la firma simétrica a la asimétrica: cada receptor mira sólo las de
    su variante. Si alguno no puede firmar, el mensaje no se firma: el resultado es el
    problema del primero.
    """
    if not signers:
        raise ConfigurationError("signers no puede estar vacío")
    return _CombinedSigner(signers)
