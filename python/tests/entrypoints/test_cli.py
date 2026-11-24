import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from omniwebhook.cli import CliIo, run_cli
from tests.support.servidor import servidor

SECRETO = "secreto-sintetico"
ESTANDAR = "whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="
CUERPO = '{"id":"evt_1","ñ":true}'
FIRMAR = ["--scheme", "stripe", "--secret-env", "FIRMA", "--body", "cuerpo.json"]
VERIFICAR = ["verify", "--scheme", "stripe", "--secret-env", "FIRMA", "--request"]


@dataclass
class Consola:
    """El entorno de la línea de comandos, con todo en memoria."""

    archivos: dict[str, str] = field(default_factory=dict)
    estado: int | Exception = 204
    salida: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    enviados: list[tuple[str, list[tuple[str, str]], bytes]] = field(default_factory=list)

    def _leer(self, ruta: str) -> bytes:
        contenido = {"cuerpo.json": CUERPO, **self.archivos}.get(ruta)
        if contenido is None:
            raise FileNotFoundError(f"no existe {ruta}")
        return contenido.encode("utf-8")

    def _enviar(self, url: str, cabeceras: Sequence[tuple[str, str]], cuerpo: bytes) -> int:
        self.enviados.append((url, list(cabeceras), cuerpo))
        if isinstance(self.estado, Exception):
            raise self.estado
        return self.estado

    def correr(self, *argumentos: str) -> int:
        entorno = CliIo(
            env={"FIRMA": SECRETO, "ESTANDAR": ESTANDAR, "VACIA": ""},
            read=self._leer,
            out=self.salida.append,
            err=self.errores.append,
            post=self._enviar,
        )
        return run_cli(list(argumentos), entorno)


def test_sin_comando_muestra_la_ayuda_y_termina_con_2() -> None:
    consola = Consola()

    assert consola.correr() == 2
    assert consola.correr("--help") == 0
    assert "omniwebhook" in consola.salida[0]


def test_lo_que_firma_sign_lo_acepta_verify() -> None:
    firma = Consola()
    assert firma.correr("sign", *FIRMAR) == 0
    pedido = "\n".join(firma.salida)
    assert json.loads(pedido)["body"] == CUERPO

    verificacion = Consola(archivos={"-": pedido})

    assert verificacion.correr(*VERIFICAR, "-") == 0
    resultado = json.loads(verificacion.salida[0])
    assert (resultado["outcome"], resultado["eventKey"]) == ("ok", "stripe:evt_1")


def test_verify_termina_con_1_si_el_pedido_no_verifica() -> None:
    firma = Consola()
    firma.correr("sign", *FIRMAR, "--timestamp", "1")
    verificacion = Consola(archivos={"pedido.json": "\n".join(firma.salida)})

    assert verificacion.correr(*VERIFICAR, "pedido.json") == 1
    assert verificacion.salida == ['{"outcome":"stale"}']


@pytest.mark.parametrize(
    ("esquema", "variable", "al_firmar", "siempre"),
    [
        ("standard", "ESTANDAR", [], []),
        ("slack", "FIRMA", [], []),
        ("tiktok", "FIRMA", [], []),
        ("mercadopago", "FIRMA", ["--id", "req-1", "--data-id", "abc"], []),
        ("github", "FIRMA", ["--id", "entrega-1"], []),
        ("creem", "FIRMA", [], []),
        ("shopify", "FIRMA", [], []),
        ("hmac-body", "FIRMA", [], ["--header", "x-firma", "--prefix", "v1=", "--encoding", "base64"]),
    ],
)
def test_cada_esquema_firma_y_verifica(
    esquema: str, variable: str, al_firmar: list[str], siempre: list[str]
) -> None:
    comunes = ["--scheme", esquema, "--secret-env", variable, *siempre]
    firma = Consola()
    assert firma.correr("sign", *comunes, *al_firmar, "--body", "cuerpo.json") == 0

    verificacion = Consola(archivos={"-": "\n".join(firma.salida)})

    assert verificacion.correr("verify", *comunes, "--tolerance", "600", "--request", "-") == 0


