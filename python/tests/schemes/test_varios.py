from typing import Any

import pytest

from omniwebhook import (
    ConfigurationError,
    IncomingRequest,
    Rejected,
    Verification,
    Verified,
    Verifier,
    VerifierRoute,
    github_scheme,
    routed_verifier,
    stripe_scheme,
)
from omniwebhook.standard import standard_scheme
from tests.support.dobles import RelojFijo
from tests.support.vectors import Caso, a_pedido, casos, nombre


def _esquema(ruta: dict[str, Any], reloj: RelojFijo) -> Verifier:
    if ruta["scheme"] == "stripe":
        return stripe_scheme(secrets=ruta["secrets"], clock=reloj)
    if ruta["scheme"] == "github":
        return github_scheme(secrets=ruta["secrets"])
    return standard_scheme(secrets=ruta["secrets"], clock=reloj)


@pytest.mark.parametrize("caso", casos("verificar/varios"), ids=nombre)
def test_vectores(caso: Caso) -> None:
    reloj = RelojFijo(caso["now"])
    verificador = routed_verifier(
        [VerifierRoute(ruta["header"], _esquema(ruta, reloj)) for ruta in caso["routes"]]
    )

    resultado = verificador.verify(a_pedido(caso["request"]))

    esperado = caso["expected"]
    if esperado["outcome"] == "ok":
        assert resultado == Verified(event_key=esperado["event_key"], timestamp=esperado["timestamp"])
    else:
        assert resultado == Rejected(esperado["outcome"])


class _Nunca:
    def verify(self, request: IncomingRequest) -> Verification:
        raise AssertionError("no se tenía que verificar")


class _Invalido:
    def verify(self, request: IncomingRequest) -> Verification:
        return Rejected("invalid")


PEDIDO = IncomingRequest(headers=[("x-a", "1")], query=[], body=b"")


def test_solo_le_pasa_el_pedido_al_verificador_de_la_ruta_que_coincide() -> None:
    verificador = routed_verifier([VerifierRoute("x-b", _Nunca()), VerifierRoute(" X-A ", _Invalido())])

    assert verificador.verify(PEDIDO) == Rejected("invalid")


def test_con_dos_rutas_que_coinciden_no_verifica_con_ninguna() -> None:
    verificador = routed_verifier([VerifierRoute("x-a", _Nunca()), VerifierRoute("x-b", _Nunca())])
    pedido = IncomingRequest(headers=[("x-a", "1"), ("x-b", "2")], query=[], body=b"")

    assert verificador.verify(pedido) == Rejected("ambiguous")


@pytest.mark.parametrize(
    "rutas",
    [
        [],
        [VerifierRoute(" ", _Nunca())],
        [VerifierRoute(None, _Nunca())],  # type: ignore[arg-type]
        [VerifierRoute("x-a", _Nunca()), VerifierRoute("X-A", _Nunca())],
    ],
    ids=["sin rutas", "una cabecera vacía", "una cabecera que no es texto", "una cabecera repetida"],
)
def test_rechaza_una_configuracion_invalida(rutas: list[VerifierRoute]) -> None:
    with pytest.raises(ConfigurationError):
        routed_verifier(rutas)
