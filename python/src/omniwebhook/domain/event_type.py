"""Tipos de evento y los patrones con los que un destino dice cuáles recibe (sección 8.6)."""

import re
from collections.abc import Sequence
from typing import Final

from omniwebhook.domain.errors import ConfigurationError

_SEGMENT: Final = r"[A-Za-z0-9_-]+"
_TYPE: Final = re.compile(rf"{_SEGMENT}(\.{_SEGMENT})*")
_PATTERN: Final = re.compile(rf"\*|{_SEGMENT}(\.{_SEGMENT})*(\.\*)?")
_MAX_LENGTH: Final = 256


def is_event_type(text: str) -> bool:
    """Si el texto es un tipo de evento: `pedido.creado`, `pedido.item.agregado`."""
    return isinstance(text, str) and len(text) <= _MAX_LENGTH and _TYPE.fullmatch(text) is not None


def is_event_pattern(text: str) -> bool:
    """Si el texto es un patrón de tipos: un tipo exacto, `grupo.*` o `*`."""
    return isinstance(text, str) and len(text) <= _MAX_LENGTH and _PATTERN.fullmatch(text) is not None


def _matches(pattern: str, event_type: str) -> bool:
    if pattern == "*":
        return True
    # `pedido.*` coincide con lo que empieza con `pedido.`, a cualquier profundidad.
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


def subscribes(patterns: Sequence[str] | None, event_type: str) -> bool:
    """Si un destino que declaró esos patrones recibe un evento de ese tipo.

    Sin lista (`None`) recibe todos; con una lista vacía, ninguno.

    Un tipo o un patrón que no cumple la gramática lanza `ConfigurationError`: es un error de
    quien integra, no un evento que no coincide.
    """
    if not is_event_type(event_type):
        raise ConfigurationError("el tipo de evento no es válido")
    if patterns is None:
        return True
    if isinstance(patterns, str):
        raise ConfigurationError("patterns tiene que ser una lista de patrones, no un texto")
    for pattern in patterns:
        if not is_event_pattern(pattern):
            raise ConfigurationError("un patrón de tipos de evento no es válido")
    return any(_matches(pattern, event_type) for pattern in patterns)
