"""Agente de interoperabilidad del paquete de Python.

Lee un pedido JSON por línea de la entrada estándar y responde un JSON por línea. Se corre
con el entorno del paquete: `uv run --project python python python/interop/agent.py`.
"""

import base64
import json
import sys
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit

from psycopg_pool import ConnectionPool
from standardwebhooks import Webhook

from omniwebhook import (
    AttemptOutcome,
    AttemptRecord,
    ClaimRequest,
    CompleteRequest,
    ConfigurationError,
    IncomingRequest,
    OutgoingMessage,
    ReleaseRequest,
    RetryPolicy,
    Signed,
    Verified,
    Verifier,
    allowed_networks,
    classify_delivery,
    creem_scheme,
    evaluate_destination,
    github_scheme,
    hmac_body_scheme,
    http_status_for,
    inspect_destination,
    is_blocked_address,
    mercadopago_scheme,
    next_attempt,
    stripe_scheme,
)
from omniwebhook.postgres import (
    PostgresDeliveryLedger,
    PostgresIdempotencyStore,
    PsycopgClient,
    postgres_ledger_schema,
    postgres_store_schema,
)
from omniwebhook.standard import standard_scheme, standard_signer

Json = dict[str, Any]


class Clock:
    def __init__(self, now: int) -> None:
        self._now = now

    def now(self) -> int:
        return self._now


def verifier(scheme: str, secrets: list[str], now: int, options: Json) -> Verifier:
    timed: Json = {"secrets": secrets, "clock": Clock(now)}
    if "tolerance_seconds" in options:
        timed["tolerance_seconds"] = options["tolerance_seconds"]
    if scheme == "standard":
        return standard_scheme(**timed)
    if scheme == "stripe":
        return stripe_scheme(**timed)
    if scheme == "mercadopago":
        return mercadopago_scheme(**timed)
    if scheme == "github":
        return github_scheme(secrets=secrets)
    if scheme == "creem":
        return creem_scheme(secrets=secrets)
    if scheme == "hmac-body":
        return hmac_body_scheme(secrets=secrets, **options)
    raise ValueError(f"esquema desconocido: {scheme}")


class Agent:
    def __init__(self) -> None:
        self._pool: ConnectionPool | None = None
        self._store: PostgresIdempotencyStore | None = None
        self._ledger: PostgresDeliveryLedger | None = None

    def verify(
        self, scheme: str, secrets: list[str], now: int, request: Json, options: Json | None = None
    ) -> Json:
        incoming = IncomingRequest(
            headers=[(name, value) for name, value in request["headers"]],
            query=[(name, value) for name, value in request["query"]],
            body=base64.b64decode(request["body"]),
        )
        result = verifier(scheme, secrets, now, options or {}).verify(incoming)
        if isinstance(result, Verified):
            return {"outcome": "ok", "event_key": result.event_key, "timestamp": result.timestamp}
        return {"outcome": result.outcome}

    def sign(self, secrets: list[str], id: str, timestamp: int, payload: str) -> Json:
        message = OutgoingMessage(id=id, timestamp=timestamp, payload=base64.b64decode(payload))
        result = standard_signer(secrets=secrets).sign(message)
        if isinstance(result, Signed):
            return {"outcome": "signed", "headers": dict(result.headers)}
        return {"outcome": result.outcome}

    def reference_verify(self, secret: str, headers: dict[str, str], body: str) -> Json:
        """Lo que firmó el otro paquete, verificado con la librería de referencia del formato."""
        try:
            Webhook(secret).verify(base64.b64decode(body), headers, json_parse=False)
        except Exception:
            return {"valid": False}
        return {"valid": True}

    def address(self, address: str) -> Json:
        return {"blocked": is_blocked_address(address)}

    def network(self, network: str) -> Json:
        try:
            allowed_networks([network])
        except ConfigurationError:
            return {"valid": False}
        return {"valid": True}

    def url(
        self, url: str, allow_http: bool, resolved: list[str], allowed_networks: list[str] | None = None
    ) -> Json:
        result = evaluate_destination(
            url, allow_http=allow_http, allowed_networks=allowed_networks or [], resolved=resolved
        )
        inspected = inspect_destination(url, allow_http=allow_http)
        if isinstance(inspected, str):
            return {"result": result}
        # Lo que entiende el analizador de la plataforma, que es el que usa el transporte.
        platform: Json | None
        try:
            parsed = urlsplit(url)
            platform = {"host": parsed.hostname, "port": parsed.port, "scheme": f"{parsed.scheme}:"}
        except ValueError:
            platform = None
        return {
            "result": result,
            "host": inspected.host,
            "literal": inspected.literal_address,
            "platform": platform,
        }

    def classify(self, status: int | None, failure: Any) -> Json:
        return {"class": classify_delivery(AttemptOutcome(status=status, failure=failure))}

    def status(self, outcome: Any) -> Json:
        return {"status": http_status_for(outcome)}

    def retry(self, attempt: int, now: int, random: float, retry_after: str | None, **policy: Any) -> Json:
        following = next_attempt(
            attempt=attempt, now=now, random=random, retry_after=retry_after, policy=RetryPolicy(**policy)
        )
        if following is None:
            return {"exhausted": True}
        return {"exhausted": False, "delay_seconds": following.delay_seconds, "next_at": following.next_at}

    def store_open(self, url: str, table: str, create: bool) -> Json:
        self._pool = ConnectionPool(url, min_size=1, max_size=2, open=True)
        if create:
            with self._pool.connection() as connection:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
                connection.execute(postgres_store_schema(table))
        self._store = PostgresIdempotencyStore(PsycopgClient(self._pool.connection), table=table)
        return {"ready": True}

    def store_step(self, op: str, key: str, token: str, **rest: Any) -> Json:
        assert self._store is not None
        rest.pop("expected", None)
        if op == "claim":
            return {"result": self._store.claim(ClaimRequest(key=key, token=token, **rest))}
        if op == "complete":
            return {"result": self._store.complete(CompleteRequest(key=key, token=token, **rest))}
        return {"result": self._store.release(ReleaseRequest(key=key, token=token))}

    def store_close(self, table: str, drop: bool) -> Json:
        assert self._pool is not None
        if drop:
            with self._pool.connection() as connection:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
        self._pool.close()
        return {"closed": True}

    def ledger_open(self, url: str, table: str, create: bool) -> Json:
        self._pool = ConnectionPool(url, min_size=1, max_size=2, open=True)
        if create:
            with self._pool.connection() as connection:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
                connection.execute(postgres_ledger_schema(table))
        self._ledger = PostgresDeliveryLedger(PsycopgClient(self._pool.connection), table=table)
        return {"ready": True}

    def ledger_record(self, record: Json) -> Json:
        assert self._ledger is not None
        self._ledger.record(AttemptRecord(**record))
        return {"recorded": True}

    def ledger_read(self, message_id: str, endpoint_id: str) -> Json:
        assert self._ledger is not None
        return {"attempts": [asdict(a) for a in self._ledger.attempts_of(message_id, endpoint_id)]}

    def ledger_close(self, table: str, drop: bool) -> Json:
        return self.store_close(table, drop)


def main() -> None:
    agent = Agent()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            reply = getattr(agent, data.pop("command"))(**data)
        except Exception as error:
            reply = {"crashed": repr(error)}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
