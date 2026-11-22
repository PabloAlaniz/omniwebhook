"""El dominio sólo puede importarse a sí mismo y a una lista corta de módulos puros.

`import-linter` cuida la dirección entre capas; esto cuida que el dominio no haga
entrada/salida ni dependa de paquetes externos.
"""

import ast
from pathlib import Path

import pytest

DOMINIO = Path(__file__).resolve().parents[2] / "src" / "omniwebhook" / "domain"

PERMITIDOS = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "datetime",
        "enum",
        "ipaddress",
        "math",
        "re",
        "typing",
    }
)
# De `urllib` sólo la parte que analiza texto: el resto hace entrada/salida.
MODULOS_PERMITIDOS = frozenset({"urllib.parse"})


def modulos_importados(archivo: Path) -> set[str]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    encontrados: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            encontrados.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            encontrados.add("." * nodo.level + (nodo.module or ""))
    return encontrados


def es_valido(modulo: str) -> bool:
    if modulo.startswith(".") or modulo == "omniwebhook.domain" or modulo.startswith("omniwebhook.domain."):
        return True
    return modulo in MODULOS_PERMITIDOS or modulo.split(".")[0] in PERMITIDOS


@pytest.mark.parametrize("archivo", sorted(DOMINIO.rglob("*.py")), ids=lambda p: p.name)
def test_el_dominio_no_importa_nada_de_afuera(archivo: Path) -> None:
    prohibidos = sorted(m for m in modulos_importados(archivo) if not es_valido(m))

    assert prohibidos == []
