#!/usr/bin/env python3
"""Exercise vllm-router consistent-hash affinity against local stub workers."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from verifiers.v1.clients import EvalClientConfig, resolve_client


class _TrackingServer(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


class _ConcurrencyTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.active = 0
        self.peak = 0
        self.started = 0

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.started += 1
            self.peak = max(self.peak, self.active)

    def leave(self) -> None:
        with self.lock:
            self.active -= 1

    def snapshot(self) -> tuple[int, int, int]:
        with self.lock:
            return self.active, self.peak, self.started


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _handler(worker: int, tracker: _ConcurrencyTracker) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            if self.path == "/v1/models":
                self._json({"object": "list", "data": [{"id": "affinity-smoke"}]})
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            tracker.enter()
            try:
                try:
                    body_probe = json.loads(body).get("concurrency_probe") == "hold"
                except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                    body_probe = False
                if self.headers.get("X-Concurrency-Probe") == "hold" or body_probe:
                    tracker.release.wait(timeout=30)
                self._json(
                    {
                        "id": "affinity-smoke",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "affinity-smoke",
                        "worker": worker,
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                )
            finally:
                tracker.leave()

        def _json(self, value: object) -> None:
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


async def _concurrency_probe(
    chat_url: str,
    config_path: Path,
    tracker: _ConcurrencyTracker,
    expected_concurrency: int,
    total_requests: int,
) -> None:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    client_config = dict(config["client"])
    client_config["base_url"] = chat_url.rsplit("/chat/completions", 1)[0]
    parsed = EvalClientConfig.model_validate(client_config)
    if (
        config.get("max_concurrent") != 64
        or parsed.max_connections != expected_concurrency
        or parsed.max_keepalive_connections != expected_concurrency
    ):
        raise RuntimeError("production client concurrency contract mismatch")
    client = resolve_client(parsed)

    async def request(index: int) -> int:
        response = await client.http.post(
            chat_url,
            headers={"X-Session-ID": f"concurrency-smoke-{index:04d}", "X-Concurrency-Probe": "hold"},
            json={
                "model": "affinity-smoke",
                "messages": [{"role": "user", "content": "smoke"}],
                "max_tokens": 1,
                "concurrency_probe": "hold",
            },
        )
        return response.status_code

    tasks = [asyncio.create_task(request(index)) for index in range(total_requests)]
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            active, peak, started = tracker.snapshot()
            if active == expected_concurrency and peak == expected_concurrency and started == expected_concurrency:
                break
            if peak > expected_concurrency or started > expected_concurrency:
                raise RuntimeError("provider connection pool exceeded its configured bound")
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("provider connection pool did not fill to its configured bound")
        await asyncio.sleep(0.5)
        active, peak, started = tracker.snapshot()
        if (active, peak, started) != (expected_concurrency,) * 3:
            raise RuntimeError("requests escaped the provider connection pool while responses were held")
        tracker.release.set()
        statuses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
        if statuses != [200] * total_requests:
            raise RuntimeError("concurrency probe request failed")
        _active, peak, started = tracker.snapshot()
        if peak != expected_concurrency or started != total_requests:
            raise RuntimeError("concurrency probe did not exercise the complete request wave")
    finally:
        tracker.release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await client.http.aclose()


def _request(url: str, session_id: str | None = None) -> dict:
    if url.endswith("/models"):
        request = urllib.request.Request(url)
    else:
        request = urllib.request.Request(
            url,
            data=json.dumps(
                {
                    "model": "affinity-smoke",
                    "messages": [{"role": "user", "content": "smoke"}],
                    "max_tokens": 1,
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Session-ID": session_id or "",
            },
        )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--router-site", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sessions", type=int, default=64)
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--eval-config", type=Path, required=True)
    parser.add_argument("--provider-concurrency", type=int, default=32)
    parser.add_argument("--total-requests", type=int, default=64)
    args = parser.parse_args()
    if args.workers < 2 or args.sessions < args.workers or args.turns < 2:
        parser.error("workers>=2, sessions>=workers, and turns>=2 are required")
    if args.provider_concurrency != 32 or args.total_requests != 64 or not args.eval_config.is_file():
        parser.error("the production gate requires provider concurrency 32 and 64 requests")
    if not (args.router_site / "vllm_router").is_dir():
        parser.error("--router-site must contain vllm_router")
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(variable, None)

    servers: list[ThreadingHTTPServer] = []
    threads: list[threading.Thread] = []
    router: subprocess.Popen | None = None
    tracker = _ConcurrencyTracker()
    try:
        for worker in range(args.workers):
            server = _TrackingServer(("127.0.0.1", _free_port()), _handler(worker, tracker))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            servers.append(server)
            threads.append(thread)
        router_port = _free_port()
        metrics_port = _free_port()
        with tempfile.NamedTemporaryFile(prefix="qwen-affinity-router-", suffix=".log") as log:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(args.router_site)
            command = [
                sys.executable,
                "-c",
                "from vllm_router.launch_router import main; main()",
                "--policy",
                "consistent_hash",
                "--request-id-headers",
                "x-session-id",
                "--host",
                "127.0.0.1",
                "--port",
                str(router_port),
                "--prometheus-host",
                "127.0.0.1",
                "--prometheus-port",
                str(metrics_port),
                "--worker-startup-timeout-secs",
                "30",
                "--request-timeout-secs",
                "30",
                "--disable-retries",
                "--max-concurrent-requests",
                str(args.provider_concurrency),
                "--queue-size",
                str(args.total_requests - args.provider_concurrency),
                "--queue-timeout-secs",
                "30",
                "--log-level",
                "warning",
                "--worker-urls",
                *(f"http://127.0.0.1:{server.server_port}" for server in servers),
            ]
            router = subprocess.Popen(
                command,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            models_url = f"http://127.0.0.1:{router_port}/v1/models"
            for _attempt in range(120):
                if router.poll() is not None:
                    parser.error("router exited during affinity smoke startup")
                try:
                    _request(models_url)
                    break
                except (OSError, urllib.error.URLError, json.JSONDecodeError):
                    time.sleep(0.25)
            else:
                parser.error("router did not become ready")

            chat_url = f"http://127.0.0.1:{router_port}/v1/chat/completions"
            asyncio.run(
                _concurrency_probe(
                    chat_url,
                    args.eval_config,
                    tracker,
                    args.provider_concurrency,
                    args.total_requests,
                )
            )
            assignments: dict[str, set[int]] = {}
            for session_number in range(args.sessions):
                session_id = f"affinity-smoke-{session_number:04d}"
                assignments[session_id] = {int(_request(chat_url, session_id)["worker"]) for _turn in range(args.turns)}
            unstable = sum(len(workers) != 1 for workers in assignments.values())
            used_workers = {next(iter(workers)) for workers in assignments.values() if len(workers) == 1}
            if unstable or len(used_workers) < 2:
                parser.error(f"affinity smoke failed: unstable_sessions={unstable} used_workers={len(used_workers)}")
    finally:
        if router is not None and router.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(router.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                router.wait(timeout=10)
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
    print(
        json.dumps(
            {
                "ok": True,
                "policy": "consistent_hash",
                "request_id_headers": ["x-session-id"],
                "workers": args.workers,
                "sessions": args.sessions,
                "turns": args.turns,
                "unstable_sessions": unstable,
                "used_workers": len(used_workers),
                "provider_concurrency": args.provider_concurrency,
                "total_requests": args.total_requests,
                "peak_backend_requests": tracker.snapshot()[1],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
