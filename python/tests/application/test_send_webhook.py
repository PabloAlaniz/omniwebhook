import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import pytest

from omniwebhook import (
    AsyncMemoryDeliveryLedger,
    AsyncSendWebhook,
    AttemptRecord,
    ConfigurationError,
    Delivery,
    Endpoint,
    IncomingRequest,
    MemoryDeliveryLedger,
    RetryPolicy,
    SendWebhook,
    TransportFailure,
    TransportRequest,
    TransportResponse,
    Verified,
)
from omniwebhook.standard import standard_scheme, standard_signer
from tests.support.dobles import AzarFijo, Cronometro, RelojFijo

AHORA = 1_700_000_000
SECRETOS = ["whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE="]
CUERPO = b'{"type":"pedido.creado"}'
PUBLICA = "93.184.216.34"
URL = "https://hooks.ejemplo.test/entrada"

Respuesta = TransportResponse | TransportFailure | Exception


@dataclass
class Banco:
    """Arma el caso de uso con dobles, en la variante que toque, y lo ejecuta."""

    asincronico: bool
    respuesta: Respuesta = field(default_factory=lambda: TransportResponse(200))
    direcciones: Sequence[str] | Exception = (PUBLICA,)
    opciones: dict[str, Any] = field(default_factory=dict)
    enviados: list[TransportRequest] = field(default_factory=list)
    resueltos: list[str] = field(default_factory=list)
    registrados: list[AttemptRecord] = field(default_factory=list)

    def _post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
        self.enviados.append(request)
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta

    def _resolve(self, host: str) -> Sequence[str]:
        self.resueltos.append(host)
        if isinstance(self.direcciones, Exception):
            raise self.direcciones
        return self.direcciones

    def ejecutar(self, intento: int = 1, url: str = URL) -> AttemptRecord:
        banco = self
        comunes: dict[str, Any] = {
            "signer": standard_signer(secrets=SECRETOS),
            "clock": RelojFijo(AHORA),
            "timer": Cronometro(paso=40),
            "random": AzarFijo(0.0),
            **self.opciones,
        }
        entrega = Delivery(
            endpoint=Endpoint(id="ep_1", url=url), message_id="msg_1", payload=CUERPO, attempt=intento
        )

        if not self.asincronico:

            class Transporte:
                def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
                    return banco._post(request)

            class Resolucion:
                def resolve(self, host: str) -> Sequence[str]:
                    return banco._resolve(host)

            registro = MemoryDeliveryLedger()
            try:
                return SendWebhook(
                    transport=Transporte(), resolver=Resolucion(), ledger=registro, **comunes
                ).execute(entrega)
            finally:
                self.registrados = list(registro.attempts())

        class TransporteAsincronico:
            async def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
                return banco._post(request)

        class ResolucionAsincronica:
            async def resolve(self, host: str) -> Sequence[str]:
                return banco._resolve(host)

        registro_asincronico = AsyncMemoryDeliveryLedger()
        try:
            return asyncio.run(
                AsyncSendWebhook(
                    transport=TransporteAsincronico(),
                    resolver=ResolucionAsincronica(),
                    ledger=registro_asincronico,
                    **comunes,
                ).execute(entrega)
            )
        finally:
            self.registrados = list(registro_asincronico.attempts())


@pytest.fixture(params=[False, True], ids=["sincrónico", "asincrónico"])
def asincronico(request: pytest.FixtureRequest) -> bool:
    return bool(request.param)


def test_entrega_firma_envia_a_la_direccion_validada_y_registra_el_intento(asincronico: bool) -> None:
    banco = Banco(asincronico)

    resultado = banco.ejecutar()

    esperado = AttemptRecord(
        message_id="msg_1",
        endpoint_id="ep_1",
        attempt=1,
        at=AHORA,
        delivery_class="delivered",
        state="delivered",
        status=200,
        problem=None,
        duration_ms=40,
        next_at=None,
    )
    assert resultado == esperado
    assert banco.registrados == [esperado]
    assert banco.resueltos == ["hooks.ejemplo.test"]
    [enviado] = banco.enviados
    assert (enviado.url, enviado.address, enviado.body, enviado.timeout_seconds) == (URL, PUBLICA, CUERPO, 20)


