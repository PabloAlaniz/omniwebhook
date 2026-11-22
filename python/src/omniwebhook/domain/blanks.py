"""Qué es un espacio (sección 3): el carácter de espacio o la tabulación, y nada más."""

from typing import Final

_BLANKS: Final = " \t"


def trim(text: str) -> str:
    """El texto sin espacios al principio ni al final."""
    return text.strip(_BLANKS)
