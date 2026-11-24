"""El formato Standard Webhooks: verificar lo que llega y firmar lo que se emite.

Vive en un módulo aparte porque es el único que puede necesitar la librería de referencia
del formato (`omniwebhook[standard]`). Con `signer=native_signer` no hace falta.

La firma asimétrica, `standard_public_key_scheme`, necesita `omniwebhook[ed25519]`.
"""

from typing import TYPE_CHECKING

from omniwebhook.adapters.schemes.standard import standard_scheme
from omniwebhook.adapters.schemes.standard.native_signer import native_signer
from omniwebhook.adapters.schemes.standard.signer import StandardSigner
from omniwebhook.adapters.schemes.standard.standard_signer import standard_signer
from omniwebhook.domain.errors import ConfigurationError

if TYPE_CHECKING:
    from omniwebhook.adapters.schemes.standard.public_key import standard_public_key_scheme
    from omniwebhook.adapters.schemes.standard.reference_signer import reference_signer

__all__ = [
    "StandardSigner",
    "native_signer",
    "reference_signer",
    "standard_public_key_scheme",
    "standard_scheme",
    "standard_signer",
]


def __getattr__(name: str) -> object:
    # La librería de referencia se importa recién cuando alguien la pide.
    if name == "reference_signer":
        from omniwebhook.adapters.schemes.standard.reference_signer import reference_signer

        return reference_signer
    if name == "standard_public_key_scheme":
        try:
            from omniwebhook.adapters.schemes.standard.public_key import standard_public_key_scheme
        except ImportError as error:
            raise ConfigurationError(
                "falta la librería de Ed25519: instalá `omniwebhook[ed25519]`"
            ) from error
        return standard_public_key_scheme
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
