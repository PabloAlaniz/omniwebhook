"""El formato de firma de Slack (sección 5.8)."""

from collections.abc import Sequence
from dataclasses import dataclass

from omniwebhook.adapters.crypto import hmac_sha256
from omniwebhook.adapters.schemes.event_keys import json_id_key
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier, text_key
from omniwebhook.application.ports import Clock, Verifier
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.freshness import DEFAULT_TOLERANCE_SECONDS
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.timestamp import SECONDS_DIGITS, parse_timestamp

_VERSION = "v0"


@dataclass(frozen=True, slots=True, kw_only=True)
class _SlackReading(Reading):
    raw_timestamp: str
    """La marca tal como llegó: es parte de lo que se firma."""


class _Slack:
    def key_of(self, secret: str) -> bytes | None:
        return text_key(secret)

    def read(self, request: IncomingRequest) -> _SlackReading | ReadProblem:
        fields = pick_singles(
            {
                "signature": field_values(request.headers, "x-slack-signature"),
                "timestamp": field_values(request.headers, "x-slack-request-timestamp"),
            }
        )
        if isinstance(fields, str):
            return fields

        signature, raw_timestamp = fields.required["signature"], fields.required["timestamp"]
        timestamp = parse_timestamp(raw_timestamp, SECONDS_DIGITS)
        if timestamp is None or not signature.startswith(f"{_VERSION}="):
            return "malformed"

        return _SlackReading(
            raw_timestamp=raw_timestamp,
            timestamp=timestamp,
            received=[signature[len(_VERSION) + 1 :].lower()],
            event_key=lambda: json_id_key("slack", request.body, "event_id"),
        )

    def expected(self, key: bytes, reading: _SlackReading, request: IncomingRequest) -> str:
        prefix = f"{_VERSION}:{reading.raw_timestamp}:".encode("ascii")
        return hmac_sha256(key, prefix + request.body).hex()


def slack_scheme(
    *,
    secrets: Sequence[str],
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    clock: Clock | None = None,
) -> Verifier:
    """Verifica el formato de firma de Slack."""
    return scheme_verifier(_Slack(), secrets=secrets, clock=clock, tolerance_seconds=tolerance_seconds)
