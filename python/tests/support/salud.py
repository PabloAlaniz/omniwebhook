"""Lo que comparten los tests de la salud de los destinos: los vectores de `entregar/salud`."""

from typing import Any

from omniwebhook import AttemptRecord, EndpointHealth, FailureSummary, HealthPolicy
from tests.support.vectors import Caso, casos

CASOS_DE_SALUD = casos("entregar/salud")


def politica(caso: Caso) -> HealthPolicy:
    return HealthPolicy(**caso["policy"]) if "policy" in caso else HealthPolicy()


def resumen_esperado(caso: Caso) -> FailureSummary:
    return FailureSummary(**caso["expected"]["summary"])


def salud_esperada(caso: Caso) -> EndpointHealth:
    return EndpointHealth(**caso["expected"]["health"])


def intento(destino: str, numero: int, datos: dict[str, Any]) -> AttemptRecord:
    clase = datos["delivery_class"]
    return AttemptRecord(
        message_id=f"msg_{numero}",
        endpoint_id=destino,
        attempt=1,
        at=datos["at"],
        delivery_class=clase,
        state="pending" if clase == "retryable" else clase,
        status=None,
        problem=None,
        duration_ms=1,
        next_at=datos["at"] + 5 if clase == "retryable" else None,
    )


def intentos_mezclados(caso: Caso) -> list[AttemptRecord]:
    """Los intentos del caso para `ep_1`, con los de otro destino en el medio, que no cuentan."""
    mezclados = []
    for numero, datos in enumerate(caso["attempts"]):
        mezclados.append(intento("ep_otro", numero, {"at": datos["at"], "delivery_class": "gone"}))
        mezclados.append(intento("ep_1", numero, datos))
    return mezclados
