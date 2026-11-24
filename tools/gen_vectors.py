#!/usr/bin/env python3
"""Genera los vectores de conformidad de omniwebhook.

Es una implementación INDEPENDIENTE de la especificación: no importa ninguno de los
paquetes (`python/`, `ts/`). Si los paquetes y este archivo coinciden, es porque los
dos leyeron `spec/SPEC.md` igual, no porque uno copió al otro.

Todos los secretos que aparecen acá son sintéticos y existen sólo para los vectores.

Uso:
    python3 tools/gen_vectors.py           regenera spec/vectors/
    python3 tools/gen_vectors.py --check   falla si lo generado difiere del repo

Sólo usa la biblioteca estándar.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import sys
from calendar import timegm
from collections.abc import Callable
from pathlib import Path
from time import strptime
from typing import Any

SPEC = "0"
ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "spec" / "vectors"

Vector = dict[str, Any]

# ---------------------------------------------------------------------------
# Implementación de referencia del generador.
#
# Está escrita como una tabla de pasos por esquema: cada esquema declara qué
# datos lee, cuáles deben ser únicos y cómo arma lo que se firma. Un único
# recorrido (`check`) aplica el orden de la sección 4.1.
# ---------------------------------------------------------------------------

NOW = 1_700_000_000
TOLERANCE = 300
SECONDS = re.compile(r"[0-9]{1,11}")
SECONDS_OR_MILLIS = re.compile(r"[0-9]{1,15}")
B64 = re.compile(r"[A-Za-z0-9+/]*={0,2}")

Pairs = list[list[str]]


class Stop(Exception):
    """Corta el recorrido con el resultado que corresponde."""

    def __init__(self, outcome: str) -> None:
        self.outcome = outcome


def mac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def hexmac(secret: str, message: bytes) -> str:
    return mac(secret.encode(), message).hex()


def b64mac(key: bytes, message: bytes) -> str:
    return base64.b64encode(mac(key, message)).decode()


def std_key(secret: str) -> bytes | None:
    rest = secret.removeprefix("whsec_")
    if not rest or len(rest) % 4 or not B64.fullmatch(rest):
        return None
    return base64.b64decode(rest)


BLANKS = " \t"


def values(pairs: Pairs, name: str) -> list[str]:
    found = [value.strip(BLANKS) for key, value in pairs if key.lower() == name.lower()]
    return [value for value in found if value]


def split_pairs(text: str, lower: bool = False) -> list[tuple[str, str]]:
    out = []
    for piece in text.split(","):
        key, sep, value = piece.partition("=")
        key, value = key.strip(BLANKS), value.strip(BLANKS)
        if sep and key and value:
            out.append((key.lower() if lower else key, value))
    return out


def fingerprint(scheme: str, body: bytes) -> str:
    return f"{scheme}:sha256:{hashlib.sha256(body).hexdigest()}"


def not_json(constant: str) -> None:
    raise ValueError(constant)


def json_id(scheme: str, body: bytes, field: str = "id") -> str:
    try:
        data = json.loads(body.decode("utf-8"), parse_constant=not_json, parse_int=float)
    except (UnicodeDecodeError, ValueError):
        return fingerprint(scheme, body)
    if type(data) is dict and type(data.get(field)) is str and data[field]:
        return f"{scheme}:{data[field]}"
    return fingerprint(scheme, body)


def need(found: list[list[str]]) -> None:
    """Sección 4.1: primero lo que falta, después lo repetido."""
    if any(not group for group in found):
        raise Stop("missing")


def unique(*groups: list[str]) -> None:
    if any(len(group) > 1 for group in groups):
        raise Stop("ambiguous")


def check(case: dict[str, Any]) -> dict[str, Any]:
    scheme, secrets, request = case["scheme"], case["secrets"], case["request"]
    options = case.get("options", {})
    tolerance = options.get("tolerance_seconds", TOLERANCE)
    headers, query, body = request["headers"], request["query"], request["body"].encode("utf-8")
    try:
        if not secrets or any(not secret for secret in secrets):
            raise Stop("unconfigured")
        stamp: int | None = None

        if scheme == "standard":
            keys = [std_key(secret) for secret in secrets]
            if any(key is None for key in keys):
                raise Stop("unconfigured")
            ident, ts, sig = (values(headers, f"webhook-{part}") for part in ("id", "timestamp", "signature"))
            need([ident, ts, sig])
            unique(ident, ts, sig)
            candidates = [token[3:] for token in sig[0].split(" ") if token.startswith("v1,")]
            if not SECONDS.fullmatch(ts[0]) or not candidates:
                raise Stop("malformed")
            signed = f"{ident[0]}.{ts[0]}.".encode() + body
            valid = any(b64mac(key, signed) in candidates for key in keys if key is not None)
            stamp, event = int(ts[0]), f"standard:{ident[0]}"

        elif scheme == "stripe":
            header = values(headers, "stripe-signature")
            need([header])
            unique(header)
            parts = split_pairs(header[0])
            times = [value for key, value in parts if key == "t"]
            sigs = [value.lower() for key, value in parts if key == "v1"]
            unique(times)
            if not times or not sigs or not SECONDS.fullmatch(times[0]):
                raise Stop("malformed")
            signed = f"{times[0]}.".encode() + body
            valid = any(hexmac(secret, signed) in sigs for secret in secrets)
            stamp, event = int(times[0]), json_id("stripe", body)

        elif scheme == "tiktok":
            header = values(headers, "tiktok-signature")
            need([header])
            unique(header)
            parts = split_pairs(header[0])
            times = [value for key, value in parts if key == "t"]
            sigs = [value.lower() for key, value in parts if key == "s"]
            unique(times, sigs)
            if not times or not sigs or not SECONDS.fullmatch(times[0]):
                raise Stop("malformed")
            signed = f"{times[0]}.".encode() + body
            valid = any(hexmac(secret, signed) == sigs[0] for secret in secrets)
            stamp, event = int(times[0]), fingerprint("tiktok", body)

        elif scheme == "slack":
            sig = values(headers, "x-slack-signature")
            ts = values(headers, "x-slack-request-timestamp")
            need([sig, ts])
            unique(sig, ts)
            if not SECONDS.fullmatch(ts[0]) or not sig[0].startswith("v0="):
                raise Stop("malformed")
            signed = f"v0:{ts[0]}:".encode() + body
            valid = any(hexmac(secret, signed) == sig[0][3:].lower() for secret in secrets)
            stamp, event = int(ts[0]), json_id("slack", body, "event_id")

        elif scheme == "mercadopago":
            header = values(headers, "x-signature")
            request_id = values(headers, "x-request-id")
            data_id = [value.lower() for value in values(query, "data.id")]
            need([header])
            unique(header, request_id, data_id)
            parts = split_pairs(header[0], lower=True)
            times = [value for key, value in parts if key == "ts"]
            sigs = [value.lower() for key, value in parts if key == "v1"]
            unique(times, sigs)
            if not times or not sigs or not SECONDS_OR_MILLIS.fullmatch(times[0]):
                raise Stop("malformed")
            manifest = "".join(
                f"{label}:{group[0]};"
                for label, group in (("id", data_id), ("request-id", request_id), ("ts", times))
                if group
            )
            valid = any(hexmac(secret, manifest.encode()) == sigs[0] for secret in secrets)
            raw = int(times[0])
            stamp = raw // 1000 if raw >= 100_000_000_000 else raw
            if data_id or request_id:
                event = f"mercadopago:{''.join(data_id)}:{''.join(request_id)}"
            else:
                event = f"mercadopago:ts:{times[0]}"

        elif scheme in ("github", "creem", "shopify", "hmac-body"):
            preset = {
                "github": {
                    "header": "x-hub-signature-256",
                    "prefix": "sha256=",
                    "id_header": "x-github-delivery",
                },
                "creem": {"header": "creem-signature"},
                "shopify": {
                    "header": "x-shopify-hmac-sha256",
                    "encoding": "base64",
                    "id_header": "x-shopify-webhook-id",
                },
                "hmac-body": options,
            }[scheme]
            name = options.get("name", "hmac-body") if scheme == "hmac-body" else scheme
            header = values(headers, preset["header"])
            ident = values(headers, preset["id_header"]) if preset.get("id_header") else []
            need([header])
            unique(header, ident)
            prefix = preset.get("prefix", "")
            if not header[0].startswith(prefix):
                raise Stop("malformed")
            received = header[0][len(prefix) :]
            if preset.get("encoding", "hex") == "hex":
                valid = any(hexmac(secret, body) == received.lower() for secret in secrets)
            else:
                valid = any(b64mac(secret.encode(), body) == received for secret in secrets)
            if ident:
                event = f"{name}:{ident[0]}"
            elif scheme == "creem":
                event = json_id("creem", body)
            else:
                event = fingerprint(name, body)
        else:
            raise AssertionError(scheme)

        if not valid:
            raise Stop("invalid")
        if stamp is not None and abs(case["now"] - stamp) > tolerance:
            raise Stop("stale")
        return {"outcome": "ok", "event_key": event, "timestamp": stamp}
    except Stop as stop:
        return {"outcome": stop.outcome}


def request(headers: Pairs, body: str = "", query: Pairs | None = None) -> dict[str, Any]:
    return {"headers": headers, "query": query or [], "body": body}


def verify_file(scheme: str, cases: list[dict[str, Any]]) -> Vector:
    names = [case["name"] for case in cases]
    assert len(names) == len(set(names)), f"nombres repetidos en {scheme}"
    for case in cases:
        case["scheme"] = scheme
        case.setdefault("now", NOW)
        case["expected"] = check(case)
        wanted = case.pop("want")
        assert case["expected"]["outcome"] == wanted, (scheme, case["name"], case["expected"], wanted)
    ordered = [
        {
            key: case[key]
            for key in ("name", "scheme", "options", "secrets", "now", "request", "expected")
            if key in case
        }
        for case in cases
    ]
    return {"spec": SPEC, "id": f"verificar/{scheme}", "kind": "verify", "cases": ordered}


def swap(pairs: Pairs, name: str, value: str | None) -> Pairs:
    """Reemplaza (o quita, con None) todos los valores de una cabecera."""
    kept = [pair for pair in pairs if pair[0].lower() != name]
    return kept if value is None else [*kept, [name, value]]


# --- standard ---------------------------------------------------------------

STD_SECRET = "whsec_" + base64.b64encode(b"omniwebhook-secreto-sintetico-01").decode()
STD_OTHER = "whsec_" + base64.b64encode(b"omniwebhook-secreto-sintetico-02").decode()
STD_BODY = '{"type":"pedido.creado","data":{"id":42}}'


def std_sig(secret: str, ident: str, ts: int | str, body: str) -> str:
    key = std_key(secret)
    assert key is not None
    return "v1," + b64mac(key, f"{ident}.{ts}.{body}".encode())


def std_headers(
    ident: str = "msg_2aXk", ts: int | str = NOW, body: str = STD_BODY, secret: str = STD_SECRET
) -> Pairs:
    return [
        ["webhook-id", ident],
        ["webhook-timestamp", str(ts)],
        ["webhook-signature", std_sig(secret, ident, ts, body)],
    ]


def verificar_standard() -> Vector:
    good = std_headers()
    sig = good[2][1]
    # Ejemplo público de la especificación abierta: comprueba que este generador firma igual.
    pub_secret, pub_id, pub_ts = (
        "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw",
        "msg_p5jXN8AQM9LWM0D4loKWxJek",
        1614265330,
    )
    pub_body = '{"test": 2432232314}'
    pub_sig = std_sig(pub_secret, pub_id, pub_ts, pub_body)
    assert pub_sig == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=", pub_sig
    unicode_body = '{"nombre":"Ñandú 🦤","nota":"línea\\nnueva"}'

    def case(
        name: str, want: str, headers: Pairs = good, body: str = STD_BODY, **extra: Any
    ) -> dict[str, Any]:
        return {
            "name": name,
            "want": want,
            "secrets": [STD_SECRET],
            "request": request(headers, body),
            **extra,
        }

    return verify_file(
        "standard",
        [
            case("firma válida", "ok"),
            case(
                "ejemplo público de la especificación abierta",
                "ok",
                [["webhook-id", pub_id], ["webhook-timestamp", str(pub_ts)], ["webhook-signature", pub_sig]],
                pub_body,
                secrets=[pub_secret],
                now=pub_ts,
            ),
            case("cuerpo con caracteres fuera de ASCII", "ok", std_headers(body=unicode_body), unicode_body),
            case("cuerpo vacío", "ok", std_headers(body=""), ""),
            case(
                "un espacio de no separación es parte del identificador",
                "ok",
                std_headers(ident="\u00a0msg_2aXk"),
            ),
            case(
                "espacios y tabulaciones alrededor de un valor se recortan",
                "ok",
                swap(good, "webhook-id", " \tmsg_2aXk\t "),
            ),
            case("secreto sin el prefijo", "ok", secrets=[STD_SECRET.removeprefix("whsec_")]),
            case("rotación: coincide el segundo secreto", "ok", secrets=[STD_OTHER, STD_SECRET]),
            case(
                "rotación: coincide la segunda firma",
                "ok",
                swap(good, "webhook-signature", f"{std_sig(STD_OTHER, 'msg_2aXk', NOW, STD_BODY)} {sig}"),
            ),
            case(
                "una firma de otra versión se ignora",
                "ok",
                swap(good, "webhook-signature", f"v2a,AAAA {sig}"),
            ),
            case("nombres de cabecera en mayúsculas", "ok", [[name.upper(), value] for name, value in good]),
            case("valores con espacios alrededor", "ok", [[name, f"  {value} "] for name, value in good]),
            case("una cabecera repetida pero vacía no cuenta", "ok", [*good, ["webhook-id", "  "]]),
            case("en el borde de la tolerancia", "ok", std_headers(ts=NOW - 300)),
            case("en el borde de la tolerancia, hacia el futuro", "ok", std_headers(ts=NOW + 300)),
            case(
                "tolerancia propia más amplia",
                "ok",
                std_headers(ts=NOW - 900),
                options={"tolerance_seconds": 900},
            ),
            case("sin secretos", "unconfigured", secrets=[]),
            case("secreto vacío", "unconfigured", secrets=[""]),
            case("un secreto vacío entre otros válidos", "unconfigured", secrets=[STD_SECRET, ""]),
            case("secreto que no es base64", "unconfigured", secrets=["whsec_no es base64!"]),
            case("secreto con largo inválido", "unconfigured", secrets=["whsec_abcde"]),
            case("sólo el prefijo", "unconfigured", secrets=["whsec_"]),
            case("falta el identificador", "missing", swap(good, "webhook-id", None)),
            case("falta la marca de tiempo", "missing", swap(good, "webhook-timestamp", None)),
            case("falta la firma", "missing", swap(good, "webhook-signature", None)),
            case("la firma llega vacía", "missing", swap(good, "webhook-signature", "   ")),
            case("sin cabeceras", "missing", []),
            case("identificador repetido", "ambiguous", [*good, ["webhook-id", "msg_otro"]]),
            case("marca de tiempo repetida", "ambiguous", [*good, ["Webhook-Timestamp", str(NOW)]]),
            case("firma repetida", "ambiguous", [*good, ["webhook-signature", sig]]),
            case("marca de tiempo con letras", "malformed", swap(good, "webhook-timestamp", "ahora")),
            case("marca de tiempo con signo", "malformed", swap(good, "webhook-timestamp", f"-{NOW}")),
            case("marca de tiempo con decimales", "malformed", swap(good, "webhook-timestamp", f"{NOW}.5")),
            case("marca de tiempo demasiado larga", "malformed", swap(good, "webhook-timestamp", "1" * 12)),
            case("ninguna firma v1", "malformed", swap(good, "webhook-signature", "v2a,AAAA")),
            case("firma sin versión", "malformed", swap(good, "webhook-signature", sig[3:])),
            case("firma de otro secreto", "invalid", std_headers(secret=STD_OTHER)),
            case("cuerpo alterado", "invalid", body=STD_BODY + " "),
            case("identificador alterado", "invalid", swap(good, "webhook-id", "msg_otro")),
            case("marca de tiempo alterada", "invalid", swap(good, "webhook-timestamp", str(NOW + 1))),
            case("firma que no es base64", "invalid", swap(good, "webhook-signature", "v1,***")),
            case("firma en hexadecimal", "invalid", swap(good, "webhook-signature", "v1," + "ab" * 32)),
            case("un segundo después de la tolerancia", "stale", std_headers(ts=NOW - 301)),
            case("un segundo después de la tolerancia, hacia el futuro", "stale", std_headers(ts=NOW + 301)),
            case(
                "tolerancia propia más corta",
                "stale",
                std_headers(ts=NOW - 61),
                options={"tolerance_seconds": 60},
            ),
            case("orden: lo que falta va antes que lo repetido", "missing", [good[0], good[0], good[2]]),
            case(
                "orden: lo repetido va antes que lo mal formado",
                "ambiguous",
                [*swap(good, "webhook-timestamp", "ahora"), ["webhook-id", "msg_otro"]],
            ),
            case(
                "orden: una firma inválida no se informa como vieja",
                "invalid",
                swap(std_headers(ts=NOW - 5000), "webhook-signature", "v1,AAAA"),
            ),
        ],
    )


# --- stripe -----------------------------------------------------------------

TXT_SECRET = "secreto-sintetico-uno"
TXT_OTHER = "secreto-sintetico-dos"
STRIPE_BODY = '{"id":"evt_sintetico_001","type":"invoice.paid"}'


def stripe_header(ts: int | str = NOW, body: str = STRIPE_BODY, secret: str = TXT_SECRET) -> str:
    return f"t={ts},v1={hexmac(secret, f'{ts}.{body}'.encode())}"


def verificar_stripe() -> Vector:
    good = stripe_header()
    sig = good.split("v1=")[1]

    def case(
        name: str, want: str, header: str | None = good, body: str = STRIPE_BODY, **extra: Any
    ) -> dict[str, Any]:
        headers = extra.pop("headers", None)
        if headers is None:
            headers = [] if header is None else [["stripe-signature", header]]
        return {
            "name": name,
            "want": want,
            "secrets": [TXT_SECRET],
            "request": request(headers, body),
            **extra,
        }

    plain = "no es json"
    no_id = '{"type":"invoice.paid"}'
    num_id = '{"id":7}'
    with_bom = "\ufeff" + STRIPE_BODY
    with_nan = '{"id":"evt_sintetico_001","monto":NaN}'
    with_big = '{"id":"evt_sintetico_001","monto":' + "9" * 5000 + "}"
    return verify_file(
        "stripe",
        [
            case("firma válida", "ok"),
            case("claves desconocidas se ignoran", "ok", f"{good},v0=abc,destination=we_1,payload=a25aefc6"),
            case("espacios alrededor de los pares", "ok", good.replace(",", " , ")),
            case("firma en mayúsculas", "ok", f"t={NOW},v1={sig.upper()}"),
            case("rotación: dos firmas, coincide la segunda", "ok", f"t={NOW},v1={'0' * 64},v1={sig}"),
            case("rotación: coincide el segundo secreto", "ok", secrets=[TXT_OTHER, TXT_SECRET]),
            case("cuerpo que no es JSON: la clave es la huella", "ok", stripe_header(body=plain), plain),
            case("cuerpo sin id: la clave es la huella", "ok", stripe_header(body=no_id), no_id),
            case("id que no es texto: la clave es la huella", "ok", stripe_header(body=num_id), num_id),
            case("id vacío: la clave es la huella", "ok", stripe_header(body='{"id":""}'), '{"id":""}'),
            case(
                "cuerpo JSON que es una lista: la clave es la huella",
                "ok",
                stripe_header(body='[{"id":"x"}]'),
                '[{"id":"x"}]',
            ),
            case("cuerpo JSON nulo: la clave es la huella", "ok", stripe_header(body="null"), "null"),
            case(
                "cuerpo con marca de orden de bytes: la clave es la huella",
                "ok",
                stripe_header(body=with_bom),
                with_bom,
            ),
            case("cuerpo con NaN: la clave es la huella", "ok", stripe_header(body=with_nan), with_nan),
            case("cuerpo con un número enorme: se lee el id", "ok", stripe_header(body=with_big), with_big),
            case("tabulaciones alrededor de los pares", "ok", good.replace(",", "\t,\t")),
            case("tabulaciones alrededor de la cabecera", "ok", f"\t{good}\t"),
            case("un espacio de no separación es parte de la firma", "invalid", f"{good}\u00a0"),
            case("un espacio de no separación es parte de la clave del par", "malformed", f"\u00a0{good}"),
            case("en el borde de la tolerancia", "ok", stripe_header(ts=NOW - 300)),
            case("sin secretos", "unconfigured", secrets=[]),
            case("falta la cabecera", "missing", None),
            case(
                "cabecera repetida",
                "ambiguous",
                headers=[["stripe-signature", good], ["Stripe-Signature", good]],
            ),
            case("marca de tiempo repetida", "ambiguous", f"{good},t={NOW - 1}"),
            case("marca de tiempo repetida y sin firma", "ambiguous", f"t={NOW},t={NOW}"),
            case("sin marca de tiempo", "malformed", f"v1={sig}"),
            case("sin firma v1", "malformed", f"t={NOW},v0={sig}"),
            case("marca de tiempo con letras", "malformed", f"t=ayer,v1={sig}"),
            case("marca de tiempo demasiado larga", "malformed", f"t={'1' * 12},v1={sig}"),
            case("sin pares", "malformed", "cualquier cosa"),
            case("un par con el valor vacío se ignora", "malformed", f"t={NOW},v1="),
            case("firma de otro secreto", "invalid", stripe_header(secret=TXT_OTHER)),
            case("cuerpo alterado", "invalid", body=STRIPE_BODY + "\n"),
            case("la clave v1 distingue mayúsculas", "malformed", f"t={NOW},V1={sig}"),
            case("un segundo después de la tolerancia", "stale", stripe_header(ts=NOW - 301)),
            case("del futuro", "stale", stripe_header(ts=NOW + 301)),
        ],
    )


# --- tiktok -----------------------------------------------------------------

TIKTOK_BODY = (
    '{"client_key":"clave_sintetica","event":"authorization.removed","create_time":1700000000,'
    '"user_openid":"openid_sintetico","content":"{\\"reason\\":1}"}'
)


def tiktok_header(ts: int | str = NOW, body: str = TIKTOK_BODY, secret: str = TXT_SECRET) -> str:
    return f"t={ts},s={hexmac(secret, f'{ts}.{body}'.encode())}"


def verificar_tiktok() -> Vector:
    good = tiktok_header()
    sig = good.split("s=")[1]

    def case(
        name: str, want: str, header: str | None = good, body: str = TIKTOK_BODY, **extra: Any
    ) -> dict[str, Any]:
        headers = extra.pop("headers", None)
        if headers is None:
            headers = [] if header is None else [["tiktok-signature", header]]
        return {
            "name": name,
            "want": want,
            "secrets": [TXT_SECRET],
            "request": request(headers, body),
            **extra,
        }

    return verify_file(
        "tiktok",
        [
            case("firma válida", "ok"),
            case("el orden de los pares no importa", "ok", f"s={sig},t={NOW}"),
            case("claves desconocidas se ignoran", "ok", f"{good},v=1"),
            case("espacios alrededor de los pares", "ok", good.replace(",", " , ")),
            case("firma en mayúsculas", "ok", f"t={NOW},s={sig.upper()}"),
            case("nombre de la cabecera en mayúsculas", "ok", headers=[["TikTok-Signature", good]]),
            case("rotación: coincide el segundo secreto", "ok", secrets=[TXT_OTHER, TXT_SECRET]),
            case(
                "un cuerpo con id no cambia la clave: es la huella",
                "ok",
                tiktok_header(body='{"id":"x"}'),
                '{"id":"x"}',
            ),
            case("en el borde de la tolerancia", "ok", tiktok_header(ts=NOW - 300)),
            case("sin secretos", "unconfigured", secrets=[]),
            case("falta la cabecera", "missing", None),
            case(
                "cabecera repetida",
                "ambiguous",
                headers=[["tiktok-signature", good], ["TikTok-Signature", good]],
            ),
            case("marca de tiempo repetida", "ambiguous", f"{good},t={NOW - 1}"),
            case("firma repetida", "ambiguous", f"{good},s={'0' * 64}"),
            case("sin marca de tiempo", "malformed", f"s={sig}"),
            case("sin firma", "malformed", f"t={NOW}"),
            case("la firma de Stripe no cuenta", "malformed", f"t={NOW},v1={sig}"),
            case("marca de tiempo con letras", "malformed", f"t=ayer,s={sig}"),
            case("marca de tiempo demasiado larga", "malformed", f"t={'1' * 12},s={sig}"),
            case("sin pares", "malformed", "cualquier cosa"),
            case("la clave s distingue mayúsculas", "malformed", f"t={NOW},S={sig}"),
            case("firma de otro secreto", "invalid", tiktok_header(secret=TXT_OTHER)),
            case("cuerpo alterado", "invalid", body=TIKTOK_BODY + "\n"),
            case("firma de otra marca de tiempo", "invalid", f"t={NOW - 1},s={sig}"),
            case("un segundo después de la tolerancia", "stale", tiktok_header(ts=NOW - 301)),
            case("del futuro", "stale", tiktok_header(ts=NOW + 301)),
        ],
    )


# --- mercadopago ------------------------------------------------------------


def mp_manifest(data_id: str | None, request_id: str | None, ts: int | str) -> str:
    out = ""
    if data_id:
        out += f"id:{data_id.lower()};"
    if request_id:
        out += f"request-id:{request_id};"
    return out + f"ts:{ts};"


def mp_request(
    data_id: str | None = "123456789",
    request_id: str | None = "a1b2c3d4-0000-4000-8000-000000000001",
    ts: int | str = NOW,
    secret: str = TXT_SECRET,
    body: str = '{"action":"payment.updated","data":{"id":"123456789"}}',
) -> dict[str, Any]:
    headers = [["x-signature", f"ts={ts},v1={hexmac(secret, mp_manifest(data_id, request_id, ts).encode())}"]]
    if request_id:
        headers.append(["x-request-id", request_id])
    return request(headers, body, [["data.id", data_id]] if data_id else [])


def verificar_mercadopago() -> Vector:
    good = mp_request()
    sig = good["headers"][0][1]
    hash_only = sig.split("v1=")[1]

    def case(name: str, want: str, req: dict[str, Any] = good, **extra: Any) -> dict[str, Any]:
        return {"name": name, "want": want, "secrets": [TXT_SECRET], "request": req, **extra}

    def with_sig(value: str, base: dict[str, Any] = good) -> dict[str, Any]:
        return {**base, "headers": swap(base["headers"], "x-signature", value)}

    upper = mp_request(data_id="ABC123DEF")
    millis = mp_request(ts=NOW * 1000 + 250)
    return verify_file(
        "mercadopago",
        [
            case("firma válida", "ok"),
            case("identificador alfanumérico: se firma en minúsculas", "ok", upper),
            case("sin x-request-id", "ok", mp_request(request_id=None)),
            case("sin data.id", "ok", mp_request(data_id=None)),
            case("sin ninguno de los dos: la clave usa la marca de tiempo", "ok", mp_request(None, None)),
            case("marca de tiempo en milisegundos", "ok", millis),
            case("claves en mayúsculas", "ok", with_sig(sig.replace("ts=", "TS=").replace("v1=", "V1="))),
            case("claves desconocidas se ignoran", "ok", with_sig(f"{sig},v2=abc")),
            case("el cuerpo no está firmado: cambiarlo no invalida", "ok", {**good, "body": "otro cuerpo"}),
            case(
                "otros parámetros de la URL se ignoran",
                "ok",
                {**good, "query": [["type", "payment"], *good["query"]]},
            ),
            case("rotación: coincide el segundo secreto", "ok", secrets=[TXT_OTHER, TXT_SECRET]),
            case("en el borde de la tolerancia", "ok", mp_request(ts=NOW - 300)),
            case("sin secretos", "unconfigured", secrets=[]),
            case(
                "falta la cabecera de firma",
                "missing",
                {**good, "headers": swap(good["headers"], "x-signature", None)},
            ),
            case(
                "cabecera de firma repetida",
                "ambiguous",
                {**good, "headers": [*good["headers"], ["X-Signature", sig]]},
            ),
            case(
                "x-request-id repetido",
                "ambiguous",
                {**good, "headers": [*good["headers"], ["x-request-id", "otro"]]},
            ),
            case("data.id repetido", "ambiguous", {**good, "query": [*good["query"], ["data.id", "999"]]}),
            case(
                "marca de tiempo repetida", "ambiguous", with_sig(f"ts={NOW},ts={NOW - 4000},v1={hash_only}")
            ),
            case("firma repetida", "ambiguous", with_sig(f"{sig},v1={'0' * 64}")),
            case("sin marca de tiempo", "malformed", with_sig(f"v1={hash_only}")),
            case("sin firma", "malformed", with_sig(f"ts={NOW}")),
            case("marca de tiempo con letras", "malformed", with_sig(f"ts=hoy,v1={hash_only}")),
            case("marca de tiempo demasiado larga", "malformed", with_sig(f"ts={'1' * 16},v1={hash_only}")),
            case("firma de otro secreto", "invalid", mp_request(secret=TXT_OTHER)),
            case("data.id alterado", "invalid", {**good, "query": [["data.id", "987654321"]]}),
            case(
                "x-request-id alterado",
                "invalid",
                {**good, "headers": swap(good["headers"], "x-request-id", "otro")},
            ),
            case(
                "quitar x-request-id invalida",
                "invalid",
                {**good, "headers": swap(good["headers"], "x-request-id", None)},
            ),
            case("un segundo después de la tolerancia", "stale", mp_request(ts=NOW - 301)),
            case("vieja, en milisegundos", "stale", mp_request(ts=(NOW - 301) * 1000)),
            case("del futuro", "stale", mp_request(ts=NOW + 301)),
        ],
    )


# --- github, creem y hmac-body ------------------------------------------------

GH_BODY = '{"action":"opened","number":1}'


def verificar_github() -> Vector:
    sig = "sha256=" + hexmac(TXT_SECRET, GH_BODY.encode())
    good = [["x-hub-signature-256", sig], ["x-github-delivery", "72d3162e-cc78-11e3-81ab-4c9367dc0958"]]
    # Ejemplo de la documentación pública del emisor.
    doc_secret, doc_body = "It's a Secret to Everybody", "Hello, World!"
    doc_sig = "sha256=" + hexmac(doc_secret, doc_body.encode())
    assert doc_sig == "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"

    def case(
        name: str, want: str, headers: Pairs = good, body: str = GH_BODY, **extra: Any
    ) -> dict[str, Any]:
        return {
            "name": name,
            "want": want,
            "secrets": [TXT_SECRET],
            "request": request(headers, body),
            **extra,
        }

    return verify_file(
        "github",
        [
            case("firma válida", "ok"),
            case(
                "ejemplo de la documentación pública",
                "ok",
                [["X-Hub-Signature-256", doc_sig]],
                doc_body,
                secrets=[doc_secret],
            ),
            case("sin identificador de entrega: la clave es la huella", "ok", good[:1]),
            case("firma en mayúsculas", "ok", swap(good, "x-hub-signature-256", "sha256=" + sig[7:].upper())),
            case("no hay marca de tiempo: el reloj no importa", "ok", now=NOW + 10_000_000),
            case("rotación: coincide el segundo secreto", "ok", secrets=[TXT_OTHER, TXT_SECRET]),
            case("sin secretos", "unconfigured", secrets=[]),
            case("falta la cabecera", "missing", good[1:]),
            case("cabecera repetida", "ambiguous", [*good, ["x-hub-signature-256", sig]]),
            case("identificador de entrega repetido", "ambiguous", [*good, ["x-github-delivery", "otro"]]),
            case("sin el prefijo", "malformed", swap(good, "x-hub-signature-256", sig[7:])),
            case(
                "prefijo de otro algoritmo", "malformed", swap(good, "x-hub-signature-256", "sha1=" + sig[7:])
            ),
            case(
                "firma de otro secreto",
                "invalid",
                swap(good, "x-hub-signature-256", "sha256=" + hexmac(TXT_OTHER, GH_BODY.encode())),
            ),
            case("cuerpo alterado", "invalid", body=GH_BODY + " "),
            case("firma truncada", "invalid", swap(good, "x-hub-signature-256", sig[:-2])),
        ],
    )


CREEM_BODY = '{"id":"evt_sintetico_creem_1","eventType":"checkout.completed"}'


def verificar_creem() -> Vector:
    sig = hexmac(TXT_SECRET, CREEM_BODY.encode())
    other = '{"eventType":"checkout.completed"}'

    def case(
        name: str, want: str, headers: Pairs | None = None, body: str = CREEM_BODY, **extra: Any
    ) -> dict[str, Any]:
        headers = [["creem-signature", sig]] if headers is None else headers
        return {
            "name": name,
            "want": want,
            "secrets": [TXT_SECRET],
            "request": request(headers, body),
            **extra,
        }

    return verify_file(
        "creem",
        [
            case("firma válida", "ok"),
            case(
                "cuerpo sin id: la clave es la huella",
                "ok",
                [["creem-signature", hexmac(TXT_SECRET, other.encode())]],
                other,
            ),
            case("firma en mayúsculas", "ok", [["Creem-Signature", sig.upper()]]),
            case("sin secretos", "unconfigured", secrets=[]),
            case("falta la cabecera", "missing", []),
            case("cabecera repetida", "ambiguous", [["creem-signature", sig], ["creem-signature", sig]]),
            case(
                "firma de otro secreto",
                "invalid",
                [["creem-signature", hexmac(TXT_OTHER, CREEM_BODY.encode())]],
            ),
            case("cuerpo alterado", "invalid", body=CREEM_BODY + " "),
            case(
                "firma en base64",
                "invalid",
                [["creem-signature", b64mac(TXT_SECRET.encode(), CREEM_BODY.encode())]],
            ),
        ],
    )


def verificar_hmac_body() -> Vector:
    body = '{"evento":"alerta","nivel":"alto"}'
    hexsig = hexmac(TXT_SECRET, body.encode())
    b64sig = b64mac(TXT_SECRET.encode(), body.encode())
    basic = {"header": "x-firma"}
    prefixed = {"header": "x-firma", "prefix": "sha256="}
    b64 = {"header": "x-firma", "encoding": "base64"}
    named = {"header": "x-firma", "name": "alertas", "id_header": "x-entrega"}

    def case(
        name: str, want: str, options: dict[str, Any], headers: Pairs, text: str = body, **extra: Any
    ) -> dict[str, Any]:
        return {
            "name": name,
            "want": want,
            "options": options,
            "secrets": [TXT_SECRET],
            "request": request(headers, text),
            **extra,
        }

    return verify_file(
        "hmac-body",
        [
            case("hexadecimal sin prefijo", "ok", basic, [["x-firma", hexsig]]),
            case("con prefijo", "ok", prefixed, [["X-Firma", "sha256=" + hexsig]]),
            case("base64", "ok", b64, [["x-firma", b64sig]]),
            case(
                "con nombre propio e identificador",
                "ok",
                named,
                [["x-firma", hexsig], ["x-entrega", "e-001"]],
            ),
            case(
                "con nombre propio y sin identificador: huella con ese nombre",
                "ok",
                named,
                [["x-firma", hexsig]],
            ),
            case("sin secretos", "unconfigured", basic, [["x-firma", hexsig]], secrets=[]),
            case("falta la cabecera", "missing", basic, []),
            case("cabecera repetida", "ambiguous", basic, [["x-firma", hexsig], ["x-firma", hexsig]]),
            case(
                "identificador repetido",
                "ambiguous",
                named,
                [["x-firma", hexsig], ["x-entrega", "a"], ["x-entrega", "b"]],
            ),
            case("falta el prefijo configurado", "malformed", prefixed, [["x-firma", hexsig]]),
            case("el prefijo distingue mayúsculas", "malformed", prefixed, [["x-firma", "SHA256=" + hexsig]]),
            case("firma de otro secreto", "invalid", basic, [["x-firma", hexmac(TXT_OTHER, body.encode())]]),
            case("cuerpo alterado", "invalid", basic, [["x-firma", hexsig]], body + " "),
            case("hexadecimal donde se espera base64", "invalid", b64, [["x-firma", hexsig]]),
            case("base64 sin relleno", "invalid", b64, [["x-firma", b64sig.rstrip("=")]]),
        ],
    )


# --- slack y shopify ------------------------------------------------------------

SLACK_BODY = '{"type":"event_callback","event_id":"Ev0SINTETICO1","event":{"type":"app_mention"}}'


def slack_headers(
    ts: int | str = NOW, body: str = SLACK_BODY, secret: str = TXT_SECRET, version: str = "v0"
) -> Pairs:
    signature = hexmac(secret, f"v0:{ts}:{body}".encode())
    return [["x-slack-signature", f"{version}={signature}"], ["x-slack-request-timestamp", str(ts)]]


def verificar_slack() -> Vector:
    good = slack_headers()
    sig = good[0][1]
    # Ejemplo de la documentación pública del emisor. Sólo comprueba que acá se firma igual: no
    # va a los vectores, porque su cuerpo trae una URL del emisor.
    doc_secret, doc_ts = "8f742231b10e8888abcd99yyyzzz85a5", 1531420618
    doc_body = (
        "token=xyzz0WbapA4vBCDEFasx0q6G&team_id=T1DC2JH3J&team_domain=testteamnow&channel_id=G8PSS9T3V"
        "&channel_name=foobar&user_id=U2CERLKJA&user_name=roadrunner&command=%2Fwebhook-collect&text="
        "&response_url=https%3A%2F%2Fhooks.slack.com%2Fcommands%2FT1DC2JH3J%2F397700885554"
        "%2F96rGlfmibIGlgcZRskXaIFfN&trigger_id=398738663015.47445629121.803a0bc887a14d10d2c447fce8b6703c"
    )
    doc_headers = slack_headers(doc_ts, doc_body, doc_secret)
    assert doc_headers[0][1] == "v0=a2114d57b48eac39b9ad189dd8316235a7b4a8d21a10bd27519666489c69b503"

    def case(
        name: str, want: str, headers: Pairs = good, body: str = SLACK_BODY, **extra: Any
    ) -> dict[str, Any]:
        return {
            "name": name,
            "want": want,
            "secrets": [TXT_SECRET],
            "request": request(headers, body),
            **extra,
        }

    form = "token=sintetico&command=%2Fpedido&trigger_id=1.2.abc"
    no_id = '{"type":"url_verification","challenge":"sintetico"}'
    return verify_file(
        "slack",
        [
            case("firma válida", "ok"),
            case("cuerpo de formulario: la clave es la huella", "ok", slack_headers(body=form), form),
            case("cuerpo sin event_id: la clave es la huella", "ok", slack_headers(body=no_id), no_id),
            case("firma en mayúsculas", "ok", swap(good, "x-slack-signature", "v0=" + sig[3:].upper())),
            case("nombres de cabecera en mayúsculas", "ok", [[name.upper(), value] for name, value in good]),
            case("rotación: coincide el segundo secreto", "ok", secrets=[TXT_OTHER, TXT_SECRET]),
            case("en el borde de la tolerancia", "ok", slack_headers(ts=NOW - 300)),
            case("sin secretos", "unconfigured", secrets=[]),
            case("falta la firma", "missing", good[1:]),
            case("falta la marca de tiempo", "missing", good[:1]),
            case("firma repetida", "ambiguous", [*good, ["x-slack-signature", sig]]),
            case("marca de tiempo repetida", "ambiguous", [*good, ["x-slack-request-timestamp", str(NOW)]]),
            case("falta la marca de tiempo y la firma está repetida", "missing", [good[0], good[0]]),
            case("sin el prefijo de versión", "malformed", swap(good, "x-slack-signature", sig[3:])),
            case("otra versión de firma", "malformed", slack_headers(version="v1")),
            case("el prefijo de versión distingue mayúsculas", "malformed", slack_headers(version="V0")),
            case("marca de tiempo con letras", "malformed", swap(good, "x-slack-request-timestamp", "ayer")),
            case(
                "marca de tiempo demasiado larga",
                "malformed",
                swap(good, "x-slack-request-timestamp", "1" * 12),
            ),
            case("firma de otro secreto", "invalid", slack_headers(secret=TXT_OTHER)),
            case("cuerpo alterado", "invalid", body=SLACK_BODY + "\n"),
            case(
                "marca de tiempo cambiada después de firmar",
                "invalid",
                swap(good, "x-slack-request-timestamp", str(NOW - 1)),
            ),
            case("un segundo después de la tolerancia", "stale", slack_headers(ts=NOW - 301)),
            case("del futuro", "stale", slack_headers(ts=NOW + 301)),
        ],
    )


SHOPIFY_BODY = '{"id":820982911946154508,"email":"cliente@ejemplo.test","total_price":"10.00"}'


def verificar_shopify() -> Vector:
    sig = b64mac(TXT_SECRET.encode(), SHOPIFY_BODY.encode())
    good = [["x-shopify-hmac-sha256", sig], ["x-shopify-webhook-id", "b54557e4-bdd9-4b37-8a5f-bf7d70bcd043"]]

    def case(
        name: str, want: str, headers: Pairs = good, body: str = SHOPIFY_BODY, **extra: Any
    ) -> dict[str, Any]:
        return {
            "name": name,
            "want": want,
            "secrets": [TXT_SECRET],
            "request": request(headers, body),
            **extra,
        }

    return verify_file(
        "shopify",
        [
            case("firma válida", "ok"),
            case("sin identificador de webhook: la clave es la huella", "ok", good[:1]),
            case("nombres de cabecera en mayúsculas", "ok", [[name.upper(), value] for name, value in good]),
            case("no hay marca de tiempo: el reloj no importa", "ok", now=NOW + 10_000_000),
            case("rotación: coincide el segundo secreto", "ok", secrets=[TXT_OTHER, TXT_SECRET]),
            case("sin secretos", "unconfigured", secrets=[]),
            case("falta la cabecera", "missing", good[1:]),
            case("cabecera repetida", "ambiguous", [*good, ["x-shopify-hmac-sha256", sig]]),
            case("identificador de webhook repetido", "ambiguous", [*good, ["x-shopify-webhook-id", "otro"]]),
            case(
                "firma de otro secreto",
                "invalid",
                swap(good, "x-shopify-hmac-sha256", b64mac(TXT_OTHER.encode(), SHOPIFY_BODY.encode())),
            ),
            case("cuerpo alterado", "invalid", body=SHOPIFY_BODY + " "),
            case(
                "firma en hexadecimal",
                "invalid",
                swap(good, "x-shopify-hmac-sha256", hexmac(TXT_SECRET, SHOPIFY_BODY.encode())),
            ),
            case(
                "la firma en base64 distingue mayúsculas",
                "invalid",
                swap(good, "x-shopify-hmac-sha256", sig.swapcase()),
            ),
            case("firma sin el relleno", "invalid", swap(good, "x-shopify-hmac-sha256", sig.rstrip("="))),
        ],
    )


# --- varios esquemas en una ruta ----------------------------------------------


def verificar_varios() -> Vector:
    routes = [
        {"header": "stripe-signature", "scheme": "stripe", "secrets": [TXT_SECRET]},
        {"header": "x-hub-signature-256", "scheme": "github", "secrets": [TXT_OTHER]},
        {"header": "webhook-signature", "scheme": "standard", "secrets": [STD_SECRET]},
    ]
    stripe = [["stripe-signature", stripe_header()]]
    github = [["x-hub-signature-256", "sha256=" + hexmac(TXT_OTHER, GH_BODY.encode())]]

    def case(name: str, want: str, headers: Pairs, body: str, **extra: Any) -> dict[str, Any]:
        used = extra.pop("routes", routes)
        req = request(headers, body)
        matching = [route for route in used if values(headers, route["header"])]
        if not matching:
            expected: dict[str, Any] = {"outcome": "missing"}
        elif len(matching) > 1:
            expected = {"outcome": "ambiguous"}
        else:
            route = matching[0]
            expected = check(
                {
                    "scheme": route["scheme"],
                    "secrets": route["secrets"],
                    "options": route.get("options", {}),
                    "now": NOW,
                    "request": req,
                }
            )
        assert expected["outcome"] == want, (name, expected, want)
        return {"name": name, "routes": used, "now": NOW, "request": req, "expected": expected}

    cases = [
        case("coincide la primera ruta", "ok", stripe, STRIPE_BODY),
        case("coincide la segunda ruta", "ok", github, GH_BODY),
        case("coincide la tercera ruta", "ok", std_headers(), STD_BODY),
        case(
            "el nombre de la cabecera no distingue mayúsculas",
            "ok",
            [["Stripe-Signature", stripe[0][1]]],
            STRIPE_BODY,
        ),
        case("no coincide ninguna ruta", "missing", [["x-otra-firma", "abc"]], STRIPE_BODY),
        case("sin cabeceras", "missing", [], STRIPE_BODY),
        case(
            "una cabecera vacía no hace coincidir la ruta",
            "missing",
            [["stripe-signature", " "]],
            STRIPE_BODY,
        ),
        case("coinciden dos rutas: no se elige ninguna", "ambiguous", [*stripe, *github], STRIPE_BODY),
        case(
            "coinciden dos rutas aunque una firma sea válida y la otra no",
            "ambiguous",
            [*stripe, ["x-hub-signature-256", "sha256=" + "0" * 64]],
            STRIPE_BODY,
        ),
        case(
            "el resultado de la ruta pasa tal cual: firma inválida",
            "invalid",
            [["stripe-signature", stripe_header(secret=TXT_OTHER)]],
            STRIPE_BODY,
        ),
        case(
            "el resultado de la ruta pasa tal cual: cabecera repetida",
            "ambiguous",
            [*stripe, *stripe],
            STRIPE_BODY,
        ),
        case(
            "el resultado de la ruta pasa tal cual: pedido viejo",
            "stale",
            [["stripe-signature", stripe_header(ts=NOW - 301)]],
            STRIPE_BODY,
        ),
        case(
            "una firma válida para otra ruta no sirve: cada ruta tiene su secreto",
            "invalid",
            [["x-hub-signature-256", "sha256=" + hexmac(TXT_SECRET, GH_BODY.encode())]],
            GH_BODY,
        ),
        case(
            "una ruta sin secretos no afecta a las demás",
            "ok",
            stripe,
            STRIPE_BODY,
            routes=[routes[0], {**routes[1], "secrets": []}],
        ),
        case(
            "la ruta que coincide no tiene secretos",
            "unconfigured",
            github,
            GH_BODY,
            routes=[routes[0], {**routes[1], "secrets": []}],
        ),
    ]
    return {"spec": SPEC, "id": "verificar/varios", "kind": "route", "cases": cases}


# --- firmar ------------------------------------------------------------------


def firmar_standard() -> Vector:
    def signed(name: str, secrets: list[str], ident: str, ts: int, payload: str) -> dict[str, Any]:
        headers = {
            "webhook-id": ident,
            "webhook-timestamp": str(ts),
            "webhook-signature": " ".join(std_sig(secret, ident, ts, payload) for secret in secrets),
        }
        return {
            "name": name,
            "secrets": secrets,
            "id": ident,
            "timestamp": ts,
            "payload": payload,
            "expected": {"headers": headers},
        }

    def refused(name: str, error: str, secrets: list[str], ident: str, ts: int = NOW) -> dict[str, Any]:
        return {
            "name": name,
            "secrets": secrets,
            "id": ident,
            "timestamp": ts,
            "payload": "{}",
            "expected": {"error": error},
        }

    return {
        "spec": SPEC,
        "id": "firmar/standard",
        "kind": "sign",
        "cases": [
            signed("un secreto", [STD_SECRET], "msg_2aXk", NOW, STD_BODY),
            signed(
                "dos secretos: una firma por secreto, en orden",
                [STD_SECRET, STD_OTHER],
                "msg_2aXk",
                NOW,
                STD_BODY,
            ),
            signed("cuerpo vacío", [STD_SECRET], "msg_vacio", NOW, ""),
            signed(
                "cuerpo con caracteres fuera de ASCII",
                [STD_SECRET],
                "msg_ñ",
                NOW,
                '{"saludo":"¡Hola, señor! 👋"}',
            ),
            signed("época cero", [STD_SECRET], "msg_0", 0, "{}"),
            refused("identificador vacío", "invalid_id", [STD_SECRET], ""),
            refused("identificador con punto", "invalid_id", [STD_SECRET], "msg.1"),
            refused("marca de tiempo negativa", "invalid_timestamp", [STD_SECRET], "msg_1", -1),
            refused("sin secretos", "unconfigured", [], "msg_1"),
            refused("secreto inutilizable", "unconfigured", ["whsec_***"], "msg_1"),
        ],
    }


# --- reservas ------------------------------------------------------------------


class Shelf:
    """Almacén de referencia: un diccionario de clave → (estado, token, vencimiento)."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str, int]] = {}

    def run(self, step: dict[str, Any]) -> Any:
        key, token = step["key"], step["token"]
        row = self.rows.get(key)
        if step["op"] == "claim":
            if row and step["now"] < row[2]:
                return "in_progress" if row[0] == "reserved" else "duplicate"
            self.rows[key] = ("reserved", token, step["now"] + step["lease_seconds"])
            return "claimed"
        mine = bool(row) and row[0] == "reserved" and row[1] == token
        if mine and step["op"] == "complete":
            self.rows[key] = ("completed", token, step["now"] + step["retention_seconds"])
        elif mine:
            del self.rows[key]
        return mine


