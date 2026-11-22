"""El formato Standard Webhooks: verificar lo que llega y firmar lo que se emite.

Vive en un módulo aparte porque es el único que puede necesitar la librería de referencia
del formato (`omniwebhook[standard]`). Con `signer=native_signer` no hace falta.
"""

from typing import TYPE_CHECKING

from omniwebhook.adapters.schemes.standard import standard_scheme
from omniwebhook.adapters.schemes.standard.native_signer import native_signer
from omniwebhook.adapters.schemes.standard.signer import StandardSigner
from omniwebhook.adapters.schemes.standard.standard_signer import standard_signer

if TYPE_CHECKING:
    from omniwebhook.adapters.schemes.standard.reference_signer import reference_signer

__all__ = ["StandardSigner", "native_signer", "reference_signer", "standard_scheme", "standard_signer"]


def __getattr__(name: str) -> object:
    # La librería de referencia se importa recién cuando alguien la pide.
    if name == "reference_signer":
        from omniwebhook.adapters.schemes.standard.reference_signer import reference_signer

        return reference_signer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
