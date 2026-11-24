"""Esquemas de token compartido: el emisor no firma, manda un secreto tal cual (sección 5.12)."""

from collections.abc import Sequence
from dataclasses import dataclass

from omniwebhook.adapters.schemes.event_keys import body_fingerprint
from omniwebhook.adapters.schemes.scheme_verifier import Reading, ReadProblem, scheme_verifier, text_key
from omniwebhook.application.ports import Verifier
from omniwebhook.domain.errors import ConfigurationError
from omniwebhook.domain.event_key import event_key
from omniwebhook.domain.fields import pick_singles
from omniwebhook.domain.incoming_request import IncomingRequest, field_values


class TokenDefinition:
    """Lo común a los esquemas de token: el secreto es el token y lo esperado es el secreto mismo.

    Así el recorrido de la sección 4.1 (el orden, la rotación y la comparación en tiempo
    constante) es el mismo que el de los esquemas que firman. Cada esquema define `read`.
    """

    def key_of(self, secret: str) -> bytes | None:
        return text_key(secret)

    def expected(self, key: bytes, reading: Reading, request: IncomingRequest) -> str:
        return key.decode("utf-8")


def checked_name(option: str, value: object) -> str:
    """Un nombre de cabecera, de parámetro o de esquema: un texto que no está en blanco."""
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"{option} no puede estar vacío")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class _SharedToken(TokenDefinition):
    name: str
    field: str
    """La cabecera o el parámetro de la URL que trae el token."""
    in_query: bool
    id_header: str | None

    def read(self, request: IncomingRequest) -> Reading | ReadProblem:
        token = field_values(request.query if self.in_query else request.headers, self.field)
        fields = pick_singles(
            {"token": token},
            {"id": [] if self.id_header is None else field_values(request.headers, self.id_header)},
        )
        if isinstance(fields, str):
            return fields
        identifier = fields.optional["id"]

        def key() -> str:
            if identifier is not None:
                return event_key(self.name, identifier)
            return body_fingerprint(self.name, request.body)

        return Reading(timestamp=None, received=[fields.required["token"]], event_key=key)


def shared_token_scheme(
    *,
    secrets: Sequence[str],
    header: str | None = None,
    query: str | None = None,
    name: str = "shared-token",
    id_header: str | None = None,
) -> Verifier:
    """Verifica a un emisor que manda un token secreto, tal cual, en una cabecera o en la URL.

    Hay que dar exactamente uno entre `header` y `query`. `name` es el nombre del esquema en
    la clave del evento. Sin `id_header`, la clave es la huella del cuerpo.

    El token no cubre el cuerpo ni las demás cabeceras: conviene tratar el aviso como una
    señal de cambio y consultar el recurso al emisor antes de actuar. Un token en la URL
    suele quedar en los logs de acceso.
    """
    if (header is None) == (query is None):
        raise ConfigurationError("hay que configurar header o query, y sólo uno de los dos")
    place, field = ("header", header) if query is None else ("query", query)
    definition = _SharedToken(
        name=checked_name("name", name),
        field=checked_name(place, field),
        in_query=query is not None,
        id_header=None if id_header is None else checked_name("id_header", id_header),
    )
    return scheme_verifier(definition, secrets=secrets)
