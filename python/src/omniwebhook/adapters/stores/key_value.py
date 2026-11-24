"""Almacén de reservas sobre cualquier almacén clave-valor con vencimiento.

Con un cliente `conditional`, cada operación lee y después escribe sólo si nadie escribió en
el medio: entre pedidos simultáneos por la misma clave, uno solo la reserva. La garantía es
la misma que la de los otros almacenes.

Con uno que no lo es, entre la lectura y la escritura puede colarse otro proceso: dos
entregas simultáneas del mismo evento pueden reservarlo las dos. Sigue evitando los
duplicados que llegan separados en el tiempo, que son los reintentos del emisor.
`guarantee` dice cuál de las dos es.
"""

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from omniwebhook.application.ports import ClaimRequest, CompleteRequest, ReleaseRequest
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.reservation import ClaimOutcome

DEFAULT_KEY_VALUE_PREFIX: Final = "omniwebhook:events:"
DEFAULT_KEY_VALUE_GRACE_SECONDS: Final = 86_400
# Cuántas veces se vuelve a leer después de perder una escritura condicional.
_CLAIM_ATTEMPTS: Final = 3
_CONDITION_FAILED: Final = "ConditionalCheckFailedException"

Guarantee = Literal["atomic", "best-effort"]


@dataclass(frozen=True, slots=True)
class KeyValueRecord:
    """Lo que hay guardado en una clave, con la versión que identifica esa escritura."""

    value: str
    version: str
    """Cambia en cada escritura. Un cliente sin escritura condicional puede dejarla vacía."""


class KeyValueClient(Protocol):
    """Lo mínimo que hace falta de un almacén clave-valor: leer, escribir con vencimiento y borrar.

    Es el puerto que hay que implementar para usar uno que el paquete no trae.

    `only_if` es la versión que tiene que seguir guardada para que la operación se aplique;
    `None` significa que la clave no tiene que existir. Un cliente `conditional` DEBE
    comprobarla y escribir en un solo paso atómico, y devolver `False` si no coincide. Uno
    que no lo es la ignora y devuelve siempre `True`. `get` tiene que ser una lectura
    consistente: ver lo último que se escribió.
    """

    @property
    def conditional(self) -> bool: ...

    def get(self, key: str) -> KeyValueRecord | None: ...

    def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool: ...

    def delete(self, key: str, *, only_if: str) -> bool: ...


class AsyncKeyValueClient(Protocol):
    """Lo mismo que `KeyValueClient`, asincrónico."""

    @property
    def conditional(self) -> bool: ...

    def get(self, key: str) -> Awaitable[KeyValueRecord | None]: ...

    def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> Awaitable[bool]: ...

    def delete(self, key: str, *, only_if: str) -> Awaitable[bool]: ...


@dataclass(frozen=True, slots=True)
class _Entry:
    state: Literal["reserved", "completed"]
    token: str
    expires_at: int


def _encode(entry: _Entry) -> str:
    """El valor guardado: el mismo JSON en los dos paquetes, así comparten las reservas."""
    return json.dumps(
        {"state": entry.state, "token": entry.token, "expires_at": entry.expires_at}, separators=(",", ":")
    )


def _decode(value: str) -> _Entry:
    try:
        data = json.loads(value)
    except ValueError:
        data = None
    fields = data if isinstance(data, dict) else {}
    state, token, expires_at = fields.get("state"), fields.get("token"), fields.get("expires_at")
    if (
        state not in ("reserved", "completed")
        or not isinstance(token, str)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
    ):
        raise RuntimeError("el almacén clave-valor tiene una entrada que no es de omniwebhook")
    return _Entry(state, token, expires_at)


class _Rules:
    """Lo que comparten las dos variantes: todo menos la entrada/salida."""

    def __init__(self, *, conditional: bool, prefix: str, grace_seconds: int) -> None:
        if not isinstance(prefix, str) or prefix == "":
            raise ConfigurationError("prefix no puede estar vacío")
        if isinstance(grace_seconds, bool) or not isinstance(grace_seconds, int) or grace_seconds < 0:
            raise ConfigurationError("grace_seconds tiene que ser un entero mayor o igual que cero")
        self._conditional = conditional
        self._prefix = prefix
        self._grace_seconds = grace_seconds

    @property
    def guarantee(self) -> Guarantee:
        """`atomic` si el cliente escribe con condición; `best-effort` si no."""
        return "atomic" if self._conditional else "best-effort"

    def _taken(self, record: KeyValueRecord | None, now: int) -> ClaimOutcome | None:
        """Cómo está la clave para quien la quiere reservar; `None` si está libre."""
        if record is None:
            return None
        entry = _decode(record.value)
        if entry.expires_at <= now:
            return None
        return "duplicate" if entry.state == "completed" else "in_progress"

    def _reserved(self, request: ClaimRequest) -> str:
        return _encode(_Entry("reserved", request.token, request.now + request.lease_seconds))

    def _completed(self, request: CompleteRequest) -> str:
        return _encode(_Entry("completed", request.token, request.now + request.retention_seconds))

    def _own(self, record: KeyValueRecord | None, token: str) -> KeyValueRecord | None:
        """Lo guardado, sólo si es una reserva hecha con este token."""
        if record is None:
            return None
        entry = _decode(record.value)
        return record if entry.state == "reserved" and entry.token == token else None


