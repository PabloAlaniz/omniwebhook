"""Almacén de reservas sobre Redis.

Cada operación es un script, así que es atómica y sirve con varios procesos a la vez. Las
entradas se borran solas: no hace falta purgar.

No importa ningún cliente: recibe uno que cumpla `eval(script, numkeys, *keys_and_args)`,
como los de `redis` (`redis.Redis` y `redis.asyncio.Redis`).

Una diferencia con los otros almacenes: una reserva cuyo plazo venció se puede completar
mientras nadie la haya tomado, pero sólo durante `grace_seconds`. Después Redis la borra.
"""

from collections.abc import Awaitable
from typing import Any, Final, Protocol

from omniwebhook.application.ports import ClaimRequest, CompleteRequest, ReleaseRequest
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.reservation import ClaimOutcome

DEFAULT_REDIS_PREFIX: Final = "omniwebhook:events:"
DEFAULT_REDIS_GRACE_SECONDS: Final = 86_400

# Cada entrada es un hash con `state`, `token` y `expires_at`. Los dos paquetes usan estos
# mismos scripts, así que comparten las reservas.
#
# El vencimiento se decide comparando con el `now` que llega, igual que en los otros
# almacenes. El TTL de Redis sólo limpia: nunca vence antes que la entrada.
CLAIM_SCRIPT: Final = """
local entry = redis.call('HMGET', KEYS[1], 'state', 'expires_at')
if entry[1] and tonumber(entry[2]) > tonumber(ARGV[2]) then
  if entry[1] == 'completed' then return 'duplicate' end
  return 'in_progress'
end
redis.call('HSET', KEYS[1], 'state', 'reserved', 'token', ARGV[1], 'expires_at', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 'claimed'"""

COMPLETE_SCRIPT: Final = """
local entry = redis.call('HMGET', KEYS[1], 'state', 'token')
if entry[1] ~= 'reserved' or entry[2] ~= ARGV[1] then return 0 end
redis.call('HSET', KEYS[1], 'state', 'completed', 'expires_at', ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1"""

RELEASE_SCRIPT: Final = """
local entry = redis.call('HMGET', KEYS[1], 'state', 'token')
if entry[1] ~= 'reserved' or entry[2] ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
return 1"""


class RedisClient(Protocol):
    """Lo mínimo que hace falta de un cliente sincrónico de Redis."""

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...


class AsyncRedisClient(Protocol):
    """Lo mínimo que hace falta de un cliente asincrónico de Redis."""

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Awaitable[Any]: ...


def _claim_outcome(reply: object) -> ClaimOutcome:
    text = reply.decode("utf-8", "replace") if isinstance(reply, bytes) else reply
    if text == "claimed":
        return "claimed"
    if text == "duplicate":
        return "duplicate"
    if text == "in_progress":
        return "in_progress"
    raise RuntimeError("el almacén de Redis devolvió una respuesta inesperada")


class _Scripts:
    """Lo que comparten las dos variantes: las claves y los argumentos de cada script."""

    def __init__(
        self, *, prefix: str = DEFAULT_REDIS_PREFIX, grace_seconds: int = DEFAULT_REDIS_GRACE_SECONDS
    ) -> None:
        if not isinstance(prefix, str) or prefix == "":
            raise ConfigurationError("prefix no puede estar vacío")
        if isinstance(grace_seconds, bool) or not isinstance(grace_seconds, int) or grace_seconds < 0:
            raise ConfigurationError("grace_seconds tiene que ser un entero mayor o igual que cero")
        self._prefix = prefix
        self._grace_seconds = grace_seconds

    def _claim(self, request: ClaimRequest) -> tuple[Any, ...]:
        return (
            CLAIM_SCRIPT,
            1,
            self._prefix + request.key,
            request.token,
            str(request.now),
            str(request.now + request.lease_seconds),
            str(request.lease_seconds + self._grace_seconds),
        )

    def _complete(self, request: CompleteRequest) -> tuple[Any, ...]:
        return (
            COMPLETE_SCRIPT,
            1,
            self._prefix + request.key,
            request.token,
            str(request.now + request.retention_seconds),
            str(request.retention_seconds),
        )

    def _release(self, request: ReleaseRequest) -> tuple[Any, ...]:
        return (RELEASE_SCRIPT, 1, self._prefix + request.key, request.token)


class RedisIdempotencyStore(_Scripts):
    """El almacén sobre Redis, sincrónico."""

    def __init__(
        self,
        client: RedisClient,
        *,
        prefix: str = DEFAULT_REDIS_PREFIX,
        grace_seconds: int = DEFAULT_REDIS_GRACE_SECONDS,
    ) -> None:
        super().__init__(prefix=prefix, grace_seconds=grace_seconds)
        self._client = client

    def claim(self, request: ClaimRequest) -> ClaimOutcome:
        return _claim_outcome(self._client.eval(*self._claim(request)))

    def complete(self, request: CompleteRequest) -> bool:
        return int(self._client.eval(*self._complete(request))) == 1

    def release(self, request: ReleaseRequest) -> bool:
        return int(self._client.eval(*self._release(request))) == 1


class AsyncRedisIdempotencyStore(_Scripts):
    """El almacén sobre Redis, asincrónico."""

    def __init__(
        self,
        client: AsyncRedisClient,
        *,
        prefix: str = DEFAULT_REDIS_PREFIX,
        grace_seconds: int = DEFAULT_REDIS_GRACE_SECONDS,
    ) -> None:
        super().__init__(prefix=prefix, grace_seconds=grace_seconds)
        self._client = client

    async def claim(self, request: ClaimRequest) -> ClaimOutcome:
        return _claim_outcome(await self._client.eval(*self._claim(request)))

    async def complete(self, request: CompleteRequest) -> bool:
        return int(await self._client.eval(*self._complete(request))) == 1

    async def release(self, request: ReleaseRequest) -> bool:
        return int(await self._client.eval(*self._release(request))) == 1