def test_send_manda_el_pedido_firmado_y_termina_segun_el_estado() -> None:
    consola = Consola(estado=200)
    argumentos = ["send", *FIRMAR, "--url", "http://localhost:3000/webhooks?a=1"]

    assert consola.correr(*argumentos) == 0
    assert consola.salida == ["200"]
    url, cabeceras, cuerpo = consola.enviados[0]
    assert url == "http://localhost:3000/webhooks?a=1"
    assert dict(cabeceras)["stripe-signature"].startswith("t=")
    assert cuerpo == CUERPO.encode()

    rechazado = Consola(estado=401)
    assert rechazado.correr(*argumentos) == 1
    assert rechazado.salida == ["401"]


def test_send_agrega_a_la_url_los_parametros_que_firma_el_emisor() -> None:
    consola = Consola()

    consola.correr(
        "send",
        "--scheme",
        "mercadopago",
        "--secret-env",
        "FIRMA",
        "--body",
        "cuerpo.json",
        "--data-id",
        "abc",
        "--url",
        "http://localhost:3000/webhooks",
    )

    assert consola.enviados[0][0] == "http://localhost:3000/webhooks?data.id=abc"


def test_un_fallo_de_red_en_send_termina_con_1_y_lo_dice() -> None:
    consola = Consola(estado=ConnectionRefusedError("conexión rechazada"))

    assert consola.correr("send", *FIRMAR, "--url", "http://localhost:9/") == 1
    assert consola.errores == ["omniwebhook: conexión rechazada"]


@pytest.mark.parametrize(
    ("argumentos", "mensaje"),
    [
        (["otro"], "otro"),
        (["sign", *FIRMAR, "--otra", "x"], "otra"),
        (["sign", "--secret-env", "FIRMA", "--body", "cuerpo.json"], "--scheme"),
        (["sign", "--scheme", "stripe", "--secret-env", "FIRMA"], "--body"),
        (["sign", "--scheme", "stripe", "--secret-env", "VACIA", "--body", "cuerpo.json"], "VACIA"),
        (["sign", "--scheme", "stripe", "--secret-env", "NO", "--body", "-"], "NO está"),
        (["sign", *FIRMAR, "--timestamp", "ayer"], "--timestamp"),
        (["sign", *FIRMAR, "--encoding", "rot13"], "--encoding"),
        (
            ["sign", "--scheme", "otro", "--secret-env", "FIRMA", "--body", "cuerpo.json"],
            "esquema desconocido",
        ),
        (["sign", "--scheme", "hmac-body", "--secret-env", "FIRMA", "--body", "cuerpo.json"], "header"),
        (["send", *FIRMAR, "--url", "no es una url"], "--url"),
        (["verify", "--scheme", "otro", "--secret-env", "FIRMA", "--request", "cuerpo.json"], "esquema"),
        (
            ["verify", "--scheme", "hmac-body", "--secret-env", "FIRMA", "--request", "cuerpo.json"],
            "--header",
        ),
        ([*VERIFICAR, "cuerpo.json", "--tolerance", "0"], "tolerance_seconds"),
    ],
)
def test_un_uso_incorrecto_termina_con_2_sin_mostrar_el_secreto(argumentos: list[str], mensaje: str) -> None:
    consola = Consola()

    assert consola.correr(*argumentos) == 2
    assert mensaje in "\n".join(consola.errores)
    assert SECRETO not in "\n".join(consola.errores)


@pytest.mark.parametrize(
    ("guardado", "mensaje"),
    [
        ("no es json", "no es JSON"),
        ('{"headers":[],"body":7}', "body"),
        ('{"headers":[["a"]],"body":""}', "headers"),
        ('{"headers":"x","body":""}', "headers"),
        ("7", "body"),
    ],
)
def test_verify_rechaza_un_pedido_guardado_que_no_tiene_la_forma(guardado: str, mensaje: str) -> None:
    consola = Consola(archivos={"pedido.json": guardado})

    assert consola.correr(*VERIFICAR, "pedido.json") == 2
    assert mensaje in "\n".join(consola.errores)


def test_un_archivo_que_no_se_puede_leer_termina_con_1() -> None:
    consola = Consola()

    assert consola.correr("sign", *FIRMAR[:5], "no-existe.json") == 1
    assert consola.errores == ["omniwebhook: no existe no-existe.json"]