class KeyValueIdempotencyStore(_Rules):
    """El almacén sobre un cliente clave-valor, sincrónico."""

    def __init__(
        self,
        client: KeyValueClient,
        *,
        prefix: str = DEFAULT_KEY_VALUE_PREFIX,
        grace_seconds: int = DEFAULT_KEY_VALUE_GRACE_SECONDS,
    ) -> None:
        super().__init__(conditional=client.conditional, prefix=prefix, grace_seconds=grace_seconds)
        self._client = client

    def claim(self, request: ClaimRequest) -> ClaimOutcome:
        name = self._prefix + request.key
        for _ in range(_CLAIM_ATTEMPTS):
            record = self._client.get(name)
            taken = self._taken(record, request.now)
            if taken is not None:
                return taken
            if self._client.put(
                name,
                self._reserved(request),
                ttl_seconds=request.lease_seconds + self._grace_seconds,
                only_if=None if record is None else record.version,
            ):
                return "claimed"
            # Otro proceso escribió entre la lectura y la escritura: se vuelve a mirar qué dejó.
        return "in_progress"

    def complete(self, request: CompleteRequest) -> bool:
        name = self._prefix + request.key
        record = self._own(self._client.get(name), request.token)
        if record is None:
            return False
        return self._client.put(
            name, self._completed(request), ttl_seconds=request.retention_seconds, only_if=record.version
        )

    def release(self, request: ReleaseRequest) -> bool:
        name = self._prefix + request.key
        record = self._own(self._client.get(name), request.token)
        return record is not None and self._client.delete(name, only_if=record.version)


class AsyncKeyValueIdempotencyStore(_Rules):
    """El almacén sobre un cliente clave-valor, asincrónico."""

    def __init__(
        self,
        client: AsyncKeyValueClient,
        *,
        prefix: str = DEFAULT_KEY_VALUE_PREFIX,
        grace_seconds: int = DEFAULT_KEY_VALUE_GRACE_SECONDS,
    ) -> None:
        super().__init__(conditional=client.conditional, prefix=prefix, grace_seconds=grace_seconds)
        self._client = client

    async def claim(self, request: ClaimRequest) -> ClaimOutcome:
        name = self._prefix + request.key
        for _ in range(_CLAIM_ATTEMPTS):
            record = await self._client.get(name)
            taken = self._taken(record, request.now)
            if taken is not None:
                return taken
            if await self._client.put(
                name,
                self._reserved(request),
                ttl_seconds=request.lease_seconds + self._grace_seconds,
                only_if=None if record is None else record.version,
            ):
                return "claimed"
        return "in_progress"

    async def complete(self, request: CompleteRequest) -> bool:
        name = self._prefix + request.key
        record = self._own(await self._client.get(name), request.token)
        if record is None:
            return False
        return await self._client.put(
            name, self._completed(request), ttl_seconds=request.retention_seconds, only_if=record.version
        )

    async def release(self, request: ReleaseRequest) -> bool:
        name = self._prefix + request.key
        record = self._own(await self._client.get(name), request.token)
        return record is not None and await self._client.delete(name, only_if=record.version)


class MemoryKeyValueClient:
    """Un cliente clave-valor en memoria, con escritura condicional.

    Sirve para tests y como referencia de lo que tiene que cumplir uno propio. No vence
    nada: el vencimiento del almacén sólo limpia.
    """

    conditional: Final = True

    def __init__(self) -> None:
        self._records: dict[str, KeyValueRecord] = {}
        self._writes = 0

    def get(self, key: str) -> KeyValueRecord | None:
        return self._records.get(key)

    def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool:
        current = self._records.get(key)
        if (None if current is None else current.version) != only_if:
            return False
        self._writes += 1
        self._records[key] = KeyValueRecord(value, str(self._writes))
        return True

    def delete(self, key: str, *, only_if: str) -> bool:
        current = self._records.get(key)
        if current is None or current.version != only_if:
            return False
        del self._records[key]
        return True


