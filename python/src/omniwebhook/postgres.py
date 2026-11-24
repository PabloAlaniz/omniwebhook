"""El almacén de reservas, el registro de entregas y la bandeja de salida sobre PostgreSQL.

No necesitan ninguna dependencia.
"""

from omniwebhook.adapters.ledger.postgres import (
    DEFAULT_LEDGER_TABLE,
    AsyncPostgresDeliveryLedger,
    PostgresDeliveryLedger,
    postgres_ledger_schema,
)
from omniwebhook.adapters.outbox.postgres import (
    DEFAULT_OUTBOX_TABLE,
    AsyncPostgresOutbox,
    AsyncPsycopgConnectionClient,
    PostgresOutbox,
    PsycopgConnectionClient,
    postgres_outbox_schema,
)
from omniwebhook.adapters.stores.postgres import (
    DEFAULT_TABLE,
    AsyncPostgresIdempotencyStore,
    AsyncPsycopgClient,
    AsyncSqlClient,
    PostgresIdempotencyStore,
    PsycopgClient,
    SqlClient,
    postgres_store_schema,
)

__all__ = [
    "DEFAULT_LEDGER_TABLE",
    "DEFAULT_OUTBOX_TABLE",
    "DEFAULT_TABLE",
    "AsyncPostgresDeliveryLedger",
    "AsyncPostgresIdempotencyStore",
    "AsyncPostgresOutbox",
    "AsyncPsycopgClient",
    "AsyncPsycopgConnectionClient",
    "AsyncSqlClient",
    "PostgresDeliveryLedger",
    "PostgresIdempotencyStore",
    "PostgresOutbox",
    "PsycopgClient",
    "PsycopgConnectionClient",
    "SqlClient",
    "postgres_ledger_schema",
    "postgres_outbox_schema",
    "postgres_store_schema",
]
