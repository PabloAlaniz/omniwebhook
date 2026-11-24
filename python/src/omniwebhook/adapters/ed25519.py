"""Verificación de firmas Ed25519.

Es el único módulo que importa `cryptography`: la biblioteca estándar no trae Ed25519.
"""

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def verifies_ed25519(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """Si `signature` es la firma de `message` para la clave pública cruda `public_key`.

    Una clave que la plataforma no puede cargar cuenta como que no verifica.
    """
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True
