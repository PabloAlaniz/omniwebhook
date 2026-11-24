import re

import pytest

from omniwebhook import ConfigurationError, IncomingRequest, NotSigned, OutgoingMessage, Signed, Verified
from omniwebhook.standard import (
    combined_signer,
    generate_standard_key_pair,
    native_signer,
    standard_key_signer,
    standard_public_key_of,
    standard_public_key_scheme,
    standard_scheme,
    standard_signer,
)
from tests.support.dobles import RelojFijo
from tests.support.vectors import Caso, casos, nombre

CASOS = casos("firmar/standard-v2a")
FIRMADOS = [caso for caso in CASOS if "headers" in caso["expected"]]
SECRETO = "whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="


def _mensaje(caso: Caso) -> OutgoingMessage:
    return OutgoingMessage(
        id=caso["id"],
        timestamp=caso["timestamp"],
        payload=caso["payload"].encode("utf-8"),
        endpoint_id=caso["endpoint_id"],
    )


@pytest.mark.parametrize("caso", CASOS, ids=nombre)
def test_vectores(caso: Caso) -> None:
    resultado = standard_key_signer(secret_keys=caso["secrets"]).sign(_mensaje(caso))

    esperado = caso["expected"]
    if "headers" in esperado:
        assert resultado == Signed(headers=esperado["headers"])
        assert [standard_public_key_of(clave) for clave in caso["secrets"]] == esperado["public_keys"]
    else:
        assert resultado == NotSigned(esperado["error"])


@pytest.mark.parametrize("caso", FIRMADOS, ids=nombre)
def test_lo_firmado_lo_verifica_la_clave_publica(caso: Caso) -> None:
    mensaje = _mensaje(caso)
    firmado = standard_key_signer(secret_keys=caso["secrets"]).sign(mensaje)
    assert isinstance(firmado, Signed)

    verificado = standard_public_key_scheme(
        public_keys=[caso["expected"]["public_keys"][-1]],
        endpoint_id=caso["endpoint_id"],
        clock=RelojFijo(caso["timestamp"]),
    ).verify(IncomingRequest(headers=list(firmado.headers.items()), query=[], body=mensaje.payload))

    assert verificado == Verified(f"standard:{caso['id']}", caso["timestamp"])


def test_un_par_nuevo_firma_y_verifica_y_no_muestra_la_clave_privada() -> None:
    par, otro = generate_standard_key_pair(), generate_standard_key_pair()
    mensaje = OutgoingMessage(id="msg_1", timestamp=1000, payload=b"{}", endpoint_id="ep_1")

    firmado = standard_key_signer(secret_keys=[par.secret_key]).sign(mensaje)
    assert isinstance(firmado, Signed)
    pedido = IncomingRequest(headers=list(firmado.headers.items()), query=[], body=b"{}")

    def esquema(clave: str) -> object:
        return standard_public_key_scheme(
            public_keys=[clave], endpoint_id="ep_1", clock=RelojFijo(1000)
        ).verify(pedido)

    assert re.fullmatch(r"whsk_[A-Za-z0-9+/]{43}=", par.secret_key)
    assert standard_public_key_of(par.secret_key) == par.public_key
    assert isinstance(esquema(par.public_key), Verified)
    assert esquema(otro.public_key).outcome == "invalid"  # type: ignore[attr-defined]
    assert par.secret_key not in repr(par)
    assert par.public_key in repr(par)


@pytest.mark.parametrize("clave", ["whsk_***", "", "whpk_abc", 7])
def test_una_clave_privada_inutilizable_no_tiene_clave_publica(clave: str) -> None:
    assert standard_public_key_of(clave) is None


def test_las_claves_son_una_lista_y_no_un_texto() -> None:
    with pytest.raises(ConfigurationError, match="lista"):
        standard_key_signer(secret_keys="whsk_abc")


def test_la_firma_combinada_la_verifica_cada_receptor_con_la_suya() -> None:
    par = generate_standard_key_pair()
    mensaje = OutgoingMessage(id="msg_1", timestamp=1000, payload=b'{"hola":"mundo"}', endpoint_id="ep_1")
    firmante = combined_signer(
        [
            standard_signer(secrets=[SECRETO], signer=native_signer),
            standard_key_signer(secret_keys=[par.secret_key]),
        ]
    )

    firmado = firmante.sign(mensaje)
    assert isinstance(firmado, Signed)
    pedido = IncomingRequest(headers=list(firmado.headers.items()), query=[], body=mensaje.payload)
    reloj = RelojFijo(1000)

    assert re.fullmatch(r"v1,\S+ v2a,\S+", firmado.headers["webhook-signature"])
    assert sorted(firmado.headers) == ["webhook-id", "webhook-signature", "webhook-timestamp"]
    assert isinstance(
        standard_scheme(secrets=[SECRETO], clock=reloj, signer=native_signer).verify(pedido), Verified
    )
    assert isinstance(
        standard_public_key_scheme(public_keys=[par.public_key], endpoint_id="ep_1", clock=reloj).verify(
            pedido
        ),
        Verified,
    )


def test_si_un_firmante_no_puede_firmar_el_mensaje_no_se_firma() -> None:
    firmante = combined_signer(
        [standard_signer(secrets=[SECRETO], signer=native_signer), standard_key_signer(secret_keys=[])]
    )

    assert firmante.sign(OutgoingMessage(id="m", timestamp=1, payload=b"", endpoint_id="ep_1")) == NotSigned(
        "unconfigured"
    )


def test_la_firma_combinada_rechaza_una_lista_vacia() -> None:
    with pytest.raises(ConfigurationError, match="signers"):
        combined_signer([])
