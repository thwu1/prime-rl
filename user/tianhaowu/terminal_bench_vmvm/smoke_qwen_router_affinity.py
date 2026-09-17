#!/usr/bin/env python3
"""Exercise vllm-router consistent-hash affinity against local stub workers."""

from __future__ import annotations

import argparse
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
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _handler(worker: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return
            if self.path == "/v1/models":
                self._json({"object": "list", "data": [{"id": "affinity-smoke"}]})
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
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
    args = parser.parse_args()
    if args.workers < 2 or args.sessions < args.workers or args.turns < 2:
        parser.error("workers>=2, sessions>=workers, and turns>=2 are required")
    if not (args.router_site / "vllm_router").is_dir():
        parser.error("--router-site must contain vllm_router")

    servers: list[ThreadingHTTPServer] = []
    threads: list[threading.Thread] = []
    router: subprocess.Popen | None = None
    try:
        for worker in range(args.workers):
            server = ThreadingHTTPServer(("127.0.0.1", _free_port()), _handler(worker))
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
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
