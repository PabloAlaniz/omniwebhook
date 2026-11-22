"""El formato Standard Webhooks con firma simétrica `v1` (sección 5.1)."""

from collections.abc import Sequence
from dataclasses import dataclass

from omniwebhook.adapters.crypto import utf8
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier
from omniwebhook.adapters.schemes.standard.secret import default_signer, standard_key
from omniwebhook.adapters.schemes.standard.signer import StandardSigner
from omniwebhook.application.ports import Clock, Verifier
from omniwebhook.domain.event_key import event_key
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.freshness import DEFAULT_TOLERANCE_SECONDS
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.timestamp import SECONDS_DIGITS, parse_timestamp

_VERSION = "v1,"


@dataclass(frozen=True, slots=True, kw_only=True)
class _StandardReading(Reading):
    identifier: str
    signed_at: int


@dataclass(frozen=True, slots=True)
class _Standard:
    signer: StandardSigner

    def key_of(self, secret: str) -> bytes | None:
        return standard_key(secret)

    def read(self, request: IncomingRequest) -> _StandardReading | ReadProblem:
        fields = pick_singles(
            {
                "id": field_values(request.headers, "webhook-id"),
                "timestamp": field_values(request.headers, "webhook-timestamp"),
                "signature": field_values(request.headers, "webhook-signature"),
            }
        )
        if isinstance(fields, str):
            return fields

        identifier = fields.required["id"]
        timestamp = parse_timestamp(fields.required["timestamp"], SECONDS_DIGITS)
        received = [token for token in fields.required["signature"].split(" ") if token.startswith(_VERSION)]
        # Un identificador que no se puede pasar a bytes no se puede firmar.
        if timestamp is None or not received or utf8(identifier) is None:
            return "malformed"

        return _StandardReading(
            identifier=identifier,
            signed_at=timestamp,
            timestamp=timestamp,
            received=received,
            event_key=lambda: event_key("standard", identifier),
        )

    def expected(self, key: bytes, reading: _StandardReading, request: IncomingRequest) -> str:
        return self.signer.sign(key, reading.identifier, reading.signed_at, request.body)


def standard_scheme(
    *,
    secrets: Sequence[str],
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    clock: Clock | None = None,
    signer: StandardSigner | None = None,
) -> Verifier:
    """Verifica el formato Standard Webhooks.

    `signer` es quien calcula la firma; por defecto, la librería de referencia del formato.
    """
    return scheme_verifier(
        _Standard(signer or default_signer()),
        secrets=secrets,
        clock=clock,
        tolerance_seconds=tolerance_seconds,
    )
