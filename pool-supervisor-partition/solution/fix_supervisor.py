"""
Fixed Connection Pool Supervisor -- PartitionSupervisor Pattern
================================================================

Replaces the single-mailbox supervisor with K independent partitions,
each running its own asyncio task and message queue.  Requests are
distributed across partitions by hashing the destination, and
critical-priority traffic (service registry heartbeats) is routed to
a dedicated partition to prevent starvation.

Reads configuration from /app/config.toml:
  - [partitioning] for partition count and hash algorithm
  - [priority] for critical traffic isolation
  - [telemetry] for SQLite event recording

This eliminates the cascading bottleneck by:
  1. Reducing per-partition deferred queue from O(N) to O(N/K)
  2. Enabling parallel request processing across K concurrent loops
  3. Isolating critical traffic from bulk RPC connections

Inspired by Elixir 1.14's PartitionSupervisor and the fix described
in Discord's voice outage postmortem.

"""

import asyncio
import hashlib
import os
import time
import tomllib
import uuid
import logging

logger = logging.getLogger(__name__)

SCAN_COST_PER_MSG = 3e-5
SCAN_COST_THRESHOLD = 0.001

CONFIG_PATH = "/app/config.toml"


def _load_config():
    """Load pool configuration from TOML file."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


class _Partition:
    """
    A single supervisor partition with its own mailbox and processing loop.

    Architecturally identical to the original ConnectionPoolSupervisor,
    but each instance handles only a fraction of the total traffic.
    """

    def __init__(self, name, max_connections, connection_timeout, telemetry=None):
        self.name = name
        self.max_connections = max_connections
        self.connection_timeout = connection_timeout
        self._telemetry = telemetry
        self._mailbox = asyncio.Queue()
        self._deferred = []
        self._connections = {}
        self._available = {}
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

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def request_connection(self, destination, timeout=None):
        timeout = timeout or self.connection_timeout
        if self._telemetry:
            self._telemetry.record_event(
                "request", destination=destination, partition_id=self.name
            )
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        await self._mailbox.put({
            "type": "request",
            "destination": destination,
            "timeout": timeout,
            "future": fut,
            "ts": time.monotonic(),
        })
        try:
            return await asyncio.wait_for(fut, timeout=timeout + 0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._stats["timeouts"] += 1
            return None

    async def release_connection(self, conn_id):
        if conn_id in self._connections:
            dest = self._connections[conn_id]["destination"]
            self._available.setdefault(dest, []).append(conn_id)

    def get_stats(self):
        return dict(self._stats)

    # -- internal ---------------------------------------------------------

    async def _loop(self):
        while self._running:
            try:
                depth = self._mailbox.qsize() + len(self._deferred)
                if depth > self._stats["mailbox_peak"]:
                    self._stats["mailbox_peak"] = depth
                if len(self._deferred) > self._stats["deferred_peak"]:
                    self._stats["deferred_peak"] = len(self._deferred)

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
        self._stats["requests"] += 1
        fut = msg["future"]
        dest = msg["destination"]
        timeout = msg["timeout"]

        if fut.done():
            return

        if dest in self._available and self._available[dest]:
            conn_id = self._available[dest].pop()
            self._stats["successes"] += 1
            if self._telemetry:
                self._telemetry.record_event(
                    "connect", connection_id=conn_id, destination=dest,
                    partition_id=self.name, success=True
                )
            if not fut.done():
                fut.set_result(conn_id)
            return

        if self._active >= self.max_connections:
            self._stats["failures"] += 1
            if not fut.done():
                fut.set_result(None)
            return

        conn_id = uuid.uuid4().hex[:8]
        self._active += 1
        asyncio.create_task(self._establish_connection(conn_id, dest))

        ack = await self._selective_receive(conn_id, timeout)

        if ack and not fut.done():
            self._connections[conn_id] = {"destination": dest}
            self._stats["successes"] += 1
            if self._telemetry:
                self._telemetry.record_event(
                    "connect", connection_id=conn_id, destination=dest,
                    partition_id=self.name, success=True
                )
            fut.set_result(conn_id)
        else:
            self._active -= 1
            self._stats["failures"] += 1
            if not fut.done():
                fut.set_result(None)

    async def _establish_connection(self, conn_id, destination):
        latency = 0.005 + (abs(hash(destination)) % 20) * 0.001
        await asyncio.sleep(latency)
        await self._mailbox.put({
            "type": "ack",
            "conn_id": conn_id,
            "ts": time.monotonic(),
        })

    async def _selective_receive(self, target_conn_id, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
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
                self._deferred.append(m)
            except asyncio.TimeoutError:
                pass
        return None


class ConnectionPoolSupervisor:
    """
    Partitioned connection pool supervisor.

    Reads /app/config.toml for architecture and telemetry settings.
    Distributes requests across independent partitions using consistent
    hashing on the destination string. Critical-priority requests are
    routed to a dedicated partition to prevent starvation during burst
    traffic.

    Same public API as the original single-supervisor implementation.
    """

    def __init__(self, name="pool", max_connections=500, connection_timeout=5.0):
        self.name = name
        self.max_connections = max_connections
        self.connection_timeout = connection_timeout

        # Load configuration
        self._config = _load_config()

        # Initialize telemetry
        self._telemetry = None
        tel_config = self._config.get("telemetry", {})
        if tel_config.get("enabled", False):
            from telemetry import TelemetryRecorder
            db_path = tel_config.get("db_path", "/app/telemetry.db")
            self._telemetry = TelemetryRecorder(db_path)

        # Partitioning configuration
        part_config = self._config.get("partitioning", {})
        prio_config = self._config.get("priority", {})

        if part_config.get("enabled", False):
            num_partitions = part_config.get("num_partitions", 16)
        else:
            num_partitions = 1

        self._num_partitions = num_partitions
        self._use_dedicated_critical = prio_config.get(
            "dedicated_partition", False
        )

        total_parts = num_partitions + (
            1 if self._use_dedicated_critical else 0
        )
        max_per = max(10, max_connections // total_parts + 1)

        self._partitions = [
            _Partition(
                f"{name}-p{i}", max_per, connection_timeout, self._telemetry
            )
            for i in range(num_partitions)
        ]

        if self._use_dedicated_critical:
            self._critical_partition = _Partition(
                f"{name}-critical", max_per, connection_timeout,
                self._telemetry
            )
        else:
            self._critical_partition = None

    async def start(self):
        tasks = [p.start() for p in self._partitions]
        if self._critical_partition:
            tasks.append(self._critical_partition.start())
        await asyncio.gather(*tasks)

    async def stop(self):
        tasks = [p.stop() for p in self._partitions]
        if self._critical_partition:
            tasks.append(self._critical_partition.stop())
        await asyncio.gather(*tasks)
        if self._telemetry:
            self._telemetry.close()

    async def request_connection(self, destination, timeout=None,
                                 priority="normal"):
        if priority == "critical" and self._critical_partition:
            return await self._critical_partition.request_connection(
                destination, timeout
            )
        idx = self._hash_destination(destination)
        return await self._partitions[idx].request_connection(
            destination, timeout
        )

    async def release_connection(self, conn_id):
        for p in self._partitions:
            if conn_id in p._connections:
                await p.release_connection(conn_id)
                return
        if (self._critical_partition
                and conn_id in self._critical_partition._connections):
            await self._critical_partition.release_connection(conn_id)

    def get_stats(self):
        stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "timeouts": 0,
            "mailbox_peak": 0,
            "deferred_peak": 0,
        }
        all_parts = list(self._partitions)
        if self._critical_partition:
            all_parts.append(self._critical_partition)
        for p in all_parts:
            s = p.get_stats()
            for k in ("requests", "successes", "failures", "timeouts"):
                stats[k] += s[k]
            for k in ("mailbox_peak", "deferred_peak"):
                stats[k] = max(stats[k], s[k])
        return stats

    def _hash_destination(self, destination):
        h = int(hashlib.md5(destination.encode()).hexdigest(), 16)
        return h % self._num_partitions
