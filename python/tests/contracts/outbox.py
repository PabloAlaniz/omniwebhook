"""El contrato que cumple toda bandeja de salida: los vectores de `entregar/bandeja`."""

from collections.abc import Sequence

from omniwebhook import (
    AsyncOutbox,
    EnqueueRequest,
    Outbox,
    OutboxClaimRequest,
    OutboxEntry,
    RequeueRequest,
    SettleRequest,
)
from tests.support.vectors import Caso, casos

CASOS_DE_BANDEJA = casos("entregar/bandeja")

Pedido = EnqueueRequest | OutboxClaimRequest | SettleRequest | RequeueRequest


def _pedido(paso: Caso) -> Pedido:
    if paso["op"] == "enqueue":
        return EnqueueRequest(
            message_id=paso["message_id"],
            endpoint_id=paso["endpoint_id"],
            payload=paso["payload"].encode("utf-8"),
            now=paso["now"],
        )
    if paso["op"] == "claim":
        return OutboxClaimRequest(
            token=paso["token"], now=paso["now"], limit=paso["limit"], lease_seconds=paso["lease_seconds"]
        )
    if paso["op"] == "requeue":
        return RequeueRequest(
            endpoint_id=paso["endpoint_id"], since=paso["from"], until=paso["to"], now=paso["now"]
        )
    return SettleRequest(
        message_id=paso["message_id"],
        endpoint_id=paso["endpoint_id"],
        token=paso["token"],
        state=paso["state"],
        next_at=paso.get("next_at"),
    )


def _vistas(entradas: Sequence[OutboxEntry]) -> list[dict[str, object]]:
    return [
        {
            "message_id": entrada.message_id,
            "endpoint_id": entrada.endpoint_id,
            "payload": entrada.payload.decode("utf-8"),
            "attempt": entrada.attempt,
        }
        for entrada in entradas
    ]


def reproducir_bandeja(bandeja: Outbox, pasos: Sequence[Caso]) -> None:
    """Ejecuta los pasos de un vector contra una bandeja y comprueba cada resultado."""
    for numero, paso in enumerate(pasos, start=1):
        pedido = _pedido(paso)
        resultado: object
        if isinstance(pedido, EnqueueRequest):
            resultado = bandeja.enqueue(pedido)
        elif isinstance(pedido, OutboxClaimRequest):
            resultado = _vistas(bandeja.claim(pedido))
        elif isinstance(pedido, RequeueRequest):
            resultado = bandeja.requeue(pedido)
        else:
            resultado = bandeja.settle(pedido)
        assert resultado == paso["expected"], f"paso {numero} ({paso['op']})"


async def reproducir_bandeja_async(bandeja: AsyncOutbox, pasos: Sequence[Caso]) -> None:
    for numero, paso in enumerate(pasos, start=1):
        pedido = _pedido(paso)
        resultado: object
        if isinstance(pedido, EnqueueRequest):
            resultado = await bandeja.enqueue(pedido)
        elif isinstance(pedido, OutboxClaimRequest):
            resultado = _vistas(await bandeja.claim(pedido))
        elif isinstance(pedido, RequeueRequest):
            resultado = await bandeja.requeue(pedido)
        else:
            resultado = await bandeja.settle(pedido)
        assert resultado == paso["expected"], f"paso {numero} ({paso['op']})"
