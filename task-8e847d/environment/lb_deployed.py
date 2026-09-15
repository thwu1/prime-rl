#!/usr/bin/env python3
"""TCP Load Balancer."""
import asyncio
import hashlib
import json
import logging
import signal
import time

import yaml

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("lb")


class TokenBucket:
    __slots__ = ("rate", "burst", "tokens", "last")

    def __init__(self, rate, burst=None):
        self.rate = float(rate)
        self.burst = float(burst if burst is not None else rate)
        self.tokens = self.burst
        self.last = time.monotonic()

    def consume(self):
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
        self.last = now
        return self.tokens >= 1.0


class Backend:
    def __init__(self, address, port, weight=1):
        self.address = address
        self.port = port
        self.weight = weight
        self.healthy = True
        self.draining = False
        self.active_connections = 0
        self.total_connections = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.consecutive_failures = 0
        self.consecutive_successes = 0

    def to_dict(self):
        return {
            "address": self.address,
            "port": self.port,
            "weight": self.weight,
            "healthy": self.healthy,
            "draining": self.draining,
            "active_connections": self.active_connections,
            "total_connections": self.total_connections,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
        }


class BackendPool:
    def __init__(self, name, cfg):
        self.name = name
        self.backends = [
            Backend(b["address"], b["port"], b.get("weight", 1))
            for b in cfg.get("backends", [])
        ]
        hc = cfg.get("health_check", {})
        self.hc_interval = hc.get("interval_sec", 5)
        self.hc_timeout = hc.get("timeout_sec", 2)
        self.hc_unhealthy_threshold = hc.get("unhealthy_threshold", 3)
        self.hc_healthy_threshold = hc.get("healthy_threshold", 2)
        self._wrr_idx = 0
        self._wrr_remaining = 0

    def _available(self):
        return [b for b in self.backends if b.healthy]

    def select_wrr(self):
        avail = self._available()
        if not avail:
            return None
        if len(avail) == 1:
            return avail[0]
        idx = self._wrr_idx % len(avail)
        backend = avail[idx]
        self._wrr_remaining += 1
        if self._wrr_remaining >= backend.weight:
            self._wrr_remaining = 0
            self._wrr_idx += 1
        return backend

    def select_lc(self):
        avail = self._available()
        if not avail:
            return None
        min_conns = min(b.active_connections for b in avail)
        for b in avail:
            if b.active_connections == min_conns:
                return b
        return avail[0]

    def select_ip_hash(self, src_ip):
        avail = self._available()
        if not avail:
            return None
        h = int(hashlib.md5(src_ip.encode()).hexdigest(), 16)
        return avail[h % len(avail)]


