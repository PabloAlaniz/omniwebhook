"""Datos que tienen que llegar una sola vez (sección 4.5)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Singles:
    required: Mapping[str, str]
    optional: Mapping[str, str | None]


def pick_singles(
    required: Mapping[str, Sequence[str]],
    optional: Mapping[str, Sequence[str]] | None = None,
) -> Singles | Literal["missing", "ambiguous"]:
    """Reduce cada campo a su único valor, en el orden de la sección 4.1.

    Primero se informa lo que falta y después lo repetido. Nunca elige entre valores
    repetidos.
    """
    optional = optional or {}
    if any(len(values) == 0 for values in required.values()):
        return "missing"
    if any(len(values) > 1 for values in (*required.values(), *optional.values())):
        return "ambiguous"
    return Singles(
        required={name: values[0] for name, values in required.items()},
        optional={name: values[0] if values else None for name, values in optional.items()},
    )
