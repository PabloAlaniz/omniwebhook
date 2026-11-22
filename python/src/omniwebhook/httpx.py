"""El transporte asincrónico sobre httpx. Necesita `omniwebhook[httpx]`."""

from omniwebhook.adapters.transport.httpx_transport import AsyncHttpxTransport

__all__ = ["AsyncHttpxTransport"]