def test_como_modulo_lee_la_entrada_estandar_y_el_entorno() -> None:
    corrida = subprocess.run(
        [
            sys.executable,
            "-m",
            "omniwebhook",
            "sign",
            "--scheme",
            "creem",
            "--secret-env",
            "FIRMA",
            "--body",
            "-",
        ],
        input=CUERPO.encode(),
        env={"FIRMA": SECRETO},
        capture_output=True,
        check=True,
    )

    assert json.loads(corrida.stdout)["headers"][0][0] == "creem-signature"


def test_send_de_punta_a_punta_contra_un_servidor_local(tmp_path: Path) -> None:
    archivo = tmp_path / "cuerpo.json"
    archivo.write_text(CUERPO, encoding="utf-8")
    salida: list[str] = []

    with servidor() as local:
        codigo = run_cli(
            [
                "send",
                "--scheme",
                "github",
                "--secret-env",
                "FIRMA",
                "--body",
                str(archivo),
                "--url",
                f"http://127.0.0.1:{local.port}/entrada",
            ],
            CliIo(env={"FIRMA": SECRETO}, out=salida.append),
        )

    assert (codigo, salida) == (0, ["200"])
    assert local.recibidos[0].body == CUERPO.encode()
    assert local.recibidos[0].headers["x-hub-signature-256"].startswith("sha256=")


def test_send_informa_el_estado_de_un_rechazo_y_no_sigue_redirecciones() -> None:
    salida: list[str] = []

    with servidor() as local:
        codigo = run_cli(
            [
                "send",
                "--scheme",
                "creem",
                "--secret-env",
                "FIRMA",
                "--body",
                "-",
                "--url",
                f"http://127.0.0.1:{local.port}/mudado",
            ],
            CliIo(env={"FIRMA": SECRETO}, out=salida.append, read=lambda _ruta: b"{}"),
        )

    assert codigo == 1
    assert salida == ["302"]
    assert len(local.recibidos) == 1


def test_keygen_da_un_par_con_el_que_se_firma_y_se_verifica() -> None:
    generacion = Consola()
    assert generacion.correr("keygen") == 0
    par = json.loads("\n".join(generacion.salida))
    comunes = ["--scheme", "standard-v2a", "--endpoint-id", "ep_1"]

    def consola(archivos: dict[str, str] | None = None) -> tuple[Consola, CliIo]:
        nueva = Consola(archivos=archivos or {})
        entorno = CliIo(
            env={"PRIVADA": par["secretKey"], "PUBLICA": par["publicKey"]},
            read=nueva._leer,
            out=nueva.salida.append,
            err=nueva.errores.append,
        )
        return nueva, entorno

    firma, entorno = consola()
    assert run_cli(["sign", *comunes, "--secret-env", "PRIVADA", "--body", "cuerpo.json"], entorno) == 0
    pedido = "\n".join(firma.salida)

    _, entorno = consola({"-": pedido})
    assert run_cli(["verify", *comunes, "--secret-env", "PUBLICA", "--request", "-"], entorno) == 0
    _, entorno = consola({"-": pedido})
    otro = ["verify", "--scheme", "standard-v2a", "--endpoint-id", "ep_2", "--secret-env", "PUBLICA"]
    assert run_cli([*otro, "--request", "-"], entorno) == 1
    errores, entorno = consola({"-": pedido})
    sin_destino = ["verify", "--scheme", "standard-v2a", "--secret-env", "PUBLICA", "--request", "-"]
    assert run_cli(sin_destino, entorno) == 2
    assert "endpoint-id" in "\n".join(errores.errores)


def test_discord_firma_con_la_semilla_y_verifica_con_la_clave_publica() -> None:
    claves = {
        "PRIVADA": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "PUBLICA": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
    }
    firma = Consola()
    entorno = CliIo(env=claves, read=firma._leer, out=firma.salida.append, err=firma.errores.append)
    assert (
        run_cli(["sign", "--scheme", "discord", "--secret-env", "PRIVADA", "--body", "cuerpo.json"], entorno)
        == 0
    )

    verificacion = Consola(archivos={"-": "\n".join(firma.salida)})
    entorno = CliIo(env=claves, read=verificacion._leer, out=verificacion.salida.append)
    argumentos = ["verify", "--scheme", "discord", "--secret-env", "PUBLICA", "--tolerance", "600"]

    assert run_cli([*argumentos, "--request", "-"], entorno) == 0
    assert json.loads(verificacion.salida[0])["eventKey"] == "discord:evt_1"
