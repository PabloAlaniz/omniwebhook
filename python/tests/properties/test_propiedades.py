"""Lo que interpreta entrada ajena no puede lanzar.

Cualquier cosa que llegue termina en uno de los resultados definidos. Los vectores cubren los
casos pensados; esto, los que no.
"""

import json
from urllib.parse import urlsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from omniwebhook import (
    DEFAULT_MAX_DELAY_SECONDS,
    IncomingRequest,
    OutgoingMessage,
    Rejected,
    Signed,
    Verified,
    Verifier,
    creem_scheme,
    github_scheme,
    hmac_body_scheme,
    is_blocked_address,
    mercadopago_scheme,
    next_attempt,
    stripe_scheme,
    tiktok_scheme,
)
from omniwebhook.domain.destination import InspectedDestination, inspect_destination
from omniwebhook.domain.signature_pairs import parse_pairs
from omniwebhook.standard import standard_scheme, standard_signer
from tests.support.dobles import RelojFijo

AHORA = 1_700_000_000
RELOJ = RelojFijo(AHORA)
SECRETO = "whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="
RESULTADOS = {"ok", "unconfigured", "missing", "ambiguous", "malformed", "invalid", "stale"}

ESQUEMAS: dict[str, Verifier] = {
    "standard": standard_scheme(secrets=[SECRETO], clock=RELOJ),
    "stripe": stripe_scheme(secrets=["secreto-sintetico"], clock=RELOJ),
    "tiktok": tiktok_scheme(secrets=["secreto-sintetico"], clock=RELOJ),
    "mercadopago": mercadopago_scheme(secrets=["secreto-sintetico"], clock=RELOJ),
    "github": github_scheme(secrets=["secreto-sintetico"]),
    "creem": creem_scheme(secrets=["secreto-sintetico"]),
    "hmac-body": hmac_body_scheme(secrets=["secreto-sintetico"], header="x-firma"),
}

# Los nombres que algún esquema lee, para que la entrada al azar llegue más allá de `missing`.
NOMBRES = [
    "webhook-id",
    "webhook-timestamp",
    "webhook-signature",
    "stripe-signature",
    "tiktok-signature",
    "x-signature",
    "x-request-id",
    "x-hub-signature-256",
    "creem-signature",
    "x-firma",
    "data.id",
]
# Valores con la forma de los que los esquemas esperan, mezclados con cualquier cosa.
VALOR = st.one_of(
    st.text(),
    st.from_regex(r"(t|ts|v1|s|sha256)=[0-9a-f]{0,64}(,(t|ts|v1|s)=[0-9a-f]{0,64}){0,3}", fullmatch=True),
    st.from_regex(r"v1,[A-Za-z0-9+/]{0,44}={0,2}( v1,[A-Za-z0-9+/]{0,44})?", fullmatch=True),
    st.from_regex(r"[0-9]{1,16}", fullmatch=True),
    st.just(str(AHORA)),
)
CAMPO = st.tuples(st.one_of(st.sampled_from(NOMBRES), st.text()), VALOR)
PEDIDO = st.builds(
    IncomingRequest,
    headers=st.lists(CAMPO, max_size=8),
    query=st.lists(CAMPO, max_size=4),
    body=st.one_of(
        st.binary(max_size=256),
        st.recursive(
            st.none() | st.booleans() | st.integers() | st.text(),
            lambda hijos: st.lists(hijos, max_size=3) | st.dictionaries(st.text(), hijos, max_size=3),
            max_leaves=8,
        ).map(lambda valor: json.dumps(valor).encode()),
    ),
)


@pytest.mark.parametrize("esquema", sorted(ESQUEMAS))
@settings(max_examples=300, deadline=None)
@given(pedido=PEDIDO)
def test_cualquier_pedido_termina_en_un_resultado_definido(esquema: str, pedido: IncomingRequest) -> None:
    resultado = ESQUEMAS[esquema].verify(pedido)

    assert isinstance(resultado, Verified | Rejected)
    assert resultado.outcome in RESULTADOS


