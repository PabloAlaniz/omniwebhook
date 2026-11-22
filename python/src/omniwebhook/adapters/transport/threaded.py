"""Usa un transporte sincrónico desde código asincrónico, en un hilo aparte."""

import asyncio

from omniwebhook.application.ports import HttpTransport, TransportFailure, TransportRequest, TransportResponse


class ThreadedTransport:
    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    async def post(self, request: TransportRequest) -> TransportResponse | TransportFailure:
        return await asyncio.to_thread(self._transport.post, request)
