#!/usr/bin/env python3
"""Levanta cada ejemplo de `examples/` y comprueba que recibe como dice.

A cada uno le manda, con la línea de comandos del paquete, un evento firmado, el mismo evento
otra vez y uno firmado con otro secreto. Tiene que responder 200, 200 y 401, y procesar el
evento una sola vez.

Uso: `python3 tools/check_examples.py`. Necesita `pnpm install`, `pnpm build` y `uv sync`.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ["uv", "run", "--project", str(ROOT / "python"), "python"]
EXAMPLES: dict[str, list[str]] = {
    "node-http": ["node", "server.mjs"],
    "python-wsgi": [*PYTHON, "app.py"],
    "python-starlette": [*PYTHON, "app.py"],
    "python-django": [*PYTHON, "app.py"],
}
# Sintéticos: no son secretos de nadie.
SECRET = "secreto-sintetico-de-los-ejemplos"
OTHER = "otro-secreto-sintetico"
EVENT = '{"id":"evt_ejemplo_1","type":"invoice.paid"}'


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"terminó antes de escuchar:\n{process.stdout.read() if process.stdout else ''}"
            )
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError("no empezó a escuchar a tiempo")


def send(port: int, body: Path, variable: str, env: dict[str, str]) -> str:
    """Manda el evento firmado con el secreto de `variable` y devuelve el estado de la respuesta."""
    command = [*PYTHON, "-m", "omniwebhook", "send", "--scheme", "stripe", "--secret-env", variable]
    command += ["--body", str(body), "--url", f"http://127.0.0.1:{port}/webhooks"]
    done = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    return done.stdout.strip() or done.stderr.strip()


def check(name: str, command: list[str], body: Path) -> list[str]:
    port = free_port()
    env = {**os.environ, "WEBHOOK_SECRET": SECRET, "OTRO_SECRETO": OTHER, "PORT": str(port)}
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=ROOT / "examples" / name,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for(port, process)
        statuses = [
            send(port, body, "WEBHOOK_SECRET", env),
            send(port, body, "WEBHOOK_SECRET", env),
            send(port, body, "OTRO_SECRETO", env),
        ]
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()

    problems = []
    if statuses != ["200", "200", "401"]:
        problems.append(f"respondió {statuses}, se esperaba ['200', '200', '401']")
    processed = [line for line in output.splitlines() if line.startswith("procesado ")]
    if processed != ["procesado stripe:evt_ejemplo_1 invoice.paid"]:
        problems.append(f"procesó {processed}, se esperaba una sola vez el evento\n{output}")
    return problems


def check_outbox(body: Path) -> list[str]:
    """Encola en una transacción y despacha contra el receptor de Starlette, con el formato estándar."""
    url = os.environ["OMNIWEBHOOK_PG_URL"]
    port = free_port()
    secret = "whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="  # sintético
    env = {**os.environ, "PORT": str(port)}
    receiver = subprocess.Popen(  # noqa: S603
        [*PYTHON, "-c", RECEIVER, secret],
        cwd=ROOT / "examples" / "python-outbox",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    order = f"pedido-{time.time_ns()}"
    emitter_env = {
        **os.environ,
        "OMNIWEBHOOK_PG_URL": url,
        "WEBHOOK_SIGNING_SECRET": secret,
        "ENDPOINT_URL": f"http://127.0.0.1:{port}/webhooks",
        "ALLOW_LOCAL": "1",
    }
    try:
        wait_for(port, receiver)
        emitted = subprocess.run(  # noqa: S603
            [*PYTHON, "app.py", order],
            cwd=ROOT / "examples" / "python-outbox",
            env=emitter_env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        receiver.terminate()
        try:
            received, _ = receiver.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            receiver.kill()
            received, _ = receiver.communicate()

    problems = []
    if "despachado ep_cliente_1 intento 1: delivered" not in emitted.stdout:
        problems.append(f"no despachó la entrega:\n{emitted.stdout}{emitted.stderr}")
    if received.count(f"recibido {order}") != 1:
        problems.append(f"el receptor no procesó el pedido una vez:\n{received}")
    return problems


# Un receptor mínimo del formato estándar, para el ejemplo de la bandeja.
RECEIVER = """
import json, os, sys
from wsgiref.simple_server import WSGIRequestHandler, make_server
from omniwebhook import MemoryIdempotencyStore, create_receiver, incoming_request_from_environ, wsgi_response
from omniwebhook.standard import native_signer, standard_scheme

receive = create_receiver(
    verifier=standard_scheme(secrets=[sys.argv[1]], signer=native_signer), store=MemoryIdempotencyStore()
)

def app(environ, start_response):
    def process(event):
        print("recibido", json.loads(event.request.body)["pedido"], flush=True)
    return wsgi_response(receive.execute(incoming_request_from_environ(environ), process), start_response)

class Silent(WSGIRequestHandler):
    def log_message(self, *args):
        pass

make_server("127.0.0.1", int(os.environ["PORT"]), app, handler_class=Silent).serve_forever()
"""


def report(name: str, problems: list[str]) -> bool:
    print(f"{'✗' if problems else '✓'} {name}")
    for problem in problems:
        print(f"  {problem}")
    return bool(problems)


def main() -> int:
    for tool in ("node", "uv"):
        if shutil.which(tool) is None:
            print(f"Falta {tool}.", file=sys.stderr)
            return 2

    failed = False
    with tempfile.TemporaryDirectory() as folder:
        body = Path(folder) / "evento.json"
        body.write_text(EVENT, encoding="utf-8")
        for name, command in EXAMPLES.items():
            try:
                problems = check(name, command, body)
            except RuntimeError as error:
                problems = [str(error)]
            failed = report(name, problems) or failed

        if "OMNIWEBHOOK_PG_URL" in os.environ:
            try:
                problems = check_outbox(body)
            except RuntimeError as error:
                problems = [str(error)]
            failed = report("python-outbox", problems) or failed
        else:
            print("- python-outbox: omitido, necesita OMNIWEBHOOK_PG_URL")

    print("Hay ejemplos que no funcionan." if failed else "Los ejemplos reciben como dice la documentación.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
