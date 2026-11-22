from pathlib import Path

from omniwebhook import SPEC_VERSION

RAIZ = Path(__file__).resolve().parents[3]


def test_coincide_con_spec_version() -> None:
    declarada = (RAIZ / "spec" / "VERSION").read_text(encoding="utf-8")

    assert declarada.strip() == SPEC_VERSION
