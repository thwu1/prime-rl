"""Process-scoped bridge to the maintained :mod:`sandoq_client` lifecycle API.

The official client is async and owns one aiohttp session.  Prime's synchronous
teardown paths and the OCI pool broker are not, so every process gets one client
on one dedicated event-loop thread.  Async callers submit work to that loop too;
cancelling their await cancels the official-client operation instead of leaving a
lease acquisition running in the background.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import json
import math
import random
import threading
import time
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from sandoq_provider.utils import exception_chain, exception_http_status

if TYPE_CHECKING:
    from sandoq_client import Renewal, SandoqClientProtocol, Session
else:
    SandoqClientProtocol = Any

_T = TypeVar("_T")

# The pinned client bounds DELETE at five 30-second attempts with four
# exponential-backoff sleeps (5, 10, 20, and 40 seconds, each with up to 50%
# jitter). Keep an outer cancellation guard without truncating that contract.
_OFFICIAL_DELETE_BUDGET_SECONDS = 270.0
_CREATE_BACKOFF_CAP_SECONDS = 600.0


@dataclass(frozen=True)
class VerifiedDeletion:
    """Proof that ``get_session`` returned the client's typed missing result."""

    session_id: str
    verified_http_status: int = 404
    cleanup_seconds: float = 0.0
    verification_seconds: float = 0.0


class SandoqDeletionUnconfirmedError(RuntimeError):
    """Deletion did not reach a typed ``session_not_found`` before its deadline."""


class SandoqHttpTransportError(RuntimeError):
    """A proxied-port request failed before a complete HTTP response arrived."""

    def __init__(
        self,
        method: str,
        error_type: str,
        *,
        timed_out: bool,
        delivery_state: str = "unknown",
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"Sandoq HTTP transport failed during {method.upper()} request ({error_type})")
        self.error_type = error_type
        self.timed_out = timed_out
        self.delivery_state = delivery_state
        self.http_status = http_status
        self.retryable = retryable


def _classify_http_transport_error(method: str, error: BaseException) -> SandoqHttpTransportError | None:
    """Classify delivery conservatively without retaining target URLs or headers."""
    import aiohttp

    chain = exception_chain(error)
    timed_out = any(isinstance(item, TimeoutError) for item in chain)
    for item in chain:
        if isinstance(item, aiohttp.ClientHttpProxyError):
            status = item.status if isinstance(item.status, int) else None
            return SandoqHttpTransportError(
                method,
                type(item).__name__,
                timed_out=timed_out,
                delivery_state="not_sent",
                http_status=status,
                retryable=status in {502, 503, 504},
            )
        if isinstance(item, aiohttp.ClientConnectorError):
            return SandoqHttpTransportError(
                method,
                type(item).__name__,
                timed_out=timed_out,
                delivery_state="not_sent",
                retryable=not timed_out,
            )
    for item in chain:
        if (
            isinstance(item, (aiohttp.ClientError, TimeoutError, OSError))
            or getattr(item, "response_received", None) is False
        ):
            status = exception_http_status(item)
            return SandoqHttpTransportError(
                method,
                type(item).__name__,
                timed_out=timed_out,
                delivery_state="unknown",
                http_status=status if isinstance(status, int) else None,
                retryable=False,
            )
    return None


@dataclass(frozen=True)
class SandoqHttpResponse:
    """Normalized response from the official client's pooled HTTP facade."""

    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class SandoqTransportSummary:
    """Redacted view of the official client's selected transport."""

    mode: str
    mtls_available: bool


ClientFactory = Callable[[str, str], SandoqClientProtocol]


def _creation_retry_client_type(base_type: type[Any]) -> type[Any]:
    """Scope capped full-jitter backoff to session creation only."""
    if not hasattr(base_type, "_sleep_with_backoff"):
        return base_type
    in_create: ContextVar[bool] = ContextVar("sandoq_capacity_retry", default=False)

    class ReliableCreationClient(base_type):
        async def create_session(self, *args: Any, **kwargs: Any) -> Any:
            token = in_create.set(True)
            try:
                return await super().create_session(*args, **kwargs)
            finally:
                in_create.reset(token)

        async def _sleep_with_backoff(self, retry_state: Any) -> None:
            if not in_create.get():
                await super()._sleep_with_backoff(retry_state)
                return
            sleep_time = random.uniform(
                0.0,
                min(float(retry_state.backoff), _CREATE_BACKOFF_CAP_SECONDS),
            )
            await asyncio.sleep(sleep_time)
            retry_state.total_wait_time += sleep_time
            retry_state.backoff = min(retry_state.backoff * 2, _CREATE_BACKOFF_CAP_SECONDS)

    ReliableCreationClient.__name__ = f"ReliableCreation{base_type.__name__}"
    return ReliableCreationClient


