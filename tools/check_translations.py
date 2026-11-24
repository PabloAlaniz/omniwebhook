#!/usr/bin/env python3
"""Comprueba que cada traducción siga la estructura de su original.

No juzga el texto: comprueba lo que se puede comprobar sin leerlo. Para cada par de
documentos, que tengan los mismos títulos (cantidad y nivel, en orden), las mismas filas de
tabla, los mismos bloques de código y que los enlaces relativos de la traducción existan.

Así, un cambio en un original que no llegó a su traducción hace fallar la integración
continua en vez de quedar desactualizado en silencio.

Uso: `python3 tools/check_translations.py`. No necesita dependencias.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^```")
LINK = re.compile(r"\]\(([^)\s]+)\)")
COMMENT = re.compile(r"\s*(//|#).*$")


@dataclass(frozen=True)
class Pair:
    original: str
    translation: str
    # De dónde salen los bloques de código con los que se compara. Los README traducidos usan
    # los nombres del README en inglés, no los del original en español.
    code_from: str | None = None
    # En la especificación los bloques son normativos: ni los comentarios pueden cambiar.
    exact_code: bool = False


PAIRS = [
    Pair("README.md", "README.en.md", code_from="README.en.md"),
    Pair("README.md", "README.zh-CN.md", code_from="README.en.md"),
    Pair("README.md", "README.pt-BR.md", code_from="README.en.md"),
    Pair("spec/SPEC.md", "spec/SPEC.en.md", exact_code=True),
    Pair("docs/recibir.md", "docs/en/recibir.md"),
    Pair("docs/emitir.md", "docs/en/emitir.md"),
    Pair("docs/telemetria.md", "docs/en/telemetria.md"),
    Pair("docs/compatibilidad.md", "docs/en/compatibilidad.md"),
    Pair("docs/agregar-un-esquema.md", "docs/en/agregar-un-esquema.md"),
    Pair("docs/roadmap.md", "docs/en/roadmap.md"),
    Pair("docs/criterios-1.0.md", "docs/en/criterios-1.0.md"),
    Pair("docs/publicar.md", "docs/en/publicar.md"),
    Pair("CONTRIBUTING.md", "CONTRIBUTING.en.md"),
    Pair("SECURITY.md", "SECURITY.en.md"),
    Pair("CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT.en.md"),
    Pair("examples/README.md", "examples/README.en.md"),
    Pair("ts/README.md", "ts/README.en.md"),
    Pair("python/README.md", "python/README.en.md"),
    # Las decisiones de arquitectura: una por archivo, así una nueva no queda sin traducir.
    *(
        Pair(f"docs/adr/{file.name}", f"docs/en/adr/{file.name}")
        for file in sorted((ROOT / "docs" / "adr").glob("*.md"))
    ),
]


@dataclass(frozen=True)
class Shape:
    headings: list[int]
    table_rows: int
    blocks: list[str]
    links: list[str]


def shape(path: Path) -> Shape:
    headings: list[int] = []
    blocks: list[str] = []
    links: list[str] = []
    table_rows = 0
    inside: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            if inside is None:
                inside = [line]
            else:
                blocks.append("\n".join(inside[1:]))
                inside = None
            continue
        if inside is not None:
            inside.append(line)
            continue
        if line.startswith("#"):
            headings.append(len(line) - len(line.lstrip("#")))
        if line.startswith("|"):
            table_rows += 1
        links.extend(LINK.findall(line))
    return Shape(headings, table_rows, blocks, links)


def without_comments(block: str) -> str:
    return "\n".join(COMMENT.sub("", line).rstrip() for line in block.splitlines())


def problems_of(pair: Pair) -> list[str]:
    translation_path = ROOT / pair.translation
    if not translation_path.exists():
        return ["falta la traducción"]
    original = shape(ROOT / pair.original)
    translation = shape(translation_path)
    code = shape(ROOT / pair.code_from).blocks if pair.code_from else original.blocks
    found: list[str] = []

    if original.headings != translation.headings:
        found.append(
            f"los títulos no coinciden: {len(original.headings)} en el original, "
            f"{len(translation.headings)} en la traducción, o cambia algún nivel"
        )
    if original.table_rows != translation.table_rows:
        found.append(
            f"las tablas no coinciden: {original.table_rows} filas en el original, "
            f"{translation.table_rows} en la traducción"
        )
    if len(code) != len(translation.blocks):
        found.append(f"los bloques de código no coinciden: {len(code)} contra {len(translation.blocks)}")
    else:
        clean = (lambda block: block) if pair.exact_code else without_comments
        for number, (expected, actual) in enumerate(zip(code, translation.blocks, strict=True), start=1):
            if clean(expected) != clean(actual):
                found.append(f"el bloque de código {number} cambió respecto del original")

    for link in translation.links:
        target = link.split("#", 1)[0]
        if not target or re.match(r"[a-z]+:", target):
            continue
        if not (translation_path.parent / target).exists():
            found.append(f"el enlace a {link} no existe")
    return found


def main() -> int:
    failed = False
    for pair in PAIRS:
        problems = problems_of(pair)
        print(f"{'✗' if problems else '✓'} {pair.translation}")
        for problem in problems:
            failed = True
            print(f"  {problem}")
    print("Hay traducciones desincronizadas." if failed else "Las traducciones siguen a sus originales.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
