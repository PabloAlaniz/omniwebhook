"""Línea de comandos para depurar una integración sin escribir código.

Firma un cuerpo, verifica un pedido guardado y manda un pedido firmado a una URL.

El secreto nunca va en la línea de comandos, donde quedaría en el historial: se lee de la
variable de entorno que se indique.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from omniwebhook.adapters.schemes.creem import creem_scheme
from omniwebhook.adapters.schemes.github import github_scheme
from omniwebhook.adapters.schemes.hmac_body import hmac_body_scheme
from omniwebhook.adapters.schemes.mercadopago import mercadopago_scheme
from omniwebhook.adapters.schemes.shopify import shopify_scheme
from omniwebhook.adapters.schemes.slack import slack_scheme
from omniwebhook.adapters.schemes.standard import standard_scheme
from omniwebhook.adapters.schemes.standard.native_signer import native_signer
from omniwebhook.adapters.schemes.stripe import stripe_scheme
from omniwebhook.adapters.schemes.tiktok import tiktok_scheme
from omniwebhook.application.ports import Verifier
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.incoming_request import Field, IncomingRequest
from omniwebhook.domain.verification import Verified
from omniwebhook.testing import signed_request

SCHEMES = (
    "standard",
    "standard-v2a",
    "discord",
    "stripe",
    "slack",
    "shopify",
    "tiktok",
    "mercadopago",
    "github",
    "creem",
    "hmac-body",
)

EPILOG = "Es una herramienta de desarrollo: send no aplica la política de URLs de destino."


def _post(url: str, headers: Sequence[Field], body: bytes) -> int:
    request = urllib.request.Request(url, data=body, method="POST")  # noqa: S310
    request.add_header("content-type", "application/json")
    for name, value in headers:
        request.add_header(name, value)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        # El error lleva abierta la respuesta: se cierra acá, no cuando la recoja el recolector.
        with error:
            return error.code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _read(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    with open(path, "rb") as file:
        return file.read()


@dataclass(frozen=True, slots=True)
class CliIo:
    """Lo que la línea de comandos necesita del entorno. Los tests lo reemplazan."""

    env: Mapping[str, str] = field(default_factory=lambda: os.environ)
    read: Callable[[str], bytes] = _read
    """Lee un archivo; `-` es la entrada estándar."""
    out: Callable[[str], None] = print
    err: Callable[[str], None] = lambda line: print(line, file=sys.stderr)
    post: Callable[[str, Sequence[Field], bytes], int] = _post


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _parser() -> _Parser:
    parser = _Parser(prog="omniwebhook", description=__doc__, epilog=EPILOG, exit_on_error=False)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    helps = {
        "sign": "Firma un cuerpo y muestra el pedido que mandaría el emisor, en JSON.",
        "verify": "Verifica un pedido guardado. Termina con 0 si el resultado es ok, y con 1 si no.",
        "send": "Firma un cuerpo y lo manda por POST a una URL. Termina con 0 si responde 2xx.",
    }
    keygen = "Genera un par de claves para la firma asimétrica y lo muestra en JSON."
    commands.add_parser("keygen", help=keygen, description=keygen, exit_on_error=False)
    for name, text in helps.items():
        command = commands.add_parser(name, help=text, description=text, epilog=EPILOG, exit_on_error=False)
        command.add_argument("--scheme", required=True, help=", ".join(SCHEMES))
        command.add_argument(
            "--secret-env",
            required=True,
            metavar="VAR",
            help=(
                "la variable de entorno que tiene el secreto; en standard-v2a y discord, la clave "
                "privada para sign y send, y la pública para verify"
            ),
        )
        command.add_argument("--endpoint-id", help="standard-v2a: el identificador del destino")
        command.add_argument("--header", help="hmac-body: la cabecera que trae la firma")
        command.add_argument("--prefix", help="hmac-body: un texto fijo antes de la firma")
        command.add_argument("--encoding", help="hmac-body: hex o base64")
        command.add_argument("--id-header", help="hmac-body: la cabecera que identifica el evento")
        if name == "verify":
            command.add_argument(
                "--request",
                required=True,
                help="el pedido en JSON, como lo muestra sign; - para la entrada estándar",
            )
            command.add_argument(
                "--tolerance", help="cuánto puede alejarse de ahora la marca de tiempo, en segundos"
            )
        else:
            command.add_argument("--body", required=True, help="el cuerpo crudo; - para la entrada estándar")
            command.add_argument(
                "--timestamp", help="la marca de tiempo a firmar, en segundos; por defecto, ahora"
            )
            command.add_argument("--id", help="el identificador que el emisor manda fuera del cuerpo")
            command.add_argument("--data-id", help="mercadopago: el parámetro data.id")
        if name == "send":
            command.add_argument("--url", required=True, help="a dónde mandar el pedido")
    return parser


def _secret(options: argparse.Namespace, io: CliIo) -> str:
    secret = io.env.get(options.secret_env, "")
    if secret == "":
        raise UsageError(f"la variable de entorno {options.secret_env} está vacía o no existe")
    return secret


def _integer(value: str | None, name: str) -> int | None:
    if value is None:
        return None
    if not (value.isascii() and value.isdigit() and len(value) <= 11):
        raise UsageError(f"--{name} tiene que ser un entero")
    return int(value)


def _encoding(options: argparse.Namespace) -> dict[str, Any]:
    if options.encoding is None:
        return {}
    if options.encoding not in ("hex", "base64"):
        raise UsageError("--encoding tiene que ser hex o base64")
    return {"encoding": options.encoding}


def _hmac_body(options: argparse.Namespace) -> dict[str, Any]:
    given = {"header": options.header, "prefix": options.prefix, "id_header": options.id_header}
    return {**{name: value for name, value in given.items() if value is not None}, **_encoding(options)}


def _signed(options: argparse.Namespace, io: CliIo) -> IncomingRequest:
    if options.scheme not in SCHEMES:
        raise UsageError(f"esquema desconocido: {options.scheme}")
    return signed_request(
        options.scheme,
        secret=_secret(options, io),
        body=io.read(options.body),
        timestamp=_integer(options.timestamp, "timestamp"),
        id=options.id,
        data_id=options.data_id,
        endpoint_id=options.endpoint_id,
        **_hmac_body(options),
    )


def _verifier(options: argparse.Namespace, io: CliIo) -> Verifier:
    secrets = [_secret(options, io)]
    tolerance = _integer(options.tolerance, "tolerance")
    timed: dict[str, Any] = {"secrets": secrets}
    if tolerance is not None:
        timed["tolerance_seconds"] = tolerance
    match options.scheme:
        case "standard":
            return standard_scheme(signer=native_signer, **timed)
        case "standard-v2a" | "discord":
            return _public_key_verifier(options, secrets, tolerance)
        case "stripe":
            return stripe_scheme(**timed)
        case "slack":
            return slack_scheme(**timed)
        case "tiktok":
            return tiktok_scheme(**timed)
        case "mercadopago":
            return mercadopago_scheme(**timed)
        case "github":
            return github_scheme(secrets=secrets)
        case "creem":
            return creem_scheme(secrets=secrets)
        case "shopify":
            return shopify_scheme(secrets=secrets)
        case "hmac-body":
            if options.header is None:
                raise UsageError("falta --header")
            return hmac_body_scheme(secrets=secrets, **_hmac_body(options))
        case _:
            raise UsageError(f"esquema desconocido: {options.scheme}")


def _ed25519(build: Callable[[], Any]) -> Any:
    """Corre algo que necesita `omniwebhook[ed25519]` y explica qué falta si no está."""
    try:
        return build()
    except ImportError as error:
        raise UsageError("falta la librería de Ed25519: instalá omniwebhook[ed25519]") from error


def _public_key_verifier(options: argparse.Namespace, keys: list[str], tolerance: int | None) -> Verifier:
    timed: dict[str, Any] = {"public_keys": keys}
    if tolerance is not None:
        timed["tolerance_seconds"] = tolerance

    def build() -> Verifier:
        if options.scheme == "discord":
            from omniwebhook.adapters.schemes.discord import discord_scheme

            return discord_scheme(**timed)
        from omniwebhook.adapters.schemes.standard.public_key import standard_public_key_scheme

        if options.endpoint_id is None:
            raise UsageError("falta --endpoint-id")
        return standard_public_key_scheme(endpoint_id=options.endpoint_id, **timed)

    verifier: Verifier = _ed25519(build)
    return verifier


def _keygen() -> str:
    def build() -> str:
        from omniwebhook.adapters.schemes.standard.key_signer import generate_standard_key_pair

        pair = generate_standard_key_pair()
        return json.dumps({"secretKey": pair.secret_key, "publicKey": pair.public_key}, indent=2)

    shown: str = _ed25519(build)
    return shown


def _pairs(value: object, name: str) -> list[Field]:
    if isinstance(value, list):
        found = [
            (pair[0], pair[1])
            for pair in value
            if isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair)
        ]
        if len(found) == len(value):
            return found
    raise UsageError(f"{name} tiene que ser una lista de pares de texto")


def _saved_request(text: bytes) -> IncomingRequest:
    try:
        data = json.loads(text.decode("utf-8"))
    except ValueError as error:
        raise UsageError("el pedido no es JSON") from error
    saved = data if isinstance(data, dict) else {}
    if not isinstance(saved.get("body"), str):
        raise UsageError("body tiene que ser un texto")
    return IncomingRequest(
        headers=_pairs(saved.get("headers"), "headers"),
        query=_pairs(saved.get("query", []), "query"),
        body=saved["body"].encode("utf-8"),
    )


def _shown(request: IncomingRequest) -> str:
    return json.dumps(
        {
            "headers": [list(pair) for pair in request.headers],
            "query": [list(pair) for pair in request.query],
            "body": request.body.decode("utf-8"),
        },
        indent=2,
        ensure_ascii=False,
    )


def _with_query(url: str, query: Sequence[Field]) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UsageError("--url tiene que ser una URL http o https")
    merged = [*parse_qsl(parts.query, keep_blank_values=True), *query]
    return urlunsplit(parts._replace(query=urlencode(merged)))


def run_cli(argv: Sequence[str], io: CliIo | None = None) -> int:
    """Corre un comando y devuelve el código de salida."""
    io = io or CliIo()
    parser = _parser()
    if not argv or argv[0] in ("help", "--help", "-h"):
        io.out(parser.format_help())
        return 0 if argv else 2

    try:
        try:
            options = parser.parse_args(list(argv))
        except argparse.ArgumentError as error:
            raise UsageError(str(error)) from error

        if options.command == "keygen":
            # La clave privada sale por la salida estándar porque se la pidió: guardala en un
            # gestor de secretos y compartí sólo la pública.
            io.out(_keygen())
            return 0
        if options.command == "sign":
            io.out(_shown(_signed(options, io)))
            return 0
        if options.command == "verify":
            result = _verifier(options, io).verify(_saved_request(io.read(options.request)))
            shown: dict[str, Any] = {"outcome": result.outcome}
            if isinstance(result, Verified):
                shown |= {"eventKey": result.event_key, "timestamp": result.timestamp}
            io.out(json.dumps(shown, separators=(",", ":"), ensure_ascii=False))
            return 0 if result.outcome == "ok" else 1
        request = _signed(options, io)
        status = io.post(_with_query(options.url, request.query), request.headers, request.body)
        io.out(str(status))
        return 0 if 200 <= status <= 299 else 1
    except (UsageError, ConfigurationError) as error:
        # El mensaje nunca incluye el secreto: sólo el nombre de la variable que lo tiene.
        io.err(f"omniwebhook: {error}")
        return 2
    except (OSError, UnicodeDecodeError) as error:
        io.err(f"omniwebhook: {error}")
        return 1


def main() -> None:
    """La entrada del ejecutable."""
    sys.exit(run_cli(sys.argv[1:]))