def _default_client_factory(base_url: str, owner: str) -> Any:
    from sandoq_client import SandoqClient

    reliable_client = _creation_retry_client_type(SandoqClient)
    return reliable_client(base_url, owner=owner)


def _default_not_found_exception() -> type[Exception]:
    from sandoq_client import SandoqSessionNotFoundException

    return SandoqSessionNotFoundException


class SandoqGatewayAdapter:
    """Share one official client and asyncio loop across sync and async callers."""

    def __init__(
        self,
        base_url: str,
        owner: str,
        *,
        client_factory: ClientFactory | None = None,
        not_found_exception: type[Exception] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.owner = owner
        self._client_factory = client_factory or _default_client_factory
        self._not_found_exception = not_found_exception
        self._state_lock = threading.RLock()
        self._loop_ready = threading.Event()
        self._loop_running = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._closing = False
        self._closed = False

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._state_lock:
            if self._closing or self._closed:
                raise RuntimeError("Sandoq gateway adapter is closed")
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run_loop,
                    daemon=True,
                    name="sandoq-client-loop",
                )
                self._thread.start()
        self._loop_ready.wait()
        self._loop_running.wait()
        assert self._loop is not None
        return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._state_lock:
            self._loop = loop
            self._loop_ready.set()
        try:
            loop.call_soon(self._loop_running.set)
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self.base_url, self.owner)
        return self._client

    def _not_found_type(self) -> type[Exception]:
        if self._not_found_exception is None:
            self._not_found_exception = _default_not_found_exception()
        return self._not_found_exception

    def is_session_not_found(self, error: BaseException) -> bool:
        """Whether ``error`` is the official client's authoritative miss."""
        return isinstance(error, self._not_found_type())

    @staticmethod
    def _validate_http_url(url: str) -> None:
        request_url = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        if "/api/v1/sessions" in request_url or "/api/v1/environments" in request_url:
            raise ValueError("Sandoq HTTP facade cannot call lifecycle URLs")

    def _submit(self, operation: Coroutine[Any, Any, _T]) -> concurrent.futures.Future[_T]:
        try:
            loop = self._ensure_loop()
        except BaseException:
            operation.close()
            raise
        return asyncio.run_coroutine_threadsafe(operation, loop)

    async def _await(
        self,
        operation: Coroutine[Any, Any, _T],
        *,
        timeout: float | None = None,
    ) -> _T:
        future = self._submit(operation)
        wrapped = asyncio.wrap_future(future)
        try:
            if timeout is None:
                return await wrapped
            async with asyncio.timeout(timeout):
                return await wrapped
        except BaseException:
            future.cancel()
            raise

    def _wait(
        self,
        operation: Coroutine[Any, Any, _T],
        *,
        timeout: float | None = None,
    ) -> _T:
        future = self._submit(operation)
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise

    async def _request_json(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        headers: dict[str, str] | None,
        timeout: float,
        latest_completion_monotonic: float | None = None,
    ) -> SandoqHttpResponse:
        import aiohttp

        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        client = self._get_client()
        if latest_completion_monotonic is not None:
            if (
                not isinstance(latest_completion_monotonic, (int, float))
                or isinstance(latest_completion_monotonic, bool)
                or not math.isfinite(float(latest_completion_monotonic))
                or time.monotonic() + timeout > latest_completion_monotonic
            ):
                raise SandoqHttpTransportError(
                    method,
                    "AdmissionDeadlineExceeded",
                    timed_out=True,
                    delivery_state="not_sent",
                )
        kwargs: dict[str, Any] = {
            "headers": request_headers,
            "timeout": aiohttp.ClientTimeout(total=timeout),
        }
        if body is not None:
            kwargs["json"] = body
        try:
            async with asyncio.timeout(timeout):
                async with client.http.request(method, url, **kwargs) as response:
                    raw = await response.text(errors="replace")
                    if not raw:
                        normalized: dict[str, Any] = {}
                    else:
                        try:
                            parsed = json.loads(raw)
                        except json.JSONDecodeError:
                            normalized = {"raw": raw}
                        else:
                            normalized = parsed if isinstance(parsed, dict) else {"raw": parsed}
                    return SandoqHttpResponse(status_code=response.status, body=normalized)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            classified = _classify_http_transport_error(method, exc)
            if classified is None:
                raise
            raise classified from None

    async def request_json_async(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
        latest_completion_monotonic: float | None = None,
    ) -> SandoqHttpResponse:
        self._validate_http_url(url)
        return await self._await(self._request_json(method, url, body, headers, timeout, latest_completion_monotonic))

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
        latest_completion_monotonic: float | None = None,
    ) -> SandoqHttpResponse:
        self._validate_http_url(url)
        try:
            return self._wait(
                self._request_json(method, url, body, headers, timeout, latest_completion_monotonic),
                timeout=timeout + 1.0,
            )
        except TimeoutError:
            raise SandoqHttpTransportError(method, "TimeoutError", timed_out=True) from None

    async def _transport_summary(self) -> SandoqTransportSummary:
        http = self._get_client().http
        proxy_url = http.proxy_url
        ssl_context = http.ssl_context
        return SandoqTransportSummary(
            mode="proxy" if proxy_url else "direct",
            mtls_available=ssl_context is not None,
        )

    async def transport_summary_async(self) -> SandoqTransportSummary:
        return await self._await(self._transport_summary())

    def transport_summary(self) -> SandoqTransportSummary:
        return self._wait(self._transport_summary())

    async def _create(
        self,
        environment_name: str,
        lease_duration: str,
        request_id: str,
    ) -> Any:
        client = self._get_client()
        return await client.create_session(
            environment_name=environment_name,
            lease_duration=lease_duration,
            request_id=request_id,
        )

    async def create_session_async(
        self,
        environment_name: str,
        lease_duration: str,
        request_id: str,
        *,
        timeout: float,
    ) -> Session:
        # The official client retries pool-exhaustion 429s for up to eight
        # hours. This outer deadline deliberately preserves our configured
        # acquisition bound while retaining one request ID across its retries.
        return await self._await(
            self._create(environment_name, lease_duration, request_id),
            timeout=timeout,
        )

    def create_session(
        self,
        environment_name: str,
        lease_duration: str,
        request_id: str,
        *,
        timeout: float,
    ) -> Session:
        return self._wait(
            self._create(environment_name, lease_duration, request_id),
            timeout=timeout,
        )

    async def _get(self, session_id: str) -> Any:
        return await self._get_client().get_session(session_id)

    async def get_session_async(self, session_id: str, *, timeout: float | None = None) -> Session:
        return await self._await(self._get(session_id), timeout=timeout)

    def get_session(self, session_id: str, *, timeout: float | None = None) -> Session:
        return self._wait(self._get(session_id), timeout=timeout)

    async def _renew(self, session_id: str, lease_duration: str) -> Any:
        return await self._get_client().renew_lease(session_id, lease_duration)

    async def renew_lease_async(
        self,
        session_id: str,
        lease_duration: str,
        *,
        timeout: float | None = None,
    ) -> Renewal:
        return await self._await(self._renew(session_id, lease_duration), timeout=timeout)

    def renew_lease(
        self,
        session_id: str,
        lease_duration: str,
        *,
        timeout: float | None = None,
    ) -> Renewal:
        return self._wait(self._renew(session_id, lease_duration), timeout=timeout)

    async def _delete_verified(
        self,
        session_id: str,
        timeout: float,
        poll_interval: float,
        prime: bool,
    ) -> VerifiedDeletion:
        client = self._get_client()
        not_found = self._not_found_type()
        started = time.monotonic()
        if prime:
            try:
                await client.get_session(session_id)
            except not_found:
                return VerifiedDeletion(
                    session_id,
                    verification_seconds=time.monotonic() - started,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # The probe's purpose is also to open the official Http facade.
                # An untyped or transient result is not proof of absence, but
                # the idempotent DELETE and typed verification can still run.
                pass

        await client.delete_session(session_id)
        delete_finished = time.monotonic()
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while True:
            try:
                await client.get_session(session_id)
                last_error = None
            except not_found:
                return VerifiedDeletion(
                    session_id,
                    cleanup_seconds=delete_finished - started,
                    verification_seconds=time.monotonic() - delete_finished,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Only the official typed miss is authoritative.  Untyped 404s,
                # 5xx responses, malformed bodies and transport errors are not.
                last_error = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = f": {last_error}" if last_error is not None else ""
                raise SandoqDeletionUnconfirmedError(
                    f"Sandoq session {session_id} deletion was not confirmed by typed HTTP 404{detail}"
                )
            await asyncio.sleep(min(poll_interval, remaining))

    async def delete_session_async(
        self,
        session_id: str,
        *,
        timeout: float,
        poll_interval: float = 0.5,
        prime: bool = True,
        overall_timeout: float | None = None,
    ) -> VerifiedDeletion:
        cancellation_timeout = (
            overall_timeout if overall_timeout is not None else timeout + _OFFICIAL_DELETE_BUDGET_SECONDS
        )
        try:
            return await self._await(
                self._delete_verified(session_id, timeout, poll_interval, prime),
                timeout=cancellation_timeout,
            )
        except TimeoutError as exc:
            raise SandoqDeletionUnconfirmedError(
                f"Sandoq session {session_id} deletion exceeded the official-client "
                f"retry budget plus {timeout:.1f}s verification timeout"
            ) from exc

    def delete_session(
        self,
        session_id: str,
        *,
        timeout: float,
        poll_interval: float = 0.5,
        prime: bool = True,
        overall_timeout: float | None = None,
    ) -> VerifiedDeletion:
        cancellation_timeout = (
            overall_timeout if overall_timeout is not None else timeout + _OFFICIAL_DELETE_BUDGET_SECONDS
        )
        try:
            return self._wait(
                self._delete_verified(session_id, timeout, poll_interval, prime),
                timeout=cancellation_timeout,
            )
        except TimeoutError as exc:
            raise SandoqDeletionUnconfirmedError(
                f"Sandoq session {session_id} deletion exceeded the official-client "
                f"retry budget plus {timeout:.1f}s verification timeout"
            ) from exc

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

    def close(self) -> None:
        """Close aiohttp, flush default OTLP telemetry, and stop the loop once."""
        with self._state_lock:
            if self._closed or self._closing:
                return
            self._closing = True
            loop = self._loop
            thread = self._thread
        if thread is not None and loop is None:
            # The thread may have been started by another caller but not yet
            # published its loop. Do not mark the adapter closed while that
            # thread is about to open the client.
            self._loop_ready.wait(timeout=5.0)
            with self._state_lock:
                loop = self._loop
        try:
            if loop is not None and thread is not None and thread.is_alive():

                async def _close_client() -> None:
                    client = self._client
                    self._client = None
                    if client is not None:
                        await client.close()

                future = asyncio.run_coroutine_threadsafe(_close_client(), loop)
                close_error: BaseException | None = None
                try:
                    future.result(timeout=30.0)
                except BaseException as exc:
                    close_error = exc
                finally:
                    loop.call_soon_threadsafe(loop.stop)
                if thread is not None and thread is not threading.current_thread():
                    thread.join(timeout=30.0)
                if close_error is not None:
                    raise close_error
        finally:
            with self._state_lock:
                self._closed = True
                self._closing = False


_adapters_lock = threading.Lock()
_adapters: dict[tuple[str, str], SandoqGatewayAdapter] = {}


def get_gateway_adapter(base_url: str, owner: str) -> SandoqGatewayAdapter:
    key = (base_url.rstrip("/"), owner)
    with _adapters_lock:
        adapter = _adapters.get(key)
        if adapter is None or adapter._closing or adapter._closed:
            adapter = SandoqGatewayAdapter(*key)
            _adapters[key] = adapter
        return adapter


def close_gateway_adapters() -> None:
    with _adapters_lock:
        adapters = list(_adapters.values())
        _adapters.clear()
    for adapter in adapters:
        adapter.close()


atexit.register(close_gateway_adapters)


__all__ = [
    "SandoqDeletionUnconfirmedError",
    "SandoqGatewayAdapter",
    "SandoqHttpResponse",
    "SandoqHttpTransportError",
    "SandoqTransportSummary",
    "VerifiedDeletion",
    "close_gateway_adapters",
    "get_gateway_adapter",
]
