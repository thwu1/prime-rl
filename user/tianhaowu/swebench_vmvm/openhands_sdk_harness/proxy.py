#!/usr/bin/env python3

import argparse
import copy
import hashlib
import http.cookiejar
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DROP_PARAMS = {
    "max_tokens",
    "max_completion_tokens",
    "max_input_tokens_per_task",
    "no_rebuild",
}
HASH_PREFIX_LEN = 256
THINK = re.compile(r"^\s*<think>(.*?)</think>", re.DOTALL)


class TurnBudgetExceeded(Exception):
    pass


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _content_key(content: Any) -> str | None:
    text = _content_text(content)[:HASH_PREFIX_LEN]
    if not text.strip():
        return None
    return "h:" + hashlib.sha256(text.encode()).hexdigest()[:16]


def _message_keys(message: dict[str, Any]) -> list[str]:
    keys = []
    for tool_call in message.get("tool_calls") or []:
        if not isinstance(tool_call, dict):
            continue
        tool_call_id = tool_call.get("id")
        if isinstance(tool_call_id, str) and tool_call_id:
            keys.append(f"c:{tool_call_id}")
    if not keys:
        content_key = _content_key(message.get("content"))
        if content_key:
            keys.append(content_key)
    return keys


def _wrap_reasoning(content: Any, reasoning: str) -> Any:
    prefix = f"<think>{reasoning}</think>\n"
    if isinstance(content, list):
        return [{"type": "text", "text": prefix}, *content]
    if isinstance(content, str):
        return prefix + content
    return prefix


def _content_to_str(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content) if content else ""


