import base64
import io
from collections.abc import Iterable
from typing import Any
from wsgiref.util import setup_testing_defaults

import django
import pytest
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from omniwebhook import (
    ConfigurationError,
    MemoryIdempotencyStore,
    OutgoingMessage,
    Signed,
    VerifiedEvent,
    create_receiver,
    incoming_request_from_environ,
    wsgi_response,
)
from omniwebhook.adapters.clock import SystemClock
from omniwebhook.django import to_incoming_request, to_response
from omniwebhook.standard import standard_scheme, standard_signer

SECRETOS = ["whsec_" + base64.b64encode(b"omniwebhook-secreto-sintetico-01").decode()]
CUERPO = b'{"type":"pedido.creado"}'

if not settings.configured:
    settings.configure(DEBUG=False, ALLOWED_HOSTS=["testserver"], SECRET_KEY="sintetica")
    django.setup()


def _firmado(identificador: str = "msg_1", cuerpo: bytes = CUERPO) -> dict[str, str]:
    firmado = standard_signer(secrets=SECRETOS).sign(
        OutgoingMessage(id=identificador, timestamp=SystemClock().now(), payload=cuerpo)
    )
    assert isinstance(firmado, Signed)
    return dict(firmado.headers)


class Aplicacion:
    """Una aplicación WSGI mínima que recibe webhooks."""

    def __init__(self, max_body_bytes: int = 1024) -> None:
        self.eventos: list[VerifiedEvent] = []
        self.maximo = max_body_bytes
        self.recibir = create_receiver(
            verifier=standard_scheme(secrets=SECRETOS),
            store=MemoryIdempotencyStore(),
            max_body_bytes=max_body_bytes,
        )

    def __call__(self, environ: dict[str, Any], start_response: Any) -> Iterable[bytes]:
        pedido = incoming_request_from_environ(environ, max_body_bytes=self.maximo)
        return wsgi_response(self.recibir.execute(pedido, self.eventos.append), start_response)

    def post(self, cuerpo: bytes, cabeceras: dict[str, str], consulta: str = "") -> tuple[str, bytes]:
        environ: dict[str, Any] = {}
        setup_testing_defaults(environ)
        environ.update(
            REQUEST_METHOD="POST",
            QUERY_STRING=consulta,
            CONTENT_LENGTH=str(len(cuerpo)),
            CONTENT_TYPE="application/json",
            **{"HTTP_" + nombre.upper().replace("-", "_"): valor for nombre, valor in cabeceras.items()},
        )
        environ["wsgi.input"] = self.entrada = io.BytesIO(cuerpo)
        estados: list[str] = []
        salida = self(environ, lambda estado, _cabeceras: estados.append(estado))
        return estados[0], b"".join(salida)


def test_wsgi_recibe_verifica_y_responde() -> None:
    aplicacion = Aplicacion()
    cabeceras = _firmado()

    primera = aplicacion.post(CUERPO, cabeceras, "canal=1")
    segunda = aplicacion.post(CUERPO, cabeceras, "canal=1")
    alterada = aplicacion.post(CUERPO + b" ", _firmado("msg_2"))
    sin_firma = aplicacion.post(CUERPO, {})

    assert [estado for estado, _ in (primera, segunda, alterada, sin_firma)] == [
        "200 OK",
        "200 OK",
        "401 Unauthorized",
        "401 Unauthorized",
    ]
    assert primera[1] == alterada[1] == b""
    assert len(aplicacion.eventos) == 1
    pedido = aplicacion.eventos[0].request
    assert pedido.body == CUERPO
    assert pedido.query == [("canal", "1")]
    assert ("content-type", "application/json") in pedido.headers


def test_wsgi_deja_de_leer_al_pasarse_del_maximo() -> None:
    aplicacion = Aplicacion(max_body_bytes=64)
    enorme = b"x" * 4096

    estado, _ = aplicacion.post(enorme, _firmado(cuerpo=enorme))

    assert estado.startswith("413 ")
    assert aplicacion.entrada.tell() == 65
    assert aplicacion.eventos == []


def test_wsgi_usa_el_cuerpo_que_ya_leyo_el_framework() -> None:
    pedido = incoming_request_from_environ({"HTTP_X_FIRMA": "abc", "QUERY_STRING": "a=1"}, body=CUERPO)

    assert pedido.headers == [("x-firma", "abc")]
    assert pedido.query == [("a", "1")]
    assert pedido.body == CUERPO


@pytest.mark.parametrize("largo", ["", "no-es-un-numero", "-5"])
def test_wsgi_sin_un_largo_valido_no_lee_el_cuerpo(largo: str) -> None:
    entrada = io.BytesIO(CUERPO)

    pedido = incoming_request_from_environ({"CONTENT_LENGTH": largo, "wsgi.input": entrada})

    assert pedido.body == b""
    assert entrada.tell() == 0


def test_wsgi_rechaza_un_maximo_invalido() -> None:
    with pytest.raises(ConfigurationError, match="max_body_bytes"):
        incoming_request_from_environ({}, max_body_bytes=0)


def test_django_recibe_verifica_y_responde() -> None:
    eventos: list[VerifiedEvent] = []
    recibir = create_receiver(verifier=standard_scheme(secrets=SECRETOS), store=MemoryIdempotencyStore())

    def vista(request: HttpRequest) -> HttpResponse:
        return to_response(recibir.execute(to_incoming_request(request), eventos.append))

    fabrica = RequestFactory()

    def post(cuerpo: bytes, cabeceras: dict[str, str], ruta: str = "/webhooks") -> HttpResponse:
        return vista(fabrica.post(ruta, data=cuerpo, content_type="application/json", headers=cabeceras))

    cabeceras = _firmado()
    primera = post(CUERPO, cabeceras, "/webhooks?canal=1")
    segunda = post(CUERPO, cabeceras, "/webhooks?canal=1")
    alterada = post(CUERPO + b" ", _firmado("msg_2"))
    sin_firma = post(CUERPO, {})

    assert [r.status_code for r in (primera, segunda, alterada, sin_firma)] == [200, 200, 401, 401]
    assert [r.content for r in (primera, alterada)] == [b"", b""]
    assert len(eventos) == 1
    assert eventos[0].request.body == CUERPO
    assert eventos[0].request.query == [("canal", "1")]
