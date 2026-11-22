"""Los secretos del formato estándar (sección 5.1)."""

import base64
import re
from typing import Final

from omniwebhook.adapters.schemes.standard.signer import StandardSigner
from omniwebhook.domain.errors import ConfigurationError

_PREFIX: Final = "whsec_"
_BASE64: Final = re.compile(r"[A-Za-z0-9+/]*={0,2}")


def standard_key(secret: str) -> bytes | None:
    """La clave de un secreto del formato estándar, o `None` si no se puede usar."""
    encoded = secret.removeprefix(_PREFIX)
    if encoded == "" or len(encoded) % 4 != 0 or _BASE64.fullmatch(encoded) is None:
        return None
    return base64.b64decode(encoded)


def default_signer() -> StandardSigner:
    """Quien firma si no se indica otro: la librería de referencia del formato."""
    try:
        from omniwebhook.adapters.schemes.standard.reference_signer import reference_signer
    except ImportError as error:
        raise ConfigurationError(
            "falta la librería de referencia del formato estándar: instalá `omniwebhook[standard]` "
            "o pasá `signer=native_signer`"
        ) from error
    return reference_signer