class AsyncMemoryKeyValueClient:
    """El cliente en memoria, asincrónico."""

    conditional: Final = True

    def __init__(self) -> None:
        self._client = MemoryKeyValueClient()

    async def get(self, key: str) -> KeyValueRecord | None:
        return self._client.get(key)

    async def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool:
        return self._client.put(key, value, ttl_seconds=ttl_seconds, only_if=only_if)

    async def delete(self, key: str, *, only_if: str) -> bool:
        return self._client.delete(key, only_if=only_if)


def _condition_failed(error: Exception) -> bool:
    """Si el error es el de una condición que no se cumplió. No importa la librería del servicio."""
    response = getattr(error, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    return bool(code == _CONDITION_FAILED)


class _DynamoDbRequests:
    """Los pedidos a una tabla de DynamoDB, iguales para las dos variantes."""

    conditional: Final = True

    def __init__(
        self, table: Any, *, key_attribute: str = "pk", now: Callable[[], int] | None = None
    ) -> None:
        if not isinstance(key_attribute, str) or key_attribute == "":
            raise ConfigurationError("key_attribute no puede estar vacío")
        self._table = table
        self._key_attribute = key_attribute
        self._now = now or (lambda: int(time.time()))

    def _get(self, key: str) -> dict[str, Any]:
        return {"Key": {self._key_attribute: key}, "ConsistentRead": True}

    def _record(self, response: Any) -> KeyValueRecord | None:
        item = response.get("Item")
        return None if item is None else KeyValueRecord(str(item["value"]), str(item["version"]))

    def _put(self, key: str, value: str, ttl_seconds: int, only_if: str | None) -> dict[str, Any]:
        item = {
            self._key_attribute: key,
            "value": value,
            "version": uuid.uuid4().hex,
            "ttl": self._now() + ttl_seconds,
        }
        if only_if is None:
            return {
                "Item": item,
                "ConditionExpression": "attribute_not_exists(#k)",
                "ExpressionAttributeNames": {"#k": self._key_attribute},
            }
        return {"Item": item, **self._expecting(only_if)}

    def _delete(self, key: str, only_if: str) -> dict[str, Any]:
        return {"Key": {self._key_attribute: key}, **self._expecting(only_if)}

    def _expecting(self, version: str) -> dict[str, Any]:
        return {
            "ConditionExpression": "#v = :expected",
            "ExpressionAttributeNames": {"#v": "version"},
            "ExpressionAttributeValues": {":expected": version},
        }


class DynamoDbTableClient(_DynamoDbRequests):
    """Adapta una tabla de DynamoDB, con escritura condicional: la garantía es `atomic`.

    Recibe el recurso de tabla de `boto3` (`boto3.resource("dynamodb").Table(nombre)`); no
    importa ninguna librería. La tabla tiene una clave de partición de texto (`pk` si no se
    indica otra) y ninguna de ordenamiento. Cada ítem lleva `value`, `version` y `ttl`;
    activando el vencimiento de la tabla sobre el atributo `ttl`, las entradas se borran
    solas.
    """

    def get(self, key: str) -> KeyValueRecord | None:
        return self._record(self._table.get_item(**self._get(key)))

    def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool:
        try:
            self._table.put_item(**self._put(key, value, ttl_seconds, only_if))
        except Exception as error:
            if _condition_failed(error):
                return False
            raise
        return True

    def delete(self, key: str, *, only_if: str) -> bool:
        try:
            self._table.delete_item(**self._delete(key, only_if))
        except Exception as error:
            if _condition_failed(error):
                return False
            raise
        return True


class AsyncDynamoDbTableClient(_DynamoDbRequests):
    """Lo mismo, para un recurso de tabla asincrónico, como el de `aioboto3`."""

    async def get(self, key: str) -> KeyValueRecord | None:
        return self._record(await self._table.get_item(**self._get(key)))

    async def put(self, key: str, value: str, *, ttl_seconds: int, only_if: str | None) -> bool:
        try:
            await self._table.put_item(**self._put(key, value, ttl_seconds, only_if))
        except Exception as error:
            if _condition_failed(error):
                return False
            raise
        return True

    async def delete(self, key: str, *, only_if: str) -> bool:
        try:
            await self._table.delete_item(**self._delete(key, only_if))
        except Exception as error:
            if _condition_failed(error):
                return False
            raise
        return True
