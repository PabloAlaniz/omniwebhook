"""Almacén de reservas sobre Firestore.

Cada operación corre en una transacción, así que es atómica y sirve con varios procesos a
la vez. Cada entrada guarda `expire_time` para poder borrar lo vencido con una política de
TTL sobre ese campo.
"""

from datetime import UTC, datetime
from typing import Any, Final

from google.cloud import firestore

from omniwebhook.adapters.crypto import sha256_hex
from omniwebhook.application.ports import ClaimRequest, CompleteRequest, ReleaseRequest
from omniwebhook.domain.errors import ConfigurationError, positive_integer
from omniwebhook.domain.reservation import ClaimOutcome

DEFAULT_COLLECTION: Final = "omniwebhook_events"
# Reintentos de la transacción optimista ante contención por la misma clave. Firestore usa 5 por
# defecto; con muchos procesos reclamando a la vez conviene un número mayor.
DEFAULT_MAX_ATTEMPTS: Final = 10

_Entry = dict[str, Any]


def _checked_collection(collection: str) -> str:
    valid = (
        isinstance(collection, str)
        and collection not in ("", ".", "..")
        and "/" not in collection
        and not (collection.startswith("__") and collection.endswith("__"))
    )
    if not valid:
        raise ConfigurationError("collection tiene que ser el nombre de una colección, sin barras")
    return collection


def _document_id(key: str) -> str:
    # Una clave puede traer barras o ser muy larga; su huella siempre sirve de identificador.
    return sha256_hex(key.encode("utf-8", "surrogatepass"))


def _entry(key: str, state: str, token: str, expires_at: int) -> _Entry:
    return {
        "key": key,
        "state": state,
        "token": token,
        "expires_at": expires_at,
        "expire_time": datetime.fromtimestamp(expires_at, tz=UTC),
    }


def _held(stored: _Entry | None, now: int) -> ClaimOutcome | None:
    """Lo que hay que responder si la clave está tomada; `None` si se puede reservar."""
    if stored is None or now >= stored["expires_at"]:
        return None
    return "in_progress" if stored["state"] == "reserved" else "duplicate"


def _reserved_by(stored: _Entry | None, token: str) -> bool:
    return stored is not None and stored["state"] == "reserved" and stored["token"] == token


class FirestoreIdempotencyStore:
    def __init__(
        self,
        client: firestore.Client,
        *,
        collection: str = DEFAULT_COLLECTION,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._client = client
        self._collection = client.collection(_checked_collection(collection))
        self._max_attempts = positive_integer("max_attempts", max_attempts)

    def claim(self, request: ClaimRequest) -> ClaimOutcome:
        reference = self._collection.document(_document_id(request.key))

        @firestore.transactional
        def run(transaction: firestore.Transaction) -> ClaimOutcome:
            held = _held(reference.get(transaction=transaction).to_dict(), request.now)
            if held is not None:
                return held
            expires_at = request.now + request.lease_seconds
            transaction.set(reference, _entry(request.key, "reserved", request.token, expires_at))
            return "claimed"

        outcome: ClaimOutcome = run(self._client.transaction(max_attempts=self._max_attempts))
        return outcome

    def complete(self, request: CompleteRequest) -> bool:
        reference = self._collection.document(_document_id(request.key))

        @firestore.transactional
        def run(transaction: firestore.Transaction) -> bool:
            if not _reserved_by(reference.get(transaction=transaction).to_dict(), request.token):
                return False
            expires_at = request.now + request.retention_seconds
            transaction.set(reference, _entry(request.key, "completed", request.token, expires_at))
            return True

        applied: bool = run(self._client.transaction(max_attempts=self._max_attempts))
        return applied

    def release(self, request: ReleaseRequest) -> bool:
        reference = self._collection.document(_document_id(request.key))

        @firestore.transactional
        def run(transaction: firestore.Transaction) -> bool:
            if not _reserved_by(reference.get(transaction=transaction).to_dict(), request.token):
                return False
            transaction.delete(reference)
            return True

        applied: bool = run(self._client.transaction(max_attempts=self._max_attempts))
        return applied


class AsyncFirestoreIdempotencyStore:
    def __init__(
        self,
        client: firestore.AsyncClient,
        *,
        collection: str = DEFAULT_COLLECTION,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._client = client
        self._collection = client.collection(_checked_collection(collection))
        self._max_attempts = positive_integer("max_attempts", max_attempts)

    async def claim(self, request: ClaimRequest) -> ClaimOutcome:
        reference = self._collection.document(_document_id(request.key))

        @firestore.async_transactional
        async def run(transaction: firestore.AsyncTransaction) -> ClaimOutcome:
            snapshot = await reference.get(transaction=transaction)
            held = _held(snapshot.to_dict(), request.now)
            if held is not None:
                return held
            expires_at = request.now + request.lease_seconds
            transaction.set(reference, _entry(request.key, "reserved", request.token, expires_at))
            return "claimed"

        outcome: ClaimOutcome = await run(self._client.transaction(max_attempts=self._max_attempts))
        return outcome

    async def complete(self, request: CompleteRequest) -> bool:
        reference = self._collection.document(_document_id(request.key))

        @firestore.async_transactional
        async def run(transaction: firestore.AsyncTransaction) -> bool:
            snapshot = await reference.get(transaction=transaction)
            if not _reserved_by(snapshot.to_dict(), request.token):
                return False
            expires_at = request.now + request.retention_seconds
            transaction.set(reference, _entry(request.key, "completed", request.token, expires_at))
            return True

        applied: bool = await run(self._client.transaction(max_attempts=self._max_attempts))
        return applied

    async def release(self, request: ReleaseRequest) -> bool:
        reference = self._collection.document(_document_id(request.key))

        @firestore.async_transactional
        async def run(transaction: firestore.AsyncTransaction) -> bool:
            snapshot = await reference.get(transaction=transaction)
            if not _reserved_by(snapshot.to_dict(), request.token):
                return False
            transaction.delete(reference)
            return True

        applied: bool = await run(self._client.transaction(max_attempts=self._max_attempts))
        return applied
