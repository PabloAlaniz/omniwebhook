import sqlite3
from contextlib import closing

import pytest

from omniwebhook import (
    AsyncMemoryDeliveryLedger,
    ConfigurationError,
    FailureSummary,
    HealthPolicy,
    MemoryDeliveryLedger,
    endpoint_health,
    summarize_failures,
)
from omniwebhook.sqlite import Sqlite3Client, SqliteDeliveryLedger, sqlite_ledger_schema
from tests.support.salud import (
    CASOS_DE_SALUD,
    intento,
    intentos_mezclados,
    politica,
    resumen_esperado,
    salud_esperada,
)
from tests.support.vectors import Caso, nombre


@pytest.mark.parametrize("caso", CASOS_DE_SALUD, ids=nombre)
def test_vectores(caso: Caso) -> None:
    intentos = [intento("ep_1", numero, datos) for numero, datos in enumerate(caso["attempts"])]

    resumen = summarize_failures(intentos, caso["since"])

    assert resumen == resumen_esperado(caso)
    assert endpoint_health(resumen, caso["now"], politica(caso)) == salud_esperada(caso)


@pytest.mark.parametrize("caso", CASOS_DE_SALUD, ids=nombre)
async def test_el_registro_en_memoria_da_el_mismo_resumen(caso: Caso) -> None:
    registro, asincronico = MemoryDeliveryLedger(), AsyncMemoryDeliveryLedger()
    for registrado in intentos_mezclados(caso):
        registro.record(registrado)
        await asincronico.record(registrado)

    assert registro.failures_of("ep_1", caso["since"]) == resumen_esperado(caso)
    assert await asincronico.failures_of("ep_1", caso["since"]) == resumen_esperado(caso)


@pytest.mark.parametrize("caso", CASOS_DE_SALUD, ids=nombre)
def test_el_registro_sobre_sqlite_da_el_mismo_resumen(caso: Caso) -> None:
    with closing(sqlite3.connect(":memory:")) as conexion:
        conexion.executescript(sqlite_ledger_schema())
        registro = SqliteDeliveryLedger(Sqlite3Client(conexion))
        for registrado in intentos_mezclados(caso):
            registro.record(registrado)

        assert registro.failures_of("ep_1", caso["since"]) == resumen_esperado(caso)


@pytest.mark.parametrize("opciones", [{"window_seconds": 0}, {"min_failures": 1.5}])
def test_rechaza_una_politica_invalida(opciones: dict[str, int]) -> None:
    with pytest.raises(ConfigurationError, match=next(iter(opciones))):
        HealthPolicy(**opciones)


def test_sin_politica_usa_la_de_la_especificacion() -> None:
    cinco_dias = FailureSummary(failures=5, failing_since=0)

    assert endpoint_health(cinco_dias, 432_000).status == "disabled"
    assert endpoint_health(cinco_dias, 431_999).status == "failing"