def claim(token: str, now: int, key: str = "standard:msg_1", lease: int = 300) -> dict[str, Any]:
    return {"op": "claim", "key": key, "token": token, "now": now, "lease_seconds": lease}


def complete(token: str, now: int, key: str = "standard:msg_1", retention: int = 604800) -> dict[str, Any]:
    return {"op": "complete", "key": key, "token": token, "now": now, "retention_seconds": retention}


def release(token: str, key: str = "standard:msg_1") -> dict[str, Any]:
    return {"op": "release", "key": key, "token": token}


def played(steps: list[dict[str, Any]], shelf: Shelf | None = None) -> list[dict[str, Any]]:
    shelf = shelf or Shelf()
    return [{**step, "expected": shelf.run(step)} for step in steps]


def reservas_almacen() -> Vector:
    t = NOW
    scripts = {
        "reservar, completar y volver a pedir": [claim("a", t), complete("a", t + 1), claim("b", t + 2)],
        "mientras está reservada, otro la ve en curso": [claim("a", t), claim("b", t + 1), claim("a", t + 2)],
        "liberar deja la clave disponible": [claim("a", t), release("a"), claim("b", t + 1)],
        "una reserva vencida se puede tomar": [claim("a", t), claim("b", t + 299), claim("b", t + 300)],
        "quien perdió la reserva no completa ni libera": [
            claim("a", t),
            claim("b", t + 300),
            complete("a", t + 301),
            release("a"),
            claim("c", t + 302),
            complete("b", t + 303),
        ],
        "completar tarde vale si nadie tomó la clave": [
            claim("a", t),
            complete("a", t + 900),
            claim("b", t + 901),
        ],
        "un evento completado se olvida al vencer la retención": [
            claim("a", t),
            complete("a", t, retention=60),
            claim("b", t + 59),
            claim("b", t + 60),
        ],
        "completar o liberar sin reserva no hace nada": [complete("a", t), release("a"), claim("a", t)],
        "completar con otro token no hace nada": [
            claim("a", t),
            complete("b", t + 1),
            release("b"),
            claim("c", t + 2),
        ],
        "no se completa ni se libera dos veces": [
            claim("a", t),
            complete("a", t + 1),
            complete("a", t + 2),
            release("a"),
        ],
        "las claves son independientes": [
            claim("a", t, key="standard:msg_1"),
            claim("a", t, key="standard:msg_2"),
            complete("a", t, key="standard:msg_1"),
            claim("b", t + 1, key="standard:msg_2"),
            claim("b", t + 1, key="standard:msg_1"),
        ],
        "plazo propio": [claim("a", t, lease=10), claim("b", t + 9, lease=10), claim("b", t + 10, lease=10)],
    }
    cases = [{"name": name, "steps": played(steps)} for name, steps in scripts.items()]
    return {"spec": SPEC, "id": "reservas/almacen", "kind": "store", "cases": cases}


