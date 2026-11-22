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


def values(pairs: Pairs, name: str) -> list[str]:
    found = [value.strip() for key, value in pairs if key.lower() == name.lower()]
    return [value for value in found if value]


def split_pairs(text: str, lower: bool = False) -> list[tuple[str, str]]:
    out = []
    for piece in text.split(","):
        key, sep, value = piece.partition("=")
        key, value = key.strip(), value.strip()
        if sep and key and value:
            out.append((key.lower() if lower else key, value))
    return out


def fingerprint(scheme: str, body: bytes) -> str:
    return f"{scheme}:sha256:{hashlib.sha256(body).hexdigest()}"


def json_id(scheme: str, body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return fingerprint(scheme, body)
    if type(data) is dict and type(data.get("id")) is str and data["id"]:
        return f"{scheme}:{data['id']}"
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

        elif scheme in ("github", "creem", "hmac-body"):
            preset = {
                "github": {
                    "header": "x-hub-signature-256",
                    "prefix": "sha256=",
                    "id_header": "x-github-delivery",
                },
                "creem": {"header": "creem-signature"},
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
}


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
    ) -> dict[str, Any]:
        secrets = [STD_SECRET] if secrets is None else secrets
        shelf = Shelf()
        prior = played(before or [], shelf)
        verdict = check({"scheme": "standard", "secrets": secrets, "now": NOW, "request": req})
        outcome, called = verdict["outcome"], False
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


def is_blocked(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return True
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address.version == net.version and address in net for net in BLOCKED_NETS)


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


def entregar_url() -> Vector:
    def case(
        name: str, url: str, expected: str, resolved: list[str] | None = None, allow_http: bool = False
    ) -> dict[str, Any]:
        return {
            "name": name,
            "url": url,
            "allow_http": allow_http,
            "resolved": resolved or [],
            "expected": {"result": expected},
        }

    ok = ["93.184.216.34"]
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
        case("texto que no es una URL", "esto no es una url", "invalid_url"),
        case("texto vacío", "", "invalid_url"),
        case("URL relativa", "/entrada", "invalid_url"),
        case("esquema sin host", "mailto:alguien@ejemplo.test", "invalid_url"),
        case("archivo local", "file:///etc/hosts", "invalid_url"),
        case("http sin permiso", "http://hooks.ejemplo.test/entrada", "scheme", ok),
        case("otro esquema", "ftp://hooks.ejemplo.test/entrada", "scheme", ok),
        case(
            "otro esquema aunque se permita http",
            "ftp://hooks.ejemplo.test/entrada",
            "scheme",
            ok,
            allow_http=True,
        ),
        case("con usuario y contraseña", "https://ana:clave@hooks.ejemplo.test/entrada", "credentials", ok),
        case("sólo con usuario", "https://ana@hooks.ejemplo.test/entrada", "credentials", ok),
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
        case("una dirección literal no usa la resolución", "https://10.0.0.5/entrada", "blocked_address", ok),
    ]
    return {"spec": SPEC, "id": "entregar/url", "kind": "url", "cases": cases}


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
    verificar_mercadopago,
    verificar_github,
    verificar_creem,
    verificar_hmac_body,
    firmar_standard,
    reservas_almacen,
    recibir_respuesta,
    recibir_caso_de_uso,
    entregar_direcciones,
    entregar_url,
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
