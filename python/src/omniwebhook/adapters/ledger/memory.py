"""Registro de entregas en memoria. Sirve para tests y para un único proceso."""

from omniwebhook.application.ports import AttemptRecord
from omniwebhook.domain.endpoint_health import FailureSummary, summarize_failures


class MemoryDeliveryLedger:
    def __init__(self) -> None:
        self._records: list[AttemptRecord] = []

    def record(self, attempt: AttemptRecord) -> None:
        self._records.append(attempt)

    def attempts(self) -> list[AttemptRecord]:
        """Todos los intentos, en el orden en que se registraron."""
        return list(self._records)

    def attempts_of(self, message_id: str, endpoint_id: str) -> list[AttemptRecord]:
        """Los intentos de un mensaje hacia un destino."""
        return [r for r in self._records if r.message_id == message_id and r.endpoint_id == endpoint_id]

    def failures_of(self, endpoint_id: str, since: int) -> FailureSummary:
        """El resumen de fallos de un destino desde `since` (sección 8.5)."""
        return summarize_failures((r for r in self._records if r.endpoint_id == endpoint_id), since)


class AsyncMemoryDeliveryLedger:
    """El mismo registro para código asincrónico. Registrar no espera, así que no bloquea."""

    def __init__(self) -> None:
        self._ledger = MemoryDeliveryLedger()

    async def record(self, attempt: AttemptRecord) -> None:
        self._ledger.record(attempt)

    def attempts(self) -> list[AttemptRecord]:
        return self._ledger.attempts()

    def attempts_of(self, message_id: str, endpoint_id: str) -> list[AttemptRecord]:
        return self._ledger.attempts_of(message_id, endpoint_id)

    async def failures_of(self, endpoint_id: str, since: int) -> FailureSummary:
        return self._ledger.failures_of(endpoint_id, since)
