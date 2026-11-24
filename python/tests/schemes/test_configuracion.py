import base64
import json

import pytest

from omniwebhook import (
    ConfigurationError,
    IncomingRequest,
    OutgoingMessage,
    Rejected,
    Signed,
    Verified,
    creem_scheme,
    github_scheme,
    google_channel_scheme,
    google_pubsub_scheme,
    hmac_body_scheme,
    mercadopago_scheme,
    shared_token_scheme,
    stripe_scheme,
    tiktok_scheme,
)
from omniwebhook.adapters.crypto import hmac_sha256
from omniwebhook.standard import (
    native_signer,
    reference_signer,
    standard_public_key_scheme,
    standard_scheme,
    standard_signer,
)
from tests.support.dobles import RelojFijo

SECRETO = "secreto-sintetico-uno"
SECRETO_ESTANDAR = "whsec_" + base64.b64encode(b"omniwebhook-secreto-sintetico-01").decode()


@pytest.mark.parametrize("tolerancia", [0, -5, 1.5, True])
def test_una_tolerancia_invalida_es_un_error_de_configuracion(tolerancia: int) -> None:
    for esquema in (stripe_scheme, tiktok_scheme, mercadopago_scheme, standard_scheme):
        with pytest.raises(ConfigurationError, match="tolerance_seconds"):
            esquema(secrets=[SECRETO], tolerance_seconds=tolerancia)


def test_los_secretos_son_una_lista_y_no_un_texto() -> None:
    for esquema in (
        stripe_scheme,
        tiktok_scheme,
        mercadopago_scheme,
        github_scheme,
        creem_scheme,
        google_channel_scheme,
        google_pubsub_scheme,
        standard_scheme,
    ):
        with pytest.raises(ConfigurationError, match="secrets tiene que ser una lista"):
            esquema(secrets=SECRETO)
    with pytest.raises(ConfigurationError, match="secrets tiene que ser una lista"):
        shared_token_scheme(secrets=SECRETO, header="x-token")
    with pytest.raises(ConfigurationError, match="secrets tiene que ser una lista"):
        standard_signer(secrets=SECRETO_ESTANDAR)


@pytest.mark.parametrize(
    ("opciones", "mensaje"),
    [
        ({"header": " "}, "header"),
        ({"header": "x-firma", "name": ""}, "name"),
        ({"header": "x-firma", "encoding": "base32"}, "encoding"),
    ],
)
def test_hmac_body_rechaza_opciones_invalidas(opciones: dict[str, str], mensaje: str) -> None:
    with pytest.raises(ConfigurationError, match=mensaje):
        hmac_body_scheme(secrets=[SECRETO], **opciones)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("opciones", "mensaje"),
    [
        ({}, "header o query"),
        ({"header": "x-token", "query": "token"}, "header o query"),
        ({"header": " "}, "header"),
        ({"query": ""}, "query"),
        ({"header": "x-token", "name": ""}, "name"),
        ({"header": "x-token", "id_header": " "}, "id_header"),
        ({"header": 7}, "header"),
    ],
)
def test_shared_token_rechaza_opciones_invalidas(opciones: dict[str, str], mensaje: str) -> None:
    with pytest.raises(ConfigurationError, match=mensaje):
        shared_token_scheme(secrets=[SECRETO], **opciones)


@pytest.mark.parametrize("parametro", ["", " ", None])
def test_google_pubsub_rechaza_un_parametro_vacio(parametro: str) -> None:
    with pytest.raises(ConfigurationError, match="query"):
        google_pubsub_scheme(secrets=[SECRETO], query=parametro)


def test_un_token_que_no_se_puede_codificar_deja_al_esquema_sin_configurar() -> None:
    pedido = IncomingRequest(headers=[("x-token", SECRETO)], query=[], body=b"")

    resultado = shared_token_scheme(secrets=[SECRETO, "\ud800"], header="x-token").verify(pedido)

    assert resultado == Rejected("unconfigured")


@pytest.mark.parametrize(
    "cuerpo",
    [
        b"\xff\xfe no es utf-8",
        b"[" * 100_000,
        b'{"message":' + b"[" * 100_000,
        b'{"message":{"messageId":7}}',
    ],
    ids=["no es utf-8", "anidado sin fin", "message anidado sin fin", "identificador numérico"],
)
def test_un_aviso_de_pubsub_sin_identificador_legible_usa_la_huella_y_nunca_lanza(cuerpo: bytes) -> None:
    pedido = IncomingRequest(headers=[], query=[("token", SECRETO)], body=cuerpo)

    resultado = google_pubsub_scheme(secrets=[SECRETO]).verify(pedido)

    assert isinstance(resultado, Verified)
    assert resultado.event_key.startswith("google-pubsub:sha256:")


def test_sin_reloj_inyectado_usa_el_del_sistema() -> None:
    cuerpo = b'{"id":"evt_1"}'
    viejo = 1_000_000_000
    firma = hmac_sha256(SECRETO.encode(), f"{viejo}.".encode() + cuerpo).hex()

    resultado = stripe_scheme(secrets=[SECRETO]).verify(
        IncomingRequest(headers=[("stripe-signature", f"t={viejo},v1={firma}")], query=[], body=cuerpo)
    )

    assert resultado == Rejected("stale")


def _firmado_creem(cuerpo: bytes) -> IncomingRequest:
    firma = hmac_sha256(SECRETO.encode(), cuerpo).hex()
    return IncomingRequest(headers=[("creem-signature", firma)], query=[], body=cuerpo)


