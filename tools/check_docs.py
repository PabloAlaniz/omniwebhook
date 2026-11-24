#!/usr/bin/env python3
"""Comprueba que los ejemplos de la documentación usan la API que existe.

Saca los bloques de código de los archivos Markdown y los revisa con el comprobador de
tipos de cada lenguaje. Los nombres que un ejemplo da por existentes (`pool`, `app`,
`registrarPago`) se declaran acá, en el preámbulo, como valores sin tipo.

Uso: `python3 tools/check_docs.py`. Necesita las dependencias de los dos paquetes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS = [
    "README.md",
    "README.en.md",
    "README.zh-CN.md",
    "README.pt-BR.md",
    "ts/README.md",
    "python/README.md",
    "docs/recibir.md",
    "docs/emitir.md",
    "docs/telemetria.md",
]
BLOCK = re.compile(r"^```(ts|python)\n(.*?)^```$", re.DOTALL | re.MULTILINE)

TS_PREAMBLE = """\
declare const pool: any, store: any, ledger: any, signer: any, db: any, cola: any, logger: any;
declare const secreto: string, nuevo: string, anterior: string, secretoCompartido: string, url: string;
declare const secrets: string[], payload: Uint8Array, entrega: any, pedido: any, procesar: any;
declare const receive: any, env: any, request: any, send: any, meter: any, tracer: any;
declare const esquemaDePedido: import("omniwebhook").PayloadSchema<{ id: string }>;
declare function registrarPago(evento: unknown): Promise<void>;
declare function recordPayment(event: unknown): Promise<void>;
declare function tipoDe(request: unknown): string;
"""
PY_PREAMBLE = """\
import dataclasses, json, os
from typing import Any
from omniwebhook import *
from omniwebhook.standard import *
app: Any; pool: Any; store: Any; ledger: Any; signer: Any; db: Any; cola: Any; firestore: Any; request: Any
secreto: str; nuevo: str; anterior: str; url: str; identificador: str; secrets: list[str]; payload: bytes
entrega: Any; Request = Any; Response = Any; registrar_pago: Any; tipo_de: Any; record_payment: Any
receive: Any; procesar: Any; Pedido: Any; destinos: Any; send: Any; ahora: int; meter: Any; tracer: Any
"""


def blocks(language: str) -> list[tuple[str, int, str]]:
    found = []
    for document in DOCUMENTS:
        text = (ROOT / document).read_text(encoding="utf-8")
        for number, match in enumerate(BLOCK.finditer(text), start=1):
            if match.group(1) == language:
                found.append((document, number, match.group(2)))
    return found


def hoist_imports(code: str) -> tuple[str, str]:
    """Separa las importaciones, que tienen que ir al principio del archivo."""
    imports = re.findall(r"^import [^;]*?;$", code, re.DOTALL | re.MULTILINE)
    for statement in imports:
        code = code.replace(statement, "")
    return "\n".join(imports), code


ENTRIES = {
    "omniwebhook": "index.ts",
    "omniwebhook/standard": "standard.ts",
    "omniwebhook/node": "node.ts",
    "omniwebhook/testing": "testing.ts",
    "omniwebhook/otel": "otel.ts",
}


def missing_imports(imports: str, body: str) -> str:
    """Las importaciones que un fragmento sin encabezado da por hechas."""
    lines = []
    for entry, file in ENTRIES.items():
        source = (ROOT / "ts" / "src" / file).read_text(encoding="utf-8")
        exported = set(re.findall(r"\b([a-z][A-Za-z]+)\b(?=[,\s]*(?:,|\}| as))", source))
        exported |= set(re.findall(r"export function ([a-z][A-Za-z]+)", source))
        used = sorted(
            name
            for name in exported
            if re.search(rf"(?<![.\w]){name}\(", body) and not re.search(rf"\b{name}\b", imports)
        )
        if used:
            lines.append(f"import {{ {', '.join(used)} }} from '{entry}';")
    return "\n".join(lines)


def check_typescript() -> bool:
    folder = ROOT / "ts" / ".docscheck"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    for index, (document, number, code) in enumerate(blocks("ts")):
        imports, body = hoist_imports(code)
        # Cada bloque va en su propia función para que sus nombres no choquen con los de otro.
        body = re.sub(r"^export ", "", body, flags=re.MULTILINE)
        source = (
            f"// {document}, bloque {number}\n{imports}\n{missing_imports(imports, body)}\n{TS_PREAMBLE}\n"
            f"async function ejemplo() {{\n{body}\n}}\nvoid ejemplo;\nexport {{}};\n"
        )
        (folder / f"bloque_{index}.ts").write_text(source, encoding="utf-8")
    (folder / "tsconfig.json").write_text(
        '{"extends": "../tsconfig.json", "compilerOptions": {"noEmit": true, "noUnusedLocals": false, '
        '"rootDir": "..", "paths": {"omniwebhook": ["../src/index.ts"], '
        '"omniwebhook/standard": ["../src/standard.ts"], "omniwebhook/node": ["../src/node.ts"], '
        '"omniwebhook/testing": ["../src/testing.ts"], "omniwebhook/otel": ["../src/otel.ts"]}}, '
        '"include": ["*.ts"]}',
        encoding="utf-8",
    )
    command = ["pnpm", "exec", "tsc", "-p", ".docscheck"]
    result = subprocess.run(command, cwd=ROOT / "ts", check=False)  # noqa: S603
    shutil.rmtree(folder, ignore_errors=True)
    return result.returncode == 0


def check_python() -> bool:
    folder = ROOT / "python" / ".docscheck"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    for index, (document, number, code) in enumerate(blocks("python")):
        source = f"# {document}, bloque {number}\n{PY_PREAMBLE}\n{code}"
        (folder / f"bloque_{index}.py").write_text(source, encoding="utf-8")
    command = ["uv", "run", "mypy", "--no-incremental", "--disable-error-code=no-redef", ".docscheck"]
    command += ["--disable-error-code=assignment", "--allow-untyped-defs", "--allow-untyped-decorators"]
    result = subprocess.run(command, cwd=ROOT / "python", check=False)  # noqa: S603
    shutil.rmtree(folder, ignore_errors=True)
    return result.returncode == 0


def main() -> int:
    ok = check_typescript()
    ok = check_python() and ok
    print(
        "Los ejemplos de la documentación coinciden con la API." if ok else "Hay ejemplos que no coinciden."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