# --- recibir -------------------------------------------------------------------

STATUS = {
    "ok": 200,
    "duplicate": 200,
    "in_progress": 409,
    "missing": 401,
    "ambiguous": 401,
    "malformed": 401,
    "invalid": 401,
    "stale": 401,
    "unconfigured": 500,
    "failed": 500,
    "too_large": 413,
}
MAX_BODY_BYTES = 1_048_576


def recibir_respuesta() -> Vector:
    cases = [
        {"name": outcome, "outcome": outcome, "expected": {"status": status}}
        for outcome, status in STATUS.items()
    ]
    return {"spec": SPEC, "id": "recibir/respuesta-http", "kind": "response", "cases": cases}


def recibir_caso_de_uso() -> Vector:
    key = "standard:msg_2aXk"
    good = request(std_headers(), STD_BODY)

    def case(
        name: str,
        handler: str,
        req: dict[str, Any] = good,
        before: list[dict[str, Any]] | None = None,
        after: list[dict[str, Any]] | None = None,
        secrets: list[str] | None = None,
        max_body: int = MAX_BODY_BYTES,
    ) -> dict[str, Any]:
        secrets = [STD_SECRET] if secrets is None else secrets
        shelf = Shelf()
        prior = played(before or [], shelf)
        called = False
        if len(req["body"].encode()) > max_body:
            outcome = "too_large"
        else:
            outcome = check({"scheme": "standard", "secrets": secrets, "now": NOW, "request": req})["outcome"]
        if outcome == "ok":
            state = shelf.run(claim("t-nuevo", NOW, key=key))
            if state == "claimed":
                called = True
                if handler == "succeeds":
                    shelf.run(complete("t-nuevo", NOW, key=key))
                else:
                    shelf.run(release("t-nuevo", key=key))
                    outcome = "failed"
            else:
                outcome = state
        expected: dict[str, Any] = {"outcome": outcome, "status": STATUS[outcome], "handler_called": called}
        if outcome in ("ok", "failed", "duplicate", "in_progress"):
            expected["event_key"] = key
        return {
            "name": name,
            "scheme": "standard",
            "secrets": secrets,
            "now": NOW,
            "token": "t-nuevo",
            "lease_seconds": 300,
            "retention_seconds": 604800,
            "max_body_bytes": max_body,
            "handler": handler,
            "before": prior,
            "request": req,
            "expected": expected,
            "after": played(after or [], shelf),
        }

    probe = [claim("t-sonda", NOW + 1, key=key)]
    cases = [
        case("se procesa y queda completado", "succeeds", after=probe),
        case("si el procesamiento falla, la reserva se libera", "fails", after=probe),
        case(
            "ya procesado: no se vuelve a ejecutar",
            "succeeds",
            before=[claim("t-previo", NOW - 50, key=key), complete("t-previo", NOW - 40, key=key)],
            after=probe,
        ),
        case(
            "en curso en otro proceso: no se ejecuta",
            "succeeds",
            before=[claim("t-previo", NOW - 50, key=key)],
            after=probe,
        ),
        case(
            "una reserva vencida de otro proceso se retoma",
            "succeeds",
            before=[claim("t-previo", NOW - 300, key=key)],
            after=probe,
        ),
        case(
            "firma inválida: no se reserva ni se ejecuta",
            "succeeds",
            request(std_headers(secret=STD_OTHER), STD_BODY),
            after=probe,
        ),
        case(
            "pedido viejo: no se reserva ni se ejecuta",
            "succeeds",
            request(std_headers(ts=NOW - 301), STD_BODY),
            after=probe,
        ),
        case("sin secretos: no se reserva ni se ejecuta", "succeeds", secrets=[], after=probe),
        case("sin cabeceras: no se reserva ni se ejecuta", "succeeds", request([], STD_BODY), after=probe),
        case(
            "un cuerpo del tamaño máximo se procesa",
            "succeeds",
            max_body=len(STD_BODY.encode()),
            after=probe,
        ),
        case(
            "un byte más que el máximo: no se reserva ni se ejecuta",
            "succeeds",
            max_body=len(STD_BODY.encode()) - 1,
            after=probe,
        ),
        case(
            "el tamaño se comprueba antes que la firma",
            "succeeds",
            request(std_headers(secret=STD_OTHER), STD_BODY),
            max_body=len(STD_BODY.encode()) - 1,
            after=probe,
        ),
        case(
            "el tamaño se comprueba antes que los secretos",
            "succeeds",
            secrets=[],
            max_body=len(STD_BODY.encode()) - 1,
            after=probe,
        ),
    ]
    return {"spec": SPEC, "id": "recibir/caso-de-uso", "kind": "receive", "cases": cases}


