"""Ayudas para Starlette y FastAPI. Necesita `omniwebhook[starlette]`."""

from omniwebhook.entrypoints.starlette import to_incoming_request, to_response

__all__ = ["to_incoming_request", "to_response"]
