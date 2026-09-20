"""Turn streaming agent calls into token-preserving Chat Completions calls.

Agent CLIs generally insist on SSE even though Prime-RL's training client must
produce one complete response so it can retain token ids and log probabilities.
This loopback-only proxy clears ``stream`` on the request sent to Verifiers and
serializes the resulting completion back into a valid SSE stream for the agent.
The model boundary therefore remains Verifiers' ordinary non-streaming path;
only the wire representation seen by the guest changes. OpenAI Responses
requests are also translated to Chat Completions for compatible future agents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientSession, ClientTimeout, web
from verifiers.v1.dialects import ChatDialect, ResponsesDialect
from verifiers.v1.dialects.chat import message_to_wire

_FORWARDED_HEADERS = frozenset(
    {
        "x-stainless-retry-count",
        "x-stainless-timeout",
    }
)


@dataclass
class BufferedChatStats:
    requests: int = 0
    streamed_requests: int = 0
    response_bytes: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    protocols: dict[str, int] = field(default_factory=dict)
    paths: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "streamed_requests": self.streamed_requests,
            "response_bytes": self.response_bytes,
            "statuses": dict(self.statuses),
            "protocols": dict(self.protocols),
            "paths": dict(self.paths),
            "errors": list(self.errors),
        }


class BufferedChatCompletionsProxy:
    """A rollout-scoped, loopback-only streaming compatibility endpoint.

    Prime-RL 0.9's training client must receive a non-streaming Chat
    Completions request to retain generated token ids and log probabilities.
    OpenCode, Pi, and Muse Code's OpenRouter transport speak that protocol. This
    boundary can also convert a Responses request and response without changing
    the canonical request seen by the trainer.
    """

    def __init__(
        self,
        endpoint: str,
        secret: str,
        *,
        model: str = "policy",
        context_window: int = 65_536,
        max_output_tokens: int = 32_768,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port is None:
            raise ValueError(f"buffered chat proxy requires a loopback HTTP endpoint, got {endpoint!r}")
        self._origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        self._secret = secret
        self._model = model
        self._context_window = context_window
        self._max_output_tokens = max_output_tokens
        self._runner: web.AppRunner | None = None
        self._session: ClientSession | None = None
        self.port = 0
        self.stats = BufferedChatStats()

    async def start(self) -> None:
        if self._runner is not None:
            raise RuntimeError("buffered chat proxy is already started")
        self._session = ClientSession(timeout=ClientTimeout(total=None))
        app = web.Application(client_max_size=1024**3)
        app.router.add_route("*", "/{path:.*}", self._handle)
        runner = self._runner = web.AppRunner(app, access_log=None)
        try:
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            server = site._server
            assert server is not None and server.sockets
            self.port = int(server.sockets[0].getsockname()[1])
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        runner, self._runner = self._runner, None
        session, self._session = self._session, None
        if runner is not None:
            await runner.cleanup()
        if session is not None:
            await session.close()
        self.port = 0

    def _error(self, message: str, status: int) -> web.Response:
        return web.json_response(
            {"error": {"message": message, "type": "invalid_request_error"}},
            status=status,
        )

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        self.stats.paths[request.path] = self.stats.paths.get(request.path, 0) + 1
        if request.headers.get("Authorization") != f"Bearer {self._secret}":
            return self._error("unauthorized", 401)
        if request.method == "GET" and request.path == "/muse-code/models":
            return web.json_response(self._muse_model_catalog())
        protocols = {
            "/v1/chat/completions": "chat_completions",
            "/v1/responses": "responses",
        }
        protocol = protocols.get(request.path)
        if request.method != "POST" or protocol is None:
            return self._error(
                "only POST /v1/chat/completions and POST /v1/responses are supported",
                404,
            )
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return self._error("request body must be JSON", 400)
        if not isinstance(body, dict):
            return self._error("request body must be an object", 400)

        streaming = bool(body.get("stream"))
        try:
            upstream_body = self._responses_to_chat(body) if protocol == "responses" else dict(body)
        except (KeyError, TypeError, ValueError) as error:
            return self._error(f"invalid {protocol} request: {error}", 400)
        upstream_body["stream"] = False
        upstream_body.pop("stream_options", None)
        headers = {
            "Authorization": f"Bearer {self._secret}",
            "Content-Type": "application/json",
            **{name: value for name, value in request.headers.items() if name.lower() in _FORWARDED_HEADERS},
        }
        self.stats.requests += 1
        self.stats.streamed_requests += int(streaming)
        self.stats.protocols[protocol] = self.stats.protocols.get(protocol, 0) + 1
        assert self._session is not None
        try:
            async with self._session.post(
                self._origin + "/v1/chat/completions",
                json=upstream_body,
                headers=headers,
            ) as upstream:
                raw = await upstream.read()
                self.stats.response_bytes += len(raw)
                status = upstream.status
                self.stats.statuses[str(status)] = self.stats.statuses.get(str(status), 0) + 1
                if status < 200 or status >= 300 or (protocol == "chat_completions" and not streaming):
                    return web.Response(
                        body=raw,
                        status=status,
                        content_type=(upstream.content_type or "application/json"),
                    )
                completion = json.loads(raw)
        except Exception as error:
            self.stats.errors.append(f"{type(error).__name__}: {error}"[:1000])
            del self.stats.errors[:-20]
            return self._error("buffered model proxy failure", 502)

        if protocol == "responses":
            response_body = self._chat_to_responses(completion, body)
            events = self._response_events(response_body)
        else:
            response_body = completion
            events = ChatDialect().stream_events(completion)

        if not streaming:
            return web.json_response(response_body)

        response = web.StreamResponse(
            status=200,
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
        response.content_type = "text/event-stream"
        await response.prepare(request)
        try:
            for event in events:
                await response.write(event)
            await response.write_eof()
        except ConnectionResetError:
            pass
        return response

    def _muse_model_catalog(self) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": self._model,
                    "object": "model",
                    "created": 0,
                    "owned_by": "prime-rl",
                    "metadata": {
                        "muse-code": {
                            "name": self._model,
                            "family": "openai",
                            "release_date": "1970-01-01",
                            "is_hidden": False,
                            "attachment": False,
                            "reasoning": True,
                            "temperature": True,
                            "tool_call": True,
                            "modalities": {"input": ["text"], "output": ["text"]},
                            "limit": {
                                "context": self._context_window,
                                "output": self._max_output_tokens,
                            },
                            "options": {"reasoningEffort": "high"},
                            "variants": {
                                effort: {"reasoningEffort": effort} for effort in ("minimal", "low", "medium", "high")
                            },
                        }
                    },
                }
            ],
        }

    @staticmethod
    def _responses_to_chat(body: dict[str, Any]) -> dict[str, Any]:
        request = ResponsesDialect().parse_request(body)
        tools: list[dict[str, Any]] = []
        names: set[str] = set()

        def append_function(tool: dict[str, Any], namespace: str | None = None) -> None:
            name = str(tool.get("name") or "")
            if not name:
                return
            if name in names:
                raise ValueError(f"duplicate function tool after namespace flattening: {name!r}")
            names.add(name)
            description = str(tool.get("description") or "")
            if namespace:
                description = f"[{namespace} namespace] {description}".strip()
            function: dict[str, Any] = {
                "name": name,
                "description": description,
                "parameters": tool.get("parameters") or {},
            }
            if tool.get("strict") is not None:
                function["strict"] = tool["strict"]
            tools.append({"type": "function", "function": function})

        for tool in body.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function":
                append_function(tool)
            elif tool.get("type") == "namespace":
                namespace = str(tool.get("name") or "") or None
                for nested in tool.get("tools") or []:
                    if isinstance(nested, dict) and nested.get("type") == "function":
                        append_function(nested, namespace)
        chat: dict[str, Any] = {
            "model": body.get("model", ""),
            "messages": [message_to_wire(message) for message in request.messages],
        }
        if tools:
            chat["tools"] = tools
        for key in ("temperature", "top_p", "parallel_tool_calls", "seed"):
            if key in body:
                chat[key] = body[key]
        if body.get("max_output_tokens") is not None:
            chat["max_completion_tokens"] = body["max_output_tokens"]
        reasoning = body.get("reasoning")
        if isinstance(reasoning, dict) and reasoning.get("effort") is not None:
            chat["reasoning_effort"] = reasoning["effort"]
        return chat

    @staticmethod
    def _chat_to_responses(completion: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        choices = completion.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("Chat Completions response has no first choice")
        message = choices[0].get("message") or {}
        if not isinstance(message, dict):
            raise ValueError("Chat Completions first choice has no message")
        response_id = str(completion.get("id") or "resp_intercepted")
        output: list[dict[str, Any]] = []
        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            output.append(
                {
                    "type": "reasoning",
                    "id": f"rs_{response_id}",
                    "summary": [{"type": "summary_text", "text": reasoning}],
                }
            )
        content = message.get("content")
        if isinstance(content, str) and content:
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{response_id}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": content,
                            "annotations": [],
                        }
                    ],
                }
            )
        for index, call in enumerate(message.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            kind = call.get("type", "function")
            native = call.get(kind) or call.get("function") or {}
            if not isinstance(native, dict):
                continue
            call_id = str(call.get("id") or f"call_{index}")
            output.append(
                {
                    "type": "custom_tool_call" if kind == "custom" else "function_call",
                    "id": f"fc_{call_id}",
                    "call_id": call_id,
                    "name": str(native.get("name") or ""),
                    ("input" if kind == "custom" else "arguments"): str(
                        native.get("input" if kind == "custom" else "arguments") or ""
                    ),
                    "status": "completed",
                }
            )
        usage = completion.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        reasoning_tokens = (
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            if isinstance(usage.get("completion_tokens_details"), dict)
            else None
        )
        response_usage: dict[str, Any] = {
            "input_tokens": prompt_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": completion_tokens,
            "output_tokens_details": {"reasoning_tokens": reasoning_tokens or 0},
            "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
        }
        return {
            "id": response_id,
            "object": "response",
            "created_at": int(completion.get("created") or 0),
            "completed_at": int(completion.get("created") or 0),
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "instructions": request.get("instructions"),
            "max_output_tokens": request.get("max_output_tokens"),
            "model": completion.get("model") or request.get("model") or "",
            "output": output,
            "output_text": content if isinstance(content, str) else "",
            "parallel_tool_calls": request.get("parallel_tool_calls", True),
            "previous_response_id": None,
            "reasoning": request.get("reasoning"),
            "store": False,
            "temperature": request.get("temperature"),
            "text": request.get("text") or {"format": {"type": "text"}},
            "tool_choice": request.get("tool_choice", "auto"),
            "tools": request.get("tools") or [],
            "top_p": request.get("top_p"),
            "truncation": request.get("truncation", "disabled"),
            "usage": response_usage,
        }

    @staticmethod
    def _response_events(response: dict[str, Any]) -> list[bytes]:
        sequence = 0
        events: list[bytes] = []

        def add(kind: str, **payload: Any) -> None:
            nonlocal sequence
            event = {"type": kind, "sequence_number": sequence, **payload}
            events.append(f"event: {kind}\ndata: {json.dumps(event)}\n\n".encode())
            sequence += 1

        head = {**response, "status": "in_progress", "output": [], "completed_at": None}
        add("response.created", response=head)
        add("response.in_progress", response=head)
        for output_index, item in enumerate(response["output"]):
            kind = item["type"]
            added = dict(item)
            if kind == "message":
                added["content"] = []
            elif kind == "function_call":
                added["arguments"] = ""
            elif kind == "custom_tool_call":
                added["input"] = ""
            elif kind == "reasoning":
                added["summary"] = []
            add("response.output_item.added", output_index=output_index, item=added)
            if kind == "message":
                for content_index, part in enumerate(item.get("content") or []):
                    common = {
                        "output_index": output_index,
                        "item_id": item["id"],
                        "content_index": content_index,
                    }
                    add("response.content_part.added", **common, part={**part, "text": ""})
                    add("response.output_text.delta", **common, delta=part.get("text", ""))
                    add("response.output_text.done", **common, text=part.get("text", ""))
                    add("response.content_part.done", **common, part=part)
            elif kind == "function_call":
                common = {"output_index": output_index, "item_id": item["id"]}
                add(
                    "response.function_call_arguments.delta",
                    **common,
                    delta=item.get("arguments", ""),
                )
                add(
                    "response.function_call_arguments.done",
                    **common,
                    arguments=item.get("arguments", ""),
                )
            elif kind == "custom_tool_call":
                common = {"output_index": output_index, "item_id": item["id"]}
                add(
                    "response.custom_tool_call_input.delta",
                    **common,
                    delta=item.get("input", ""),
                )
                add(
                    "response.custom_tool_call_input.done",
                    **common,
                    input=item.get("input", ""),
                )
            add("response.output_item.done", output_index=output_index, item=item)
        add("response.completed", response=response)
        events.append(b"data: [DONE]\n\n")
        return events


__all__ = ["BufferedChatCompletionsProxy", "BufferedChatStats"]
