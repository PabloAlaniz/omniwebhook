"""Contra el emulador de Firestore. Necesita `OMNIWEBHOOK_FIRESTORE_EMULATOR` (host:puerto)."""

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from omniwebhook import ClaimRequest, CompleteRequest, ConfigurationError
from omniwebhook.firestore import AsyncFirestoreIdempotencyStore, FirestoreIdempotencyStore
from tests.contracts.idempotency_store import CASOS_DE_ALMACEN, reproducir, reproducir_async
from tests.support.vectors import Caso, nombre

pytestmark = pytest.mark.integration
PROYECTO = "omniwebhook-prueba"
_ANONIMO = AnonymousCredentials()  # type: ignore[no-untyped-call]


@pytest.fixture(autouse=True)
def emulador(monkeypatch: pytest.MonkeyPatch) -> None:
    host = os.environ.get("OMNIWEBHOOK_FIRESTORE_EMULATOR")
    if host is None:
        pytest.fail("Falta OMNIWEBHOOK_FIRESTORE_EMULATOR: estos tests necesitan el emulador de Firestore.")
    # Con esta variable el cliente habla con el emulador y nunca con un proyecto de verdad.
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", host)


@pytest.fixture
def coleccion() -> str:
    return f"eventos_{uuid.uuid4().hex}"


@pytest.fixture
def cliente(emulador: None) -> firestore.Client:
    return firestore.Client(project=PROYECTO, credentials=_ANONIMO)


@pytest.fixture
def almacen(cliente: firestore.Client, coleccion: str) -> FirestoreIdempotencyStore:
    return FirestoreIdempotencyStore(cliente, collection=coleccion)


@pytest.fixture
def almacen_asincronico(emulador: None, coleccion: str) -> AsyncFirestoreIdempotencyStore:
    cliente = firestore.AsyncClient(project=PROYECTO, credentials=_ANONIMO)
    return AsyncFirestoreIdempotencyStore(cliente, collection=coleccion)


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
def test_cumple_el_contrato(almacen: FirestoreIdempotencyStore, caso: Caso) -> None:
    reproducir(almacen, caso["steps"])


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
async def test_la_variante_asincrona_cumple_el_contrato(
    almacen_asincronico: AsyncFirestoreIdempotencyStore, caso: Caso
) -> None:
    await reproducir_async(almacen_asincronico, caso["steps"])


def _pedido(numero: int) -> ClaimRequest:
    return ClaimRequest(key="carrera", token=f"t-{numero}", now=1000, lease_seconds=60)


def test_entre_pedidos_simultaneos_por_la_misma_clave_uno_solo_la_reserva(
    almacen: FirestoreIdempotencyStore,
) -> None:
    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(lambda n: almacen.claim(_pedido(n)), range(12)))

    assert sorted(resultados) == ["claimed"] + ["in_progress"] * 11


async def test_entre_tareas_simultaneas_por_la_misma_clave_una_sola_la_reserva(
    almacen_asincronico: AsyncFirestoreIdempotencyStore,
) -> None:
    resultados = await asyncio.gather(*(almacen_asincronico.claim(_pedido(n)) for n in range(12)))

    assert sorted(resultados) == ["claimed"] + ["in_progress"] * 11


def test_una_clave_con_barras_o_muy_larga_se_guarda_igual(almacen: FirestoreIdempotencyStore) -> None:
    for clave in ("standard:a/b/c", "standard:" + "x" * 3000, "standard:..", "standard:__reservado__"):
        assert almacen.claim(ClaimRequest(key=clave, token="a", now=1000, lease_seconds=60)) == "claimed"
        assert almacen.claim(ClaimRequest(key=clave, token="b", now=1001, lease_seconds=60)) == "in_progress"


def test_guarda_la_fecha_de_vencimiento_para_la_politica_de_ttl(
    almacen: FirestoreIdempotencyStore, cliente: firestore.Client, coleccion: str
) -> None:
    almacen.claim(ClaimRequest(key="standard:msg_1", token="a", now=1_700_000_000, lease_seconds=60))
    almacen.complete(
        CompleteRequest(key="standard:msg_1", token="a", now=1_700_000_010, retention_seconds=100)
    )

    [documento] = [d.to_dict() for d in cliente.collection(coleccion).stream()]

    assert documento is not None
    assert documento["key"] == "standard:msg_1"
    assert documento["state"] == "completed"
    assert documento["expires_at"] == 1_700_000_110
    assert int(documento["expire_time"].timestamp()) == 1_700_000_110


@pytest.mark.parametrize("coleccion_invalida", ["", "a/b", "__interna__", "."])
def test_rechaza_un_nombre_de_coleccion_invalido(cliente: firestore.Client, coleccion_invalida: str) -> None:
    with pytest.raises(ConfigurationError, match="collection"):
        FirestoreIdempotencyStore(cliente, collection=coleccion_invalida)
