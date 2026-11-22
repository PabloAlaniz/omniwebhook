"""El pedido entrante tal como llegó (sección 3 de la especificación)."""

from collections.abc import Sequence
from dataclasses import dataclass

Field = tuple[str, str]
"""Un par nombre-valor. Un mismo nombre puede aparecer en más de un par."""


@dataclass(frozen=True, slots=True)
class IncomingRequest:
    headers: Sequence[Field]
    """Cabeceras. Los nombres no distinguen mayúsculas."""
    query: Sequence[Field]
    """Parámetros de la URL."""
    body: bytes
    """El cuerpo crudo, antes de interpretarlo."""


def field_values(fields: Sequence[Field], name: str) -> list[str]:
    """Los valores de un campo, recortados y sin los vacíos.

    Un valor vacío equivale a que el campo no esté.
    """
    wanted = name.lower()
    found = (value.strip() for candidate, value in fields if candidate.lower() == wanted)
    return [value for value in found if value]
