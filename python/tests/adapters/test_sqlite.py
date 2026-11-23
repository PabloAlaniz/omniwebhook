"""El almacén de reservas y el registro de entregas sobre SQLite, con `sqlite3` en memoria."""

import sqlite3
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from omniwebhook import AttemptRecord, ClaimRequest, ConfigurationError
from omniwebhook.sqlite import (
    Sqlite3Client,
    SqliteDeliveryLedger,
    SqliteIdempotencyStore,
    sqlite_ledger_schema,
    sqlite_store_schema,
)
from tests.contracts.idempotency_store import CASOS_DE_ALMACEN, reproducir
from tests.support.vectors import Caso, nombre

Base = Callable[[str], sqlite3.Connection]


@pytest.fixture
def base() -> Iterator[Base]:
    """Abre bases en memoria con el esquema indicado y las cierra al terminar el test."""
    abiertas: list[sqlite3.Connection] = []

    def abrir(schema: str) -> sqlite3.Connection:
        conexion = sqlite3.connect(":memory:")
        conexion.executescript(schema)
        abiertas.append(conexion)
        return conexion

    yield abrir
    for conexion in abiertas:
        conexion.close()


@pytest.fixture
def almacen(base: Base) -> SqliteIdempotencyStore:
    return SqliteIdempotencyStore(Sqlite3Client(base(sqlite_store_schema())))


@pytest.fixture
def registro(base: Base) -> SqliteDeliveryLedger:
    return SqliteDeliveryLedger(Sqlite3Client(base(sqlite_ledger_schema())))


@pytest.mark.parametrize("caso", CASOS_DE_ALMACEN, ids=nombre)
def test_cumple_el_contrato(almacen: SqliteIdempotencyStore, caso: Caso) -> None:
    reproducir(almacen, caso["steps"])


def test_crear_el_esquema_dos_veces_no_falla(base: Base) -> None:
    conexion = base(sqlite_store_schema())
    conexion.executescript(sqlite_store_schema())
    conexion.executescript(sqlite_ledger_schema())
    conexion.executescript(sqlite_ledger_schema())


def test_entre_pedidos_simultaneos_uno_solo_reserva(tmp_path: Path) -> None:
    archivo = tmp_path / "reservas.db"
    with closing(sqlite3.connect(archivo)) as conexion:
        conexion.executescript(sqlite_store_schema())

    def reservar(numero: int) -> str:
        # Una conexión por hilo, como varios procesos sobre el mismo archivo.
        conexion = sqlite3.connect(archivo, timeout=10)
        try:
            almacen = SqliteIdempotencyStore(Sqlite3Client(conexion))
            return almacen.claim(ClaimRequest(key="carrera", token=f"t-{numero}", now=1000, lease_seconds=60))
        finally:
            conexion.close()

    with ThreadPoolExecutor(max_workers=8) as hilos:
        resultados = list(hilos.map(reservar, range(20)))

    assert resultados.count("claimed") == 1
    assert resultados.count("in_progress") == 19


def test_purge_expired_borra_solo_lo_vencido(almacen: SqliteIdempotencyStore) -> None:
    almacen.claim(ClaimRequest(key="vieja", token="a", now=1000, lease_seconds=10))
    almacen.claim(ClaimRequest(key="vigente", token="a", now=1000, lease_seconds=500))

    assert almacen.purge_expired(1010) == 1
    assert almacen.claim(ClaimRequest(key="vigente", token="b", now=1011, lease_seconds=10)) == "in_progress"


@pytest.mark.parametrize("tabla", ["Eventos", "a b", "x; DROP TABLE y", "", "main.eventos"])
def test_rechaza_nombres_de_tabla_invalidos(base: Base, tabla: str) -> None:
    cliente = Sqlite3Client(base(""))
    with pytest.raises(ConfigurationError):
        SqliteIdempotencyStore(cliente, table=tabla)
    with pytest.raises(ConfigurationError):
        sqlite_store_schema(tabla)
    with pytest.raises(ConfigurationError):
        SqliteDeliveryLedger(cliente, table=tabla)
    with pytest.raises(ConfigurationError):
        sqlite_ledger_schema(tabla)


PENDIENTE = AttemptRecord(
    message_id="msg_1",
    endpoint_id="ep_1",
    attempt=1,
    at=1_700_000_000,
    delivery_class="retryable",
    state="pending",
    status=503,
    problem=None,
    duration_ms=40,
    next_at=1_700_000_005,
)
BLOQUEADO = AttemptRecord(
    message_id="msg_1",
    endpoint_id="ep_1",
    attempt=2,
    at=1_700_000_005,
    delivery_class="blocked",
    state="blocked",
    status=None,
    problem="blocked_address",
    duration_ms=0,
    next_at=None,
)


def test_el_registro_devuelve_los_intentos_en_orden(registro: SqliteDeliveryLedger) -> None:
    registro.record(PENDIENTE)
    registro.record(BLOQUEADO)
    registro.record(replace(PENDIENTE, endpoint_id="ep_2"))

    assert registro.attempts_of("msg_1", "ep_1") == [PENDIENTE, BLOQUEADO]


def test_purge_before_borra_solo_los_anteriores(registro: SqliteDeliveryLedger) -> None:
    registro.record(PENDIENTE)
    registro.record(BLOQUEADO)

    assert registro.purge_before(BLOQUEADO.at) == 1
    assert registro.attempts_of("msg_1", "ep_1") == [BLOQUEADO]
