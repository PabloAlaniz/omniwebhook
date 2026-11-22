"""Firma el formato estándar con la biblioteca estándar del lenguaje, sin dependencias."""

import base64

from omniwebhook.adapters.crypto import hmac_sha256


class NativeSigner:
    def sign(self, key: bytes, identifier: str, timestamp: int, payload: bytes) -> str:
        signed = f"{identifier}.{timestamp}.".encode() + payload
        return "v1," + base64.b64encode(hmac_sha256(key, signed)).decode("ascii")


native_signer = NativeSigner()
