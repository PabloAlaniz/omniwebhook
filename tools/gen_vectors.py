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

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

SPEC = "0"
ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "spec" / "vectors"

Vector = dict[str, Any]

# Cada función arma un archivo de vectores: {"spec", "id", "kind", "cases"}.
# El `id` es además la ruta del archivo dentro de spec/vectors/.
ALL: list[Callable[[], Vector]] = []


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
