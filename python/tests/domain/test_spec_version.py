import tomllib
from pathlib import Path

from omniwebhook import PACKAGE_VERSION, SPEC_VERSION, USER_AGENT

RAIZ = Path(__file__).resolve().parents[3]


def test_coincide_con_spec_version() -> None:
    declarada = (RAIZ / "spec" / "VERSION").read_text(encoding="utf-8")

    assert declarada.strip() == SPEC_VERSION


def test_la_version_del_paquete_coincide_con_pyproject() -> None:
    proyecto = tomllib.loads((RAIZ / "python" / "pyproject.toml").read_text(encoding="utf-8"))

    assert proyecto["project"]["version"] == PACKAGE_VERSION
    assert f"omniwebhook/{PACKAGE_VERSION} (python)" == USER_AGENT