@settings(max_examples=200, deadline=None)
@given(
    ident=st.from_regex(r"[A-Za-z0-9_-]{1,40}", fullmatch=True),
    payload=st.binary(min_size=1, max_size=512),
    posicion=st.integers(min_value=0),
)
def test_lo_que_se_firma_se_verifica_y_con_un_byte_cambiado_no(
    ident: str, payload: bytes, posicion: int
) -> None:
    firmado = standard_signer(secrets=[SECRETO]).sign(
        OutgoingMessage(id=ident, timestamp=AHORA, payload=payload)
    )
    assert isinstance(firmado, Signed)
    cabeceras = list(firmado.headers.items())
    verificador = ESQUEMAS["standard"]

    assert verificador.verify(IncomingRequest(headers=cabeceras, query=[], body=payload)) == Verified(
        f"standard:{ident}", AHORA
    )

    alterado = bytearray(payload)
    alterado[posicion % len(alterado)] ^= 1
    assert verificador.verify(IncomingRequest(headers=cabeceras, query=[], body=bytes(alterado))) == Rejected(
        "invalid"
    )


@given(texto=st.text())
def test_los_pares_nunca_tienen_claves_o_valores_vacios_ni_con_blancos_en_los_bordes(texto: str) -> None:
    for clave, valor in parse_pairs(texto):
        for parte in (clave, valor):
            assert parte != ""
            assert parte[0] not in " \t"
            assert parte[-1] not in " \t"
            assert "," not in parte


# URLs casi válidas: es donde un analizador estricto y uno tolerante pueden no coincidir.
PIEZA = st.one_of(
    st.sampled_from(["a", "A", "z", "0", "1", "9", "-", "_", ".", "..", "xn--", "example", "test"]),
    st.sampled_from([":", "/", "//", "@", "?", "#", "[", "]", "%", "%2e", "%00", "\\", " ", "\t"]),
    st.sampled_from(["127.0.0.1", "0x7f", "0177", "2130706433", "::1", "::ffff:10.0.0.1", "。", "ａ"]),
    st.text(max_size=3),
)
CASI_URL = st.builds(
    lambda esquema, piezas: esquema + "".join(piezas),
    st.sampled_from(["https://", "http://", "HTTPS://", "https:/", "https:", "ftp://", ""]),
    st.lists(PIEZA, max_size=8),
)
URL = st.one_of(CASI_URL, st.text())


@settings(max_examples=2000, deadline=None)
@given(url=URL, permite_http=st.booleans())
def test_cualquier_texto_termina_en_un_destino_o_en_un_motivo_definido(url: str, permite_http: bool) -> None:
    revisado = inspect_destination(url, allow_http=permite_http)

    assert isinstance(revisado, InspectedDestination) or revisado in {"invalid_url", "scheme", "credentials"}


@settings(max_examples=5000, deadline=None)
@given(url=URL)
def test_si_acepta_una_url_el_analizador_de_la_plataforma_lee_el_mismo_host(url: str) -> None:
    revisado = inspect_destination(url, allow_http=True)
    if not isinstance(revisado, InspectedDestination):
        return

    # La conexión la arma el analizador de la plataforma: si leyera otro host, la política
    # habría validado un destino y el pedido saldría hacia otro.
    try:
        partes = urlsplit(url)
        host = partes.hostname
    except ValueError:
        # Que la plataforma rechace una URL que la política aceptó no es un problema: el
        # intento falla sin salir hacia ningún lado.
        return
    assert partes.username is None
    assert partes.password is None
    assert host == revisado.host


@settings(max_examples=2000, deadline=None)
@given(texto=st.one_of(st.text(), st.ip_addresses().map(str)))
def test_cualquier_texto_es_una_direccion_bloqueada_o_una_permitida(texto: str) -> None:
    assert isinstance(is_blocked_address(texto), bool)


RETRY_AFTER = st.one_of(
    st.none(),
    st.text(),
    st.from_regex(r"[0-9]{1,20}", fullmatch=True),
    st.datetimes().map(lambda fecha: fecha.strftime("%a, %d %b %Y %H:%M:%S GMT")),
)


@settings(max_examples=2000, deadline=None)
@given(
    intento=st.integers(min_value=1, max_value=30),
    azar=st.floats(min_value=0, max_value=1, exclude_max=True),
    cabecera=RETRY_AFTER,
)
def test_la_espera_nunca_es_negativa_ni_supera_el_tope_mas_su_variacion(
    intento: int, azar: float, cabecera: str | None
) -> None:
    proximo = next_attempt(attempt=intento, now=AHORA, random=azar, retry_after=cabecera)
    if proximo is None:
        return

    assert proximo.delay_seconds >= 0
    assert proximo.delay_seconds < DEFAULT_MAX_DELAY_SECONDS * 1.1
    assert proximo.next_at == AHORA + proximo.delay_seconds
