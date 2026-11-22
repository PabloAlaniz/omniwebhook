"""El formato de firma de Mercado Pago (sección 5.3)."""

from collections.abc import Sequence
from dataclasses import dataclass

from omniwebhook.adapters.crypto import hmac_sha256
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier, text_key
from omniwebhook.application.ports import Clock, Verifier
from omniwebhook.domain.event_key import event_key
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.freshness import DEFAULT_TOLERANCE_SECONDS
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.signature_pairs import pair_values, parse_pairs
from omniwebhook.domain.timestamp import SECONDS_OR_MILLIS_DIGITS, parse_timestamp, to_seconds


@dataclass(frozen=True, slots=True, kw_only=True)
class _MercadoPagoReading(Reading):
    manifest: str
    """Lo que se firma: `id:…;request-id:…;ts:…;`, sin las partes que falten."""


class _MercadoPago:
    def key_of(self, secret: str) -> bytes | None:
        return text_key(secret)

    def read(self, request: IncomingRequest) -> _MercadoPagoReading | ReadProblem:
        fields = pick_singles(
            {"signature": field_values(request.headers, "x-signature")},
            {
                "request_id": field_values(request.headers, "x-request-id"),
                "data_id": field_values(request.query, "data.id"),
            },
        )
        if isinstance(fields, str):
            return fields

        pairs = parse_pairs(fields.required["signature"], lowercase_keys=True)
        times = pair_values(pairs, "ts")
        signatures = pair_values(pairs, "v1")
        if len(times) > 1 or len(signatures) > 1:
            return "ambiguous"
        if not times or not signatures:
            return "malformed"
        raw_timestamp = times[0]
        raw = parse_timestamp(raw_timestamp, SECONDS_OR_MILLIS_DIGITS)
        if raw is None:
            return "malformed"

        request_id = fields.optional["request_id"]
        data_id = fields.optional["data_id"]
        data_id = None if data_id is None else data_id.lower()
        parts = (
            "" if data_id is None else f"id:{data_id};",
            "" if request_id is None else f"request-id:{request_id};",
            f"ts:{raw_timestamp};",
        )

        def key() -> str:
            if data_id is None and request_id is None:
                return event_key("mercadopago", f"ts:{raw_timestamp}")
            return event_key("mercadopago", f"{data_id or ''}:{request_id or ''}")

        return _MercadoPagoReading(
            manifest="".join(parts),
            timestamp=to_seconds(raw),
            received=[signatures[0].lower()],
            event_key=key,
        )

    def expected(self, key: bytes, reading: _MercadoPagoReading, request: IncomingRequest) -> str:
        return hmac_sha256(key, reading.manifest.encode("utf-8", "surrogatepass")).hex()


def mercadopago_scheme(
    *,
    secrets: Sequence[str],
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    clock: Clock | None = None,
) -> Verifier:
    """Verifica el formato de firma de Mercado Pago.

    La firma no cubre el cuerpo: conviene tratar el aviso como una señal de cambio y
    consultar el recurso al emisor antes de actuar.
    """
    return scheme_verifier(_MercadoPago(), secrets=secrets, clock=clock, tolerance_seconds=tolerance_seconds)
