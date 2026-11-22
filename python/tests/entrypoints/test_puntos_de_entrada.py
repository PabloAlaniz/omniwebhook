import base64
import time
from collections.abc import Sequence

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from omniwebhook import (
    AsyncMemoryDeliveryLedger,
    AsyncMemoryIdempotencyStore,
    Delivery,
    Endpoint,
    HttpClientTransport,
    IncomingRequest,
    MemoryDeliveryLedger,
    MemoryIdempotencyStore,
    OutgoingMessage,
    Reception,
    Signed,
    TransportFailure,
    TransportRequest,
    TransportResponse,
    VerifiedEvent,
    create_async_receiver,
    create_async_sender,
    create_receiver,
    create_sender,
    incoming_request,
    incoming_request_from_scope,
)
from omniwebhook.adapters.clock import MonotonicTimer, SystemClock
from omniwebhook.adapters.tokens import SystemRandom, random_message_id, random_tokens
from omniwebhook.standard import standard_scheme, standard_signer
from omniwebhook.starlette import to_incoming_request, to_response
from tests.support.servidor import servidor

SECRETOS = ["whsec_" + base64.b64encode(b"omniwebhook-secreto-sintetico-01").decode()]
CUERPO = b'{"type":"pedido.creado"}'


def _firmado(identificador: str = "msg_1") -> dict[str, str]:
    firmado = standard_signer(secrets=SECRETOS).sign(
        OutgoingMessage(id=identificador, timestamp=SystemClock().now(), payload=CUERPO)
    )
    assert isinstance(firmado, Signed)
    return dict(firmado.headers)


def test_incoming_request_acepta_pares_o_diccionarios_y_la_consulta_como_texto() -> None:
    desde_pares = incoming_request(headers=[("X-A", "1"), ("X-A", "2")], query=[("data.id", "5")], body=b"x")
    desde_texto = incoming_request(
        headers={"X-A": "1"}, query="data.id=5&data.id=6&vacio=&t=a%20b", body=b"x"
    )

    assert desde_pares == IncomingRequest(
        headers=[("X-A", "1"), ("X-A", "2")], query=[("data.id", "5")], body=b"x"
    )
    assert desde_texto.headers == [("X-A", "1")]
    assert desde_texto.query == [("data.id", "5"), ("data.id", "6"), ("vacio", ""), ("t", "a b")]
    assert incoming_request(headers={}, body=b"").query == []
    assert incoming_request(headers={}, query={"data.id": "5"}, body=b"").query == [("data.id", "5")]


def test_incoming_request_exige_el_cuerpo_crudo() -> None:
    with pytest.raises(TypeError, match="cuerpo crudo"):
        incoming_request(headers={}, body='{"ya":"interpretado"}')  # type: ignore[arg-type]


def test_desde_un_scope_asgi_conserva_las_cabeceras_repetidas() -> None:
    scope = {
        "type": "http",
        "headers": [(b"webhook-id", b"a"), (b"webhook-id", b"b"), (b"x-latin", b"caf\xe9")],
        "query_string": b"data.id=5&data.id=6",
    }

    pedido = incoming_request_from_scope(scope, b"cuerpo")

    assert pedido.headers == [("webhook-id", "a"), ("webhook-id", "b"), ("x-latin", "café")]
    assert pedido.query == [("data.id", "5"), ("data.id", "6")]
    assert pedido.body == b"cuerpo"
    assert incoming_request_from_scope({"type": "http"}, b"").headers == []


def test_los_valores_por_defecto_del_sistema() -> None:
    assert abs(SystemClock().now() - int(time.time())) <= 1
    assert MonotonicTimer().now_ms() <= MonotonicTimer().now_ms()
    assert 0 <= SystemRandom().next() < 1
    assert random_tokens.next() != random_tokens.next()
    identificador = random_message_id()
    assert identificador.startswith("msg_")
    assert "." not in identificador
    assert identificador != random_message_id()


def test_create_receiver_usa_el_reloj_del_sistema_y_tokens_aleatorios() -> None:
    recibir = create_receiver(verifier=standard_scheme(secrets=SECRETOS), store=MemoryIdempotencyStore())
    eventos: list[VerifiedEvent] = []
    pedido = incoming_request(headers=_firmado(), body=CUERPO)

    assert recibir.execute(pedido, eventos.append) == Reception("ok", "standard:msg_1")
    assert recibir.execute(pedido, eventos.append) == Reception("duplicate", "standard:msg_1")
    assert len(eventos) == 1


async def test_create_async_receiver_usa_el_reloj_del_sistema_y_tokens_aleatorios() -> None:
    recibir = create_async_receiver(
        verifier=standard_scheme(secrets=SECRETOS), store=AsyncMemoryIdempotencyStore()
    )
    eventos: list[VerifiedEvent] = []

    async def procesar(evento: VerifiedEvent) -> None:
        eventos.append(evento)

    pedido = incoming_request(headers=_firmado(), body=CUERPO)

    assert await recibir.execute(pedido, procesar) == Reception("ok", "standard:msg_1")
    assert await recibir.execute(pedido, procesar) == Reception("duplicate", "standard:msg_1")
    assert len(eventos) == 1


