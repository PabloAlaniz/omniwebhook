"""Primitivas criptográficas sobre la biblioteca estándar."""

import hashlib
import hmac


def utf8(text: str) -> bytes | None:
    """El texto en UTF-8, o `None` si no se puede codificar."""
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        return None


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def sha256_hex(message: bytes) -> str:
    return hashlib.sha256(message).hexdigest()


def equal_in_constant_time(a: str, b: str) -> bool:
    """Compara dos textos sin cortar en la primera diferencia (sección 4.3)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))