class LoadBalancer:
    def __init__(self, config_path):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.pools = {
            name: BackendPool(name, pcfg)
            for name, pcfg in self.config.get("backend_pools", {}).items()
        }
        self._rate_limiters = {}
        self._running = True

    def _check_rate(self, frontend_cfg, src_ip):
        rl = frontend_cfg.get("rate_limit")
        if not rl:
            return True
        key = (frontend_cfg["name"], src_ip)
        if key not in self._rate_limiters:
            self._rate_limiters[key] = TokenBucket(rl["max_per_sec"])
        return self._rate_limiters[key].consume()

    @staticmethod
    async def _pipe(reader, writer, backend, direction):
        try:
            while True:
                data = await reader.read(16384)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
                if direction == "c2b":
                    backend.bytes_sent += len(data)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError,
                OSError):
            pass
        finally:
            try:
                if writer.can_write_eof():
                    writer.write_eof()
            except (OSError, RuntimeError):
                pass

    async def _handle(self, cr, cw, fc):
        peer = cw.get_extra_info("peername") or ("0.0.0.0", 0)
        src_ip, src_port = peer[0], peer[1]

        if not self._check_rate(fc, src_ip):
            cw.close()
            try:
                await cw.wait_closed()
            except Exception:
                pass
            return

        pool = self.pools.get(fc["backend_pool"])
        if pool is None:
            cw.close()
            return

        algo = fc.get("algorithm", "weighted_round_robin")
        if algo == "least_connections":
            backend = pool.select_lc()
        elif algo == "ip_hash":
            backend = pool.select_ip_hash(src_ip)
        else:
            backend = pool.select_wrr()

        if backend is None:
            cw.close()
            return

        backend.active_connections += 1
        backend.total_connections += 1

        br = bw = None
        try:
            br, bw = await asyncio.wait_for(
                asyncio.open_connection(backend.address, backend.port),
                timeout=5,
            )

            pp = self.config.get("proxy_protocol", {})
            if pp.get("enabled"):
                sock_name = cw.get_extra_info("sockname") or ("0.0.0.0", 0)
                hdr = (
                    f"PROXY TCP4 {src_ip} {sock_name[0]} "
                    f"{fc['port']} {src_port}\r\n"
                )
                bw.write(hdr.encode())
                await bw.drain()
                backend.bytes_sent += len(hdr)

            await asyncio.gather(
                self._pipe(cr, bw, backend, "c2b"),
                self._pipe(br, cw, backend, "b2c"),
                return_exceptions=True,
            )
        except (OSError, asyncio.TimeoutError):
            pass
        finally:
            backend.active_connections -= 1
            for w in (cw, bw):
                if w is not None:
                    try:
                        w.close()
                        await w.wait_closed()
                    except Exception:
                        pass

    async def _health_loop(self, pool):
        while self._running:
            for b in pool.backends:
                try:
                    r, w = await asyncio.wait_for(
                        asyncio.open_connection(b.address, b.port),
                        timeout=pool.hc_timeout,
                    )
                    w.close()
                    await w.wait_closed()
                    b.consecutive_failures = 0
                    b.consecutive_successes += 1
                    if not b.healthy:
                        b.healthy = True
                        logger.info("Backend %s:%s healthy", b.address, b.port)
                except (OSError, asyncio.TimeoutError):
                    b.consecutive_successes = 0
                    b.consecutive_failures += 1
                    if (b.healthy
                            and b.consecutive_failures >= pool.hc_unhealthy_threshold):
                        b.healthy = False
                        logger.info("Backend %s:%s unhealthy", b.address, b.port)
            try:
                await asyncio.sleep(pool.hc_interval)
            except asyncio.CancelledError:
                return

    async def _admin_handler(self, reader, writer):
        try:
            req_line = await asyncio.wait_for(reader.readline(), timeout=5)
            if not req_line:
                writer.close()
                return
            parts = req_line.decode("utf-8", errors="replace").strip().split(" ")
            if len(parts) < 2:
                writer.close()
                return
            method, path = parts[0], parts[1]

            content_length = 0
            while True:
                hdr = await asyncio.wait_for(reader.readline(), timeout=5)
                line = hdr.decode("utf-8", errors="replace").strip()
                if not line:
                    break
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":", 1)[1].strip())

            body = None
            if content_length > 0:
                raw = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=5
                )
                body = json.loads(raw.decode())

            if method == "GET" and path == "/stats":
                resp_body = self._api_stats()
                status = 200
            elif method == "GET" and path == "/backends":
                resp_body = self._api_backends()
                status = 200
            elif method == "POST" and path == "/backends/drain":
                resp_body = self._api_drain(body)
                status = 200
            else:
                resp_body = {"error": "not found"}
                status = 404

            self._http_respond(writer, status, resp_body)
            await writer.drain()
        except Exception as exc:
            try:
                self._http_respond(writer, 500, {"error": str(exc)})
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    def _http_respond(writer, status, body):
        payload = json.dumps(body).encode()
        text = {200: "OK", 404: "Not Found", 500: "Internal Server Error"}.get(
            status, "Error"
        )
        header = (
            f"HTTP/1.1 {status} {text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        writer.write(header + payload)

    def _api_stats(self):
        return {
            pname: [
                {
                    "address": b.address,
                    "port": b.port,
                    "active_connections": b.active_connections,
                    "total_connections": b.total_connections,
                    "bytes_sent": b.bytes_sent,
                    "bytes_received": b.bytes_received,
                }
                for b in pool.backends
            ]
            for pname, pool in self.pools.items()
        }

    def _api_backends(self):
        return {
            pname: [b.to_dict() for b in pool.backends]
            for pname, pool in self.pools.items()
        }

    def _api_drain(self, body):
        if not body:
            return {"error": "empty body"}
        pool = self.pools.get(body.get("pool", ""))
        if pool is None:
            return {"error": "unknown pool"}
        for b in pool.backends:
            if b.address == body.get("address") and b.port == body.get("port"):
                b.draining = True
                return {"status": "draining", "backend": f"{b.address}:{b.port}"}
        return {"error": "backend not found"}

    async def run(self):
        loop = asyncio.get_event_loop()
        stop = asyncio.Event()

        def on_signal():
            self._running = False
            stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, on_signal)

        hc_tasks = []
        for pool in self.pools.values():
            hc_tasks.append(asyncio.create_task(self._health_loop(pool)))

        servers = []
        for fc in self.config.get("frontends", []):
            def _make(fc=fc):
                async def _handler(r, w):
                    await self._handle(r, w, fc)
                return _handler

            srv = await asyncio.start_server(
                _make(), fc["bind"], fc["port"]
            )
            servers.append(srv)
            logger.info(
                "Frontend '%s' on %s:%s [%s -> %s]",
                fc["name"], fc["bind"], fc["port"],
                fc.get("algorithm"), fc["backend_pool"],
            )

        acfg = self.config.get("admin", {})
        admin_srv = await asyncio.start_server(
            self._admin_handler,
            acfg.get("bind", "0.0.0.0"),
            acfg.get("port", 8090),
        )
        servers.append(admin_srv)
        logger.info("Admin API on %s:%s", acfg.get("bind"), acfg.get("port"))

        await stop.wait()

        for t in hc_tasks:
            t.cancel()
        for srv in servers:
            srv.close()
        await asyncio.gather(
            *(srv.wait_closed() for srv in servers), return_exceptions=True
        )
        logger.info("Shutdown complete")


def main():
    lb = LoadBalancer("/app/config.yaml")
    asyncio.run(lb.run())


if __name__ == "__main__":
    main()
