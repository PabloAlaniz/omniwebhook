"""Versión de este paquete. La actualiza el circuito de publicación."""

from typing import Final

PACKAGE_VERSION: Final = "0.4.0"  # x-release-please-version

USER_AGENT: Final = f"omniwebhook/{PACKAGE_VERSION} (python)"
"""La cabecera `user-agent` de cada intento de entrega (sección 7)."""
