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
            print(f"{'✗' if problems else '✓'} {name}")
            for problem in problems:
                failed = True
                print(f"  {problem}")

    print("Hay ejemplos que no funcionan." if failed else "Los ejemplos reciben como dice la documentación.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
