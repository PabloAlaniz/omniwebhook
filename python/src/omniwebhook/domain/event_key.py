"""La clave que identifica a un evento (sección 4.6)."""


def event_key(scheme: str, identifier: str) -> str:
    """La clave de un evento que trae su propio identificador."""
    return f"{scheme}:{identifier}"


def fingerprint_key(scheme: str, body_sha256_hex: str) -> str:
    """La clave de un evento sin identificador: la huella de su cuerpo."""
    return f"{scheme}:sha256:{body_sha256_hex}"
