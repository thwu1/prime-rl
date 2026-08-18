import copy
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def reasoning_text(message: dict[str, Any]) -> str | None:
    value = message.get("reasoning") or message.get("reasoning_content")
    return value if isinstance(value, str) and value.strip() else None


def reasoning_sequence(messages: list[dict[str, Any]]) -> tuple[list[str], int, int]:
    hashes = []
    reasoning_chars = 0
    missing = 0
    for message in messages:
        if message.get("role") != "assistant":
            continue
        reasoning = reasoning_text(message)
        if reasoning is None:
            missing += 1
            continue
        hashes.append(hashlib.sha256(reasoning.encode()).hexdigest())
        reasoning_chars += len(reasoning)
    return hashes, reasoning_chars, missing


def task_key(messages: list[dict[str, Any]]) -> str:
    prompt = [
        {"role": message.get("role"), "content": message.get("content")}
        for message in messages
        if message.get("role") in {"system", "user"}
    ][:2]
    return hashlib.sha256(json.dumps(prompt, sort_keys=True).encode()).hexdigest()[:16]


class CaptureServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def __init__(
        self,
        address: tuple[str, int],
        *,
        upstream: str,
        latest_dir: Path,
        summary_path: Path,
    ) -> None:
        super().__init__(address, CaptureHandler)
        self.upstream = upstream.rstrip("/")
        self.latest_dir = latest_dir
        self.summary_path = summary_path
        self.lock = threading.Lock()
        self.request_count = 0
        self.task_states: dict[str, dict[str, Any]] = {}
        latest_dir.mkdir(parents=True, exist_ok=True)
        summary_path.parent.mkdir(parents=True, exist_ok=True)

    def capture_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_messages = payload.get("messages")
        messages = [message for message in raw_messages if isinstance(message, dict)] if isinstance(raw_messages, list) else []
        key = task_key(messages)
        hashes, reasoning_chars, missing = reasoning_sequence(messages)
        with self.lock:
            state = self.task_states.setdefault(
                key,
                {
                    "requests": 0,
                    "attempt": 1,
                    "attempt_requests": 0,
                    "reasoning_hashes": [],
                },
            )
            previous = state["reasoning_hashes"]
            retry_boundary = (
                state["requests"] > 0
                and bool(previous)
                and not hashes
                and len(messages) == 2
            )
            if retry_boundary:
                state["attempt"] += 1
                state["attempt_requests"] = 0
                state["reasoning_hashes"] = []
                previous = []
            prefix_preserved = len(hashes) >= len(previous) and hashes[: len(previous)] == previous
            if prefix_preserved:
                state["reasoning_hashes"] = hashes
            state["requests"] += 1
            state["attempt_requests"] += 1
            self.request_count += 1
            request_id = self.request_count
            per_task_request = state["requests"]
            attempt = state["attempt"]
            per_attempt_request = state["attempt_requests"]

            target = self.latest_dir / f"{key}.json"
            temporary = target.with_suffix(f".{threading.get_ident()}.tmp")
            temporary.write_text(json.dumps(payload))
            os.replace(temporary, target)

        template_kwargs = payload.get("chat_template_kwargs")
        return {
            "request_id": request_id,
            "task_key": key,
            "attempt": attempt,
            "per_attempt_request": per_attempt_request,
            "retry_boundary": retry_boundary,
            "per_task_request": per_task_request,
            "started_at": time.time(),
            "message_count": len(messages),
            "assistant_reasoning_count": len(hashes),
            "assistant_reasoning_chars": reasoning_chars,
            "assistant_messages_missing_reasoning": missing,
            "previous_reasoning_prefix_preserved": prefix_preserved,
            "chat_template_kwargs": template_kwargs,
        }

    def capture_response(
        self,
        summary: dict[str, Any],
        status: int,
        body: bytes,
    ) -> None:
        summary["finished_at"] = time.time()
        summary["http_status"] = status
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if isinstance(payload, dict):
            usage = payload.get("usage")
            if isinstance(usage, dict):
                summary["usage"] = {
                    key: usage.get(key)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
            choices = payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                summary["finish_reason"] = choices[0].get("finish_reason")
                message = choices[0].get("message")
                if isinstance(message, dict):
                    reasoning = reasoning_text(message)
                    if reasoning is not None:
                        summary["response_reasoning_chars"] = len(reasoning)
                        summary["response_reasoning_sha256"] = hashlib.sha256(
                            reasoning.encode()
                        ).hexdigest()
            error = payload.get("error")
            if error is not None:
                summary["error"] = error
        with self.lock:
            with self.summary_path.open("a") as file:
                file.write(json.dumps(summary, sort_keys=True) + "\n")


class CaptureHandler(BaseHTTPRequestHandler):
    server: CaptureServer

    def do_GET(self) -> None:
        self._forward(None)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self._forward(self.rfile.read(length))

    def _forward(self, body: bytes | None) -> None:
        summary = None
        if self.path.rstrip("/") == "/v1/chat/completions" and body is not None:
            payload = json.loads(body)
            if isinstance(payload, dict):
                summary = self.server.capture_request(payload)

        headers = {
            key: value
            for key in ("Content-Type", "Accept", "Authorization")
            if (value := self.headers.get(key)) is not None
        }
        request = urllib.request.Request(
            f"{self.server.upstream}{self.path}",
            data=body,
            headers=headers,
            method=self.command,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=2 * 60 * 60) as response:
                response_body = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as error:
            response_body = error.read()
            status = error.code
            content_type = error.headers.get("Content-Type", "application/json")
        except OSError as error:
            response_body = json.dumps({"error": str(error)}).encode()
            status = 502
            content_type = "application/json"

        if summary is not None:
            self.server.capture_response(summary, status, response_body)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: object) -> None:
        return


