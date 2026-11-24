"""El paquete principal se importa sin ninguna de las dependencias opcionales."""

import subprocess
import sys

OPCIONALES = ("standardwebhooks", "httpx", "starlette", "django", "psycopg", "google", "cryptography")


def test_importar_el_paquete_no_carga_dependencias_opcionales() -> None:
    programa = (
        "import sys, omniwebhook, omniwebhook.standard, omniwebhook.postgres\n"
        f"cargadas = sorted(m for m in {OPCIONALES!r} if m in sys.modules)\n"
        "print(cargadas)"
    )

    salida = subprocess.run([sys.executable, "-c", programa], capture_output=True, text=True, check=True)  # noqa: S603

    assert salida.stdout.strip() == "[]"
