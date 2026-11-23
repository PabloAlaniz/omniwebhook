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
    hmac_body_scheme,
    mercadopago_scheme,
    stripe_scheme,
    tiktok_scheme,
)
from omniwebhook.adapters.crypto import hmac_sha256
from omniwebhook.standard import native_signer, reference_signer, standard_scheme, standard_signer
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
        standard_scheme,
    ):
        with pytest.raises(ConfigurationError, match="secrets tiene que ser una lista"):
            esquema(secrets=SECRETO)
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
