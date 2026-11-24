import json
from typing import Any

import pytest

from omniwebhook import ClaimRequest, CompleteRequest, ConfigurationError, ReleaseRequest
from omniwebhook.key_value import (
    AsyncDynamoDbTableClient,
    AsyncKeyValueIdempotencyStore,
    AsyncMemoryKeyValueClient,
    DynamoDbTableClient,
    KeyValueIdempotencyStore,
    KeyValueRecord,
    MemoryKeyValueClient,
)
from tests.contracts.idempotency_store import CASOS_DE_ALMACEN, reproducir, reproducir_async
from tests.support.vectors import Caso, nombre

AHORA = 1_700_000_000


class CondicionFallida(Exception):
    """Tiene la forma del error que lanza la librería del servicio."""

    def __init__(self) -> None:
        super().__init__("condición")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Tabla:
    """Una tabla en memoria que cumple las dos condiciones que usa el adaptador de DynamoDB."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.pedidos: list[dict[str, Any]] = []

    def _cumple(self, actual: dict[str, Any] | None, pedido: dict[str, Any]) -> bool:
        if pedido["ConditionExpression"] == "attribute_not_exists(#k)":
            return actual is None
        return actual is not None and actual["version"] == pedido["ExpressionAttributeValues"][":expected"]

    def get_item(self, **pedido: Any) -> dict[str, Any]:
        self.pedidos.append(pedido)
        item = self.items.get(next(iter(pedido["Key"].values())))
        return {} if item is None else {"Item": item}

    def put_item(self, **pedido: Any) -> None:
        clave = pedido["Item"].get("pk") or pedido["Item"]["id"]
        if not self._cumple(self.items.get(clave), pedido):
            raise CondicionFallida
        self.items[clave] = pedido["Item"]

    def delete_item(self, **pedido: Any) -> None:
        clave = next(iter(pedido["Key"].values()))
        if not self._cumple(self.items.get(clave), pedido):
            raise CondicionFallida
        del self.items[clave]


class TablaAsincronica:
    def __init__(self) -> None:
        self.tabla = Tabla()

    async def get_item(self, **pedido: Any) -> dict[str, Any]:
        return self.tabla.get_item(**pedido)

    async def put_item(self, **pedido: Any) -> None:
        self.tabla.put_item(**pedido)

    async def delete_item(self, **pedido: Any) -> None:
        self.tabla.delete_item(**pedido)


class SinCondicion:
    """Un almacén sin escritura condicional: ignora `only_if`."""

    conditional = False

    def __init__(self) -> None:
        self.valores: dict[str, str] = {}
        self.vencimientos: dict[str, int] = {}

    def get(self, key: str) -> KeyValueRecord | None:
        return KeyValueRecord(self.valores[key], "") if key in self.valores else None

    def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool:
        self.valores[key] = value
        self.vencimientos[key] = ttl_seconds
        return True

    def delete(self, key: str, *, only_if: str) -> bool:
        self.valores.pop(key, None)
        return True


def _reservar(token: str, ahora: int = AHORA) -> ClaimRequest:
    return ClaimRequest(key="evt:1", token=token, now=ahora, lease_seconds=300)


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
@pytest.mark.parametrize("cliente", ["memoria", "dynamodb", "sin condición"])
def test_contrato(cliente: str, caso: Caso) -> None:
    clientes: dict[str, Any] = {
        "memoria": MemoryKeyValueClient,
        "dynamodb": lambda: DynamoDbTableClient(Tabla()),
        "sin condición": SinCondicion,
    }
    reproducir(KeyValueIdempotencyStore(clientes[cliente]()), caso["steps"])


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
@pytest.mark.parametrize("cliente", ["memoria", "dynamodb"])
async def test_contrato_asincronico(cliente: str, caso: Caso) -> None:
    clientes: dict[str, Any] = {
        "memoria": AsyncMemoryKeyValueClient,
        "dynamodb": lambda: AsyncDynamoDbTableClient(TablaAsincronica()),
    }
    await reproducir_async(AsyncKeyValueIdempotencyStore(clientes[cliente]()), caso["steps"])


def test_dice_que_garantia_da_segun_el_cliente() -> None:
    assert KeyValueIdempotencyStore(MemoryKeyValueClient()).guarantee == "atomic"
    assert KeyValueIdempotencyStore(SinCondicion()).guarantee == "best-effort"


class Entrometido(MemoryKeyValueClient):
    """Deja que otro proceso actúe justo después de la primera lectura."""

    def __init__(self) -> None:
        super().__init__()
        self.despues_de_leer: Any = None

    def get(self, key: str) -> KeyValueRecord | None:
        leido = super().get(key)
        if self.despues_de_leer is not None:
            accion, self.despues_de_leer = self.despues_de_leer, None
            accion()
        return leido


def test_si_pierde_la_escritura_vuelve_a_mirar_quien_gano_la_tiene_en_curso() -> None:
    cliente = Entrometido()
    almacen, rival = KeyValueIdempotencyStore(cliente), KeyValueIdempotencyStore(cliente)
    cliente.despues_de_leer = lambda: rival.claim(_reservar("t-rival"))

    assert almacen.claim(_reservar("t-lento")) == "in_progress"
    assert rival.complete(CompleteRequest(key="evt:1", token="t-rival", now=AHORA, retention_seconds=60))
    assert almacen.claim(_reservar("t-lento")) == "duplicate"


def test_quien_perdio_su_reserva_no_pisa_a_quien_la_tomo_despues() -> None:
    cliente = Entrometido()
    almacen = KeyValueIdempotencyStore(cliente)
    almacen.claim(_reservar("t-viejo"))
    cliente.despues_de_leer = lambda: almacen.claim(_reservar("t-nuevo", AHORA + 301))

    assert not almacen.complete(
        CompleteRequest(key="evt:1", token="t-viejo", now=AHORA + 302, retention_seconds=60)
    )
    assert almacen.release(ReleaseRequest(key="evt:1", token="t-nuevo"))


class SiemprePierde:
    conditional = True

    def __init__(self) -> None:
        self.intentos = 0

    def get(self, key: str) -> KeyValueRecord | None:
        return None

    def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool:
        self.intentos += 1
        return False

    def delete(self, key: str, *, only_if: str) -> bool:
        return False


def test_si_la_escritura_se_pierde_siempre_deja_de_insistir() -> None:
    cliente = SiemprePierde()

    assert KeyValueIdempotencyStore(cliente).claim(_reservar("t-1")) == "in_progress"
    assert cliente.intentos == 3


async def test_la_variante_asincronica_tambien_deja_de_insistir() -> None:
    class Asincronico:
        conditional = True
        intentos = 0

        async def get(self, key: str) -> KeyValueRecord | None:
            return None

        async def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool:
            Asincronico.intentos += 1
            return False

        async def delete(self, key: str, *, only_if: str) -> bool:
            return False

    assert await AsyncKeyValueIdempotencyStore(Asincronico()).claim(_reservar("t-1")) == "in_progress"
    assert Asincronico.intentos == 3


def test_guarda_el_mismo_json_que_el_paquete_de_typescript_y_le_pone_vencimiento() -> None:
    cliente = SinCondicion()
    almacen = KeyValueIdempotencyStore(cliente, prefix="p:", grace_seconds=60)

    almacen.claim(_reservar("t-1"))
    assert json.loads(cliente.valores["p:evt:1"]) == {
        "state": "reserved",
        "token": "t-1",
        "expires_at": AHORA + 300,
    }
    assert cliente.vencimientos["p:evt:1"] == 360

    almacen.complete(CompleteRequest(key="evt:1", token="t-1", now=AHORA, retention_seconds=1000))
    # Byte a byte lo que escribe el paquete de TypeScript.
    assert cliente.valores["p:evt:1"] == f'{{"state":"completed","token":"t-1","expires_at":{AHORA + 1000}}}'
    assert cliente.vencimientos["p:evt:1"] == 1000


@pytest.mark.parametrize(
    "valor", ['{"otra":"cosa"}', "no es json", "7", '{"state":"reserved","token":"t","expires_at":true}']
)
def test_una_entrada_que_no_es_suya_es_un_error_y_no_un_resultado(valor: str) -> None:
    cliente = SinCondicion()
    cliente.valores["omniwebhook:events:evt:1"] = valor
    almacen = KeyValueIdempotencyStore(cliente)

    with pytest.raises(RuntimeError, match="no es de omniwebhook"):
        almacen.claim(_reservar("t-1"))
    with pytest.raises(RuntimeError, match="no es de omniwebhook"):
        almacen.release(ReleaseRequest(key="evt:1", token="t-1"))


@pytest.mark.parametrize("opciones", [{"prefix": ""}, {"grace_seconds": -1}, {"grace_seconds": 1.5}])
def test_rechaza_una_configuracion_invalida(opciones: dict[str, Any]) -> None:
    with pytest.raises(ConfigurationError):
        KeyValueIdempotencyStore(MemoryKeyValueClient(), **opciones)


def test_dynamodb_lee_de_forma_consistente_y_escribe_con_condicion_y_vencimiento() -> None:
    tabla = Tabla()
    cliente = DynamoDbTableClient(tabla, key_attribute="id", now=lambda: AHORA)

    assert cliente.put("k", "v1", ttl_seconds=30, only_if=None)
    assert tabla.items["k"] | {"version": ""} == {"id": "k", "value": "v1", "version": "", "ttl": AHORA + 30}
    assert not cliente.put("k", "v2", ttl_seconds=30, only_if=None)

    guardado = cliente.get("k")
    assert tabla.pedidos[-1] == {"Key": {"id": "k"}, "ConsistentRead": True}
    assert guardado is not None
    assert guardado.value == "v1"

    assert not cliente.put("k", "v2", ttl_seconds=30, only_if="otra")
    assert cliente.put("k", "v2", ttl_seconds=30, only_if=guardado.version)
    assert not cliente.delete("k", only_if=guardado.version)
    actual = cliente.get("k")
    assert actual is not None
    assert cliente.delete("k", only_if=actual.version)
    assert cliente.get("k") is None


def test_dynamodb_propaga_un_error_que_no_es_de_la_condicion() -> None:
    class SinPermisos(Tabla):
        def put_item(self, **pedido: Any) -> None:
            raise PermissionError("sin permisos")

        def delete_item(self, **pedido: Any) -> None:
            raise PermissionError("sin permisos")

    cliente = DynamoDbTableClient(SinPermisos())

    with pytest.raises(PermissionError):
        cliente.put("k", "v", ttl_seconds=1, only_if=None)
    with pytest.raises(PermissionError):
        cliente.delete("k", only_if="1")


async def test_dynamodb_asincronico_propaga_un_error_que_no_es_de_la_condicion() -> None:
    class SinPermisos(TablaAsincronica):
        async def put_item(self, **pedido: Any) -> None:
            raise PermissionError("sin permisos")

        async def delete_item(self, **pedido: Any) -> None:
            raise PermissionError("sin permisos")

    cliente = AsyncDynamoDbTableClient(SinPermisos())

    with pytest.raises(PermissionError):
        await cliente.put("k", "v", ttl_seconds=1, only_if=None)
    with pytest.raises(PermissionError):
        await cliente.delete("k", only_if="1")


def test_dynamodb_rechaza_un_atributo_de_clave_vacio_y_usa_el_reloj_del_sistema() -> None:
    with pytest.raises(ConfigurationError, match="key_attribute"):
        DynamoDbTableClient(Tabla(), key_attribute="")

    tabla = Tabla()
    DynamoDbTableClient(tabla).put("k", "v", ttl_seconds=10, only_if=None)
    assert tabla.items["k"]["ttl"] > AHORA
