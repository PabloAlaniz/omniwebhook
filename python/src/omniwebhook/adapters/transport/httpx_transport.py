"""Transporte asincrónico sobre httpx.

Se conecta a la dirección validada: pide a la IP, manda el nombre en la cabecera `host` y
lo usa para el TLS, así el certificado se comprueba contra el nombre de la URL.

El tiempo de espera es el plazo del intento completo, no el de cada operación de red.

Las conexiones no se reutilizan. Una conexión abierta para un nombre no debe servir para
otro nombre que resuelve a la misma dirección, porque su certificado es de otro.
"""

import asyncio
import ssl

import httpx

from omniwebhook.application.ports import TransportFailure, TransportRequest, TransportResponse


class AsyncHttpxTransport:
    def __init__(self, *, verify: ssl.SSLContext | bool = True) -> None:
        self._client = httpx.AsyncClient(
            verify=verify,
            trust_env=False,
            follow_redirects=False,
            http2=False,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    async def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
        try:
            url = httpx.URL(request.url)
            if url.scheme not in ("http", "https") or not url.host:
                return TransportFailure("network")
            async with (
                asyncio.timeout(request.timeout_seconds),
                self._client.stream(
                    "POST",
                    url.copy_with(host=request.address),
                    headers={**request.headers, "host": url.netloc.decode("ascii")},
                    content=request.body,
                    timeout=request.timeout_seconds,
                    extensions={"sni_hostname": url.host},
                ) as response,
            ):
                return TransportResponse(response.status_code, response.headers.get("retry-after"))
        except (httpx.TimeoutException, TimeoutError):
            return TransportFailure("timeout")
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            return TransportFailure("network")

    async def aclose(self) -> None:
        """Cierra el cliente. Después no se puede seguir usando."""
        await self._client.aclose()
