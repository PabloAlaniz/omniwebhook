"""Emitir sin perder eventos: encolar en la transacción del negocio y despachar aparte.

Hace las dos mitades de una bandeja de salida, una después de la otra:

1. Registra un pedido y encola su webhook en la misma transacción. Si la transacción no se
   confirma, no hay pedido ni webhook; si se confirma, el webhook no se pierde aunque el
   proceso se caiga en la línea siguiente.
2. Despacha una tanda: toma lo pendiente, lo firma, lo envía y lo cierra con el resultado.
   En producción esta mitad corre aparte, llamada cada pocos segundos desde un cron, una
   cola o un bucle.

Variables de entorno: `OMNIWEBHOOK_PG_URL`, `WEBHOOK_SIGNING_SECRET`, `ENDPOINT_URL` y, sólo
para probar contra un receptor local, `ALLOW_LOCAL=1`.
"""

import json
import os
import sys

import psycopg

from omniwebhook import EnqueueRequest, ResolvedEndpoint, create_dispatcher, create_sender, random_message_id
from omniwebhook.adapters.clock import system_clock
from omniwebhook.postgres import (
    PostgresDeliveryLedger,
    PostgresOutbox,
    PsycopgClient,
    PsycopgConnectionClient,
    postgres_ledger_schema,
    postgres_outbox_schema,
)
from omniwebhook.standard import native_signer, standard_signer

URL = os.environ["OMNIWEBHOOK_PG_URL"]
LOCAL = os.environ.get("ALLOW_LOCAL") == "1"


class Endpoints:
    """Dónde viven tus destinos. La bandeja guarda sólo el identificador, nunca la URL."""

    def resolve(self, endpoint_id: str) -> ResolvedEndpoint | None:
        # En una aplicación real es una consulta a tu tabla de destinos; uno deshabilitado
        # devuelve None y su entrega se cancela.
        return ResolvedEndpoint(os.environ["ENDPOINT_URL"]) if endpoint_id == "ep_cliente_1" else None


def register_order(order_id: str) -> None:
    payload = json.dumps({"id": random_message_id(), "type": "pedido.creado", "pedido": order_id})
    with psycopg.connect(URL) as connection:
        # Una sola transacción: el cambio del negocio y el webhook que lo anuncia.
        connection.execute("INSERT INTO ejemplo_pedidos (id) VALUES (%s)", (order_id,))
        PostgresOutbox(PsycopgConnectionClient(connection)).enqueue(
            EnqueueRequest(
                message_id=json.loads(payload)["id"],
                endpoint_id="ep_cliente_1",
                payload=payload.encode("utf-8"),
                now=system_clock.now(),
            )
        )


def dispatch_batch() -> int:
    def connection() -> psycopg.Connection:
        return psycopg.connect(URL)

    client = PsycopgClient(connection)
    dispatcher = create_dispatcher(
        outbox=PostgresOutbox(client),
        endpoints=Endpoints(),
        sender=create_sender(
            signer=standard_signer(secrets=[os.environ["WEBHOOK_SIGNING_SECRET"]], signer=native_signer),
            ledger=PostgresDeliveryLedger(client),
            # Sólo para probar contra un receptor en esta máquina. Por defecto se entrega
            # nada más que a https y a direcciones públicas.
            allow_http=LOCAL,
            allowed_networks=["127.0.0.0/8"] if LOCAL else [],
        ),
    )
    result = dispatcher.execute()
    for dispatched in result.dispatched:
        print(f"despachado {dispatched.endpoint_id} intento {dispatched.attempt}: {dispatched.state}")
    for failure in result.failures:
        print(f"sin intentar {failure.endpoint_id}: {failure.error}", file=sys.stderr)
    return len(result.dispatched)


if __name__ == "__main__":
    with psycopg.connect(URL) as setup:
        setup.execute("CREATE TABLE IF NOT EXISTS ejemplo_pedidos (id text PRIMARY KEY)")
        setup.execute(postgres_outbox_schema())
        setup.execute(postgres_ledger_schema())
    register_order(sys.argv[1] if len(sys.argv) > 1 else "pedido-1")
    dispatch_batch()