def test_lo_que_envia_lo_verifica_un_receptor_con_el_mismo_secreto(asincronico: bool) -> None:
    banco = Banco(asincronico)

    banco.ejecutar()

    [enviado] = banco.enviados
    verificacion = standard_scheme(secrets=SECRETOS, clock=RelojFijo(AHORA)).verify(
        IncomingRequest(headers=list(enviado.headers.items()), query=[], body=enviado.body)
    )
    assert verificacion == Verified("standard:msg_1", AHORA)
    assert enviado.headers["content-type"] == "application/json"


def test_las_cabeceras_extra_no_pisan_la_firma_ni_el_tipo_de_contenido(asincronico: bool) -> None:
    extra = {"X-Origen": "tienda", "Webhook-Id": "falso", "Content-Type": "text/plain"}
    banco = Banco(asincronico, opciones={"headers": extra, "content_type": "application/cloudevents+json"})

    banco.ejecutar()

    cabeceras = banco.enviados[0].headers
    assert cabeceras["x-origen"] == "tienda"
    assert cabeceras["webhook-id"] == "msg_1"
    assert cabeceras["content-type"] == "application/cloudevents+json"
    assert sorted(cabeceras) == sorted({name.lower() for name in cabeceras})
    assert len(cabeceras) == 5


def test_un_fallo_reintentable_deja_la_entrega_pendiente_con_su_proximo_intento(asincronico: bool) -> None:
    resultado = Banco(asincronico, respuesta=TransportResponse(503)).ejecutar(2)

    assert (resultado.delivery_class, resultado.state, resultado.status) == ("retryable", "pending", 503)
    assert resultado.next_at == AHORA + 300


def test_respeta_retry_after_y_la_variacion(asincronico: bool) -> None:
    banco = Banco(asincronico, respuesta=TransportResponse(429, "1000"), opciones={"random": AzarFijo(0.5)})

    assert banco.ejecutar().next_at == AHORA + 1000 + 50


def test_usa_la_politica_de_reintentos_propia(asincronico: bool) -> None:
    politica = RetryPolicy(schedule=[7], jitter_ratio=0)
    banco = Banco(asincronico, respuesta=TransportResponse(500), opciones={"retry_policy": politica})

    assert banco.ejecutar(1).next_at == AHORA + 7
    agotado = banco.ejecutar(2)
    assert (agotado.state, agotado.next_at) == ("exhausted", None)


def test_despues_del_ultimo_intento_la_entrega_queda_agotada(asincronico: bool) -> None:
    resultado = Banco(asincronico, respuesta=TransportFailure("timeout")).ejecutar(10)

    assert (resultado.delivery_class, resultado.state) == ("retryable", "exhausted")
    assert (resultado.status, resultado.next_at) == (None, None)


@pytest.mark.parametrize(("estado", "clase"), [(410, "gone"), (404, "rejected"), (302, "rejected")])
def test_hay_estados_que_no_se_reintentan(asincronico: bool, estado: int, clase: str) -> None:
    resultado = Banco(asincronico, respuesta=TransportResponse(estado, "5")).ejecutar()

    assert (resultado.delivery_class, resultado.state) == (clase, clase)
    assert (resultado.status, resultado.next_at) == (estado, None)


@pytest.mark.parametrize(
    ("url", "motivo"),
    [
        ("esto no es una url", "invalid_url"),
        ("http://hooks.ejemplo.test/entrada", "scheme"),
        ("https://ana:clave@hooks.ejemplo.test/entrada", "credentials"),
        ("https://127.0.0.1/entrada", "blocked_address"),
    ],
)
def test_la_politica_de_urls_bloquea_sin_enviar_nada(asincronico: bool, url: str, motivo: str) -> None:
    banco = Banco(asincronico)

    resultado = banco.ejecutar(1, url)

    assert (resultado.delivery_class, resultado.state, resultado.problem) == ("blocked", "blocked", motivo)
    assert (resultado.status, resultado.next_at) == (None, None)
    assert banco.enviados == []
    assert banco.registrados == [resultado]


@pytest.mark.parametrize(
    ("direcciones", "motivo"),
    [
        (["10.0.0.5"], "blocked_address"),
        ([PUBLICA, "169.254.169.254"], "blocked_address"),
        ([], "unresolved"),
    ],
)
def test_bloquea_segun_a_donde_resuelve_el_nombre(
    asincronico: bool, direcciones: list[str], motivo: str
) -> None:
    banco = Banco(asincronico, direcciones=direcciones)

    resultado = banco.ejecutar()

    assert (resultado.state, resultado.problem) == ("blocked", motivo)
    assert banco.enviados == []