def test_la_politica_de_urls_no_deja_llegar_a_la_maquina_local() -> None:
    registro = MemoryDeliveryLedger()
    enviar = create_sender(signer=standard_signer(secrets=SECRETOS), ledger=registro, allow_http=True)
    with servidor() as local:
        resultado = enviar.execute(
            Delivery(
                endpoint=Endpoint("ep_1", f"http://localhost:{local.port}/ok"),
                message_id="msg_1",
                payload=CUERPO,
            )
        )

        assert (resultado.state, resultado.problem) == ("blocked", "blocked_address")
        assert local.recibidos == []


def test_de_punta_a_punta_lo_que_se_envia_se_recibe_una_sola_vez() -> None:
    recibir = create_receiver(verifier=standard_scheme(secrets=SECRETOS), store=MemoryIdempotencyStore())
    eventos: list[VerifiedEvent] = []

    registro = MemoryDeliveryLedger()
    with servidor() as local:
        # La política de URLs no deja entregar a la máquina local, así que el test fija a
        # mano la dirección validada y usa el transporte de verdad.
        class HaciaElServidorLocal:
            def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
                local_request = TransportRequest(
                    url=request.url,
                    address="127.0.0.1",
                    headers=request.headers,
                    body=request.body,
                    timeout_seconds=request.timeout_seconds,
                )
                return HttpClientTransport().post(local_request)

        class ResuelvePublica:
            def resolve(self, host: str) -> Sequence[str]:
                return ["93.184.216.34"]

        enviar = create_sender(
            signer=standard_signer(secrets=SECRETOS),
            ledger=registro,
            transport=HaciaElServidorLocal(),
            resolver=ResuelvePublica(),
            allow_http=True,
        )
        entrega = Delivery(
            endpoint=Endpoint("ep_1", f"http://hooks.ejemplo.test:{local.port}/entrada"),
            message_id="msg_e2e",
            payload=CUERPO,
        )

        primero = enviar.execute(entrega)
        segundo = enviar.execute(entrega)

        assert (primero.state, segundo.state) == ("delivered", "delivered")
        resultados = [
            recibir.execute(incoming_request(headers=r.headers, body=r.body), eventos.append)
            for r in local.recibidos
        ]

    assert [r.outcome for r in resultados] == ["ok", "duplicate"]
    assert [e.event_key for e in eventos] == ["standard:msg_e2e"]
    assert len(registro.attempts_of("msg_e2e", "ep_1")) == 2


async def test_create_async_sender_arma_el_envio_con_los_adaptadores_por_defecto() -> None:
    registro = AsyncMemoryDeliveryLedger()
    enviar = create_async_sender(signer=standard_signer(secrets=SECRETOS), ledger=registro)

    resultado = await enviar.execute(
        Delivery(endpoint=Endpoint("ep_1", "https://127.0.0.1/entrada"), message_id="msg_1", payload=CUERPO)
    )

    assert (resultado.state, resultado.problem) == ("blocked", "blocked_address")
    assert registro.attempts() == [resultado]


async def test_create_async_sender_resuelve_con_el_sistema() -> None:
    enviar = create_async_sender(
        signer=standard_signer(secrets=SECRETOS), ledger=AsyncMemoryDeliveryLedger(), allow_http=True
    )

    resultado = await enviar.execute(
        Delivery(endpoint=Endpoint("ep_1", "http://localhost:9/entrada"), message_id="msg_1", payload=CUERPO)
    )

    assert (resultado.state, resultado.problem) == ("blocked", "blocked_address")


def _aplicacion(eventos: list[VerifiedEvent]) -> Starlette:
    recibir = create_async_receiver(
        verifier=standard_scheme(secrets=SECRETOS), store=AsyncMemoryIdempotencyStore()
    )

    async def procesar(evento: VerifiedEvent) -> None:
        eventos.append(evento)

    async def entrada(request: Request) -> Response:
        return to_response(await recibir.execute(await to_incoming_request(request), procesar))

    return Starlette(routes=[Route("/webhooks", entrada, methods=["POST"])])


def test_starlette_recibe_verifica_y_responde() -> None:
    eventos: list[VerifiedEvent] = []
    cliente = TestClient(_aplicacion(eventos))
    cabeceras = _firmado()

    primera = cliente.post("/webhooks?canal=1", content=CUERPO, headers=cabeceras)
    segunda = cliente.post("/webhooks?canal=1", content=CUERPO, headers=cabeceras)
    alterada = cliente.post("/webhooks", content=CUERPO + b" ", headers=_firmado("msg_2"))
    sin_firma = cliente.post("/webhooks", content=CUERPO)

    assert [r.status_code for r in (primera, segunda, alterada, sin_firma)] == [200, 200, 401, 401]
    assert [r.content for r in (primera, alterada)] == [b"", b""]
    assert len(eventos) == 1
    assert eventos[0].request.body == CUERPO
    assert eventos[0].request.query == [("canal", "1")]


def test_starlette_informa_una_cabecera_repetida_como_ambigua() -> None:
    eventos: list[VerifiedEvent] = []
    cliente = TestClient(_aplicacion(eventos))
    cabeceras = [*_firmado().items(), ("webhook-id", "otro")]

    respuesta = cliente.post("/webhooks", content=CUERPO, headers=cabeceras)

    assert respuesta.status_code == 401
    assert eventos == []
