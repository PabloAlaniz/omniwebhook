"""Errores de configuración."""


class ConfigurationError(Exception):
    """Lo lanza un constructor cuando recibe una opción inválida.

    Nunca lo provoca un pedido entrante; eso siempre termina en un resultado tipado.
    """


def positive_integer(name: str, value: object) -> int:
    """Devuelve `value` si es un entero mayor que cero; si no, lanza `ConfigurationError`."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{name} tiene que ser un entero mayor que cero")
    return value
