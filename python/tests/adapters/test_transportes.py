import asyncio
import socket
import ssl
import time
from collections.abc import Callable, Iterator

import pytest
import trustme

from omniwebhook import (
    HttpClientTransport,
    ThreadedTransport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)
from omniwebhook.httpx import AsyncHttpxTransport
from tests.support.servidor import Servidor, servidor

Enviar = Callable[[TransportRequest], TransportResponse | TransportFailure]
Fabrica = Callable[[ssl.SSLContext | None], Enviar]
NOMBRE = "hooks.ejemplo.test"


def _sincronico(confianza: ssl.SSLContext | None) -> Enviar:
    return HttpClientTransport(ssl_context=confianza).post


def _en_un_hilo(confianza: ssl.SSLContext | None) -> Enviar:
    transporte = ThreadedTransport(HttpClientTransport(ssl_context=confianza))
    return lambda pedido: asyncio.run(transporte.post(pedido))


def _httpx(confianza: ssl.SSLContext | None) -> Enviar:
    async def enviar(pedido: TransportRequest) -> TransportResponse | TransportFailure:
        transporte = AsyncHttpxTransport(verify=confianza if confianza is not None else True)
        try:
            return await transporte.post(pedido)
        finally:
            await transporte.aclose()

    return lambda pedido: asyncio.run(enviar(pedido))


@pytest.fixture(params=[_sincronico, _en_un_hilo, _httpx], ids=["http.client", "en un hilo", "httpx"])
def fabrica(request: pytest.FixtureRequest) -> Fabrica:
    fabrica: Fabrica = request.param
    return fabrica


@pytest.fixture
def local() -> Iterator[Servidor]:
    with servidor() as estado:
        yield estado


def _pedido(url: str, *, espera: int = 5, address: str = "127.0.0.1") -> TransportRequest:
    return TransportRequest(
        url=url,
        address=address,
        headers={"content-type": "application/json", "webhook-id": "msg_1"},
        body=b'{"n":1}\xff',
        timeout_seconds=espera,
    )


def test_se_conecta_a_la_direccion_validada_aunque_el_nombre_no_exista(
    fabrica: Fabrica, local: Servidor
) -> None:
    respuesta = fabrica(None)(_pedido(f"http://hooks.ejemplo.invalid:{local.port}/ok?canal=1"))

    assert respuesta == TransportResponse(200, None)
    [recibido] = local.recibidos
    assert recibido.path == "/ok?canal=1"
    assert recibido.body == b'{"n":1}\xff'
    assert recibido.headers["host"] == f"hooks.ejemplo.invalid:{local.port}"
    assert recibido.headers["webhook-id"] == "msg_1"
    assert recibido.headers["content-type"] == "application/json"
    assert recibido.headers["content-length"] == "8"


def test_una_url_sin_ruta_pide_la_raiz(fabrica: Fabrica, local: Servidor) -> None:
    fabrica(None)(_pedido(f"http://hooks.ejemplo.invalid:{local.port}"))

    assert local.recibidos[0].path == "/"


def test_devuelve_el_estado_y_retry_after(fabrica: Fabrica, local: Servidor) -> None:
    respuesta = fabrica(None)(_pedido(f"http://hooks.ejemplo.invalid:{local.port}/tarde"))

    assert respuesta == TransportResponse(503, "120")


def test_no_sigue_redirecciones(fabrica: Fabrica, local: Servidor) -> None:
    respuesta = fabrica(None)(_pedido(f"http://hooks.ejemplo.invalid:{local.port}/mudado"))

    assert isinstance(respuesta, TransportResponse)
    assert respuesta.status == 302
    assert [recibido.path for recibido in local.recibidos] == ["/mudado"]


def test_si_el_servidor_tarda_de_mas_es_un_tiempo_de_espera_agotado(
    fabrica: Fabrica, local: Servidor
) -> None:
    respuesta = fabrica(None)(_pedido(f"http://hooks.ejemplo.invalid:{local.port}/lento", espera=1))

    assert respuesta == TransportFailure("timeout")


def test_el_plazo_es_del_intento_completo_aunque_el_servidor_gotee(fabrica: Fabrica, local: Servidor) -> None:
    inicio = time.monotonic()

    respuesta = fabrica(None)(_pedido(f"http://hooks.ejemplo.invalid:{local.port}/goteo", espera=1))

    assert respuesta == TransportFailure("timeout")
    assert time.monotonic() - inicio < 2


def test_si_nadie_escucha_es_un_error_de_red(fabrica: Fabrica) -> None:
    with socket.socket() as libre:
        libre.bind(("127.0.0.1", 0))
        puerto = libre.getsockname()[1]

    assert fabrica(None)(_pedido(f"http://hooks.ejemplo.invalid:{puerto}/ok")) == TransportFailure("network")


def test_una_url_que_no_se_puede_pedir_es_un_error_de_red(fabrica: Fabrica) -> None:
    assert fabrica(None)(_pedido("ftp://hooks.ejemplo.invalid/ok")) == TransportFailure("network")
    assert fabrica(None)(_pedido("http:///sin-host")) == TransportFailure("network")


@pytest.fixture(scope="module")
def autoridad() -> trustme.CA:
    return trustme.CA()


def _contextos(autoridad: trustme.CA, nombre_del_certificado: str) -> tuple[ssl.SSLContext, ssl.SSLContext]:
    del_servidor = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    autoridad.issue_cert(nombre_del_certificado).configure_cert(del_servidor)
    del_cliente = ssl.create_default_context()
    autoridad.configure_trust(del_cliente)
    return del_servidor, del_cliente


def test_con_tls_el_certificado_se_comprueba_contra_el_nombre_de_la_url(
    fabrica: Fabrica, autoridad: trustme.CA
) -> None:
    del_servidor, del_cliente = _contextos(autoridad, NOMBRE)
    with servidor(del_servidor) as local:
        respuesta = fabrica(del_cliente)(_pedido(f"https://{NOMBRE}:{local.port}/ok"))

        assert respuesta == TransportResponse(200, None)
        assert local.recibidos[0].headers["host"] == f"{NOMBRE}:{local.port}"


def test_con_tls_un_certificado_de_otro_nombre_es_un_error_de_red(
    fabrica: Fabrica, autoridad: trustme.CA
) -> None:
    del_servidor, del_cliente = _contextos(autoridad, "otro.ejemplo.test")
    with servidor(del_servidor) as local:
        respuesta = fabrica(del_cliente)(_pedido(f"https://{NOMBRE}:{local.port}/ok"))

        assert respuesta == TransportFailure("network")
        assert local.recibidos == []


def test_con_tls_una_autoridad_desconocida_es_un_error_de_red(
    fabrica: Fabrica, autoridad: trustme.CA
) -> None:
    del_servidor, _ = _contextos(autoridad, NOMBRE)
    with servidor(del_servidor) as local:
        respuesta = fabrica(None)(_pedido(f"https://{NOMBRE}:{local.port}/ok"))

        assert respuesta == TransportFailure("network")
        assert local.recibidos == []
