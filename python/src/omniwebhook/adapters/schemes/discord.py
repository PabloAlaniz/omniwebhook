"""El formato de firma de Discord (sección 5.11). Necesita `omniwebhook[ed25519]`."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from omniwebhook.adapters.ed25519 import verifies_ed25519
from omniwebhook.adapters.schemes.event_keys import json_id_key
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, public_key_scheme_verifier
from omniwebhook.application.ports import Clock, Verifier
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.freshness import DEFAULT_TOLERANCE_SECONDS
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.timestamp import SECONDS_DIGITS, parse_timestamp

_KEY: Final = re.compile(r"[0-9A-Fa-f]{64}")
_SIGNATURE: Final = re.compile(r"[0-9A-Fa-f]{128}")


@dataclass(frozen=True, slots=True, kw_only=True)
class _DiscordReading(Reading):
    raw_timestamp: str
    """La marca tal como llegó: es parte de lo que se firma."""


class _Discord:
    def key_of(self, secret: str) -> bytes | None:
        return bytes.fromhex(secret) if _KEY.fullmatch(secret) else None

    def read(self, request: IncomingRequest) -> _DiscordReading | ReadProblem:
        fields = pick_singles(
            {
                "signature": field_values(request.headers, "x-signature-ed25519"),
                "timestamp": field_values(request.headers, "x-signature-timestamp"),
            }
        )
        if isinstance(fields, str):
            return fields

        raw_timestamp = fields.required["timestamp"]
        timestamp = parse_timestamp(raw_timestamp, SECONDS_DIGITS)
        if timestamp is None:
            return "malformed"

        return _DiscordReading(
            raw_timestamp=raw_timestamp,
            timestamp=timestamp,
            received=[fields.required["signature"]],
            event_key=lambda: json_id_key("discord", request.body),
        )

    def verifies(self, key: bytes, received: str, reading: _DiscordReading, request: IncomingRequest) -> bool:
        if _SIGNATURE.fullmatch(received) is None:
            return False
        return verifies_ed25519(
            key, bytes.fromhex(received), reading.raw_timestamp.encode("ascii") + request.body
        )


def discord_scheme(
    *,
    public_keys: Sequence[str],
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    clock: Clock | None = None,
) -> Verifier:
    """Verifica el formato de firma de Discord.

    `public_keys` son las claves aceptadas, en hexadecimal: la de la aplicación.
    """
    return public_key_scheme_verifier(
        _Discord(), keys=public_keys, clock=clock, tolerance_seconds=tolerance_seconds
    )
