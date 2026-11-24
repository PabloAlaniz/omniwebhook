"""Contra un PostgreSQL de verdad. Necesita `OMNIWEBHOOK_PG_URL`."""

import os
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from omniwebhook import ConfigurationError, EnqueueRequest, OutboxClaimRequest, OutboxEntry, SettleRequest
from omniwebhook.postgres import (
    AsyncPostgresOutbox,
    AsyncPsycopgClient,
    AsyncPsycopgConnectionClient,
    PostgresOutbox,
    PsycopgClient,
    PsycopgConnectionClient,
    postgres_outbox_schema,
)
from tests.contracts.outbox import CASOS_DE_BANDEJA, reproducir_bandeja, reproducir_bandeja_async
from tests.support.vectors import Caso, nombre

pytestmark = pytest.mark.integration
TABLA = "omniwebhook_outbox_test_py"
AHORA = 1_700_000_000
CUERPO = b'{"n":1}'


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
            conexion.execute(postgres_outbox_schema(TABLA))
            conexion.execute(postgres_outbox_schema(TABLA))
        yield abierto
        with abierto.connection() as conexion:
            conexion.execute(f"DROP TABLE IF EXISTS {TABLA}")


@pytest.fixture
def bandeja(pool: ConnectionPool) -> PostgresOutbox:
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA} RESTART IDENTITY")
    return PostgresOutbox(PsycopgClient(pool.connection), table=TABLA)


@pytest.fixture
async def asincronico(pool: ConnectionPool) -> AsyncIterator[AsyncConnectionPool]:
    with pool.connection() as conexion:
        conexion.execute(f"TRUNCATE {TABLA} RESTART IDENTITY")
    async with AsyncConnectionPool(_url(), min_size=1, max_size=8) as abierto:
        yield abierto


def _encolar(mensaje: str, cuerpo: bytes = CUERPO) -> EnqueueRequest:
    return EnqueueRequest(message_id=mensaje, endpoint_id="ep_1", payload=cuerpo, now=AHORA)


def _tomar(token: str, limite: int = 10) -> OutboxClaimRequest:
    return OutboxClaimRequest(token=token, now=AHORA, limit=limite, lease_seconds=300)


@pytest.mark.parametrize("caso", CASOS_DE_BANDEJA, ids=nombre)
def test_contrato(bandeja: PostgresOutbox, caso: Caso) -> None:
    reproducir_bandeja(bandeja, caso["steps"])


@pytest.mark.parametrize("caso", CASOS_DE_BANDEJA, ids=nombre)
async def test_contrato_asincronico(asincronico: AsyncConnectionPool, caso: Caso) -> None:
    await reproducir_bandeja_async(
        AsyncPostgresOutbox(AsyncPsycopgClient(asincronico.connection), table=TABLA), caso["steps"]
    )


def test_entre_tomas_simultaneas_cada_entrega_la_toma_un_solo_proceso(bandeja: PostgresOutbox) -> None:
    for numero in range(50):
        bandeja.enqueue(_encolar(f"msg_{numero}"))

    with ThreadPoolExecutor(max_workers=8) as hilos:
        tandas = list(hilos.map(lambda numero: bandeja.claim(_tomar(f"d-{numero}", 5)), range(20)))

    tomadas = [entrada.message_id for tanda in tandas for entrada in tanda]
    assert len(set(tomadas)) == len(tomadas)
    assert tomadas
    # Lo que una tanda no alcanzó a ver por estar bloqueado queda para la siguiente.
    assert len(tomadas) + len(bandeja.claim(_tomar("d-final", 100))) == 50


def test_lo_encolado_en_una_transaccion_que_se_deshace_no_existe(
    pool: ConnectionPool, bandeja: PostgresOutbox
) -> None:
    with pool.connection() as conexion:
        PostgresOutbox(PsycopgConnectionClient(conexion), table=TABLA).enqueue(_encolar("msg_1"))
        conexion.rollback()

    assert bandeja.claim(_tomar("d-1")) == []


def test_lo_encolado_en_una_transaccion_confirmada_sale_byte_a_byte(
    pool: ConnectionPool, bandeja: PostgresOutbox
) -> None:
    cuerpo = bytes([0, 255, 10, 13, 128])
    with pool.connection() as conexion:
        assert PostgresOutbox(PsycopgConnectionClient(conexion), table=TABLA).enqueue(
            _encolar("msg_1", cuerpo)
        )

    assert bandeja.claim(_tomar("d-1")) == [
        OutboxEntry(message_id="msg_1", endpoint_id="ep_1", payload=cuerpo, attempt=1)
    ]


async def test_encolar_en_una_transaccion_asincronica(
    asincronico: AsyncConnectionPool, bandeja: PostgresOutbox
) -> None:
    async with asincronico.connection() as conexion:
        en_transaccion = AsyncPostgresOutbox(AsyncPsycopgConnectionClient(conexion), table=TABLA)
        assert await en_transaccion.enqueue(_encolar("msg_1"))
        assert not await en_transaccion.enqueue(_encolar("msg_1"))

    assert [entrada.message_id for entrada in bandeja.claim(_tomar("d-1"))] == ["msg_1"]


def test_purga_solo_las_entregas_cerradas_y_viejas(bandeja: PostgresOutbox) -> None:
    bandeja.enqueue(_encolar("cerrada"))
    bandeja.enqueue(_encolar("pendiente"))
    bandeja.claim(_tomar("d-1", 1))
    bandeja.settle(SettleRequest(message_id="cerrada", endpoint_id="ep_1", token="d-1", state="delivered"))

    assert bandeja.purge_settled_before(AHORA) == 0
    assert bandeja.purge_settled_before(AHORA + 1) == 1
    assert [entrada.message_id for entrada in bandeja.claim(_tomar("d-2"))] == ["pendiente"]


async def test_la_purga_asincronica(asincronico: AsyncConnectionPool) -> None:
    bandeja = AsyncPostgresOutbox(AsyncPsycopgClient(asincronico.connection), table=TABLA)
    await bandeja.enqueue(_encolar("msg_1"))
    await bandeja.claim(_tomar("d-1"))
    await bandeja.settle(SettleRequest(message_id="msg_1", endpoint_id="ep_1", token="d-1", state="gone"))

    assert await bandeja.purge_settled_before(AHORA + 1) == 1


def test_rechaza_un_nombre_de_tabla_que_no_es_un_identificador(pool: ConnectionPool) -> None:
    with pytest.raises(ConfigurationError):
        PostgresOutbox(PsycopgClient(pool.connection), table="x; DROP TABLE y")
    with pytest.raises(ConfigurationError):
        postgres_outbox_schema("X")
