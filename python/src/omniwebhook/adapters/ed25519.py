"""Firmas Ed25519: verificar, firmar y derivar la clave pública.

Es el único módulo que importa `cryptography`: la biblioteca estándar no trae Ed25519.
"""

import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def verifies_ed25519(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """Si `signature` es la firma de `message` para la clave pública cruda `public_key`.

    Una clave que la plataforma no puede cargar cuenta como que no verifica.
    """
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


def sign_ed25519(seed: bytes, message: bytes) -> bytes:
    """La firma de `message` con la clave privada de semilla `seed` (32 bytes)."""
    return Ed25519PrivateKey.from_private_bytes(seed).sign(message)


def ed25519_public_key(seed: bytes) -> bytes:
    """Los 32 bytes de la clave pública que le corresponde a una semilla."""
    return (
        Ed25519PrivateKey.from_private_bytes(seed)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def random_ed25519_seed() -> bytes:
    """Una semilla nueva: 32 bytes al azar."""
    return secrets.token_bytes(32)
