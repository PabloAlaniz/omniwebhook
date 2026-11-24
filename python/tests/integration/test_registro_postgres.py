"""El registro de entregas contra un PostgreSQL de verdad. Necesita `OMNIWEBHOOK_PG_URL`."""

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace

import pytest
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from omniwebhook import AttemptRecord, ConfigurationError
from omniwebhook.postgres import (
    AsyncPostgresDeliveryLedger,
    AsyncPsycopgClient,
    PostgresDeliveryLedger,
    PsycopgClient,
    postgres_ledger_schema,
)
from tests.support.salud import CASOS_DE_SALUD, intentos_mezclados, resumen_esperado
from tests.support.vectors import Caso, nombre

pytestmark = pytest.mark.integration
TABLA = "omniwebhook_attempts_test_py"

PENDIENTE = AttemptRecord(
    message_id="msg_1",
    endpoint_id="ep_1",
    attempt=1,
    at=1_700_000_000,
    delivery_class="retryable",
    state="pending",
    status=503,
    problem=None,
    duration_ms=40,
    next_at=1_700_000_005,
)
BLOQUEADO = replace(
    PENDIENTE,
    attempt=2,
    at=1_700_000_005,
    delivery_class="blocked",
    state="blocked",
    status=None,
    problem="blocked_address",
    duration_ms=0,
    next_at=None,
)


def _url() -> str:
    url = os.environ.get("OMNIWEBHOOK_PG_URL")
    if url is None:
        pytest.fail("Falta OMNIWEBHOOK_PG_URL: estos tests necesitan un PostgreSQL de prueba.")
    return url


@pytest.fixture(scope="module")
def pool() -> Iterator[ConnectionPool]:
    with ConnectionPool(_url(), min_size=1, max_size=4) as abierto:
        with abierto.connection() as conexion:
            conexion.execute(f"DROP TABLE IF EXISTS {TABLA}")
            conexion.execute(postgres_ledger_schema(TABLA))
            conexion.execute(postgres_ledger_schema(TABLA))
        yield abierto
        with abierto.connection() as conexion:
            conexion.execute(f"DROP TABLE IF EXISTS {TABLA}")


@pytest.fixture
def registro(pool: ConnectionPool) -> PostgresDeliveryLedger:
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA}")
    return PostgresDeliveryLedger(PsycopgClient(pool.connection), table=TABLA)


@pytest.fixture
async def registro_asincronico(pool: ConnectionPool) -> AsyncIterator[AsyncPostgresDeliveryLedger]:
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA}")
    async with AsyncConnectionPool(_url(), min_size=1, max_size=2) as abierto:
        yield AsyncPostgresDeliveryLedger(AsyncPsycopgClient(abierto.connection), table=TABLA)


def test_guarda_cada_intento_y_los_devuelve_tal_cual_en_orden(registro: PostgresDeliveryLedger) -> None:
    registro.record(PENDIENTE)
    registro.record(BLOQUEADO)
    registro.record(replace(PENDIENTE, endpoint_id="ep_2"))

    assert registro.attempts_of("msg_1", "ep_1") == [PENDIENTE, BLOQUEADO]


def test_un_reenvio_repite_el_numero_de_intento_sin_chocar(registro: PostgresDeliveryLedger) -> None:
    registro.record(PENDIENTE)
    registro.record(replace(PENDIENTE, at=PENDIENTE.at + 60, state="delivered", next_at=None))

    assert len(registro.attempts_of("msg_1", "ep_1")) == 2


def test_purge_before_borra_solo_lo_anterior(registro: PostgresDeliveryLedger) -> None:
    registro.record(PENDIENTE)
    registro.record(BLOQUEADO)

    assert registro.purge_before(BLOQUEADO.at) == 1
    assert registro.attempts_of("msg_1", "ep_1") == [BLOQUEADO]


async def test_la_variante_asincrona(registro_asincronico: AsyncPostgresDeliveryLedger) -> None:
    await registro_asincronico.record(PENDIENTE)
    await registro_asincronico.record(BLOQUEADO)

    assert await registro_asincronico.attempts_of("msg_1", "ep_1") == [PENDIENTE, BLOQUEADO]
    assert await registro_asincronico.purge_before(BLOQUEADO.at) == 1


@pytest.mark.parametrize("tabla", ["Intentos", "a b", "x; DROP TABLE y", ""])
def test_rechaza_un_nombre_de_tabla_invalido(pool: ConnectionPool, tabla: str) -> None:
    with pytest.raises(ConfigurationError, match="table"):
        PostgresDeliveryLedger(PsycopgClient(pool.connection), table=tabla)
    with pytest.raises(ConfigurationError, match="table"):
        postgres_ledger_schema(tabla)


def test_con_esquema_los_indices_van_sin_esquema_en_el_nombre() -> None:
    sql = postgres_ledger_schema("public.intentos")

    assert "CREATE TABLE IF NOT EXISTS public.intentos" in sql
    assert "intentos_message_idx ON public.intentos" in sql


@pytest.mark.parametrize("caso", CASOS_DE_SALUD, ids=nombre)
def test_el_resumen_de_fallos_de_un_destino(pool: ConnectionPool, caso: Caso) -> None:
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA} RESTART IDENTITY")
    registro = PostgresDeliveryLedger(PsycopgClient(pool.connection), table=TABLA)
    for registrado in intentos_mezclados(caso):
        registro.record(registrado)

    assert registro.failures_of("ep_1", caso["since"]) == resumen_esperado(caso)


async def test_el_resumen_de_fallos_asincronico(pool: ConnectionPool) -> None:
    caso = next(caso for caso in CASOS_DE_SALUD if caso["name"] == "un 410 pesa más que la racha")
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA} RESTART IDENTITY")
    async with AsyncConnectionPool(_url(), min_size=1, max_size=2) as abierto:
        registro = AsyncPostgresDeliveryLedger(AsyncPsycopgClient(abierto.connection), table=TABLA)
        for registrado in intentos_mezclados(caso):
            await registro.record(registrado)

        assert await registro.failures_of("ep_1", caso["since"]) == resumen_esperado(caso)
