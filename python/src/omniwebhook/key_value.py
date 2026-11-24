"""El almacén de reservas sobre cualquier almacén clave-valor con vencimiento.

Trae un cliente en memoria y uno para DynamoDB. Para otro almacén, se implementa
`KeyValueClient`. No importa la librería de ningún servicio.
"""

from omniwebhook.adapters.stores.key_value import (
    DEFAULT_KEY_VALUE_GRACE_SECONDS,
    DEFAULT_KEY_VALUE_PREFIX,
    AsyncDynamoDbTableClient,
    AsyncKeyValueClient,
    AsyncKeyValueIdempotencyStore,
    AsyncMemoryKeyValueClient,
    DynamoDbTableClient,
    Guarantee,
    KeyValueClient,
    KeyValueIdempotencyStore,
    KeyValueRecord,
    MemoryKeyValueClient,
)

__all__ = [
    "DEFAULT_KEY_VALUE_GRACE_SECONDS",
    "DEFAULT_KEY_VALUE_PREFIX",
    "AsyncDynamoDbTableClient",
    "AsyncKeyValueClient",
    "AsyncKeyValueIdempotencyStore",
    "AsyncMemoryKeyValueClient",
    "DynamoDbTableClient",
    "Guarantee",
    "KeyValueClient",
    "KeyValueIdempotencyStore",
    "KeyValueRecord",
    "MemoryKeyValueClient",
]
