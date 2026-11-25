"""Las suscripciones de entrega de Google Cloud Pub/Sub (sección 5.14)."""

from collections.abc import Sequence
from dataclasses import dataclass

from omniwebhook.adapters.schemes.event_keys import pubsub_message_key
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier
from omniwebhook.adapters.schemes.shared_token import TokenDefinition, checked_name
from omniwebhook.application.ports import Verifier
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.incoming_request import IncomingRequest, field_values


@dataclass(frozen=True, slots=True)
class _GooglePubSub(TokenDefinition):
    query: str

    def read(self, request: IncomingRequest) -> Reading | ReadProblem:
        fields = pick_singles({"token": field_values(request.query, self.query)})
        if isinstance(fields, str):
            return fields
        return Reading(
            timestamp=None,
            received=[fields.required["token"]],
            event_key=lambda: pubsub_message_key("google-pubsub", request.body),
        )


def google_pubsub_scheme(*, secrets: Sequence[str], query: str = "token") -> Verifier:
    """Verifica los avisos de una suscripción de entrega de Pub/Sub, como los de Gmail.

    El secreto es el token que va en la URL de entrega de la suscripción, en el parámetro
    `query`. No se verifica el token de identidad (JWT) de la cabecera `authorization`. El
    token no cubre el cuerpo: conviene tratar el aviso como una señal y consultar los cambios
    a la API. Un token en la URL suele quedar en los logs de acceso.
    """
    return scheme_verifier(_GooglePubSub(checked_name("query", query)), secrets=secrets)