class ProxyState:
    def __init__(self, system_prompt: str, audit_path: Path) -> None:
        self.system_prompt = system_prompt
        self.system_prompt_sha256 = hashlib.sha256(system_prompt.encode()).hexdigest()
        self.audit_path = audit_path
        self.client_id = str(uuid.uuid4())
        self.lock = threading.Lock()
        self.reasoning: OrderedDict[str, str] = OrderedDict()
        self.requests = 0
        self.responses = 0
        self.reasoning_responses = 0
        self.replay_hits = 0
        self.replay_misses = 0
        self.tool_call_responses = 0
        self.http_errors = 0
        self.transport_errors = 0
        self.request_details: list[dict[str, Any]] = []
        self.started_at = time.time()

    def _store_reasoning(self, key: str, value: str) -> None:
        if key in self.reasoning:
            self.reasoning.move_to_end(key)
        self.reasoning[key] = value
        while len(self.reasoning) > 10_000:
            self.reasoning.popitem(last=False)

    def transform_request(self, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        body = copy.deepcopy(raw)
        with self.lock:
            self.requests += 1
            turn = self.requests
            if turn > 200:
                self._write_audit()
                raise TurnBudgetExceeded(
                    f"Turn budget exhausted: {turn}/200 turns used. "
                    "The evaluation framework has terminated this agent session."
                )

            messages = body.get("messages")
            if not isinstance(messages, list):
                messages = []
            non_system = [
                message for message in messages if isinstance(message, dict) and message.get("role") != "system"
            ]
            messages = [{"role": "system", "content": self.system_prompt}, *non_system]

            remaining = 200 - turn
            if turn >= 190:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"[SYSTEM] URGENT: Turn {turn}/200 — only {remaining} turn(s) left. "
                            "You MUST provide your final answer NOW. Do not start new work."
                        ),
                    }
                )
            elif turn >= 160:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"[SYSTEM] Turn {turn}/200 — {remaining} turns remaining. "
                            "Begin wrapping up: finish current work and prepare your final answer."
                        ),
                    }
                )

            system_parts = []
            final_messages = []
            for message in messages:
                if message.get("role") == "system":
                    text = _content_to_str(message.get("content"))
                    if text:
                        system_parts.append(text)
                else:
                    final_messages.append(message)
            if system_parts:
                final_messages.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})

            request_hits = 0
            request_misses = 0
            for message in final_messages:
                if message.get("role") != "assistant":
                    continue
                cached = None
                for key in _message_keys(message):
                    cached = self.reasoning.get(key)
                    if cached:
                        self.reasoning.move_to_end(key)
                        break
                if cached is None:
                    if message.get("tool_calls") or _content_text(message.get("content")):
                        request_misses += 1
                    continue
                if not _content_text(message.get("content")).lstrip().startswith("<think>"):
                    message["content"] = _wrap_reasoning(message.get("content"), cached)
                    request_hits += 1
            self.replay_hits += request_hits
            self.replay_misses += request_misses

            body["messages"] = final_messages
            for key in DROP_PARAMS:
                body.pop(key, None)
            body["temperature"] = 1.0
            body["top_p"] = 0.95
            body["chat_template_kwargs"] = {"enable_thinking": True}
            body["skip_special_tokens"] = False

            tool_names = []
            for tool in body.get("tools") or []:
                if not isinstance(tool, dict):
                    continue
                function = tool.get("function")
                if isinstance(function, dict) and isinstance(function.get("name"), str):
                    tool_names.append(function["name"])

            detail = {
                "turn": turn,
                "message_count": len(final_messages),
                "assistant_messages": sum(message.get("role") == "assistant" for message in final_messages),
                "tool_definitions": len(body.get("tools") or []),
                "tool_names": sorted(tool_names),
                "replay_hits": request_hits,
                "replay_misses": request_misses,
                "system_prompt_sha256": hashlib.sha256(
                    _content_to_str(final_messages[0].get("content", "")).encode()
                ).hexdigest()
                if final_messages and final_messages[0].get("role") == "system"
                else None,
                "model": body.get("model"),
                "temperature": body.get("temperature"),
                "top_p": body.get("top_p"),
                "enable_thinking": (body.get("chat_template_kwargs") or {}).get("enable_thinking"),
                "skip_special_tokens": body.get("skip_special_tokens"),
                "forbidden_params_present": sorted(DROP_PARAMS.intersection(body)),
            }
            self.request_details.append(detail)
            self._write_audit()
        return body, detail

    def transform_response(self, body: dict[str, Any], detail: dict[str, Any], status: int) -> dict[str, Any]:
        with self.lock:
            if status >= 400:
                self.http_errors += 1
            else:
                self.responses += 1
            reasoning_found = 0
            tool_calls_found = 0
            for choice in body.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if not isinstance(message, dict):
                    continue
                if "content" in message and message["content"] is None:
                    message["content"] = ""
                if "reasoning_content" not in message:
                    if isinstance(message.get("reasoning"), str):
                        message["reasoning_content"] = message.pop("reasoning")
                    elif isinstance(message.get("content"), str):
                        match = THINK.match(message["content"])
                        if match:
                            message["reasoning_content"] = match.group(1).strip()
                            message["content"] = message["content"][match.end() :].lstrip()
                reasoning = message.get("reasoning_content")
                tool_calls = message.get("tool_calls") or []
                tool_calls_found += len(tool_calls)
                if isinstance(reasoning, str) and reasoning.strip():
                    reasoning_found += 1
                    for key in _message_keys(message):
                        self._store_reasoning(key, reasoning)
            self.reasoning_responses += reasoning_found
            self.tool_call_responses += tool_calls_found
            detail["status"] = status
            detail["reasoning_responses"] = reasoning_found
            detail["tool_calls"] = tool_calls_found
            self._write_audit()
        return body

    def record_transport_error(self, detail: dict[str, Any], error: Exception) -> None:
        with self.lock:
            self.transport_errors += 1
            detail["status"] = 502
            detail["transport_error"] = f"{type(error).__name__}: {error}"
            self._write_audit()

    def _write_audit(self) -> None:
        payload = {
            "schema_version": 2,
            "official_recipe": {
                "nemo_gym_commit": "354babf7e3554fcd006807c86e80ef476aec9408",
                "nemo_evaluator_commit": "230c8411fff82fa581195b7d088d7fb67d3bc98c",
                "openhands_sdk_version": "1.17.0",
                "max_iterations": 200,
                "command_timeout_seconds": 1800,
                "request_timeout_seconds": 3600,
                "temperature": 1.0,
                "top_p": 0.95,
                "reasoning_replay": "think_tags",
            },
            "system_prompt_sha256": self.system_prompt_sha256,
            "requests": self.requests,
            "responses": self.responses,
            "reasoning_responses": self.reasoning_responses,
            "reasoning_cache_entries": len(self.reasoning),
            "replay_hits": self.replay_hits,
            "replay_misses": self.replay_misses,
            "tool_call_responses": self.tool_call_responses,
            "http_errors": self.http_errors,
            "transport_errors": self.transport_errors,
            "started_at": self.started_at,
            "updated_at": time.time(),
            "request_details": self.request_details,
        }
        temporary = self.audit_path.with_suffix(self.audit_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, self.audit_path)


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        upstream: str,
        secret: str,
        state: ProxyState,
    ) -> None:
        super().__init__(server_address, handler)
        self.upstream = upstream.rstrip("/")
        self.secret = secret
        self.state = state
        cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(cookie_jar),
        )

    def upstream_url(self, path: str) -> str:
        clean_path = path.split("?", 1)[0]
        if clean_path.startswith("/v1/") and self.upstream.endswith("/v1"):
            clean_path = clean_path[3:]
        return self.upstream + clean_path


