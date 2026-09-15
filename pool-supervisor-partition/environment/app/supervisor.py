"""
Connection Pool Supervisor -- Actor-Model Single-Mailbox Pattern
================================================================

Manages a pool of outgoing HTTP connections using a pattern modeled
after Erlang/OTP's DynamicSupervisor.  A single supervisor task
processes all connection lifecycle operations through a message queue
(the "mailbox").

Connection creation flow:
1. Client calls request_connection(), which enqueues a request message
2. The supervisor picks up the message and spawns a connection task
3. The connection task sends an ACK back to the supervisor's mailbox
4. The supervisor scans the mailbox for the expected ACK, deferring
   non-matching messages for later processing

Configuration is available at /app/config.toml but is not currently
used by the supervisor.  A TelemetryRecorder is available in
/app/telemetry.py for event logging.

"""

import asyncio
import time
import uuid
import logging

logger = logging.getLogger(__name__)

# Cost per deferred message when scanning during selective receive.
SCAN_COST_PER_MSG = 3e-5  # 30 microseconds per message

# Minimum accumulated scan cost before yielding.
SCAN_COST_THRESHOLD = 0.001  # 1ms


class ConnectionPoolSupervisor:
    """
    Manages outgoing HTTP connections via a single-mailbox supervisor.

    All connection requests, ACK messages, and releases flow through one
    asyncio.Queue processed by a single asyncio task.

    Public API:
        start() / stop()
        request_connection(destination, timeout, priority) -> Optional[str]
        release_connection(conn_id)
        get_stats() -> dict
    """

    def __init__(self, name="pool", max_connections=500, connection_timeout=5.0):
        self.name = name
        self.max_connections = max_connections
        self.connection_timeout = connection_timeout

        # Configuration at /app/config.toml is not currently read.
        # Telemetry recorder from /app/telemetry.py is not initialized.
        self._telemetry = None

        # Single mailbox -- every message type goes here
        self._mailbox = asyncio.Queue()

        # Messages pulled from the mailbox during a selective receive that
        # didn't match the target pattern.
        self._deferred = []

        # Connection bookkeeping
        self._connections = {}      # conn_id -> {destination: str}
        self._available = {}        # destination -> [conn_id, ...]
        self._active = 0

        self._running = False
        self._task = None

        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "timeouts": 0,
            "mailbox_peak": 0,
            "deferred_peak": 0,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self):
        """Start the supervisor's message processing loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        """Gracefully stop the supervisor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._telemetry:
            self._telemetry.close()

    async def request_connection(self, destination, timeout=None, priority="normal"):
        """
        Request a connection to *destination*.

        Args:
            destination: Target host/endpoint identifier.
            timeout:     Max seconds to wait (default: self.connection_timeout).
            priority:    "normal" for bulk traffic, "critical" for registry
                         heartbeats and other latency-sensitive operations.

        Returns:
            A connection-ID string on success, or None on failure/timeout.
        """
        timeout = timeout or self.connection_timeout
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        await self._mailbox.put({
            "type": "request",
            "destination": destination,
            "timeout": timeout,
            "priority": priority,
            "future": fut,
            "ts": time.monotonic(),
        })
        try:
            return await asyncio.wait_for(fut, timeout=timeout + 0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._stats["timeouts"] += 1
            return None

    async def release_connection(self, conn_id):
        """Return a connection to the idle pool for reuse."""
        if conn_id in self._connections:
            dest = self._connections[conn_id]["destination"]
            self._available.setdefault(dest, []).append(conn_id)

    def get_stats(self):
        """Return a copy of the current statistics dictionary."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal: single-threaded message processing
    # ------------------------------------------------------------------

    async def _loop(self):
        """Main supervisor loop. Processes messages one at a time."""
        while self._running:
            try:
                # Track peak queue depths for diagnostics
                depth = self._mailbox.qsize() + len(self._deferred)
                if depth > self._stats["mailbox_peak"]:
                    self._stats["mailbox_peak"] = depth
                if len(self._deferred) > self._stats["deferred_peak"]:
                    self._stats["deferred_peak"] = len(self._deferred)

                # Drain deferred queue first, then pull from mailbox
                if self._deferred:
                    msg = self._deferred.pop(0)
                else:
                    msg = await asyncio.wait_for(
                        self._mailbox.get(), timeout=0.1
                    )

                if msg["type"] == "request":
                    await self._handle_request(msg)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _handle_request(self, msg):
        """Process a single connection-request message."""
        self._stats["requests"] += 1
        fut = msg["future"]
        dest = msg["destination"]
        timeout = msg["timeout"]

        if fut.done():
            return  # caller already timed out

        # Try to reuse an idle connection to the same destination
        if dest in self._available and self._available[dest]:
            conn_id = self._available[dest].pop()
            self._stats["successes"] += 1
            if not fut.done():
                fut.set_result(conn_id)
            return

        # Enforce connection cap
        if self._active >= self.max_connections:
            self._stats["failures"] += 1
            if not fut.done():
                fut.set_result(None)
            return

        # Spawn a child task to establish the connection
        conn_id = uuid.uuid4().hex[:8]
        self._active += 1
        asyncio.create_task(self._establish_connection(conn_id, dest))

        # Wait for this child's ACK via selective receive
        ack = await self._selective_receive(conn_id, timeout)

        if ack and not fut.done():
            self._connections[conn_id] = {"destination": dest}
            self._stats["successes"] += 1
            fut.set_result(conn_id)
        else:
            self._active -= 1
            self._stats["failures"] += 1
            if not fut.done():
                fut.set_result(None)

    async def _establish_connection(self, conn_id, destination):
        """
        Simulate TCP+TLS connection establishment to a remote SFU host.
        Posts an ACK back to the supervisor's mailbox on completion.
        """
        latency = 0.005 + (abs(hash(destination)) % 20) * 0.001
        await asyncio.sleep(latency)
        await self._mailbox.put({
            "type": "ack",
            "conn_id": conn_id,
            "ts": time.monotonic(),
        })

    async def _selective_receive(self, target_conn_id, timeout):
        """
        Scan the deferred queue and incoming mailbox for an ACK
        matching *target_conn_id*.  Non-matching messages are kept
        in the deferred queue for later processing.
        """
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            # Phase 1: scan deferred messages for the target ACK
            n = len(self._deferred)
            if n > 0:
                scan_cost = SCAN_COST_PER_MSG * n
                if scan_cost > SCAN_COST_THRESHOLD:
                    await asyncio.sleep(scan_cost)

                for i, m in enumerate(self._deferred):
                    if (m.get("type") == "ack"
                            and m.get("conn_id") == target_conn_id):
                        del self._deferred[i]
                        return m

            # Phase 2: pull the next message from the mailbox
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                m = await asyncio.wait_for(
                    self._mailbox.get(),
                    timeout=min(0.02, remaining),
                )
                if (m.get("type") == "ack"
                        and m.get("conn_id") == target_conn_id):
                    return m
                # Non-matching -- defer for future scan passes
                self._deferred.append(m)
            except asyncio.TimeoutError:
                pass

        return None
