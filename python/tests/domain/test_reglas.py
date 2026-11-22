import pytest

from omniwebhook import ConfigurationError, RetryPolicy, http_status_for
from omniwebhook.domain.delivery import AttemptOutcome, state_after
from omniwebhook.domain.destination import inspect_destination
from omniwebhook.domain.errors import positive_integer
from omniwebhook.domain.fields import Singles, pick_singles
from omniwebhook.domain.incoming_request import field_values
from omniwebhook.domain.retry import retry_after_seconds
from omniwebhook.domain.timestamp import parse_timestamp
from tests.support.vectors import Caso, casos, nombre


@pytest.mark.parametrize("caso", casos("recibir/respuesta-http"), ids=nombre)
def test_respuesta_http(caso: Caso) -> None:
    assert http_status_for(caso["outcome"]) == caso["expected"]["status"]


@pytest.mark.parametrize("valor", [0, -1, 1.5, True, "3", None])
def test_positive_integer_rechaza_lo_que_no_es_un_entero_mayor_que_cero(valor: object) -> None:
    with pytest.raises(ConfigurationError, match="plazo tiene que ser un entero mayor que cero"):
        positive_integer("plazo", valor)


def test_positive_integer_devuelve_el_valor() -> None:
    assert positive_integer("plazo", 7) == 7


def test_field_values_ignora_mayusculas_recorta_y_descarta_vacios() -> None:
    campos = [("X-Firma", " abc "), ("x-firma", "   "), ("otra", "1"), ("X-FIRMA", "def")]

    assert field_values(campos, "x-firma") == ["abc", "def"]


def test_pick_singles_informa_lo_que_falta_antes_que_lo_repetido() -> None:
    assert pick_singles({"a": [], "b": ["1", "2"]}) == "missing"
    assert pick_singles({"a": ["1"]}, {"b": ["1", "2"]}) == "ambiguous"
    assert pick_singles({"a": ["1"]}, {"b": []}) == Singles({"a": "1"}, {"b": None})


@pytest.mark.parametrize("texto", ["", "１２", "+1", "-1", "1.0", " 1", "1" * 12])
def test_parse_timestamp_solo_acepta_digitos_ascii_dentro_del_largo(texto: str) -> None:
    assert parse_timestamp(texto, 11) is None


def test_una_url_con_puerto_invalido_no_es_una_url() -> None:
    assert inspect_destination("https://hooks.ejemplo.test:99999999/x") == "invalid_url"
    assert inspect_destination("https://[::1/x") == "invalid_url"


def test_el_host_de_una_ipv6_literal_va_sin_corchetes() -> None:
    destino = inspect_destination("https://[2606:4700:4700::1111]:8443/x")

    assert not isinstance(destino, str)
    assert destino.host == "2606:4700:4700::1111"
    assert destino.literal_address == "2606:4700:4700::1111"


def test_un_nombre_no_es_una_direccion_literal() -> None:
    destino = inspect_destination("https://Hooks.Ejemplo.test/x")

    assert not isinstance(destino, str)
    assert (destino.host, destino.literal_address) == ("hooks.ejemplo.test", None)


@pytest.mark.parametrize(
    ("clase", "hay_proximo", "estado"),
    [
        ("delivered", False, "delivered"),
        ("gone", False, "gone"),
        ("rejected", False, "rejected"),
        ("blocked", False, "blocked"),
        ("retryable", True, "pending"),
        ("retryable", False, "exhausted"),
    ],
)
def test_estado_despues_de_un_intento(clase: str, hay_proximo: bool, estado: str) -> None:
    assert state_after(clase, hay_proximo) == estado  # type: ignore[arg-type]


def test_un_intento_tiene_estado_o_falla_pero_no_los_dos() -> None:
    with pytest.raises(ValueError, match="estado o una falla"):
        AttemptOutcome(status=200, failure="network")
    with pytest.raises(ValueError, match="estado o una falla"):
        AttemptOutcome()


@pytest.mark.parametrize(
    "valor",
    ["Sun, 31 Feb 2024 08:49:37 GMT", "Sun, 06 Nov 0000 08:49:37 GMT", "Sun, 06 Xyz 2024 08:49:37 GMT", "１"],
)
def test_retry_after_ignora_fechas_que_no_existen(valor: str) -> None:
    assert retry_after_seconds(valor, 1_700_000_000) is None


@pytest.mark.parametrize(
    ("opciones", "mensaje"),
    [
        ({"schedule": [5, -1]}, "schedule"),
        ({"schedule": [5, 1.5]}, "schedule"),
        ({"schedule": [True]}, "schedule"),
        ({"max_delay_seconds": 0}, "max_delay_seconds"),
        ({"jitter_ratio": -0.1}, "jitter_ratio"),
        ({"jitter_ratio": float("nan")}, "jitter_ratio"),
    ],
)
def test_una_politica_de_reintentos_invalida_falla_al_construirse(opciones: Caso, mensaje: str) -> None:
    with pytest.raises(ConfigurationError, match=mensaje):
        RetryPolicy(**opciones)