class Handler(BaseHTTPRequestHandler):
    server: ProxyServer

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b'{"status":"ok"}\n')
            return
        self._send(404, b'{"error":"not found"}\n')

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise TypeError("request body must be a JSON object")
        except (json.JSONDecodeError, TypeError) as error:
            self._send(400, json.dumps({"error": str(error)}).encode())
            return

        try:
            transformed, detail = self.server.state.transform_request(body)
        except TurnBudgetExceeded as error:
            self._send(
                429,
                json.dumps(
                    {
                        "error": {
                            "message": str(error),
                            "type": "invalid_request_error",
                            "code": "session_budget_exhausted",
                        }
                    }
                ).encode(),
            )
            return
        request = urllib.request.Request(
            self.server.upstream_url(self.path),
            data=json.dumps(transformed).encode(),
            headers={
                "Authorization": f"Bearer {self.server.secret}",
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
                "X-Client-ID": self.server.state.client_id,
            },
            method="POST",
        )
        status = 502
        response_headers: dict[str, str] = {}
        try:
            with self.server.opener.open(request, timeout=3600) as response:
                status = response.status
                response_headers = dict(response.headers)
                response_raw = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            response_headers = dict(error.headers)
            response_raw = error.read()
        except Exception as error:
            self.server.state.record_transport_error(detail, error)
            self._send(
                502,
                json.dumps(
                    {
                        "error": {
                            "message": f"OpenHands SDK parity proxy transport failure: {type(error).__name__}: {error}",
                            "type": "proxy_transport_error",
                        }
                    }
                ).encode(),
            )
            return

        try:
            response_body = json.loads(response_raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response_body = None
        if isinstance(response_body, dict):
            response_body = self.server.state.transform_response(response_body, detail, status)
            response_raw = json.dumps(response_body).encode()
        else:
            if status >= 400:
                with self.server.state.lock:
                    self.server.state.http_errors += 1
                    detail["status"] = status
                    self.server.state._write_audit()

        self._send(status, response_raw, response_headers.get("Content-Type", "application/json"))

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system-prompt", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()

    upstream = os.environ["OPENHANDS_UPSTREAM_URL"]
    secret = os.environ["OPENHANDS_UPSTREAM_SECRET"]
    system_prompt = args.system_prompt.read_text()
    state = ProxyState(system_prompt, args.audit)
    state._write_audit()
    server = ProxyServer(("127.0.0.1", 0), Handler, upstream, secret, state)
    args.ready.write_text(str(server.server_port) + "\n")
    server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
