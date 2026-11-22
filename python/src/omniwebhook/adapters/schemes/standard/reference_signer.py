"""Firma con la librería de referencia del formato estándar.

Es el único módulo del paquete que la importa.
"""

from datetime import UTC, datetime

from standardwebhooks import Webhook


class ReferenceSigner:
    def sign(self, key: bytes, identifier: str, timestamp: int, payload: bytes) -> str:
        return Webhook(key).sign(identifier, datetime.fromtimestamp(timestamp, tz=UTC), payload)


reference_signer = ReferenceSigner()
