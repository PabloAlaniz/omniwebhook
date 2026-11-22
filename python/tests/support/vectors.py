"""Carga los vectores de conformidad de `spec/vectors/`."""

import json
from pathlib import Path
from typing import Any

from omniwebhook import IncomingRequest

RAIZ = Path(__file__).resolve().parents[3] / "spec" / "vectors"

Caso = dict[str, Any]


def casos(vector: str) -> list[Caso]:
    datos = json.loads((RAIZ / f"{vector}.json").read_text(encoding="utf-8"))
    encontrados: list[Caso] = datos["cases"]
    return encontrados


def nombre(caso: Caso) -> str:
    return str(caso["name"])


def a_pedido(vector: Caso) -> IncomingRequest:
    return IncomingRequest(
        headers=[(str(n), str(v)) for n, v in vector["headers"]],
        query=[(str(n), str(v)) for n, v in vector["query"]],
        body=str(vector["body"]).encode("utf-8"),
    )
