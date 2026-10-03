from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Route:
    name: str
    prefix: str
    upstream: str
    api_key: str


class ProxyState:
    def __init__(self, audit_path: Path) -> None:
        self.audit_path = audit_path
        self.lock = threading.Lock()
        self.counts: dict[str, int] = {}

    def record(self, event: dict[str, Any]) -> None:
        event = {"timestamp": time.time(), **event}
        route = str(event.get("route", "unknown"))
        status = str(event.get("status", "unknown"))
        with self.lock:
            self.counts[f"{route}:{status}"] = self.counts.get(f"{route}:{status}", 0) + 1
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")


class RoutingProxy(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256

    def __init__(self, address: tuple[str, int], route: Route, audit_path: Path, timeout: int) -> None:
        super().__init__(address, ProxyHandler)
        self.route = route
        self.state = ProxyState(audit_path)
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def resolve(self, path: str) -> str:
        parsed = urllib.parse.urlsplit(path)
        if parsed.path != self.route.prefix and not parsed.path.startswith(f"{self.route.prefix}/"):
            raise KeyError(parsed.path)
        suffix = parsed.path.removeprefix(self.route.prefix)
        target = self.route.upstream.rstrip("/") + suffix
        if parsed.query:
            target = f"{target}?{parsed.query}"
        return target


class ProxyHandler(BaseHTTPRequestHandler):
    server: RoutingProxy

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b'{"status":"ok"}\n')
            return
        self._proxy("GET")

    def do_POST(self) -> None:
        self._proxy("POST")

    def _proxy(self, method: str) -> None:
        try:
            target = self.server.resolve(self.path)
        except KeyError:
            self._send(404, b'{"error":"unknown route"}\n')
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {self.server.route.api_key}",
            "Content-Type": self.headers.get("Content-Type", "application/json"),
        }
        session_header = next(
            (name for name in ("x-session-id", "x-litellm-session-id") if self.headers.get(name)),
            None,
        )
        session_id = self.headers.get(session_header) if session_header else None
        if session_header and session_id:
            headers[session_header] = session_id
        detail: dict[str, Any] = {
            "route": self.server.route.name,
            "method": method,
            "path": urllib.parse.urlsplit(self.path).path,
            "session_header": session_header,
            "session_id": session_id,
        }
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                detail["request"] = {
                    key: payload.get(key)
                    for key in (
                        "model",
                        "temperature",
                        "top_p",
                        "max_tokens",
                        "stream",
                        "tool_choice",
                        "parallel_tool_calls",
                        "chat_template_kwargs",
                    )
                    if key in payload
                }
                detail["message_count"] = len(payload.get("messages") or [])
                detail["tool_count"] = len(payload.get("tools") or [])
        request = urllib.request.Request(target, data=body, headers=headers, method=method)
        response_headers: dict[str, str] = {}
        try:
            with self.server.opener.open(request, timeout=self.server.timeout) as response:
                status = response.status
                response_headers = dict(response.headers)
                response_body = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            response_headers = dict(error.headers)
            response_body = error.read()
        except Exception as error:
            self.server.state.record(detail | {"status": 502, "error": f"{type(error).__name__}: {error}"})
            self._send(
                502,
                json.dumps(
                    {
                        "error": {
                            "message": (f"Toolathlon model proxy transport failure: {type(error).__name__}: {error}"),
                            "type": "proxy_transport_error",
                        }
                    }
                ).encode(),
            )
            return
        try:
            response_payload = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response_payload = None
        if isinstance(response_payload, dict):
            choices = response_payload.get("choices") or []
            choice = choices[0] if choices and isinstance(choices[0], dict) else {}
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            detail["response"] = {
                "finish_reason": choice.get("finish_reason"),
                "has_content": bool(message.get("content")),
                "has_reasoning": bool(message.get("reasoning_content")),
                "tool_names": [
                    call.get("function", {}).get("name")
                    for call in message.get("tool_calls") or []
                    if isinstance(call, dict) and isinstance(call.get("function"), dict)
                ],
                "usage": response_payload.get("usage"),
            }
            if response_payload.get("error") is not None:
                detail["response"]["error"] = response_payload["error"]
        self.server.state.record(detail | {"status": status})
        self._send(
            status,
            response_body,
            response_headers.get("Content-Type", "application/json"),
        )

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, format: str, *args: object) -> None:
        return


def start_proxy(
    route: Route,
    audit_path: Path,
    timeout: int,
) -> tuple[RoutingProxy, threading.Thread]:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    server = RoutingProxy(("127.0.0.1", 0), route, audit_path, timeout)
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="toolathlon-model-proxy",
    )
    thread.start()
    return server, thread


def stop_proxy(server: RoutingProxy, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join()


def write_proxy_summary(server: RoutingProxy, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(server.state.counts, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