# --- entregar ------------------------------------------------------------------

BLOCKED_NETS = [
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 "
        "192.0.0.0/24 192.0.2.0/24 "
        "192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4 "
        "::/128 ::1/128 64:ff9b::/96 100::/64 2001:db8::/32 fc00::/7 fe80::/10 ff00::/8"
    ).split()
]


NEVER_ALLOWED_NETS = [
    ipaddress.ip_network(net) for net in "169.254.0.0/16 100.100.100.200/32 fd00:ec2::254/128".split()
]
MAPPED_NET = ipaddress.ip_network("::ffff:0:0/96")
PREFIX = re.compile(r"0|[1-9][0-9]{0,2}")

Net = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_network(text: str) -> Net | None:
    """Una red permitida con la forma de la sección 8.1, o `None` si no la tiene."""
    address, slash, prefix = text.partition("/")
    if not slash or PREFIX.fullmatch(prefix) is None or "%" in address or not is_literal(address):
        return None
    try:
        net = ipaddress.ip_network(f"{address}/{prefix}", strict=True)
    except ValueError:
        return None
    if net.version == 6 and net.prefixlen >= 96 and net.subnet_of(MAPPED_NET):  # type: ignore[arg-type]
        return None
    return net


def is_blocked(text: str, allowed: list[str] | None = None) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return True
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped

    def inside(nets: list[Net]) -> bool:
        return any(address.version == net.version and address in net for net in nets)

    if inside(NEVER_ALLOWED_NETS):
        return True
    nets = [parse_network(text) for text in allowed or []]
    assert all(net is not None for net in nets), allowed
    return inside(BLOCKED_NETS) and not inside([net for net in nets if net is not None])


