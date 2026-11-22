"""Un servidor HTTP local que anota lo que recibe, con o sin TLS."""

import ssl
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class Recibido:
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Servidor:
    port: int
    recibidos: list[Recibido] = field(default_factory=list)


@contextmanager
def servidor(tls: ssl.SSLContext | None = None) -> Iterator[Servidor]:
    estado = Servidor(port=0)

    class Manejador(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            cuerpo = self.rfile.read(int(self.headers.get("content-length", "0")))
            cabeceras = {nombre.lower(): valor for nombre, valor in self.headers.items()}
            estado.recibidos.append(Recibido(self.path, cabeceras, cuerpo))
            if self.path.startswith("/lento"):
                time.sleep(1.5)
            if self.path.startswith("/tarde"):
                self.send_response(503)
                self.send_header("Retry-After", "120")
            elif self.path.startswith("/mudado"):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{estado.port}/ok")
            else:
                self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    http.daemon_threads = True
    if tls is not None:
        http.socket = tls.wrap_socket(http.socket, server_side=True)
    estado.port = http.server_address[1]
    hilo = threading.Thread(target=http.serve_forever, daemon=True)
    hilo.start()
    try:
        yield estado
    finally:
        http.shutdown()
        http.server_close()
        hilo.join()
