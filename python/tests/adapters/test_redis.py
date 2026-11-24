import re
from pathlib import Path
from typing import Any

import pytest

from omniwebhook import ClaimRequest, CompleteRequest, ConfigurationError, ReleaseRequest
from omniwebhook.adapters.stores.redis import CLAIM_SCRIPT, COMPLETE_SCRIPT, RELEASE_SCRIPT
from omniwebhook.redis import AsyncRedisIdempotencyStore, RedisIdempotencyStore

RAIZ = Path(__file__).resolve().parents[3]


class Cliente:
    """Un cliente que anota lo que le piden y responde lo que se le indica."""

    def __init__(self, respuesta: object) -> None:
        self.respuesta = respuesta
        self.pedidos: list[tuple[Any, ...]] = []

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        self.pedidos.append((script, numkeys, *keys_and_args))
        return self.respuesta


class ClienteAsincronico(Cliente):
    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        return super().eval(script, numkeys, *keys_and_args)


def test_los_scripts_son_los_mismos_que_en_el_paquete_de_typescript() -> None:
    fuente = (RAIZ / "ts" / "src" / "adapters" / "stores" / "redis.ts").read_text(encoding="utf-8")
    scripts = dict(re.findall(r"const (CLAIM|COMPLETE|RELEASE) = `(.*?)`;", fuente, re.DOTALL))

    assert scripts == {"CLAIM": CLAIM_SCRIPT, "COMPLETE": COMPLETE_SCRIPT, "RELEASE": RELEASE_SCRIPT}


def test_arma_las_claves_y_los_argumentos_de_cada_script() -> None:
    cliente = Cliente(1)
    almacen = RedisIdempotencyStore(cliente, prefix="p:", grace_seconds=60)

    almacen.complete(CompleteRequest(key="k", token="t", now=100, retention_seconds=50))
    almacen.release(ReleaseRequest(key="k", token="t"))
    cliente.respuesta = b"claimed"
    almacen.claim(ClaimRequest(key="k", token="t", now=100, lease_seconds=30))

    assert cliente.pedidos == [
        (COMPLETE_SCRIPT, 1, "p:k", "t", "150", "50"),
        (RELEASE_SCRIPT, 1, "p:k", "t"),
        (CLAIM_SCRIPT, 1, "p:k", "t", "100", "130", "90"),
    ]


@pytest.mark.parametrize("respuesta", ["claimed", b"duplicate", "in_progress"])
def test_entiende_la_respuesta_como_texto_o_como_bytes(respuesta: str | bytes) -> None:
    almacen = RedisIdempotencyStore(Cliente(respuesta))
    esperado = respuesta.decode() if isinstance(respuesta, bytes) else respuesta

    assert almacen.claim(ClaimRequest(key="k", token="t", now=1, lease_seconds=1)) == esperado


def test_una_respuesta_inesperada_es_un_error_y_no_un_resultado() -> None:
    with pytest.raises(RuntimeError, match="inesperada"):
        RedisIdempotencyStore(Cliente("otra-cosa")).claim(
            ClaimRequest(key="k", token="t", now=1, lease_seconds=1)
        )


def test_completar_y_liberar_dicen_si_se_aplico() -> None:
    aplicado, sin_aplicar = RedisIdempotencyStore(Cliente(1)), RedisIdempotencyStore(Cliente(0))
    completar = CompleteRequest(key="k", token="t", now=1, retention_seconds=1)
    liberar = ReleaseRequest(key="k", token="t")

    assert (aplicado.complete(completar), aplicado.release(liberar)) == (True, True)
    assert (sin_aplicar.complete(completar), sin_aplicar.release(liberar)) == (False, False)


async def test_la_variante_asincronica_hace_lo_mismo() -> None:
    cliente = ClienteAsincronico("claimed")
    almacen = AsyncRedisIdempotencyStore(cliente, prefix="p:")

    assert await almacen.claim(ClaimRequest(key="k", token="t", now=1, lease_seconds=1)) == "claimed"
    cliente.respuesta = 1
    assert await almacen.complete(CompleteRequest(key="k", token="t", now=1, retention_seconds=1))
    assert await almacen.release(ReleaseRequest(key="k", token="t"))
    assert [pedido[2] for pedido in cliente.pedidos] == ["p:k", "p:k", "p:k"]


@pytest.mark.parametrize("opciones", [{"prefix": ""}, {"grace_seconds": -1}, {"grace_seconds": 1.5}])
def test_rechaza_una_configuracion_invalida(opciones: dict[str, Any]) -> None:
    with pytest.raises(ConfigurationError):
        RedisIdempotencyStore(Cliente(1), **opciones)
