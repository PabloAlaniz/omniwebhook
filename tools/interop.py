#!/usr/bin/env python3
"""Prueba de interoperabilidad entre los paquetes.

Levanta un agente por paquete y les manda los mismos pedidos. Comprueba tres cosas:

1. Lo que firma un paquete lo verifica el otro, y también la librería de referencia del
   formato estándar.
2. Ante el mismo pedido, los dos responden exactamente lo mismo. Los pedidos salen de los
   vectores de conformidad y de variaciones al azar, con una semilla fija para que una
   diferencia se pueda reproducir.
3. Los dos comparten una misma tabla de reservas y de intentos: lo que reserva o registra
   uno lo ve el otro. Siempre sobre un archivo SQLite y, con `OMNIWEBHOOK_PG_URL`, también
   sobre PostgreSQL.

Uso: `python3 tools/interop.py [--seed N] [--rounds N]`. Antes hay que compilar el paquete
de TypeScript (`pnpm build`). No importa ninguno de los paquetes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "spec" / "vectors"
TABLE = "omniwebhook_events_interop"
Json = dict[str, Any]


class Agent:
    def __init__(self, name: str, command: list[str], cwd: Path) -> None:
        self.name = name
        self._process = subprocess.Popen(  # noqa: S603
            command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8"
        )

    def ask(self, command: str, **data: Any) -> Json:
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._process.stdin.write(json.dumps({"command": command, **data}) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            raise RuntimeError(f"el agente de {self.name} terminó sin responder")
        reply: Json = json.loads(line)
        return reply

    def close(self) -> None:
        assert self._process.stdin is not None
        self._process.stdin.close()
        self._process.wait(timeout=30)


class Report:
    def __init__(self) -> None:
        self.checked = 0
        self.failures: list[str] = []

    def same(self, what: str, data: Json, replies: dict[str, Json]) -> None:
        """Los dos paquetes tienen que responder lo mismo, y ninguno puede romperse."""
        self.checked += 1
        (first_name, first), (second_name, second) = replies.items()
        if first != second or "crashed" in first:
            self.failures.append(
                f"{what}\n  pedido: {json.dumps(data, ensure_ascii=True)}\n"
                f"  {first_name}: {json.dumps(first)}\n  {second_name}: {json.dumps(second)}"
            )

    def expect(self, what: str, got: Any, wanted: Any) -> None:
        self.checked += 1
        if got != wanted:
            self.failures.append(
                f"{what}\n  se esperaba: {json.dumps(wanted)}\n  se obtuvo: {json.dumps(got)}"
            )


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def cases(vector: str) -> list[Json]:
    found: list[Json] = json.loads((VECTORS / f"{vector}.json").read_text(encoding="utf-8"))["cases"]
    return found


def both(agents: list[Agent], report: Report, what: str, command: str, data: Json) -> Json:
    replies = {agent.name: agent.ask(command, **data) for agent in agents}
    report.same(what, {"command": command, **data}, replies)
    return next(iter(replies.values()))


# --- 1. Lo que firma uno lo verifica el otro ------------------------------------

SECRETS = [
    "whsec_" + b64(b"omniwebhook-secreto-sintetico-01"),
    "whsec_" + b64(b"omniwebhook-secreto-sintetico-02"),
]
PAYLOADS = [
    b'{"type":"pedido.creado","data":{"id":42}}',
    b"",
    "Ñandú 🦤   línea\nnueva".encode(),
    b"\xff\xfe\x00 no es utf-8 \x80",
    b" " * 3 + b"{}" + b"\n",
]


def cross_signing(agents: list[Agent], report: Report, rng: random.Random, rounds: int) -> None:
    payloads = [*PAYLOADS, *(rng.randbytes(rng.randrange(1, 4096)) for _ in range(rounds))]
    for index, payload in enumerate(payloads):
        now = int(time.time())
        identifier = f"msg_{index}_{rng.getrandbits(64):x}"
        secrets = SECRETS[: 1 + index % 2]
        for signer in agents:
            signed = signer.ask("sign", secrets=secrets, id=identifier, timestamp=now, payload=b64(payload))
            report.expect(f"{signer.name} firma el mensaje {index}", signed.get("outcome"), "signed")
            if signed.get("outcome") != "signed":
                continue
            headers = signed["headers"]
            request = {"headers": list(headers.items()), "query": [], "body": b64(payload)}
            altered = {**request, "body": b64(payload + b"x")}
            for verifier in agents:
                pair = f"{signer.name} firma y {verifier.name} verifica el mensaje {index}"
                # Alcanza con el último secreto de la lista: así se rota sin cortar el servicio.
                got = verifier.ask(
                    "verify", scheme="standard", secrets=secrets[-1:], now=now, request=request
                )
                wanted = {"outcome": "ok", "event_key": f"standard:{identifier}", "timestamp": now}
                report.expect(pair, got, wanted)
                got = verifier.ask(
                    "verify", scheme="standard", secrets=secrets[-1:], now=now, request=altered
                )
                report.expect(f"{pair}, con el cuerpo alterado", got, {"outcome": "invalid"})
                got = verifier.ask("reference_verify", secret=secrets[0], headers=headers, body=b64(payload))
                report.expect(f"{pair} con la librería de referencia", got, {"valid": True})


def cross_key_signing(agents: list[Agent], report: Report, rng: random.Random, rounds: int) -> None:
    """Lo mismo con la firma asimétrica: uno firma con la clave privada y el otro verifica con la pública."""
    payloads = [*PAYLOADS, *(rng.randbytes(rng.randrange(1, 4096)) for _ in range(rounds))]
    for index, payload in enumerate(payloads):
        now = int(time.time())
        identifier = f"msg_{index}_{rng.getrandbits(64):x}"
        endpoint = f"ep_{rng.getrandbits(32):x}"
        # Claves sintéticas, nuevas en cada corrida.
        keys = ["whsk_" + base64.b64encode(rng.randbytes(32)).decode() for _ in range(1 + index % 2)]
        data = {
            "secret_keys": keys,
            "id": identifier,
            "timestamp": now,
            "payload": b64(payload),
            "endpoint_id": endpoint,
        }
        # Ed25519 es determinista: los dos paquetes tienen que dar la misma firma y las mismas claves.
        signed = both(agents, report, f"firma asimétrica del mensaje {index}", "sign_key", data)
        report.expect(f"se firma el mensaje {index} con clave privada", signed.get("outcome"), "signed")
        if signed.get("outcome") != "signed":
            continue
        request = {"headers": list(signed["headers"].items()), "query": [], "body": b64(payload)}
        for verifier in agents:
            what = f"{verifier.name} verifica con la clave pública el mensaje {index}"
            base = {
                "scheme": "standard-v2a",
                "secrets": signed["public_keys"][-1:],
                "now": now,
                "request": request,
            }
            got = verifier.ask("verify", **base, options={"endpoint_id": endpoint})
            report.expect(
                what, got, {"outcome": "ok", "event_key": f"standard:{identifier}", "timestamp": now}
            )
            got = verifier.ask("verify", **base, options={"endpoint_id": endpoint + "x"})
            report.expect(f"{what}, para otro destino", got, {"outcome": "invalid"})
            altered = {**base, "request": {**request, "body": b64(payload + b"x")}}
            got = verifier.ask("verify", **altered, options={"endpoint_id": endpoint})
            report.expect(f"{what}, con el cuerpo alterado", got, {"outcome": "invalid"})


# --- 2. Ante el mismo pedido, la misma respuesta ---------------------------------

ODD = [" ", "\t", " ", "　", "\x0b", "\x1f", "﻿", " ", ",", "=", ";", "é", "İ", "ß"]
BODIES = [
    '{"id":"evt_1"}',
    '﻿{"id":"evt_1"}',
    '{"id":"evt_1","n":NaN}',
    '{"id":"evt_1","n":-Infinity}',
    '{"id":"evt_1","id":"evt_2"}',
    '{"id":"evt_\\u0000\\u00e9"}',
    '{"id":"evt_1","n":' + "9" * 5000 + "}",
    '{"id":"evt_1","n":1e999}',
    '{"id":"evt_1","n":01}',
    '{"id":"evt_1",}',
    '{"ID":"evt_1"}',
    '{"id":["evt_1"]}',
    '{"id":true}',
    ' \n\t{"id":"evt_1"}\r\n',
    '\x0b{"id":"evt_1"}',
    '{"id":"evt_1","a":' + "[" * 200 + "]" * 200 + "}",
    '"evt_1"',
    "",
    "{",
    '{"id":"línea\nrota"}',
    '{"id":"🦤"}',
]


def mutate_text(rng: random.Random, text: str) -> str:
    choice = rng.randrange(7)
    position = rng.randrange(len(text) + 1)
    if choice == 0:
        return rng.choice(ODD) + text
    if choice == 1:
        return text + rng.choice(ODD)
    if choice == 2:
        return text[:position] + rng.choice(ODD) + text[position:]
    if choice == 3 and text:
        return text[: position - 1] + text[position:]
    if choice == 4:
        return text.swapcase()
    if choice == 5:
        return text + "," + text
    return text[:position] + rng.choice("0aZ9+/=") + text[position + 1 :]


def mutate_request(rng: random.Random, case: Json) -> Json:
    case = json.loads(json.dumps(case))
    request = case["request"]
    for _ in range(rng.randrange(1, 4)):
        choice = rng.randrange(9)
        fields = request["headers"] if rng.random() < 0.8 or not request["query"] else request["query"]
        if choice <= 2 and fields:
            field = rng.choice(fields)
            field[1] = mutate_text(rng, field[1])
        elif choice == 3 and fields:
            field = rng.choice(fields)
            field[0] = field[0].upper() if rng.random() < 0.5 else mutate_text(rng, field[0])
        elif choice == 4 and fields:
            fields.append(list(rng.choice(fields)))
        elif choice == 5 and fields:
            fields.pop(rng.randrange(len(fields)))
        elif choice == 6:
            case["now"] += rng.choice([-301, -300, -1, 1, 300, 301, 10**6, -(10**9)])
        elif choice == 7:
            request["body"] = rng.choice(BODIES) if rng.random() < 0.5 else mutate_text(rng, request["body"])
        else:
            case["secrets"] = rng.choice(
                [[], [""], ["whsec_"], ["whsec_AAA"], [*case["secrets"], "otro"], ["otro"]]
            )
    return case


def ask_verify(agents: list[Agent], report: Report, what: str, case: Json) -> Json:
    request = {**case["request"], "body": b64(case["request"]["body"].encode("utf-8", "surrogatepass"))}
    data = {"scheme": case["scheme"], "secrets": case["secrets"], "now": case["now"], "request": request}
    if case.get("options"):
        data["options"] = case["options"]
    return both(agents, report, what, "verify", data)


def differential_verify(agents: list[Agent], report: Report, rng: random.Random, rounds: int) -> None:
    schemes = [
        "standard",
        "standard-v2a",
        "discord",
        "stripe",
        "tiktok",
        "mercadopago",
        "github",
        "creem",
        "slack",
        "shopify",
        "hmac-body",
        "shared-token",
        "google-channel",
        "google-pubsub",
    ]
    seeds = [case for scheme in schemes for case in cases(f"verificar/{scheme}")]
    for case in seeds:
        got = ask_verify(agents, report, f"vector {case['scheme']}: {case['name']}", case)
        report.expect(f"vector {case['scheme']}: {case['name']}", got, case["expected"])
    for number in range(rounds * 40):
        seed = rng.choice(seeds)
        ask_verify(
            agents,
            report,
            f"variación {number} de {seed['scheme']}: {seed['name']}",
            mutate_request(rng, seed),
        )

    # Cuerpos difíciles con una firma válida, para llegar hasta la clave del evento.
    secret = "secreto-sintetico-uno"
    for body in BODIES:
        raw = body.encode("utf-8", "surrogatepass")
        mac = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        stamped = hmac.new(secret.encode(), b"1700000000." + raw, hashlib.sha256).hexdigest()
        versioned = hmac.new(secret.encode(), b"v0:1700000000:" + raw, hashlib.sha256).hexdigest()
        for scheme, headers, query in (
            ("creem", [["creem-signature", mac]], []),
            ("stripe", [["stripe-signature", f"t=1700000000,v1={stamped}"]], []),
            ("tiktok", [["tiktok-signature", f"t=1700000000,s={stamped}"]], []),
            (
                "slack",
                [["x-slack-signature", f"v0={versioned}"], ["x-slack-request-timestamp", "1700000000"]],
                [],
            ),
            ("google-pubsub", [], [["token", secret]]),
        ):
            case = {
                "scheme": scheme,
                "secrets": [secret],
                "now": 1_700_000_000,
                "request": {"headers": headers, "query": query, "body": body},
            }
            got = ask_verify(agents, report, f"{scheme} con el cuerpo {body[:40]!r}", case)
            report.expect(f"{scheme} con el cuerpo {body[:40]!r} es válido", got.get("outcome"), "ok")


ADDRESS_ALPHABET = "0123456789abcdefABCDEF:::...%/ gx-"
ADDRESS_PARTS = ["::", "ffff", "0", "127", "10", "255", "256", "fe80", "64:ff9b", "1.2.3.4", "0x7f", "00", ""]


def random_address(rng: random.Random) -> str:
    choice = rng.randrange(5)
    if choice == 0:
        return ".".join(
            str(rng.choice([0, 1, 10, 100, 127, 169, 172, 192, 198, 203, 224, 255, 256])) for _ in range(4)
        )
    if choice == 1:
        groups = [f"{rng.getrandbits(16):x}" for _ in range(rng.randrange(1, 9))]
        if rng.random() < 0.6:
            groups.insert(rng.randrange(len(groups) + 1), "")
        return ":".join(groups)
    if choice == 2:
        return rng.choice([":", "::", ""]).join(rng.choice(ADDRESS_PARTS) for _ in range(rng.randrange(1, 6)))
    if choice == 3:
        return "::ffff:" + ".".join(str(rng.randrange(300)) for _ in range(4))
    return "".join(rng.choice(ADDRESS_ALPHABET) for _ in range(rng.randrange(0, 24)))


URL_SCHEMES = [
    "https",
    "https",
    "https",
    "https",
    "http",
    "HTTPS",
    "hTTp",
    "ftp",
    "file",
    "",
    "javascript",
    "ws",
]
URL_SEPARATORS = ["://", "://", "://", "://", "://", ":", ":/", ":///", ":\\\\", "//"]
URL_USERS = ["", "", "", "", "ana@", "ana:clave@", ":@", "@", "a@b@", "10.0.0.5@", "ana\\@", "%40@"]
URL_HOSTS = [
    "hooks.ejemplo.test",
    "HOOKS.Ejemplo.Test",
    "hooks.ejemplo.test.",
    "mi_servicio.sub-dominio.test",
    "xn--maana-pta.test",
    "xn--.test",
    "-a-.test",
    "localhost",
    "127.0.0.1",
    "10.0.0.5",
    "93.184.216.34",
    "169.254.169.254",
    "0.0.0.0",
    "127.1",
    "2130706433",
    "0x7f000001",
    "0x7f.1",
    "017.0.0.1",
    "1.2.3.4.5",
    "256.1.1.1",
    "ejemplo.123",
    "ejemplo.0x",
    "ejemplo.1e3",
    "1a.2b.test",
    "%31%32%37.0.0.1",
    "mañana.test",
    "hooks..test",
    ".test",
    "ｅｊｅｍｐｌｏ.test",
    "ejemplo。test",
    "a" * 63 + ".test",
    "a" * 64 + ".test",
    "[::1]",
    "[2606:4700:4700::1111]",
    "[2606:4700:4700:0:0:0:0:1111]",
    "[2606:4700:4700::ABCD]",
    "[::ffff:10.0.0.1]",
    "[::ffff:93.184.216.34]",
    "[::ffff:5db8:d822]",
    "[fe80::1%25eth0]",
    "[::1",
    "::1",
    "[93.184.216.34]",
    "[::1]x",
    "",
]
URL_PORTS = ["", "", "", ":443", ":8443", ":0", ":65535", ":65536", ":", ":80a", ":000080", ":-1", ":８０"]
URL_PATHS = [
    "",
    "/",
    "/entrada",
    "/entrada?canal=1",
    "/a/b/../c",
    "/con espacio",
    "/ñ",
    "/#parte",
    "?solo=consulta",
    "#parte",
    "/a@b",
    "/a:b",
    "/a\\b",
    "\\@10.0.0.5/",
    "/\t",
    "/%2e%2e/",
    "/\x7f",
]
URL_WRAPS = ["{}", "{}", "{}", "{}", "{}", " {}", "{} ", "\t{}", "{}\n", "\x00{}"]
RESOLVED = [
    [],
    ["93.184.216.34"],
    ["10.0.0.5"],
    ["93.184.216.34", "127.0.0.1"],
    ["2606:4700:4700::1111"],
    ["no-es-ip"],
    ["192.168.1.20"],
    ["169.254.169.254"],
    ["fd12:3456:789a::1", "::ffff:10.0.0.5"],
]
ALLOWED = [
    [],
    [],
    ["192.168.0.0/16"],
    ["10.0.0.0/8", "fc00::/7"],
    ["127.0.0.0/8", "::1/128"],
    ["0.0.0.0/0", "::/0"],
]
NETWORK_ADDRESSES = [
    "10.0.0.0",
    "10.0.0.1",
    "192.168.0.0",
    "0.0.0.0",
    "fc00::",
    "fc00::1",
    "::ffff:0:0",
    "::",
    "01.0.0.0",
]


def random_network(rng: random.Random) -> str:
    address = rng.choice([*NETWORK_ADDRESSES, random_address(rng)])
    prefix = rng.choice(
        ["0", "7", "8", "16", "32", "33", "64", "96", "104", "128", "129", "08", "", "-1", " 8"]
    )
    return rng.choice(["{}/{}", "{}/{}", "{}{}", "{}//{}", "[{}]/{}"]).format(address, prefix)


def random_url(rng: random.Random) -> str:
    scheme = rng.choice(URL_SCHEMES)
    url = (scheme + rng.choice(URL_SEPARATORS)) if scheme else rng.choice(["", "//"])
    url += rng.choice(URL_USERS) + rng.choice(URL_HOSTS) + rng.choice(URL_PORTS) + rng.choice(URL_PATHS)
    if rng.random() < 0.1:
        url = mutate_text(rng, url)
    return rng.choice(URL_WRAPS).format(url)


def normal_host(host: str | None) -> str | None:
    if host is None or ":" not in host:
        return host
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host


def check_url(agents: list[Agent], report: Report, data: Json, expected: str | None = None) -> None:
    """Los dos paquetes coinciden, y lo que aceptan lo entiende igual el analizador de cada plataforma."""
    what = f"URL {data['url']!r}"
    replies = {agent.name: agent.ask("url", **data) for agent in agents}
    # El analizador de cada plataforma escribe distinto una misma dirección: se compara aparte.
    platforms = {name: reply.pop("platform", None) for name, reply in replies.items()}
    report.same(what, {"command": "url", **data}, replies)
    reply = next(iter(replies.values()))
    if expected is not None:
        report.expect(what, reply.get("result"), expected)
    if "host" not in reply:
        return
    for name, platform in platforms.items():
        # Que la plataforma rechace una URL que la política aceptó no es una diferencia: el
        # intento falla sin salir hacia ningún lado. Pasa con etiquetas `xn--` que no son
        # Punycode válido. Lo que no puede pasar es que lea otro host.
        if platform is None:
            continue
        seen = normal_host(platform["host"])
        report.expect(f"{what}: el host que ve el analizador de {name}", seen, normal_host(reply["host"]))


def differential_domain(agents: list[Agent], report: Report, rng: random.Random, rounds: int) -> None:
    for case in cases("entregar/direcciones"):
        both(agents, report, f"dirección {case['address']!r}", "address", {"address": case["address"]})
    for _ in range(rounds * 40):
        address = random_address(rng)
        both(agents, report, f"dirección {address!r}", "address", {"address": address})

    for case in cases("entregar/redes"):
        reply = both(agents, report, f"red {case['network']!r}", "network", {"network": case["network"]})
        report.expect(f"red {case['network']!r}", reply.get("valid"), case["expected"]["valid"])
    for _ in range(rounds * 40):
        network = random_network(rng)
        both(agents, report, f"red {network!r}", "network", {"network": network})

    for case in cases("entregar/url"):
        data = {key: case[key] for key in ("url", "allow_http", "allowed_networks", "resolved")}
        check_url(agents, report, data, case["expected"]["result"])
    for _ in range(rounds * 80):
        data = {
            "url": random_url(rng),
            "allow_http": rng.random() < 0.4,
            "allowed_networks": rng.choice(ALLOWED),
            "resolved": rng.choice(RESOLVED),
        }
        check_url(agents, report, data)

    for status in [None, *range(100, 600)]:
        failures = ["network", "timeout", "blocked"] if status is None else [None]
        for failure in failures:
            both(
                agents,
                report,
                f"clasificación de {status or failure}",
                "classify",
                {"status": status, "failure": failure},
            )

    for case in cases("recibir/respuesta-http"):
        both(agents, report, f"estado HTTP de {case['outcome']}", "status", {"outcome": case["outcome"]})

    for case in cases("entregar/tipos"):
        data = {"type": case["type"], "patterns": case["patterns"]}
        got = both(agents, report, f"tipo de evento: {case['name']}", "event", data)
        report.expect(f"tipo de evento: {case['name']}", got, case["expected"])
    pieces = ["pedido", "item", "creado", "*", ".", "..", "", "a-b", "x_1", "ñ", " ", "A"]
    for number in range(rounds * 20):
        build = lambda: "".join(rng.choice(pieces) for _ in range(rng.randrange(0, 6)))  # noqa: E731
        patterns = None if rng.random() < 0.1 else [build() for _ in range(rng.randrange(0, 4))]
        both(
            agents,
            report,
            f"tipo de evento al azar {number}",
            "event",
            {"type": build(), "patterns": patterns},
        )

    for case in cases("entregar/salud"):
        data = {key: case[key] for key in ("attempts", "since", "now", "policy") if key in case}
        got = both(agents, report, f"salud: {case['name']}", "health", data)
        report.expect(f"salud: {case['name']}", got, case["expected"])
    classes = ["delivered", "retryable", "rejected", "blocked", "gone"]
    for number in range(rounds * 20):
        start = 1_700_000_000 - rng.randrange(0, 10 * 86_400)
        attempts = [
            {"at": start + rng.randrange(0, 8 * 86_400), "delivery_class": rng.choice(classes)}
            for _ in range(rng.randrange(0, 12))
        ]
        data = {
            "attempts": attempts,
            "since": rng.choice([0, start, start + 86_400]),
            "now": 1_700_000_000,
            "policy": {
                "window_seconds": rng.choice([60, 86_400, 432_000]),
                "min_failures": rng.randrange(1, 8),
            },
        }
        both(agents, report, f"salud al azar {number}", "health", data)

    now = 1_700_000_000
    retry_after = [
        None,
        "0",
        "7",
        "120",
        "86401",
        "9" * 30,
        "9" * 400,
        "-5",
        "1.5",
        " 5",
        "５",
        "",
        "Sun, 06 Nov 1994 08:49:37 GMT",
        "Tue, 14 Nov 2023 22:14:20 GMT",
        "Tue, 14 Nov 2023 23:13:20 GMT",
        "Wed, 15 Nov 2023 22:13:20 GMT",
        "Thu, 30 Feb 2023 00:00:00 GMT",
        "Tue, 14 Nov 2023 24:00:00 GMT",
        "Tue, 14 Nov 2023 23:59:60 GMT",
        "Tue, 14 Nov 0000 23:13:20 GMT",
        "Tue, 14 Nov 0099 23:13:20 GMT",
        "Fri, 31 Dec 9999 23:59:59 GMT",
        "Xyz, 14 Nov 2023 23:13:20 GMT",
        "Tue, 14 Nov 2023 23:13:20 UTC",
        "tue, 14 nov 2023 23:13:20 gmt",
        "Tue, 4 Nov 2023 23:13:20 GMT",
    ]
    for _ in range(rounds * 40):
        data: Json = {
            "attempt": rng.randrange(1, 14),
            "now": now + rng.randrange(0, 10**6),
            "random": rng.random() if rng.random() < 0.8 else rng.choice([0.0, 0.5, 0.999999999999]),
            "retry_after": rng.choice(retry_after),
        }
        if rng.random() < 0.5:
            data["schedule"] = [rng.randrange(0, 200_000) for _ in range(rng.randrange(0, 12))]
        if rng.random() < 0.5:
            data["max_delay_seconds"] = rng.choice([1, 60, 3600, 86_400, 10**9])
        if rng.random() < 0.5:
            data["jitter_ratio"] = rng.choice([0, 0.1, 0.25, 1 / 3, 1, 2.5])
        both(agents, report, "reintento", "retry", data)


# --- 3. Una misma tabla de reservas ---------------------------------------------


def shared_store(agents: list[Agent], report: Report, url: str) -> None:
    for index, agent in enumerate(agents):
        agent.ask("store_open", url=url, table=TABLE, create=index == 0)
    try:
        for offset in range(len(agents)):
            for number, case in enumerate(cases("reservas/almacen")):
                # Cada caso usa sus propias claves, y los pasos se alternan entre los paquetes.
                suffix = f":{offset}:{number}"
                for position, step in enumerate(case["steps"]):
                    agent = agents[(position + offset) % len(agents)]
                    data = {key: value for key, value in step.items() if key != "expected"}
                    data["key"] += suffix
                    got = agent.ask("store_step", **data)
                    what = f"almacén compartido, «{case['name']}», paso {position + 1} en {agent.name}"
                    report.expect(what, got, {"result": step["expected"]})
    finally:
        for index, agent in enumerate(agents):
            agent.ask("store_close", table=TABLE, drop=index == 0)


OUTBOX_TABLE = "omniwebhook_outbox_interop"


def shared_outbox(agents: list[Agent], report: Report, url: str) -> None:
    """Lo que encola un paquete lo toma y lo cierra el otro, sobre la misma tabla."""
    for index, agent in enumerate(agents):
        agent.ask("outbox_open", url=url, table=OUTBOX_TABLE, create=index == 0)
    try:
        for offset in range(len(agents)):
            for case in cases("entregar/bandeja"):
                agents[0].ask("outbox_reset", table=OUTBOX_TABLE)
                # Los pasos se alternan entre los paquetes.
                for position, step in enumerate(case["steps"]):
                    agent = agents[(position + offset) % len(agents)]
                    data = {key: value for key, value in step.items() if key != "expected"}
                    got = agent.ask("outbox_step", **data)
                    what = f"bandeja compartida, «{case['name']}», paso {position + 1} en {agent.name}"
                    report.expect(what, got, {"result": step["expected"]})
    finally:
        for index, agent in enumerate(agents):
            agent.ask("outbox_close", table=OUTBOX_TABLE, drop=index == 0)


LEDGER_TABLE = "omniwebhook_attempts_interop"
ATTEMPTS = [
    {
        "message_id": "msg_interop",
        "endpoint_id": "ep_1",
        "attempt": 1,
        "at": 1_700_000_000,
        "delivery_class": "retryable",
        "state": "pending",
        "status": 503,
        "problem": None,
        "duration_ms": 40,
        "next_at": 1_700_000_005,
    },
    {
        "message_id": "msg_interop",
        "endpoint_id": "ep_1",
        "attempt": 2,
        "at": 1_700_000_005,
        "delivery_class": "blocked",
        "state": "blocked",
        "status": None,
        "problem": "blocked_address",
        "duration_ms": 0,
        "next_at": None,
    },
    {
        "message_id": "msg_interop",
        "endpoint_id": "ep_1",
        "attempt": 1,
        "at": 4_102_444_800,
        "delivery_class": "delivered",
        "state": "delivered",
        "status": 200,
        "problem": None,
        "duration_ms": 86_400_000,
        "next_at": None,
    },
]


def shared_ledger(agents: list[Agent], report: Report, url: str) -> None:
    """Lo que registra un paquete en la tabla de intentos lo lee el otro tal cual."""
    for index, agent in enumerate(agents):
        agent.ask("ledger_open", url=url, table=LEDGER_TABLE, create=index == 0)
    try:
        for position, record in enumerate(ATTEMPTS):
            agents[position % len(agents)].ask("ledger_record", record=record)
        for agent in agents:
            got = agent.ask("ledger_read", message_id="msg_interop", endpoint_id="ep_1")
            report.expect(f"registro compartido leído en {agent.name}", got, {"attempts": ATTEMPTS})
    finally:
        for index, agent in enumerate(agents):
            agent.ask("ledger_close", table=LEDGER_TABLE, drop=index == 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=20261122)
    parser.add_argument("--rounds", type=int, default=25, help="cuántas tandas de variaciones al azar")
    parser.add_argument("--show", type=int, default=40, help="cuántas diferencias mostrar")
    arguments = parser.parse_args()

    if not (ROOT / "ts" / "dist" / "index.js").exists():
        print("Falta compilar el paquete de TypeScript: corré `pnpm build`.", file=sys.stderr)
        return 2

    agents = [
        Agent("typescript", ["node", "interop/agent.mjs"], ROOT / "ts"),
        Agent("python", ["uv", "run", "--quiet", "python", "interop/agent.py"], ROOT / "python"),
    ]
    report = Report()
    rng = random.Random(arguments.seed)  # noqa: S311
    try:
        cross_signing(agents, report, rng, arguments.rounds)
        cross_key_signing(agents, report, rng, arguments.rounds)
        differential_verify(agents, report, rng, arguments.rounds)
        differential_domain(agents, report, rng, arguments.rounds)
        with tempfile.TemporaryDirectory() as folder:
            sqlite_url = f"sqlite:{Path(folder) / 'interop.db'}"
            shared_store(agents, report, sqlite_url)
            shared_ledger(agents, report, sqlite_url)
        url = os.environ.get("OMNIWEBHOOK_PG_URL")
        if url:
            shared_store(agents, report, url)
            shared_ledger(agents, report, url)
            shared_outbox(agents, report, url)
        else:
            print("Sin OMNIWEBHOOK_PG_URL: no se prueban las tablas compartidas en PostgreSQL.")
    finally:
        for agent in agents:
            agent.close()

    for failure in report.failures[: arguments.show]:
        print(f"✗ {failure}\n")
    print(f"{report.checked} comprobaciones, {len(report.failures)} diferencias (semilla {arguments.seed}).")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