def entregar_direcciones() -> Vector:
    public = (
        "1.1.1.1 8.8.8.8 93.184.216.34 9.255.255.255 11.0.0.0 100.63.255.255 100.128.0.0 "
        "126.255.255.255 128.0.0.0 169.253.255.255 169.255.0.0 172.15.255.255 172.32.0.0 192.0.1.0 "
        "192.0.3.0 192.167.255.255 192.169.0.0 198.17.255.255 198.20.0.0 198.51.99.255 198.51.101.0 "
        "203.0.112.255 203.0.114.0 223.255.255.255 2606:4700:4700::1111 2001:4860:4860::8888 ::2 "
        "::ffff:8.8.8.8 ::ffff:808:808 2001:db7:ffff:ffff:ffff:ffff:ffff:ffff 2001:db9:: "
        "fbff:ffff:ffff:ffff:ffff:ffff:ffff:ffff fe00:: fe7f:ffff:ffff:ffff:ffff:ffff:ffff:ffff "
        "fec0:: 64:ff9a:ffff:ffff:ffff:ffff:ffff:ffff 64:ff9b:0:0:0:1:: 100:0:0:1::"
    )
    private = (
        "0.0.0.0 0.255.255.255 10.0.0.0 10.255.255.255 100.64.0.0 100.127.255.255 127.0.0.1 "
        "127.255.255.255 169.254.0.0 169.254.169.254 172.16.0.0 172.31.255.255 192.0.0.0 "
        "192.0.0.255 192.0.2.1 192.168.0.1 192.168.255.255 198.18.0.0 198.19.255.255 198.51.100.7 "
        "203.0.113.9 224.0.0.1 239.255.255.255 240.0.0.0 255.255.255.255 :: ::1 ::ffff:127.0.0.1 "
        "::ffff:7f00:1 ::ffff:10.0.0.1 ::ffff:169.254.169.254 64:ff9b::1 64:ff9b::7f00:1 100:: "
        "100::ffff 2001:db8:: 2001:db8::1 fc00:: fd12:3456:789a::1 "
        "fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff fe80:: fe80::1 "
        "febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff ff00:: ff02::1"
    )
    junk = ["", "ejemplo.test", "1.2.3", "1.2.3.4.5", "256.1.1.1", "1.2.3.4/24", "gggg::1", " 8.8.8.8"]
    junk += [
        "01.2.3.4",
        "1.2.3.4::",
        "::1.2.3.4:5",
        ":::",
        "1::2::3",
        "1:2:3:4:5:6:7:8:9",
        "1:2:3:4:5:6:7:8::",
    ]
    junk += ["12345::", "::1.2.3", "1:2:3:4:5:6:7", "fe80::1%eth0", "1.2.3.-4", "::g"]
    public += " 1:2:3:4:5:6:7:: ::2:3:4:5:6:7:8 1:2:3:4:5:6:1.2.3.4 1::8 2001:DB7::1"
    cases = []
    for text, want in [
        *((a, False) for a in public.split()),
        *((a, True) for a in private.split()),
        *((a, True) for a in junk),
    ]:
        assert is_blocked(text) is want, text
        cases.append({"name": f"«{text}»", "address": text, "expected": {"blocked": want}})
    return {"spec": SPEC, "id": "entregar/direcciones", "kind": "address", "cases": cases}


