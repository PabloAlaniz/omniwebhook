"""Valores aleatorios: tokens de reserva, identificadores de mensaje y variación."""

import random
import uuid


class RandomTokens:
    """Tokens de reserva aleatorios (UUID v4)."""

    def next(self) -> str:
        return str(uuid.uuid4())


class SystemRandom:
    """Números en [0, 1) para la variación de los reintentos. No hace falta que sean impredecibles."""

    def next(self) -> float:
        return random.random()  # noqa: S311


def random_message_id() -> str:
    """Un identificador de mensaje nuevo: aleatorio, sin puntos y con prefijo `msg_`."""
    return f"msg_{uuid.uuid4().hex}"


random_tokens = RandomTokens()