@pytest.mark.parametrize(
    "cuerpo",
    [
        b"\xff\xfe no es utf-8",
        b'{"id": "evt_1", "monto": NaN}',
        b"[" * 100_000,
        b'["id"]',
        b'{"id": 7}',
        b'{"id": ""}',
        b'\xef\xbb\xbf{"id":"evt_1"}',
    ],
    ids=[
        "no es utf-8",
        "constante que no es JSON",
        "anidado sin fin",
        "lista",
        "id numérico",
        "id vacío",
        "con BOM",
    ],
)
def test_un_cuerpo_sin_identificador_legible_usa_la_huella_y_nunca_lanza(cuerpo: bytes) -> None:
    resultado = creem_scheme(secrets=[SECRETO]).verify(_firmado_creem(cuerpo))

    assert isinstance(resultado, Verified)
    assert resultado.event_key.startswith("creem:sha256:")


def test_el_identificador_del_cuerpo_se_lee_de_un_objeto_json() -> None:
    cuerpo = json.dumps({"id": "evt_ñ", "x": [1, 2]}).encode()

    assert creem_scheme(secrets=[SECRETO]).verify(_firmado_creem(cuerpo)) == Verified("creem:evt_ñ", None)


def test_un_cuerpo_que_no_es_utf8_se_firma_y_se_verifica_byte_a_byte() -> None:
    cuerpo = b"\xff\x00\xfe binario"
    reloj = RelojFijo()
    for firmante in (reference_signer, native_signer):
        firmado = standard_signer(secrets=[SECRETO_ESTANDAR], signer=firmante).sign(
            OutgoingMessage(id="msg_1", timestamp=reloj.ahora, payload=cuerpo)
        )
        assert isinstance(firmado, Signed)

        resultado = standard_scheme(secrets=[SECRETO_ESTANDAR], clock=reloj, signer=firmante).verify(
            IncomingRequest(headers=list(firmado.headers.items()), query=[], body=cuerpo)
        )

        assert resultado == Verified("standard:msg_1", reloj.ahora)


def test_los_dos_firmantes_del_formato_estandar_dan_la_misma_firma() -> None:
    clave = b"omniwebhook-secreto-sintetico-01"

    assert reference_signer.sign(clave, "msg_1", 1_700_000_000, b"{}") == native_signer.sign(
        clave, "msg_1", 1_700_000_000, b"{}"
    )


def test_una_marca_de_once_digitos_no_rompe_al_firmante_de_referencia() -> None:
    resultado = standard_scheme(
        secrets=[SECRETO_ESTANDAR], clock=RelojFijo(), signer=reference_signer
    ).verify(
        IncomingRequest(
            headers=[
                ("webhook-id", "m"),
                ("webhook-timestamp", "99999999999"),
                ("webhook-signature", "v1,AAAA"),
            ],
            query=[],
            body=b"",
        )
    )

    assert resultado == Rejected("invalid")


def test_un_secreto_que_no_se_puede_codificar_deja_al_esquema_sin_configurar() -> None:
    pedido = IncomingRequest(headers=[("creem-signature", "ab")], query=[], body=b"{}")

    assert creem_scheme(secrets=["\ud800"]).verify(pedido) == Rejected("unconfigured")
    assert creem_scheme(secrets=[SECRETO, None]).verify(pedido) == Rejected("unconfigured")  # type: ignore[list-item]


def test_sin_la_libreria_de_referencia_el_error_dice_que_hacer(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "standardwebhooks", None)
    monkeypatch.delitem(sys.modules, "omniwebhook.adapters.schemes.standard.reference_signer", raising=False)

    with pytest.raises(ConfigurationError, match=r"omniwebhook\[standard\].*native_signer"):
        standard_scheme(secrets=[SECRETO_ESTANDAR])
    with pytest.raises(ConfigurationError, match=r"omniwebhook\[standard\]"):
        standard_signer(secrets=[SECRETO_ESTANDAR])

    assert standard_scheme(secrets=[SECRETO_ESTANDAR], signer=native_signer) is not None


def test_el_modulo_del_formato_estandar_no_inventa_nombres() -> None:
    import omniwebhook.standard

    with pytest.raises(AttributeError, match="no_existe"):
        _ = omniwebhook.standard.no_existe


CLAVE_PUBLICA = "whpk_" + base64.b64encode(bytes(range(32))).decode()


@pytest.mark.parametrize("destino", ["", "ep.1", None, 7])
def test_la_firma_asimetrica_exige_un_identificador_de_destino_valido(destino: str) -> None:
    with pytest.raises(ConfigurationError, match="endpoint_id"):
        standard_public_key_scheme(public_keys=[CLAVE_PUBLICA], endpoint_id=destino)


def test_la_firma_asimetrica_rechaza_una_tolerancia_invalida() -> None:
    with pytest.raises(ConfigurationError, match="tolerance_seconds"):
        standard_public_key_scheme(public_keys=[CLAVE_PUBLICA], endpoint_id="ep_1", tolerance_seconds=0)


@pytest.mark.parametrize("clave", [b"\xff" * 32, b"\x00" * 32, bytes(range(32))], ids=["ff", "00", "rango"])
def test_una_clave_que_no_sirve_para_verificar_nunca_verifica_ni_lanza(clave: bytes) -> None:
    esquema = standard_public_key_scheme(
        public_keys=["whpk_" + base64.b64encode(clave).decode()], endpoint_id="ep_1", clock=RelojFijo()
    )
    firma = "v2a," + base64.b64encode(b"\x01" * 64).decode()
    pedido = IncomingRequest(
        headers=[("webhook-id", "msg_1"), ("webhook-timestamp", "1700000000"), ("webhook-signature", firma)],
        query=[],
        body=b"{}",
    )

    assert esquema.verify(pedido) == Rejected("invalid")
