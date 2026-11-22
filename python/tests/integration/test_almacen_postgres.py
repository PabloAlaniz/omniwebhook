"""Contra un PostgreSQL de verdad. Necesita `OMNIWEBHOOK_PG_URL`."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from omniwebhook import ClaimRequest, ConfigurationError
from omniwebhook.postgres import (
    AsyncPostgresIdempotencyStore,
    AsyncPsycopgClient,
    PostgresIdempotencyStore,
    PsycopgClient,
    postgres_store_schema,
)
from tests.contracts.idempotency_store import CASOS_DE_ALMACEN, reproducir, reproducir_async
from tests.support.vectors import Caso, nombre

pytestmark = pytest.mark.integration
TABLA = "omniwebhook_events_test_py"


def _url() -> str:
    url = os.environ.get("OMNIWEBHOOK_PG_URL")
    if url is None:
        pytest.fail("Falta OMNIWEBHOOK_PG_URL: estos tests necesitan un PostgreSQL de prueba.")
    return url


@pytest.fixture(scope="module")
def pool() -> Iterator[ConnectionPool]:
    with ConnectionPool(_url(), min_size=1, max_size=8) as abierto:
        with abierto.connection() as conexion:
            conexion.execute(f"DROP TABLE IF EXISTS {TABLA}")
            conexion.execute(postgres_store_schema(TABLA))
            conexion.execute(postgres_store_schema(TABLA))
        yield abierto
        with abierto.connection() as conexion:
            conexion.execute(f"DROP TABLE IF EXISTS {TABLA}")


@pytest.fixture
def almacen(pool: ConnectionPool) -> PostgresIdempotencyStore:
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA}")
    return PostgresIdempotencyStore(PsycopgClient(pool.connection), table=TABLA)


@pytest.fixture
async def almacen_asincronico(pool: ConnectionPool) -> AsyncIterator[AsyncPostgresIdempotencyStore]:
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA}")
    async with AsyncConnectionPool(_url(), min_size=1, max_size=8) as abierto:
        yield AsyncPostgresIdempotencyStore(AsyncPsycopgClient(abierto.connection), table=TABLA)


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
def test_cumple_el_contrato(almacen: PostgresIdempotencyStore, caso: Caso) -> None:
    reproducir(almacen, caso["steps"])


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
async def test_la_variante_asincrona_cumple_el_contrato(
    almacen_asincronico: AsyncPostgresIdempotencyStore, caso: Caso
) -> None:
    await reproducir_async(almacen_asincronico, caso["steps"])


def _pedido(numero: int) -> ClaimRequest:
    return ClaimRequest(key="carrera", token=f"t-{numero}", now=1000, lease_seconds=60)


def test_entre_pedidos_simultaneos_por_la_misma_clave_uno_solo_la_reserva(
    almacen: PostgresIdempotencyStore,
) -> None:
    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(lambda n: almacen.claim(_pedido(n)), range(20)))

    assert sorted(resultados) == ["claimed"] + ["in_progress"] * 19


async def test_entre_tareas_simultaneas_por_la_misma_clave_una_sola_la_reserva(
    almacen_asincronico: AsyncPostgresIdempotencyStore,
) -> None:
    resultados = await asyncio.gather(*(almacen_asincronico.claim(_pedido(n)) for n in range(20)))

    assert sorted(resultados) == ["claimed"] + ["in_progress"] * 19


def test_purge_expired_borra_solo_lo_vencido(almacen: PostgresIdempotencyStore) -> None:
    almacen.claim(ClaimRequest(key="vieja", token="a", now=1000, lease_seconds=10))
    almacen.claim(ClaimRequest(key="vigente", token="a", now=1000, lease_seconds=500))

    assert almacen.purge_expired(1010) == 1
    assert almacen.claim(ClaimRequest(key="vigente", token="b", now=1011, lease_seconds=10)) == "in_progress"


async def test_purge_expired_en_la_variante_asincrona(
    almacen_asincronico: AsyncPostgresIdempotencyStore,
) -> None:
    await almacen_asincronico.claim(ClaimRequest(key="vieja", token="a", now=1000, lease_seconds=10))

    assert await almacen_asincronico.purge_expired(1010) == 1
    assert await almacen_asincronico.purge_expired(1010) == 0


@pytest.mark.parametrize("tabla", ["Eventos", "a b", "x; DROP TABLE y", ""])
def test_rechaza_un_nombre_de_tabla_invalido(pool: ConnectionPool, tabla: str) -> None:
    with pytest.raises(ConfigurationError, match="table"):
        PostgresIdempotencyStore(PsycopgClient(pool.connection), table=tabla)
    with pytest.raises(ConfigurationError, match="table"):
        postgres_store_schema(tabla)


def test_acepta_una_tabla_con_esquema() -> None:
    assert "public.eventos" in postgres_store_schema("public.eventos")
