"""Ayudas para Django. Necesita `omniwebhook[django]`."""

from omniwebhook.entrypoints.django import to_incoming_request, to_response

__all__ = ["to_incoming_request", "to_response"]
