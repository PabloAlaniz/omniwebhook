import socket
from typing import Any

import pytest

from omniwebhook import AsyncSystemDnsResolver, SystemDnsResolver

Respuesta = list[tuple[Any, Any, Any, str, tuple[Any, ...]]]


def _respuesta(*direcciones: str) -> Respuesta:
    return [
        (
            socket.AF_INET6 if ":" in direccion else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (direccion, 0, 0, 0) if ":" in direccion else (direccion, 0),
        )
        for direccion in direcciones
    ]


def test_devuelve_las_direcciones_sin_repetir_y_en_orden() -> None:
    pedidos: list[str] = []

    def buscar(host: str) -> Respuesta:
        pedidos.append(host)
        return _respuesta("93.184.216.34", "2606:4700:4700::1111", "93.184.216.34")

    direcciones = SystemDnsResolver(lookup=buscar).resolve("hooks.ejemplo.test")

    assert direcciones == ["93.184.216.34", "2606:4700:4700::1111"]
    assert pedidos == ["hooks.ejemplo.test"]


def test_un_nombre_que_no_existe_da_una_lista_vacia() -> None:
    def buscar(host: str) -> Respuesta:
        raise socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided, or not known")

    assert SystemDnsResolver(lookup=buscar).resolve("no-existe.ejemplo.test") == []


def test_otra_falla_de_resolucion_se_propaga() -> None:
    def buscar(host: str) -> Respuesta:
        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure in name resolution")

    with pytest.raises(socket.gaierror):
        SystemDnsResolver(lookup=buscar).resolve("hooks.ejemplo.test")


def test_pregunta_al_sistema() -> None:
    direcciones = SystemDnsResolver().resolve("localhost")

    assert set(direcciones) & {"127.0.0.1", "::1"}


async def test_la_variante_asincrona_hace_lo_mismo() -> None:
    async def buscar(host: str) -> Respuesta:
        return _respuesta("93.184.216.34", "93.184.216.34")

    async def no_existe(host: str) -> Respuesta:
        raise socket.gaierror(socket.EAI_NONAME, "no existe")

    async def falla(host: str) -> Respuesta:
        raise socket.gaierror(socket.EAI_AGAIN, "falla pasajera")

    assert await AsyncSystemDnsResolver(lookup=buscar).resolve("hooks.ejemplo.test") == ["93.184.216.34"]
    assert await AsyncSystemDnsResolver(lookup=no_existe).resolve("no-existe.ejemplo.test") == []
    with pytest.raises(socket.gaierror):
        await AsyncSystemDnsResolver(lookup=falla).resolve("hooks.ejemplo.test")
    assert set(await AsyncSystemDnsResolver().resolve("localhost")) & {"127.0.0.1", "::1"}
