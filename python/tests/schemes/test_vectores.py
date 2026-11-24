from collections.abc import Callable

import pytest

from omniwebhook import (
    NotSigned,
    OutgoingMessage,
    Rejected,
    Signed,
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
from omniwebhook.discord import discord_scheme
from omniwebhook.standard import (
    StandardSigner,
    native_signer,
    reference_signer,
    standard_public_key_scheme,
    standard_scheme,
    standard_signer,
)
from tests.support.dobles import RelojFijo
from tests.support.vectors import Caso, a_pedido, casos, nombre

Fabrica = Callable[[Caso, RelojFijo], Verifier]
FIRMANTES: dict[str, StandardSigner] = {"librería de referencia": reference_signer, "nativo": native_signer}


def _tolerancia(caso: Caso) -> dict[str, int]:
    opciones = caso.get("options") or {}
    return {"tolerance_seconds": opciones["tolerance_seconds"]} if "tolerance_seconds" in opciones else {}


def _estandar(firmante: StandardSigner) -> Fabrica:
    return lambda c, reloj: standard_scheme(
        secrets=c["secrets"], clock=reloj, signer=firmante, **_tolerancia(c)
    )


ESQUEMAS: dict[str, tuple[str, Fabrica]] = {
    **{f"standard ({n})": ("standard", _estandar(f)) for n, f in FIRMANTES.items()},
    "standard-v2a": (
        "standard-v2a",
        lambda c, reloj: standard_public_key_scheme(
            public_keys=c["secrets"], endpoint_id=c["options"]["endpoint_id"], clock=reloj, **_tolerancia(c)
        ),
    ),
    "discord": (
        "discord",
        lambda c, reloj: discord_scheme(public_keys=c["secrets"], clock=reloj, **_tolerancia(c)),
    ),
    "stripe": ("stripe", lambda c, reloj: stripe_scheme(secrets=c["secrets"], clock=reloj, **_tolerancia(c))),
    "tiktok": ("tiktok", lambda c, reloj: tiktok_scheme(secrets=c["secrets"], clock=reloj, **_tolerancia(c))),
    "mercadopago": (
        "mercadopago",
        lambda c, reloj: mercadopago_scheme(secrets=c["secrets"], clock=reloj, **_tolerancia(c)),
    ),
    "github": ("github", lambda c, _reloj: github_scheme(secrets=c["secrets"])),
    "creem": ("creem", lambda c, _reloj: creem_scheme(secrets=c["secrets"])),
    "shopify": ("shopify", lambda c, _reloj: shopify_scheme(secrets=c["secrets"])),
    "slack": ("slack", lambda c, reloj: slack_scheme(secrets=c["secrets"], clock=reloj, **_tolerancia(c))),
    "hmac-body": ("hmac-body", lambda c, _reloj: hmac_body_scheme(secrets=c["secrets"], **c["options"])),
}

VERIFICAR = [
    pytest.param(fabrica, caso, id=f"{etiqueta}: {nombre(caso)}")
    for etiqueta, (vector, fabrica) in ESQUEMAS.items()
    for caso in casos(f"verificar/{vector}")
]


@pytest.mark.parametrize(("fabrica", "caso"), VERIFICAR)
def test_verificar(fabrica: Fabrica, caso: Caso) -> None:
    verificador = fabrica(caso, RelojFijo(caso["now"]))

    resultado = verificador.verify(a_pedido(caso["request"]))

    esperado = caso["expected"]
    if esperado["outcome"] == "ok":
        assert resultado == Verified(event_key=esperado["event_key"], timestamp=esperado["timestamp"])
    else:
        assert resultado == Rejected(esperado["outcome"])


FIRMAR = [
    pytest.param(firmante, caso, id=f"{etiqueta}: {nombre(caso)}")
    for etiqueta, firmante in FIRMANTES.items()
    for caso in casos("firmar/standard")
]


@pytest.mark.parametrize(("firmante", "caso"), FIRMAR)
def test_firmar(firmante: StandardSigner, caso: Caso) -> None:
    firma = standard_signer(secrets=caso["secrets"], signer=firmante)

    resultado = firma.sign(
        OutgoingMessage(id=caso["id"], timestamp=caso["timestamp"], payload=caso["payload"].encode("utf-8"))
    )

    esperado = caso["expected"]
    if "error" in esperado:
        assert resultado == NotSigned(esperado["error"])
    else:
        assert resultado == Signed(headers=esperado["headers"])
