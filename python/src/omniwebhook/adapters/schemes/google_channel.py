"""Los canales de notificación de las APIs de Google Workspace (sección 5.13)."""

from collections.abc import Sequence

from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier
from omniwebhook.adapters.schemes.shared_token import TokenDefinition
from omniwebhook.application.ports import Verifier
from omniwebhook.domain.event_key import event_key
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.incoming_request import IncomingRequest, field_values
from omniwebhook.domain.timestamp import parse_timestamp

_MESSAGE_NUMBER_DIGITS = 20


class _GoogleChannel(TokenDefinition):
    def read(self, request: IncomingRequest) -> Reading | ReadProblem:
        fields = pick_singles(
            {
                "token": field_values(request.headers, "x-goog-channel-token"),
                "channel": field_values(request.headers, "x-goog-channel-id"),
                "number": field_values(request.headers, "x-goog-message-number"),
            }
        )
        if isinstance(fields, str):
            return fields
        channel = fields.required["channel"]
        number = fields.required["number"]
        if parse_timestamp(number, _MESSAGE_NUMBER_DIGITS) is None:
            return "malformed"

        return Reading(
            timestamp=None,
            received=[fields.required["token"]],
            # El número va tal como llegó: es lo que distingue un aviso de otro dentro del canal.
            event_key=lambda: event_key("google-channel", f"{channel}:{number}"),
        )


def google_channel_scheme(*, secrets: Sequence[str]) -> Verifier:
    """Verifica los avisos de un canal de notificación de Google (Calendar, Drive y otras APIs).

    El secreto es el token con el que se creó el canal. El token no cubre el cuerpo ni las
    demás cabeceras: conviene tratar el aviso como una señal y consultar los cambios a la API.
    """
    return scheme_verifier(_GoogleChannel(), secrets=secrets)
