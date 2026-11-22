import pytest

from omniwebhook import (
    RetryPolicy,
    classify_delivery,
    evaluate_destination,
    is_blocked_address,
    next_attempt,
)
from omniwebhook.domain.delivery import AttemptOutcome
from tests.support.vectors import Caso, casos, nombre


@pytest.mark.parametrize("caso", casos("entregar/direcciones"), ids=nombre)
def test_direcciones(caso: Caso) -> None:
    assert is_blocked_address(caso["address"]) is caso["expected"]["blocked"]


@pytest.mark.parametrize("caso", casos("entregar/url"), ids=nombre)
def test_url(caso: Caso) -> None:
    resultado = evaluate_destination(caso["url"], allow_http=caso["allow_http"], resolved=caso["resolved"])

    assert resultado == caso["expected"]["result"]


@pytest.mark.parametrize("caso", casos("entregar/clasificacion"), ids=nombre)
def test_clasificacion(caso: Caso) -> None:
    resultado = classify_delivery(AttemptOutcome(status=caso["status"], failure=caso["failure"]))

    assert resultado == caso["expected"]["class"]


@pytest.mark.parametrize("caso", casos("entregar/reintentos"), ids=nombre)
def test_reintentos(caso: Caso) -> None:
    opciones = {k: caso[k] for k in ("schedule", "max_delay_seconds", "jitter_ratio") if k in caso}

    resultado = next_attempt(
        attempt=caso["attempt"],
        now=caso["now"],
        random=caso["random"],
        retry_after=caso["retry_after"],
        policy=RetryPolicy(**opciones),
    )

    esperado = caso["expected"]
    if esperado["exhausted"]:
        assert resultado is None
    else:
        assert resultado is not None
        assert resultado.delay_seconds == esperado["delay_seconds"]
        assert resultado.next_at == esperado["next_at"]