def test_entrega_a_una_direccion_de_una_red_permitida(asincronico: bool) -> None:
    banco = Banco(
        asincronico, direcciones=["192.168.1.20"], opciones={"allowed_networks": ["192.168.0.0/16"]}
    )

    assert banco.ejecutar().state == "delivered"
    assert banco.enviados[0].address == "192.168.1.20"


def test_una_red_permitida_no_habilita_los_metadatos_de_la_nube(asincronico: bool) -> None:
    banco = Banco(asincronico, direcciones=["169.254.169.254"], opciones={"allowed_networks": ["0.0.0.0/0"]})

    resultado = banco.ejecutar()

    assert (resultado.state, resultado.problem) == ("blocked", "blocked_address")
    assert banco.enviados == []


@pytest.mark.parametrize("redes", [["10.0.0.1/8"], "10.0.0.0/8"])
def test_una_red_permitida_invalida_es_un_error_de_configuracion(asincronico: bool, redes: Any) -> None:
    with pytest.raises(ConfigurationError, match="red"):
        Banco(asincronico, opciones={"allowed_networks": redes}).ejecutar()


def test_con_permiso_expreso_entrega_a_http(asincronico: bool) -> None:
    banco = Banco(asincronico, opciones={"allow_http": True})

    assert banco.ejecutar(1, "http://hooks.ejemplo.test/entrada").state == "delivered"


def test_una_direccion_literal_no_se_resuelve(asincronico: bool) -> None:
    banco = Banco(asincronico)

    banco.ejecutar(1, f"https://{PUBLICA}/entrada")

    assert banco.resueltos == []
    assert banco.enviados[0].address == PUBLICA


def test_si_la_resolucion_falla_cuenta_como_error_de_red_y_se_reintenta(asincronico: bool) -> None:
    banco = Banco(asincronico, direcciones=OSError("SERVFAIL"))

    resultado = banco.ejecutar()

    assert (resultado.delivery_class, resultado.state, resultado.problem) == ("retryable", "pending", None)
    assert resultado.next_at == AHORA + 5
    assert banco.enviados == []


def test_si_el_transporte_lanza_cuenta_como_error_de_red(asincronico: bool) -> None:
    resultado = Banco(asincronico, respuesta=ConnectionResetError("ECONNRESET")).ejecutar()

    assert (resultado.delivery_class, resultado.state) == ("retryable", "pending")


def test_el_registro_nunca_guarda_la_url_de_destino(asincronico: bool) -> None:
    banco = Banco(asincronico)

    banco.ejecutar(1, "https://hooks.ejemplo.test/entrada?token=secreto")

    assert "ejemplo.test" not in json.dumps([asdict(intento) for intento in banco.registrados])


def test_sin_secretos_no_envia_es_un_error_de_configuracion(asincronico: bool) -> None:
    banco = Banco(asincronico, opciones={"signer": standard_signer(secrets=[])})

    with pytest.raises(ConfigurationError, match="no se puede firmar el mensaje: unconfigured"):
        banco.ejecutar()

    assert banco.enviados == []
    assert banco.registrados == []


@pytest.mark.parametrize("intento", [0, -1, 1.5])
def test_rechaza_un_numero_de_intento_invalido(asincronico: bool, intento: int) -> None:
    with pytest.raises(ConfigurationError, match="attempt"):
        Banco(asincronico).ejecutar(intento)


def test_rechaza_un_tiempo_de_espera_invalido_al_construirse(asincronico: bool) -> None:
    with pytest.raises(ConfigurationError, match="timeout_seconds"):
        Banco(asincronico, opciones={"timeout_seconds": 0}).ejecutar()


def test_el_registro_en_memoria_filtra_por_mensaje_y_destino() -> None:
    banco = Banco(asincronico=False)
    intento = banco.ejecutar()
    registro = MemoryDeliveryLedger()
    registro.record(intento)

    assert registro.attempts_of("msg_1", "ep_1") == [intento]
    assert registro.attempts_of("msg_1", "otro") == []


async def test_el_registro_asincronico_en_memoria_filtra_por_mensaje_y_destino() -> None:
    intento = Banco(asincronico=False).ejecutar()
    registro = AsyncMemoryDeliveryLedger()
    await registro.record(intento)

    assert registro.attempts_of("msg_1", "ep_1") == [intento]
    assert registro.attempts_of("otro", "ep_1") == []
