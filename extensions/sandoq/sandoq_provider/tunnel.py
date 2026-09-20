"""Reverse a Sandoq session's tunnel port into a caller-local TCP service.

The Firecracker launcher exposes a loopback listener inside the guest. A caller
parks WebSocket connections on the session's named ``tunnel`` port; the launcher
pairs each guest connection with one parked connection and copies bytes over
vsock. This module implements the caller half of that protocol.

The relay reuses the official Sandoq client's transport profile. This is
important on Cloud HPC, where both the DSS HTTPS proxy and its mTLS client
certificate are required. The bytes carried inside WebSocket messages remain
application-agnostic.
"""

from __future__ import annotations

import asyncio
import os
import ssl
import threading
import time
import urllib.parse
from typing import Any


def _websocket_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    scheme = {"https": "wss", "http": "ws"}.get(parsed.scheme, parsed.scheme)
    if scheme not in {"ws", "wss"}:
        raise ValueError(f"unsupported Sandoq tunnel URL scheme: {parsed.scheme!r}")
    return urllib.parse.urlunsplit((scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _fallback_ssl_context() -> ssl.SSLContext:
    ca_file = os.environ.get("SANDOQ_TUNNEL_CA_FILE") or os.environ.get("SSL_CERT_FILE")
    context = ssl.create_default_context(cafile=ca_file or None)
    cert_file = os.environ.get("SANDOQ_TUNNEL_CLIENT_CERT") or os.environ.get("SSL_CLIENT_CERT")
    if cert_file:
        key_file = os.environ.get("SANDOQ_TUNNEL_CLIENT_KEY") or os.environ.get("SSL_CLIENT_KEY") or cert_file
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


def _transport() -> tuple[str | None, ssl.SSLContext, Any | None]:
    """Resolve the proxy and mTLS context used by the maintained client.

    ``sandoq_client.Http`` exposes these specifically for callers opening their
    own connections to proxied session ports. Keep a small fallback so the
    standalone diagnostic still works in a conventional environment.
    """

    explicit_proxy = os.environ.get("SANDOQ_TUNNEL_HTTPS_PROXY")
    try:
        from sandoq_client import Http
    except ImportError:
        proxy = explicit_proxy or os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        return proxy, _fallback_ssl_context(), None

    transport = Http()
    proxy = explicit_proxy or transport.proxy_url
    context = transport.ssl_context or _fallback_ssl_context()
    return proxy, context, transport


class SandoqRelayTunnel:
    """Forward a pool of one-session Sandoq streams to a local port.

    Each worker parks one WebSocket, waits for the guest's first bytes, then
    forwards that stream bidirectionally to ``local_host:local_port``. Once a
    stream ends the worker parks a replacement. The pool size is therefore the
    maximum number of concurrent guest TCP connections.
    """

    def __init__(
        self,
        local_port: int,
        *,
        tunnel_url: str,
        local_host: str = "127.0.0.1",
        pool_size: int = 8,
        connect_timeout: float = 30,
        ready_timeout: float = 30,
    ) -> None:
        if not 1 <= local_port <= 65535:
            raise ValueError(f"invalid local port: {local_port}")
        if pool_size < 1:
            raise ValueError("Sandoq tunnel pool size must be positive")
        self.ws_url = _websocket_url(tunnel_url)
        self.local_host = local_host
        self.local_port = local_port
        self.pool_size = pool_size
        self.connect_timeout = connect_timeout
        self.ready_timeout = ready_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_stop: asyncio.Event | None = None
        self._lock = threading.Lock()
        self._started = False
        self._fatal_error: str | None = None
        self.served = 0
        self.errors: list[str] = []

    def _record_error(self, message: str) -> None:
        with self._lock:
            self.errors.append(message)
            if len(self.errors) > 100:
                del self.errors[:-100]

    @staticmethod
    async def _receive_data(websocket: Any, aiohttp: Any) -> bytes:
        while True:
            message = await websocket.receive()
            if message.type == aiohttp.WSMsgType.BINARY:
                return bytes(message.data)
            if message.type == aiohttp.WSMsgType.TEXT:
                return message.data.encode()
            if message.type == aiohttp.WSMsgType.PING:
                await websocket.pong(message.data)
                continue
            if message.type == aiohttp.WSMsgType.PONG:
                continue
            if message.type == aiohttp.WSMsgType.ERROR:
                raise ConnectionError(f"Sandoq tunnel WebSocket failed: {websocket.exception()}")
            raise ConnectionError("Sandoq tunnel WebSocket closed")

    async def _forward_stream(self, websocket: Any, first: bytes, aiohttp: Any) -> None:
        reader, writer = await asyncio.open_connection(self.local_host, self.local_port)
        with self._lock:
            self.served += 1
        if first:
            writer.write(first)
            await writer.drain()

        async def websocket_to_local() -> None:
            while True:
                payload = await self._receive_data(websocket, aiohttp)
                if payload:
                    writer.write(payload)
                    await writer.drain()

        async def local_to_websocket() -> None:
            while payload := await reader.read(65536):
                await websocket.send_bytes(payload)

        tasks = [
            asyncio.create_task(websocket_to_local()),
            asyncio.create_task(local_to_websocket()),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            results = await asyncio.gather(*done, *pending, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            await websocket.close()

    async def _worker(
        self,
        session: Any,
        ready: threading.Event,
        *,
        aiohttp: Any,
        proxy_url: str | None,
        ssl_context: ssl.SSLContext,
    ) -> None:
        assert self._async_stop is not None
        while not self._async_stop.is_set():
            try:
                async with session.ws_connect(
                    self.ws_url,
                    proxy=proxy_url,
                    ssl=ssl_context,
                    autoclose=True,
                    autoping=True,
                ) as websocket:
                    ready.set()
                    first = await self._receive_data(websocket, aiohttp)
                    if self._async_stop.is_set():
                        return
                    await self._forward_stream(websocket, first, aiohttp)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - workers retry transport failures
                if not self._async_stop.is_set():
                    self._record_error(f"{type(error).__name__}: {error}")
            try:
                await asyncio.wait_for(self._async_stop.wait(), timeout=0.5)
            except TimeoutError:
                pass

    async def _run_async(self, ready_events: list[threading.Event]) -> None:
        try:
            import aiohttp
        except ImportError as error:
            raise RuntimeError("SandoqRelayTunnel requires aiohttp (installed with sandoq-client)") from error

        proxy_url, ssl_context, transport = _transport()
        if urllib.parse.urlsplit(self.ws_url).hostname in {"127.0.0.1", "localhost"}:
            proxy_url = None
        timeout = aiohttp.ClientTimeout(total=None, connect=self.connect_timeout, sock_connect=self.connect_timeout)
        self._loop = asyncio.get_running_loop()
        self._async_stop = asyncio.Event()
        if self._stop.is_set():
            self._async_stop.set()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                workers = [
                    asyncio.create_task(
                        self._worker(
                            session,
                            ready,
                            aiohttp=aiohttp,
                            proxy_url=proxy_url,
                            ssl_context=ssl_context,
                        )
                    )
                    for ready in ready_events
                ]
                try:
                    await self._async_stop.wait()
                finally:
                    for worker in workers:
                        worker.cancel()
                    await asyncio.gather(*workers, return_exceptions=True)
        finally:
            if transport is not None:
                await transport.close()
            self._async_stop = None
            self._loop = None

    def _run(self, ready_events: list[threading.Event]) -> None:
        try:
            asyncio.run(self._run_async(ready_events))
        except BaseException as error:  # make startup failures visible to start()
            message = f"{type(error).__name__}: {error}"
            with self._lock:
                self._fatal_error = message
            self._record_error(message)
            for ready in ready_events:
                ready.set()

    def start(self) -> None:
        if self._started:
            raise RuntimeError("Sandoq tunnel is already started")
        self._started = True
        ready_events = [threading.Event() for _ in range(self.pool_size)]
        self._thread = threading.Thread(
            target=self._run,
            args=(ready_events,),
            daemon=True,
            name="sandoq-tunnel-loop",
        )
        self._thread.start()
        deadline = time.monotonic() + self.ready_timeout
        for ready in ready_events:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not ready.wait(remaining):
                self.stop()
                detail = self.errors[-1] if self.errors else "no connection completed"
                raise TimeoutError(f"Sandoq tunnel pool did not become ready: {detail}")
        with self._lock:
            fatal_error = self._fatal_error
        if fatal_error is not None:
            self.stop()
            raise RuntimeError(f"Sandoq tunnel failed to start: {fatal_error}")

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        async_stop = self._async_stop
        if loop is not None and async_stop is not None and loop.is_running():
            loop.call_soon_threadsafe(async_stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def stats(self) -> tuple[int, list[str]]:
        """Return a consistent served/error snapshot for diagnostics."""
        with self._lock:
            return self.served, list(self.errors)

    def __enter__(self) -> SandoqRelayTunnel:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


__all__ = ["SandoqRelayTunnel"]
