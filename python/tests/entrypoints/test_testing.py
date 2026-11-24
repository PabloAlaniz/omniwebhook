from typing import Any

import pytest

from omniwebhook import (
    ConfigurationError,
    Rejected,
    Verified,
    Verifier,
    creem_scheme,
    github_scheme,
    hmac_body_scheme,
    mercadopago_scheme,
    shopify_scheme,
    slack_scheme,
    stripe_scheme,
    tiktok_scheme,
)
from omniwebhook.standard import native_signer, standard_scheme
from omniwebhook.testing import SignedScheme, signed_request, tampered
from tests.support.dobles import RelojFijo

AHORA = 1_700_000_000
RELOJ = RelojFijo(AHORA)
TEXTO = "secreto-sintetico"
ESTANDAR = "whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="
CUERPO = '{"id":"evt_1","event_id":"Ev1","ñ":true}'

Fila = tuple[SignedScheme, Verifier, dict[str, Any], str]
ESQUEMAS: list[Fila] = [
    (
        "standard",
        standard_scheme(secrets=[ESTANDAR], clock=RELOJ, signer=native_signer),
        {"id": "msg_1"},
        "standard:msg_1",
    ),
    ("stripe", stripe_scheme(secrets=[TEXTO], clock=RELOJ), {}, "stripe:evt_1"),
    ("slack", slack_scheme(secrets=[TEXTO], clock=RELOJ), {}, "slack:Ev1"),
    ("tiktok", tiktok_scheme(secrets=[TEXTO], clock=RELOJ), {}, "tiktok:sha256:"),
    (
        "mercadopago",
        mercadopago_scheme(secrets=[TEXTO], clock=RELOJ),
        {"id": "req-1", "data_id": "ABC"},
        "mercadopago:abc:req-1",
    ),
    ("mercadopago", mercadopago_scheme(secrets=[TEXTO], clock=RELOJ), {}, f"mercadopago:ts:{AHORA}"),
    ("github", github_scheme(secrets=[TEXTO]), {"id": "entrega-1"}, "github:entrega-1"),
    ("github", github_scheme(secrets=[TEXTO]), {}, "github:sha256:"),
    ("creem", creem_scheme(secrets=[TEXTO]), {}, "creem:evt_1"),
    ("shopify", shopify_scheme(secrets=[TEXTO]), {"id": "wh-1"}, "shopify:wh-1"),
    (
        "hmac-body",
        hmac_body_scheme(
            secrets=[TEXTO], header="x-firma", prefix="v1=", encoding="base64", id_header="x-id"
        ),
        {"header": "x-firma", "prefix": "v1=", "encoding": "base64", "id_header": "x-id", "id": "e-1"},
        "hmac-body:e-1",
    ),
    (
        "hmac-body",
        hmac_body_scheme(secrets=[TEXTO], header="x-firma"),
        {"header": "x-firma"},
        "hmac-body:sha256:",
    ),
]
IDS = [f"{fila[0]} ({indice})" for indice, fila in enumerate(ESQUEMAS)]


def _secreto(esquema: str) -> str:
    return ESTANDAR if esquema == "standard" else TEXTO


@pytest.mark.parametrize(("esquema", "verificador", "extra", "clave"), ESQUEMAS, ids=IDS)
def test_lo_que_arma_lo_verifica_el_esquema(
    esquema: SignedScheme, verificador: Verifier, extra: dict[str, Any], clave: str
) -> None:
    pedido = signed_request(esquema, secret=_secreto(esquema), body=CUERPO, timestamp=AHORA, **extra)

    resultado = verificador.verify(pedido)

    assert isinstance(resultado, Verified)
    assert resultado.event_key.startswith(clave)


@pytest.mark.parametrize(("esquema", "verificador", "extra", "clave"), ESQUEMAS, ids=IDS)
def test_alterado_deja_de_verificarse(
    esquema: SignedScheme, verificador: Verifier, extra: dict[str, Any], clave: str
) -> None:
    pedido = signed_request(esquema, secret=_secreto(esquema), body=CUERPO, timestamp=AHORA, **extra)

    assert verificador.verify(tampered(pedido)) == Rejected("invalid")


@pytest.mark.parametrize(
    ("esquema", "verificador", "extra", "clave"),
    [fila for fila in ESQUEMAS if fila[0] in ("standard", "stripe", "slack", "tiktok")],
)
def test_con_una_marca_vieja_es_stale(
    esquema: SignedScheme, verificador: Verifier, extra: dict[str, Any], clave: str
) -> None:
    pedido = signed_request(esquema, secret=_secreto(esquema), body=CUERPO, timestamp=AHORA - 3600, **extra)

    assert verificador.verify(pedido) == Rejected("stale")


def test_por_defecto_firma_con_la_hora_actual_y_genera_el_identificador() -> None:
    pedido = signed_request("standard", secret=ESTANDAR, body=b"\x01")

    resultado = standard_scheme(secrets=[ESTANDAR], signer=native_signer).verify(pedido)

    assert isinstance(resultado, Verified)
    assert resultado.event_key.startswith("standard:msg_")


@pytest.mark.parametrize(
    ("esquema", "extra"),
    [
        ("stripe", {"secret": ""}),
        ("standard", {"secret": "whsec_***"}),
        ("hmac-body", {}),
        ("otro", {}),
    ],
    ids=["un secreto vacío", "un secreto que no es base64 en standard", "hmac-body sin cabecera", "otro"],
)
def test_rechaza_lo_que_no_puede_firmar(esquema: Any, extra: dict[str, Any]) -> None:
    with pytest.raises(ConfigurationError):
        signed_request(esquema, **{"secret": TEXTO, "body": CUERPO, **extra})
