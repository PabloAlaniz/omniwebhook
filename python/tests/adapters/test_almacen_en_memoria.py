import pytest

from omniwebhook import AsyncMemoryIdempotencyStore, MemoryIdempotencyStore
from tests.contracts.idempotency_store import CASOS_DE_ALMACEN, reproducir, reproducir_async
from tests.support.vectors import Caso, nombre


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
def test_cumple_el_contrato(caso: Caso) -> None:
    reproducir(MemoryIdempotencyStore(), caso["steps"])


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
async def test_la_variante_asincrona_cumple_el_contrato(caso: Caso) -> None:
    await reproducir_async(AsyncMemoryIdempotencyStore(), caso["steps"])
