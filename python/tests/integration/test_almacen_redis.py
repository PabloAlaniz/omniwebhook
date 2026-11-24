"""Contra un Redis de verdad. Necesita `OMNIWEBHOOK_REDIS_URL`."""

import os
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis
import redis.asyncio

from omniwebhook import ClaimRequest, CompleteRequest
from omniwebhook.redis import AsyncRedisIdempotencyStore, RedisIdempotencyStore
from tests.contracts.idempotency_store import CASOS_DE_ALMACEN, reproducir, reproducir_async
from tests.support.vectors import Caso, nombre

pytestmark = pytest.mark.integration
PREFIJO = "omniwebhook:test:py:"
AHORA = 1_700_000_000


def _url() -> str:
    url = os.environ.get("OMNIWEBHOOK_REDIS_URL")
    if url is None:
        pytest.fail("Falta OMNIWEBHOOK_REDIS_URL: estos tests necesitan un Redis de prueba.")
    return url


def _limpiar(cliente: "redis.Redis") -> None:
    claves = cliente.keys(f"{PREFIJO}*")
    if claves:
        cliente.delete(*claves)


@pytest.fixture
def cliente() -> Iterator["redis.Redis"]:
    abierto = redis.Redis.from_url(_url())
    _limpiar(abierto)
    yield abierto
    _limpiar(abierto)
    abierto.close()


@pytest.fixture
async def cliente_asincronico(cliente: "redis.Redis") -> AsyncIterator["redis.asyncio.Redis"]:
    abierto = redis.asyncio.Redis.from_url(_url(), decode_responses=True)
    yield abierto
    await abierto.aclose()


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
def test_contrato(cliente: "redis.Redis", caso: Caso) -> None:
    reproducir(RedisIdempotencyStore(cliente, prefix=PREFIJO), caso["steps"])


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
async def test_contrato_asincronico(cliente_asincronico: "redis.asyncio.Redis", caso: Caso) -> None:
    await reproducir_async(AsyncRedisIdempotencyStore(cliente_asincronico, prefix=PREFIJO), caso["steps"])


def test_entre_pedidos_simultaneos_por_la_misma_clave_uno_solo_la_reserva(cliente: "redis.Redis") -> None:
    almacen = RedisIdempotencyStore(cliente, prefix=PREFIJO)

    def reservar(numero: int) -> str:
        return almacen.claim(
            ClaimRequest(key="evt:carrera", token=f"t-{numero}", now=AHORA, lease_seconds=300)
        )

    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(reservar, range(20)))

    assert resultados.count("claimed") == 1
    assert resultados.count("in_progress") == 19


def test_las_entradas_se_borran_solas(cliente: "redis.Redis") -> None:
    almacen = RedisIdempotencyStore(cliente, prefix=PREFIJO, grace_seconds=60)

    almacen.claim(ClaimRequest(key="evt:ttl", token="t-1", now=AHORA, lease_seconds=300))
    assert 300 < cliente.ttl(f"{PREFIJO}evt:ttl") <= 360

    almacen.complete(CompleteRequest(key="evt:ttl", token="t-1", now=AHORA, retention_seconds=1000))
    assert cliente.ttl(f"{PREFIJO}evt:ttl") > 900
    assert cliente.hgetall(f"{PREFIJO}evt:ttl") == {
        b"state": b"completed",
        b"token": b"t-1",
        b"expires_at": str(AHORA + 1000).encode(),
    }
