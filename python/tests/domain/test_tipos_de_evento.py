import pytest

from omniwebhook import ConfigurationError, is_event_pattern, is_event_type, subscribes
from tests.support.vectors import Caso, casos, nombre


@pytest.mark.parametrize("caso", casos("entregar/tipos"), ids=nombre)
def test_vectores(caso: Caso) -> None:
    tipo, patrones, esperado = caso["type"], caso["patterns"], caso["expected"]

    assert is_event_type(tipo) == esperado["valid_type"]
    validos = None if patrones is None else [is_event_pattern(patron) for patron in patrones]
    assert validos == esperado["valid_patterns"]
    if esperado["subscribed"] is None:
        with pytest.raises(ConfigurationError):
            subscribes(patrones, tipo)
    else:
        assert subscribes(patrones, tipo) == esperado["subscribed"]


def test_los_patrones_son_una_lista_y_no_un_texto() -> None:
    with pytest.raises(ConfigurationError, match="lista"):
        subscribes("pedido.*", "pedido.creado")


def test_lo_que_no_es_texto_no_es_un_tipo_ni_un_patron() -> None:
    assert not is_event_type(7)  # type: ignore[arg-type]
    assert not is_event_pattern(None)  # type: ignore[arg-type]
