"""La costura por la que entra quien calcula la firma del formato estándar."""

from typing import Protocol


class StandardSigner(Protocol):
    """Calcula la firma `v1` del formato estándar.

    Cualquier implementación que pase los vectores de conformidad sirve.
    """

    def sign(self, key: bytes, identifier: str, timestamp: int, payload: bytes) -> str:
        """Devuelve la firma con su versión: `v1,<base64>`."""
        ...