def start_capture_proxy(
    upstream: str,
    latest_dir: Path,
    summary_path: Path,
) -> tuple[CaptureServer, threading.Thread, str]:
    server = CaptureServer(
        ("127.0.0.1", 0),
        upstream=upstream,
        latest_dir=latest_dir,
        summary_path=summary_path,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def stop_capture_proxy(server: CaptureServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join()


def messages_for_tokenize(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = copy.deepcopy(messages)
    for message in normalized:
        reasoning_content = message.pop("reasoning_content", None)
        if reasoning_content is not None and message.get("reasoning") is None:
            message["reasoning"] = reasoning_content
    return normalized


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10 * 60) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object from {url}")
    return value


def audit_captured_requests(
    router: str,
    latest_dir: Path,
    summary_path: Path,
    output_path: Path,
) -> None:
    summaries = [json.loads(line) for line in summary_path.read_text().splitlines() if line]
    request_failures = [
        {
            "request_id": item.get("request_id"),
            "task_key": item.get("task_key"),
            "attempt": item.get("attempt", 1),
            "missing_reasoning": item.get("assistant_messages_missing_reasoning"),
            "prefix_preserved": item.get("previous_reasoning_prefix_preserved"),
            "chat_template_kwargs": item.get("chat_template_kwargs"),
        }
        for item in summaries
        if item.get("assistant_messages_missing_reasoning")
        or item.get("previous_reasoning_prefix_preserved") is not True
        or item.get("chat_template_kwargs")
        != {"enable_thinking": True, "truncate_history_thinking": False}
        or item.get("http_status") != 200
    ]

    rendered = []
    for path in sorted(latest_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise ValueError(f"captured request has no messages: {path}")
        typed_messages = [message for message in messages if isinstance(message, dict)]
        reasoning = [
            value
            for message in typed_messages
            if (value := reasoning_text(message)) is not None
        ]
        tokenize_payload = {
            "model": payload["model"],
            "messages": messages_for_tokenize(typed_messages),
            "chat_template_kwargs": payload.get("chat_template_kwargs"),
        }
        if payload.get("tools") is not None:
            tokenize_payload["tools"] = payload["tools"]
        tokenized = post_json(f"{router}/tokenize", tokenize_payload)
        prompt = post_json(
            f"{router}/detokenize",
            {"model": payload["model"], "tokens": tokenized["tokens"]},
        )["prompt"]
        missing = [
            index + 1
            for index, value in enumerate(reasoning)
            if value.strip() not in prompt
        ]
        rendered.append(
            {
                "task_key": path.stem,
                "message_count": len(typed_messages),
                "prior_reasoning_turns": len(reasoning),
                "rendered_tokens": len(tokenized["tokens"]),
                "exact_reasoning_turns_present": len(reasoning) - len(missing),
                "missing_reasoning_turns": missing,
            }
        )

    task_keys = sorted(
        {
            item["task_key"]
            for item in summaries
            if isinstance(item.get("task_key"), str)
        }
    )
    report = {
        "request_count": len(summaries),
        "task_count": len(rendered),
        "task_attempts": {
            key: max(
                int(item.get("attempt", 1))
                for item in summaries
                if item.get("task_key") == key
            )
            for key in task_keys
        },
        "request_failures": request_failures,
        "rendered_latest_requests": rendered,
    }
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    render_failures = [item for item in rendered if item["missing_reasoning_turns"]]
    if request_failures or render_failures:
        raise RuntimeError(f"thinking trajectory audit failed: {output_path}")
