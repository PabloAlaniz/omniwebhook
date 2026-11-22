"""Dobles de prueba para los puertos que dependen del entorno."""

from dataclasses import dataclass, field


@dataclass
class RelojFijo:
    ahora: int = 1_700_000_000

    def now(self) -> int:
        return self.ahora


@dataclass
class TokensFijos:
    token: str = "t-1"

    def next(self) -> str:
        return self.token


@dataclass
class Cronometro:
    """Avanza `paso` milisegundos cada vez que se lo consulta."""

    paso: int = 7
    _ahora: int = field(default=0, init=False)

    def now_ms(self) -> int:
        self._ahora += self.paso
        return self._ahora


@dataclass
class AzarFijo:
    valor: float = 0.0

    def next(self) -> float:
        return self.valor
