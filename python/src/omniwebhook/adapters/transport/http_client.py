"""Transporte sobre la biblioteca estándar, sin dependencias.

Se conecta a la dirección validada y no vuelve a resolver el nombre; el certificado se
comprueba contra el nombre de la URL. Cada intento usa una conexión nueva.

El tiempo de espera es el plazo del intento completo: al vencer se corta la conexión,
aunque el servidor siga mandando de a un byte.
"""

import contextlib
import http.client
import socket
import ssl
import threading
from urllib.parse import quote, urlsplit

from omniwebhook.application.ports import TransportFailure, TransportRequest, TransportResponse

# Lo que puede ir tal cual en la ruta y la consulta; el resto se codifica.
_SAFE_IN_TARGET = "/?#[]@!$&'()*+,;=:%-._~"


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int | None, *, address: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self, host: str, port: int | None, *, address: str, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address
        self._tls = context

    def connect(self) -> None:
        plain = socket.create_connection((self._address, self.port), self.timeout)
        try:
            self.sock = self._tls.wrap_socket(plain, server_hostname=self.host)
        except BaseException:
            plain.close()
            raise


class HttpClientTransport:
    """Hace el POST con `http.client`. No usa proxies ni sigue redirecciones."""

    def __init__(self, *, ssl_context: ssl.SSLContext | None = None) -> None:
        self._ssl_context = ssl_context or ssl.create_default_context()

    def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
        try:
            connection, target = self._connection(request)
        except ValueError:
            return TransportFailure("network")
        expired = threading.Event()

        def expire() -> None:
            # Cortar el socket destraba la lectura en curso; el intento termina como vencido.
            expired.set()
            sock = connection.sock
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

        deadline = threading.Timer(request.timeout_seconds, expire)
        deadline.daemon = True
        deadline.start()
        try:
            connection.request("POST", target, body=request.body, headers=dict(request.headers))
            response = connection.getresponse()
            if expired.is_set():
                return TransportFailure("timeout")
            return TransportResponse(response.status, response.getheader("retry-after"))
        except TimeoutError:
            return TransportFailure("timeout")
        except (OSError, http.client.HTTPException, ValueError):
            return TransportFailure("timeout" if expired.is_set() else "network")
        finally:
            deadline.cancel()
            connection.close()

    def _connection(self, request: TransportRequest) -> tuple[http.client.HTTPConnection, str]:
        parts = urlsplit(request.url)
        host, port = parts.hostname, parts.port
        if not host:
            raise ValueError("la URL no tiene nombre de host")
        target = quote(parts.path or "/", safe=_SAFE_IN_TARGET)
        if parts.query:
            target += "?" + quote(parts.query, safe=_SAFE_IN_TARGET)

        if parts.scheme == "https":
            return (
                _PinnedHTTPSConnection(
                    host,
                    port,
                    address=request.address,
                    timeout=request.timeout_seconds,
                    context=self._ssl_context,
                ),
                target,
            )
        if parts.scheme == "http":
            return (
                _PinnedHTTPConnection(host, port, address=request.address, timeout=request.timeout_seconds),
                target,
            )
        raise ValueError("el esquema de la URL no es http ni https")
