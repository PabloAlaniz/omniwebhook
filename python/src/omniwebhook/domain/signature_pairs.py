"""Cabeceras con pares `clave=valor` separados por comas (sección 4.5.1)."""

from collections.abc import Sequence

from omniwebhook.domain.incoming_request import Field


def parse_pairs(text: str, *, lowercase_keys: bool = False) -> list[Field]:
    """Parte la cabecera. Una parte sin `=`, con la clave vacía o con el valor vacío se ignora."""
    pairs: list[Field] = []
    for piece in text.split(","):
        key, separator, value = piece.partition("=")
        key, value = key.strip(), value.strip()
        if separator and key and value:
            pairs.append((key.lower() if lowercase_keys else key, value))
    return pairs


def pair_values(pairs: Sequence[Field], key: str) -> list[str]:
    """Los valores de una clave, comparada tal cual."""
    return [value for candidate, value in pairs if candidate == key]