FORBIDDEN_IN_URL = re.compile(r"[\x00-\x20\x7f\\]")
URL_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*):")
URL_REST = re.compile(r"//([^/?#]*)(?:[/?#].*)?", re.DOTALL)
URL_LABEL = re.compile(r"[A-Za-z0-9_-]{1,63}")
NUMERIC_LABEL = re.compile(r"[0-9]+|0[xX][0-9A-Fa-f]*")
STRICT_IPV4 = re.compile(r"(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}")


def is_literal(host: str) -> bool:
    """Si el host es una dirección literal con la forma que acepta la especificación."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.version == 6 or STRICT_IPV4.fullmatch(host) is not None


def url_host(authority: str) -> str | None:
    """El host de la parte que va entre `://` y el resto, o `None` si no tiene la forma."""
    hostport = authority.rpartition("@")[2]
    if hostport.startswith("["):
        inner, closing, after = hostport[1:].partition("]")
        port = after[1:] if after.startswith(":") else None
        if (
            not closing
            or (after and port is None)
            or "%" in inner
            or ":" not in inner
            or not is_literal(inner)
        ):
            return None
        host = inner.lower()
    else:
        name, colon, after = hostport.partition(":")
        port = after if colon else None
        labels = name.removesuffix(".").split(".")
        if len(name) > 253 or any(URL_LABEL.fullmatch(label) is None for label in labels):
            return None
        if not is_literal(name) and NUMERIC_LABEL.fullmatch(labels[-1]) is not None:
            return None
        host = name.lower()
    if port is not None and (re.fullmatch(r"[0-9]{1,5}", port) is None or int(port) > 65535):
        return None
    return host


def url_policy(url: str, allow_http: bool, resolved: list[str], allowed: list[str] | None = None) -> str:
    scheme = URL_SCHEME.match(url)
    if scheme is None or FORBIDDEN_IN_URL.search(url) is not None:
        return "invalid_url"
    name = scheme.group(1).lower()
    if name != "https" and not (name == "http" and allow_http):
        return "scheme"
    rest = URL_REST.fullmatch(url[scheme.end() :])
    host = None if rest is None else url_host(rest.group(1))
    if rest is None or host is None:
        return "invalid_url"
    if "@" in rest.group(1):
        return "credentials"
    addresses = [host] if is_literal(host) else resolved
    if not addresses:
        return "unresolved"
    return "blocked_address" if any(is_blocked(address, allowed) for address in addresses) else "allowed"


def entregar_url() -> Vector:
    names: set[str] = set()

    def case(
        name: str,
        url: str,
        expected: str,
        resolved: list[str] | None = None,
        allow_http: bool = False,
        allowed: list[str] | None = None,
    ) -> dict[str, Any]:
        assert name not in names, name
        names.add(name)
        assert url_policy(url, allow_http, resolved or [], allowed) == expected, (name, url)
        return {
            "name": name,
            "url": url,
            "allow_http": allow_http,
            "allowed_networks": allowed or [],
            "resolved": resolved or [],
            "expected": {"result": expected},
        }

    ok = ["93.184.216.34"]
    host = "hooks.ejemplo.test"
    lan = ["192.168.0.0/16"]
    cases = [
        case("https con dirección pública", "https://hooks.ejemplo.test/entrada", "allowed", ok),
        case("https con puerto y consulta", "https://hooks.ejemplo.test:8443/entrada?canal=1", "allowed", ok),
        case(
            "varias direcciones públicas",
            "https://hooks.ejemplo.test/",
            "allowed",
            ["93.184.216.34", "2606:4700:4700::1111"],
        ),
        case("http con permiso expreso", "http://hooks.ejemplo.test/entrada", "allowed", ok, allow_http=True),
        case("dirección IPv4 literal pública", "https://93.184.216.34/entrada", "allowed"),
        case("dirección IPv6 literal pública", "https://[2606:4700:4700::1111]/entrada", "allowed"),
        case("IPv6 literal con puerto", "https://[2606:4700:4700::1111]:8443/entrada", "allowed"),
        case("IPv6 literal en mayúsculas", "https://[2606:4700:4700::ABCD]/", "allowed"),
        case("sin ruta", f"https://{host}", "allowed", ok),
        case("sólo consulta", f"https://{host}?canal=1", "allowed", ok),
        case("sólo fragmento", f"https://{host}#parte", "allowed", ok),
        case("esquema y nombre en mayúsculas", "HTTPS://Hooks.Ejemplo.TEST/entrada", "allowed", ok),
        case("nombre con punto final", f"https://{host}./entrada", "allowed", ok),
        case("nombre con guion bajo y guiones", "https://mi_servicio.sub-dominio.test/", "allowed", ok),
        case("nombre internacionalizado en su forma ASCII", "https://xn--maana-pta.test/", "allowed", ok),
        case("etiqueta que empieza con dígitos", "https://1a.2b.test/", "allowed", ok),
        case("puerto cero", f"https://{host}:0/", "allowed", ok),
        case("puerto máximo", f"https://{host}:65535/", "allowed", ok),
        case("ruta con caracteres fuera de ASCII", f"https://{host}/señal?año=1", "allowed", ok),
        case("arroba en la ruta", f"https://{host}/a@b", "allowed", ok),
        case("dos puntos en la ruta", f"https://{host}/a:b", "allowed", ok),
        case("texto que no es una URL", "esto no es una url", "invalid_url"),
        case("texto vacío", "", "invalid_url"),
        case("URL relativa", "/entrada", "invalid_url"),
        case("sin esquema", f"//{host}/entrada", "invalid_url", ok),
        case("nombre solo", f"{host}/entrada", "invalid_url", ok),
        case("esquema sin host", "mailto:alguien@ejemplo.test", "scheme"),
        case("archivo local", "file:///etc/hosts", "scheme"),
        case("http sin permiso", "http://hooks.ejemplo.test/entrada", "scheme", ok),
        case("otro esquema", "ftp://hooks.ejemplo.test/entrada", "scheme", ok),
        case(
            "otro esquema aunque se permita http",
            "ftp://hooks.ejemplo.test/entrada",
            "scheme",
            ok,
            allow_http=True,
        ),
        case("el esquema se revisa antes que la forma", "http:///entrada", "scheme", ok),
        case("https sin barras", f"https:{host}/entrada", "invalid_url", ok),
        case("https con una sola barra", f"https:/{host}/entrada", "invalid_url", ok),
        case("https con tres barras", f"https:///{host}/entrada", "invalid_url", ok),
        case("https sin host", "https://", "invalid_url", ok),
        case("https sin host y con puerto", "https://:443/entrada", "invalid_url", ok),
        case("barra invertida en lugar de barra", f"https:\\\\{host}/entrada", "invalid_url", ok),
        case("barra invertida antes de una arroba", f"https://{host}\\@10.0.0.5/", "invalid_url", ok),
        case("barra invertida en la ruta", f"https://{host}/a\\b", "invalid_url", ok),
        case("espacio al principio", f" https://{host}/entrada", "invalid_url", ok),
        case("espacio al final", f"https://{host}/entrada ", "invalid_url", ok),
        case("espacio en la ruta", f"https://{host}/con espacio", "invalid_url", ok),
        case("tabulación en el nombre", "https://hooks.ejem\tplo.test/", "invalid_url", ok),
        case("salto de línea en el nombre", "https://hooks.ejem\nplo.test/", "invalid_url", ok),
        case("carácter nulo", f"https://{host}/\x00", "invalid_url", ok),
        case("carácter de borrado", f"https://{host}/\x7f", "invalid_url", ok),
        case("IPv4 abreviada", "https://127.1/", "invalid_url", ok),
        case("IPv4 como un solo número", "https://2130706433/", "invalid_url", ok),
        case("IPv4 en hexadecimal", "https://0x7f000001/", "invalid_url", ok),
        case("IPv4 con una parte en hexadecimal", "https://0x7f.0.0.1/", "invalid_url", ok),
        case("IPv4 con ceros a la izquierda", "https://010.0.0.1/", "invalid_url", ok),
        case("IPv4 con una parte fuera de rango", "https://256.1.1.1/", "invalid_url", ok),
        case("IPv4 con cinco partes", "https://1.2.3.4.5/", "invalid_url", ok),
        case("nombre que termina en un número", "https://ejemplo.123/", "invalid_url", ok),
        case("nombre que termina en un número y un punto", "https://ejemplo.123./", "invalid_url", ok),
        case("nombre que termina en 0x", "https://ejemplo.0x/", "invalid_url", ok),
        case("nombre con caracteres codificados", "https://%31%32%37.0.0.1/", "invalid_url", ok),
        case("nombre con caracteres fuera de ASCII", "https://mañana.test/", "invalid_url", ok),
        case("nombre con una etiqueta vacía", "https://hooks..test/", "invalid_url", ok),
        case("nombre que empieza con punto", "https://.hooks.test/", "invalid_url", ok),
        case("etiqueta de más de 63 caracteres", f"https://{'a' * 64}.test/", "invalid_url", ok),
        case("etiqueta de 63 caracteres", f"https://{'a' * 63}.test/", "allowed", ok),
        case(
            "nombre de más de 253 caracteres",
            f"https://{'.'.join(['a' * 50] * 5)}.test/",
            "invalid_url",
            ok,
        ),
        case("puerto vacío", f"https://{host}:/entrada", "invalid_url", ok),
        case("puerto fuera de rango", f"https://{host}:65536/", "invalid_url", ok),
        case("puerto con letras", f"https://{host}:80a/", "invalid_url", ok),
        case("puerto de seis dígitos", f"https://{host}:000080/", "invalid_url", ok),
        case("IPv6 sin corchetes", "https://2606:4700:4700::1111/", "invalid_url", ok),
        case("IPv6 sin cerrar el corchete", "https://[2606:4700:4700::1111/", "invalid_url", ok),
        case("IPv6 con identificador de zona", "https://[fe80::1%25eth0]/", "invalid_url", ok),
        case("IPv6 inválida", "https://[2606:4700::gggg]/", "invalid_url", ok),
        case("IPv4 entre corchetes", "https://[93.184.216.34]/", "invalid_url", ok),
        case("texto después del corchete", "https://[2606:4700:4700::1111]x/", "invalid_url", ok),
        case("con usuario y contraseña", "https://ana:clave@hooks.ejemplo.test/entrada", "credentials", ok),
        case("sólo con usuario", "https://ana@hooks.ejemplo.test/entrada", "credentials", ok),
        case("usuario vacío", f"https://@{host}/entrada", "credentials", ok),
        case("usuario y contraseña vacíos", f"https://:@{host}/entrada", "credentials", ok),
        case(
            "dos arrobas: el host es lo que sigue a la última",
            f"https://a@10.0.0.5@{host}/",
            "credentials",
            ok,
        ),
        case("usuario que parece un host", f"https://93.184.216.34@{host}/", "credentials", ok),
        case("usuario y host sin forma", "https://ana@/entrada", "invalid_url", ok),
        case(
            "el esquema se revisa antes que las credenciales",
            "http://ana:clave@hooks.ejemplo.test/",
            "scheme",
            ok,
        ),
        case("el nombre no resuelve", "https://hooks.ejemplo.test/entrada", "unresolved", []),
        case(
            "resuelve a una dirección privada",
            "https://hooks.ejemplo.test/entrada",
            "blocked_address",
            ["10.0.0.5"],
        ),
        case(
            "resuelve al servicio de metadatos",
            "https://hooks.ejemplo.test/entrada",
            "blocked_address",
            ["169.254.169.254"],
        ),
        case(
            "una privada entre varias públicas alcanza",
            "https://hooks.ejemplo.test/entrada",
            "blocked_address",
            ["93.184.216.34", "127.0.0.1"],
        ),
        case(
            "resuelve a algo que no es una dirección",
            "https://hooks.ejemplo.test/entrada",
            "blocked_address",
            ["no-es-ip"],
        ),
        case("dirección IPv4 literal de bucle local", "https://127.0.0.1/entrada", "blocked_address"),
        case("dirección IPv6 literal de bucle local", "https://[::1]:8443/entrada", "blocked_address"),
        case(
            "IPv6 literal que envuelve una IPv4 privada",
            "https://[::ffff:10.0.0.1]/entrada",
            "blocked_address",
        ),
        case("IPv6 literal que envuelve una IPv4 pública", "https://[::ffff:93.184.216.34]/", "allowed"),
        case("una dirección literal no usa la resolución", "https://10.0.0.5/entrada", "blocked_address", ok),
        case(
            "localhost resuelve a la máquina local",
            "https://localhost/",
            "blocked_address",
            ["127.0.0.1", "::1"],
        ),
        # Redes permitidas.
        case("resuelve a una red permitida", f"https://{host}/", "allowed", ["192.168.1.20"], allowed=lan),
        case("dirección literal en una red permitida", "https://192.168.1.20/", "allowed", allowed=lan),
        case(
            "privada fuera de las redes permitidas",
            f"https://{host}/",
            "blocked_address",
            ["10.0.0.5"],
            allowed=lan,
        ),
        case(
            "una permitida y una bloqueada alcanza para rechazar",
            f"https://{host}/",
            "blocked_address",
            ["192.168.1.20", "10.0.0.5"],
            allowed=lan,
        ),
        case(
            "una pública y una permitida",
            f"https://{host}/",
            "allowed",
            ["93.184.216.34", "192.168.1.20"],
            allowed=lan,
        ),
        case(
            "varias redes permitidas",
            f"https://{host}/",
            "allowed",
            ["10.1.2.3", "fd12:3456:789a::1"],
            allowed=["10.0.0.0/8", "fc00::/7"],
        ),
        case(
            "bucle local permitido",
            "https://localhost/",
            "allowed",
            ["127.0.0.1", "::1"],
            allowed=["127.0.0.0/8", "::1/128"],
        ),
        case(
            "bucle local permitido sólo para IPv4",
            "https://localhost/",
            "blocked_address",
            ["127.0.0.1", "::1"],
            allowed=["127.0.0.0/8"],
        ),
        case(
            "IPv6 que envuelve una IPv4 de una red permitida",
            "https://[::ffff:192.168.1.20]/",
            "allowed",
            allowed=lan,
        ),
        case(
            "una red IPv6 no permite una IPv4 envuelta",
            "https://[::ffff:192.168.1.20]/",
            "blocked_address",
            allowed=["::/0"],
        ),
        case("red de un solo host", "https://10.0.0.5/", "allowed", allowed=["10.0.0.5/32"]),
        case(
            "red de un solo host, otra dirección",
            "https://10.0.0.6/",
            "blocked_address",
            allowed=["10.0.0.5/32"],
        ),
        case("todo IPv4 permitido", "https://10.0.0.5/", "allowed", allowed=["0.0.0.0/0"]),
        case(
            "metadatos de la nube aunque se permita todo",
            f"https://{host}/",
            "blocked_address",
            ["169.254.169.254"],
            allowed=["0.0.0.0/0"],
        ),
        case(
            "enlace local aunque se permita su red",
            "https://169.254.10.1/",
            "blocked_address",
            allowed=["169.254.0.0/16"],
        ),
        case(
            "metadatos de Alibaba aunque se permita la red compartida",
            "https://100.100.100.200/",
            "blocked_address",
            allowed=["100.64.0.0/10"],
        ),
        case(
            "otra dirección de la red compartida permitida",
            "https://100.100.100.100/",
            "allowed",
            allowed=["100.64.0.0/10"],
        ),
        case(
            "metadatos de AWS por IPv6 aunque se permita su red",
            "https://[fd00:ec2::254]/",
            "blocked_address",
            allowed=["fc00::/7"],
        ),
        case(
            "metadatos envueltos en IPv6 aunque se permita todo",
            "https://[::ffff:169.254.169.254]/",
            "blocked_address",
            allowed=["0.0.0.0/0"],
        ),
        case(
            "permitir no salta la revisión de la forma",
            "https://127.1/",
            "invalid_url",
            ["127.0.0.1"],
            allowed=["127.0.0.0/8"],
        ),
        case(
            "permitir no salta las credenciales",
            "https://ana@192.168.1.20/",
            "credentials",
            allowed=lan,
        ),
        case(
            "permitir no cambia el esquema",
            "http://192.168.1.20/",
            "scheme",
            allowed=lan,
        ),
        case(
            "permitir una red no bloqueada no cambia nada",
            f"https://{host}/",
            "allowed",
            ok,
            allowed=["93.184.216.0/24"],
        ),
    ]
    return {"spec": SPEC, "id": "entregar/url", "kind": "url", "cases": cases}


def entregar_redes() -> Vector:
    valid = (
        "10.0.0.0/8 192.168.0.0/16 192.168.1.20/32 0.0.0.0/0 127.0.0.0/8 100.64.0.0/10 "
        "fc00::/7 ::1/128 ::/0 fd12:3456:789a::/48 FD12:3456:789A::/48 2001:db8::/32 "
        "::/95 ::/96 ::ffff:0:0:0/96"
    )
    invalid = [
        "",
        "10.0.0.0",
        "10.0.0.0/",
        "/8",
        "10.0.0.1/8",
        "10.0.0.0/33",
        "10.0.0.0/08",
        "10.0.0.0/-1",
        "10.0.0.0/+8",
        "10.0.0.0/ 8",
        " 10.0.0.0/8",
        "10.0.0.0/8 ",
        "010.0.0.0/8",
        "10.0/8",
        "10.0.0.0/255.0.0.0",
        "10.0.0.0/8/8",
        "fc00::/129",
        "fc00::1/7",
        "[fc00::]/7",
        "fe80::%eth0/10",
        "::ffff:0:0/96",
        "::ffff:10.0.0.0/104",
        "::ffff:192.168.0.0/112",
        "ejemplo.test/8",
        "10.0.0.0/1000",
    ]
    cases = []
    for text, want in [*((n, True) for n in valid.split()), *((n, False) for n in invalid)]:
        assert (parse_network(text) is not None) is want, text
        cases.append({"name": f"«{text}»", "network": text, "expected": {"valid": want}})
    return {"spec": SPEC, "id": "entregar/redes", "kind": "network", "cases": cases}


def classify(status: int | None, failure: str | None) -> str:
    if failure == "blocked":
        return "blocked"
    if failure in ("network", "timeout"):
        return "retryable"
    assert status is not None
    if 200 <= status <= 299:
        return "delivered"
    if status == 410:
        return "gone"
    if status in (408, 409, 425, 429) or 500 <= status <= 599:
        return "retryable"
    return "rejected"


def entregar_clasificacion() -> Vector:
    cases = [
        {
            "name": f"estado {status}",
            "status": status,
            "failure": None,
            "expected": {"class": classify(status, None)},
        }
        for status in (
            200,
            201,
            202,
            204,
            299,
            100,
            199,
            300,
            301,
            302,
            307,
            308,
            400,
            401,
            403,
            404,
            405,
            408,
            409,
            410,
            413,
            422,
            425,
            429,
            451,
            499,
            500,
            502,
            503,
            504,
            599,
            600,
        )
    ]
    cases += [
        {"name": label, "status": None, "failure": failure, "expected": {"class": classify(None, failure)}}
        for label, failure in (
            ("error de red", "network"),
            ("tiempo de espera agotado", "timeout"),
            ("rechazado por la política de URLs", "blocked"),
        )
    ]
    return {"spec": SPEC, "id": "entregar/clasificacion", "kind": "delivery-class", "cases": cases}


HTTP_DATE = re.compile(r"[A-Z][a-z]{2}, [0-9]{2} [A-Z][a-z]{2} [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT")
DEFAULT_SCHEDULE = [5, 300, 1800, 7200, 18000, 36000, 50400, 72000, 86400]


def retry_after_seconds(text: str | None, now: int) -> int | None:
    if text is None:
        return None
    if re.fullmatch(r"[0-9]+", text):
        return int(text)
    if not HTTP_DATE.fullmatch(text):
        return None
    try:
        delta = timegm(strptime(text, "%a, %d %b %Y %H:%M:%S GMT")) - now
    except ValueError:
        return None
    return delta if delta >= 0 else None


def entregar_reintentos() -> Vector:
    def case(name: str, attempt: int, **extra: Any) -> dict[str, Any]:
        schedule = extra.get("schedule", DEFAULT_SCHEDULE)
        now = extra.get("now", NOW)
        if attempt > len(schedule):
            expected: dict[str, Any] = {"exhausted": True}
        else:
            wait = schedule[attempt - 1]
            hint = retry_after_seconds(extra.get("retry_after"), now)
            if hint is not None:
                wait = max(wait, hint)
            wait = min(wait, extra.get("max_delay_seconds", 86400))
            wait += int(wait * extra.get("jitter_ratio", 0.1) * extra.get("random", 0.0))
            expected = {"exhausted": False, "delay_seconds": wait, "next_at": now + wait}
        out = {
            "name": name,
            "attempt": attempt,
            "now": now,
            "random": extra.get("random", 0.0),
            "retry_after": extra.get("retry_after"),
        }
        for key in ("schedule", "max_delay_seconds", "jitter_ratio"):
            if key in extra:
                out[key] = extra[key]
        return {**out, "expected": expected}

    # 2023-11-14 22:13:20 GMT es NOW.
    cases = [case(f"lista por defecto, después del intento {n}", n) for n in range(1, 11)]
    cases += [
        case("lista propia", 2, schedule=[10, 20, 30]),
        case("lista propia agotada", 4, schedule=[10, 20, 30]),
        case("lista vacía: un solo intento", 1, schedule=[]),
        case("retry-after mayor que la base", 1, retry_after="120"),
        case("retry-after menor que la base", 2, retry_after="120"),
        case("retry-after en cero", 1, retry_after="0"),
        case("retry-after como fecha", 1, retry_after="Tue, 14 Nov 2023 22:23:20 GMT"),
        case("retry-after como fecha ya pasada", 1, retry_after="Tue, 14 Nov 2023 22:00:00 GMT"),
        case("retry-after que no se entiende", 1, retry_after="pronto"),
        case("retry-after con un mes que no existe", 1, retry_after="Tue, 14 Foo 2023 22:23:20 GMT"),
        case("retry-after con una fecha imposible", 1, retry_after="Fri, 31 Feb 2024 10:00:00 GMT"),
        case("retry-after con una hora imposible", 1, retry_after="Tue, 14 Nov 2023 25:00:00 GMT"),
        case("retry-after con el día en un dígito", 1, retry_after="Tue, 4 Nov 2025 22:23:20 GMT"),
        case("retry-after con otra zona", 1, retry_after="Tue, 14 Nov 2023 22:23:20 UTC"),
        case("retry-after con fecha lejana: manda el tope", 1, retry_after="Thu, 14 Nov 2024 22:13:20 GMT"),
        case("retry-after con decimales se ignora", 1, retry_after="1.5"),
        case("retry-after negativo se ignora", 1, retry_after="-5"),
        case("retry-after por encima del tope", 1, retry_after="999999"),
        case("tope propio por debajo de la base", 5, max_delay_seconds=3600),
        case("variación máxima", 2, random=0.999),
        case("variación a la mitad", 3, random=0.5),
        case("la variación se aplica después del tope", 9, random=0.5),
        case("proporción de variación propia", 2, random=0.5, jitter_ratio=0.5),
        case("sin variación", 2, random=0.999, jitter_ratio=0),
        case("la variación redondea hacia abajo", 1, random=0.999),
        case("retry-after con variación", 1, retry_after="100", random=0.25),
    ]
    assert retry_after_seconds("Tue, 14 Nov 2023 22:13:20 GMT", NOW) == 0
    return {"spec": SPEC, "id": "entregar/reintentos", "kind": "retry", "cases": cases}


# Cada función arma un archivo de vectores: {"spec", "id", "kind", "cases"}.
# El `id` es además la ruta del archivo dentro de spec/vectors/.
ALL: list[Callable[[], Vector]] = [
    verificar_standard,
    verificar_stripe,
    verificar_tiktok,
    verificar_mercadopago,
    verificar_github,
    verificar_slack,
    verificar_shopify,
    verificar_varios,
    verificar_creem,
    verificar_hmac_body,
    firmar_standard,
    reservas_almacen,
    recibir_respuesta,
    recibir_caso_de_uso,
    entregar_direcciones,
    entregar_url,
    entregar_redes,
    entregar_clasificacion,
    entregar_reintentos,
]


def render(data: Vector) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    expected = {VECTORS / f"{data['id']}.json": render(data) for data in (build() for build in ALL)}
    on_disk = set(VECTORS.rglob("*.json")) if VECTORS.exists() else set()

    if check:
        problems = [
            f"falta o difiere: {p.relative_to(ROOT)}"
            for p, text in expected.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text
        ]
        problems += [f"sobra: {p.relative_to(ROOT)}" for p in sorted(on_disk - set(expected))]
        for line in problems:
            print(line, file=sys.stderr)
        if problems:
            print("Los vectores no coinciden. Corré: python3 tools/gen_vectors.py", file=sys.stderr)
            return 1
        print(f"{len(expected)} vectores en sincronía.")
        return 0

    for stale in on_disk - set(expected):
        stale.unlink()
    for path, text in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    total = sum(len(json.loads(text)["cases"]) for text in expected.values())
    print(f"{len(expected)} vectores, {total} casos, en {VECTORS.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
