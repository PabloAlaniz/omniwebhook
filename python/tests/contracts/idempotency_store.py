"""El contrato que cumple todo almacén de reservas: los vectores de `reservas/almacen`."""

from collections.abc import Sequence

from omniwebhook import (
    AsyncIdempotencyStore,
    ClaimRequest,
    CompleteRequest,
    IdempotencyStore,
    ReleaseRequest,
)
from tests.support.vectors import Caso, casos

CASOS_DE_ALMACEN = casos("reservas/almacen")


def _pedido(paso: Caso) -> ClaimRequest | CompleteRequest | ReleaseRequest:
    if paso["op"] == "claim":
        return ClaimRequest(
            key=paso["key"], token=paso["token"], now=paso["now"], lease_seconds=paso["lease_seconds"]
        )
    if paso["op"] == "complete":
        return CompleteRequest(
            key=paso["key"], token=paso["token"], now=paso["now"], retention_seconds=paso["retention_seconds"]
        )
    return ReleaseRequest(key=paso["key"], token=paso["token"])


def reproducir(store: IdempotencyStore, pasos: Sequence[Caso]) -> None:
    """Ejecuta los pasos de un vector contra un almacén y comprueba cada resultado."""
    for numero, paso in enumerate(pasos, start=1):
        pedido = _pedido(paso)
        resultado: object
        if isinstance(pedido, ClaimRequest):
            resultado = store.claim(pedido)
        elif isinstance(pedido, CompleteRequest):
            resultado = store.complete(pedido)
        else:
            resultado = store.release(pedido)
        assert resultado == paso["expected"], f"paso {numero} ({paso['op']})"


async def reproducir_async(store: AsyncIdempotencyStore, pasos: Sequence[Caso]) -> None:
    for numero, paso in enumerate(pasos, start=1):
        pedido = _pedido(paso)
        resultado: object
        if isinstance(pedido, ClaimRequest):
            resultado = await store.claim(pedido)
        elif isinstance(pedido, CompleteRequest):
            resultado = await store.complete(pedido)
        else:
            resultado = await store.release(pedido)
        assert resultado == paso["expected"], f"paso {numero} ({paso['op']})"
