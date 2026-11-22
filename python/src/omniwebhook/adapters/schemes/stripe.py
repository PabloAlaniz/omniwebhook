"""El formato de firma de Stripe (sección 5.2)."""

from collections.abc import Sequence
from dataclasses import dataclass

from omniwebhook.adapters.crypto import hmac_sha256
from omniwebhook.adapters.schemes.event_keys import json_id_key
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier, text_key
from omniwebhook.application.ports import Clock, Verifier
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.freshness import DEFAULT_TOLERANCE_SECONDS
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.signature_pairs import pair_values, parse_pairs
from omniwebhook.domain.timestamp import SECONDS_DIGITS, parse_timestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class _StripeReading(Reading):
    raw_timestamp: str
    """La marca tal como llegó: es parte de lo que se firma."""


class _Stripe:
    def key_of(self, secret: str) -> bytes | None:
        return text_key(secret)

    def read(self, request: IncomingRequest) -> _StripeReading | ReadProblem:
        fields = pick_singles({"header": field_values(request.headers, "stripe-signature")})
        if isinstance(fields, str):
            return fields

        pairs = parse_pairs(fields.required["header"])
        times = pair_values(pairs, "t")
        signatures = pair_values(pairs, "v1")
        if len(times) > 1:
            return "ambiguous"
        if not times or not signatures:
            return "malformed"
        timestamp = parse_timestamp(times[0], SECONDS_DIGITS)
        if timestamp is None:
            return "malformed"

        return _StripeReading(
            raw_timestamp=times[0],
            timestamp=timestamp,
            received=[signature.lower() for signature in signatures],
            event_key=lambda: json_id_key("stripe", request.body),
        )

    def expected(self, key: bytes, reading: _StripeReading, request: IncomingRequest) -> str:
        return hmac_sha256(key, f"{reading.raw_timestamp}.".encode("ascii") + request.body).hex()


def stripe_scheme(
    *,
    secrets: Sequence[str],
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    clock: Clock | None = None,
) -> Verifier:
    """Verifica el formato de firma de Stripe."""
    return scheme_verifier(_Stripe(), secrets=secrets, clock=clock, tolerance_seconds=tolerance_seconds)
