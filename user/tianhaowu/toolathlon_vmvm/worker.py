from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import functools
import http.client
import json
import os
import random
import re
import signal
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_tools import HistoricalLocalTools, schemas_for_groups

EXIT_FATAL = 70
EXIT_RETRYABLE = 75


class RetryableRolloutError(RuntimeError):
    pass


class ExecutionVanished(RetryableRolloutError):
    pass


class TaskWallclockTimeout(RuntimeError):
    pass


class ModelProviderError(RuntimeError):
    pass


class ContextWindowExceeded(RuntimeError):
    pass


class HTTPStatusError(RuntimeError):
    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"HTTP {status} from {url}: {body[-1000:]}")
        self.status = status
        self.body = body
        self.url = url


@dataclass(frozen=True)
class Execution:
    server_url: str
    execution_id: str
    task_id: str
    start_payload: dict[str, Any]
    ready_payload: dict[str, Any]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temporary, path)


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
    opener: urllib.request.OpenerDirector | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request_headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        open_request = opener.open if opener is not None else urllib.request.urlopen
        with open_request(request, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise HTTPStatusError(error.code, error_body, url) from error
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        ConnectionError,
        http.client.HTTPException,
    ) as error:
        raise RetryableRolloutError(f"transport error for {method} {url}: {error}") from error
    if not response_body:
        return {}
    parsed = json.loads(response_body)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Expected a JSON object from {url}, got {type(parsed).__name__}")
    return parsed


class ToolathlonService:
    def __init__(self, config: dict[str, Any]) -> None:
        self.server_urls = [str(url).rstrip("/") for url in config["server_urls"]]
        self.model_name = str(config["model_name"])
        self.debug = bool(config.get("debug", False))
        self.http_timeout = float(config.get("http_timeout_seconds", 300))
        self.status_poll_interval = float(config.get("status_poll_interval_seconds", 5))
        self.start_retry_interval = float(config.get("start_retry_interval_seconds", 10))
        self.start_retry_jitter = float(config.get("start_retry_jitter_seconds", 10))
        self.start_timeout = float(config.get("start_timeout_seconds", 18000))
        self.execution_ready_timeout = float(config.get("execution_ready_timeout_seconds", 1800))
        self.max_setup_vanishes = int(config.get("max_setup_vanishes", 10))
        self.tool_call_retries = int(config.get("tool_call_retries", 3))
        self.tool_call_retry_backoff = float(config.get("tool_call_retry_backoff_seconds", 5))
        proxy_url = config.get("http_proxy_url")
        proxies = {"http": str(proxy_url)} if proxy_url else {}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))

    def start(self, task_id: str, metadata: dict[str, Any]) -> Execution:
        deadline = time.monotonic() + self.start_timeout
        setup_vanishes = 0
        last_error: BaseException | None = None
        while time.monotonic() <= deadline:
            server_urls = list(self.server_urls)
            random.shuffle(server_urls)
            for server_url in server_urls:
                try:
                    start_payload = _json_request(
                        "POST",
                        f"{server_url}/v3/tasks/{task_id}/start",
                        payload={
                            "model_name": self.model_name,
                            "debug": self.debug,
                            "metadata": metadata,
                        },
                        timeout=min(self.http_timeout, 30),
                        opener=self.opener,
                    )
                    execution_id = str(start_payload.get("execution_id", ""))
                    if not execution_id:
                        raise RuntimeError(f"Start response for {task_id} had no execution_id")
                    try:
                        ready_payload = self._wait_ready(server_url, execution_id)
                    except Exception:
                        self.delete(
                            Execution(
                                server_url=server_url,
                                execution_id=execution_id,
                                task_id=task_id,
                                start_payload=start_payload,
                                ready_payload={},
                            )
                        )
                        raise
                    return Execution(
                        server_url=server_url,
                        execution_id=execution_id,
                        task_id=task_id,
                        start_payload=start_payload,
                        ready_payload=ready_payload,
                    )
                except HTTPStatusError as error:
                    last_error = error
                    if error.status in {404, 409, 429} or error.status >= 500:
                        continue
                    raise
                except ExecutionVanished as error:
                    last_error = error
                    setup_vanishes += 1
                    if self.max_setup_vanishes > 0 and setup_vanishes >= self.max_setup_vanishes:
                        raise RetryableRolloutError(
                            f"{task_id} vanished {setup_vanishes} times during setup"
                        ) from error
                except RetryableRolloutError as error:
                    last_error = error
                    continue
            delay = self.start_retry_interval + random.uniform(0, self.start_retry_jitter)
            time.sleep(delay)
        raise RetryableRolloutError(
            f"No Toolathlon endpoint accepted {task_id} within {self.start_timeout}s: {last_error}"
        )

    def _wait_ready(self, server_url: str, execution_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.execution_ready_timeout
        last_error: BaseException | None = None
        while time.monotonic() <= deadline:
            try:
                payload = _json_request(
                    "GET",
                    f"{server_url}/v3/executions/{execution_id}/status?poll={time.time_ns()}",
                    timeout=min(self.http_timeout, 30),
                    opener=self.opener,
                )
                status = str(payload.get("status", ""))
                if status == "ready":
                    return payload
                if status in {"failed", "error", "cancelled"}:
                    raise ExecutionVanished(
                        f"Execution {execution_id} entered terminal setup state {status}: {payload}"
                    )
                last_error = RuntimeError(f"last setup status: {payload}")
            except HTTPStatusError as error:
                if error.status in {404, 410}:
                    raise ExecutionVanished(f"Execution {execution_id} vanished during setup") from error
                last_error = error
            except RetryableRolloutError as error:
                last_error = error
            except json.JSONDecodeError as error:
                last_error = error
            time.sleep(self.status_poll_interval)
        raise RetryableRolloutError(
            f"Execution {execution_id} was not ready within {self.execution_ready_timeout}s: {last_error}"
        )

    def call_tool(
        self,
        execution: Execution,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: BaseException | None = None
        for attempt in range(self.tool_call_retries + 1):
            try:
                return _json_request(
                    "POST",
                    f"{execution.server_url}/v3/executions/{execution.execution_id}/call-tool",
                    payload={"tool_name": tool_name, "arguments": arguments},
                    timeout=self.http_timeout,
                    opener=self.opener,
                )
            except HTTPStatusError as error:
                if error.status in {404, 410}:
                    raise ExecutionVanished(
                        f"Execution {execution.execution_id} vanished during {tool_name}"
                    ) from error
                if error.status < 500 and error.status not in {409, 429}:
                    raise
                last_error = error
            except RetryableRolloutError as error:
                last_error = error
            except json.JSONDecodeError as error:
                last_error = error
            if attempt < self.tool_call_retries:
                time.sleep(self.tool_call_retry_backoff * (2**attempt))
        raise RetryableRolloutError(
            f"Tool call {tool_name} failed after {self.tool_call_retries + 1} attempts: {last_error}"
        )

    def grade(self, execution: Execution) -> dict[str, Any]:
        last_error: BaseException | None = None
        for attempt in range(30):
            try:
                return _json_request(
                    "POST",
                    f"{execution.server_url}/v3/executions/{execution.execution_id}/grade",
                    timeout=600,
                    opener=self.opener,
                )
            except HTTPStatusError as error:
                if error.status in {404, 410}:
                    raise ExecutionVanished(f"Execution {execution.execution_id} vanished during grading") from error
                if error.status < 500:
                    raise
                last_error = error
            except RetryableRolloutError as error:
                last_error = error
            except json.JSONDecodeError as error:
                last_error = error
            if attempt < 29:
                time.sleep(10)
        raise RetryableRolloutError(f"Grading failed after 30 attempts: {last_error}")

    def delete(self, execution: Execution) -> None:
        try:
            _json_request(
                "DELETE",
                f"{execution.server_url}/v3/executions/{execution.execution_id}",
                timeout=min(self.http_timeout, 30),
                opener=self.opener,
            )
        except HTTPStatusError as error:
            if error.status not in {404, 410}:
                print(f"cleanup warning: {error}", file=sys.stderr, flush=True)
        except Exception as error:
            print(f"cleanup warning: {type(error).__name__}: {error}", file=sys.stderr, flush=True)


def _find_field(payloads: list[dict[str, Any]], names: tuple[str, ...]) -> Any:
    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            for name in names:
                if name in value and value[name] not in (None, "", []):
                    return value[name]
            for child in value.values():
                found = visit(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found is not None:
                    return found
        return None

    for payload in payloads:
        found = visit(payload)
        if found is not None:
            return found
    return None


def _model_tool_name(name: str) -> str:
    return name.replace("-", "_")


def _resolve_dispatch_name(
    returned_name: str,
    dispatch_names: dict[str, str],
    *,
    accept_legacy_names: bool,
) -> str | None:
    if returned_name in dispatch_names:
        return dispatch_names[returned_name]
    if not accept_legacy_names:
        return None
    normalized_name = _model_tool_name(returned_name)
    matches = [
        service_name
        for model_name, service_name in dispatch_names.items()
        if _model_tool_name(model_name) == normalized_name
    ]
    return matches[0] if len(matches) == 1 else None


_JSON_COERCIBLE_SCHEMA_TYPES = {"object", "array", "integer", "number", "boolean"}
_CONTEXT_WINDOW_ERROR_PATTERNS = (
    "contextwindowexceedederror",
    "context_length_exceeded",
    "maximum context length",
    "context length is only",
    "request exceeded model token limit",
    "prompt is too long",
    "messages_too_long",
    "exceeds the model's context window",
    "reduce the length of the input prompt",
)


def _declared_schema_types(schema: dict[str, Any]) -> set[str]:
    declared: set[str] = set()
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        declared.add(schema_type)
    elif isinstance(schema_type, list):
        declared.update(item for item in schema_type if isinstance(item, str))
    for union_key in ("anyOf", "oneOf"):
        for option in schema.get(union_key, []):
            if isinstance(option, dict):
                declared.update(_declared_schema_types(option))
    return declared


def _value_matches_schema_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "null":
        return value is None
    return False


def _matching_schema(value: Any, schema: dict[str, Any]) -> dict[str, Any]:
    for union_key in ("anyOf", "oneOf"):
        for option in schema.get(union_key, []):
            if isinstance(option, dict) and any(
                _value_matches_schema_type(value, schema_type) for schema_type in _declared_schema_types(option)
            ):
                return option
    return schema


def _coerce_stringified_json_value(value: Any, schema: dict[str, Any]) -> Any:
    declared_types = _declared_schema_types(schema)
    coercible_types = declared_types & _JSON_COERCIBLE_SCHEMA_TYPES
    if isinstance(value, str) and coercible_types and "string" not in declared_types:
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            decoded = value
        if any(_value_matches_schema_type(decoded, schema_type) for schema_type in coercible_types):
            value = decoded

    active_schema = _matching_schema(value, schema)
    if isinstance(value, dict):
        properties = active_schema.get("properties", {})
        additional_properties = active_schema.get("additionalProperties")
        return {
            key: _coerce_stringified_json_value(
                item,
                properties.get(key)
                if isinstance(properties.get(key), dict)
                else additional_properties
                if isinstance(additional_properties, dict)
                else {},
            )
            for key, item in value.items()
        }
    if isinstance(value, list) and isinstance(active_schema.get("items"), dict):
        return [_coerce_stringified_json_value(item, active_schema["items"]) for item in value]
    return value


def _add_tool(
    tools: list[dict[str, Any]],
    dispatch_names: dict[str, str],
    function: dict[str, Any],
    dispatch_name: str,
) -> None:
    raw_name = str(function.get("name") or "")
    if not raw_name:
        raise ValueError(f"Tool schema has no name: {function!r}")
    model_name = _model_tool_name(raw_name)
    if model_name in dispatch_names:
        raise ValueError(f"Duplicate model-facing tool schema: {model_name}")
    model_function = dict(function)
    model_function["name"] = model_name
    tools.append({"type": "function", "function": model_function})
    dispatch_names[model_name] = dispatch_name


def _build_static_tools(
    task: dict[str, Any],
    schemas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    schemas_by_namespace: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for schema in schemas:
        full_name = str(schema.get("name", ""))
        if "__" not in full_name:
            raise ValueError(f"Malformed bundled tool name: {full_name!r}")
        namespace, function_name = full_name.split("__", 1)
        schemas_by_namespace.setdefault(namespace, []).append((function_name, schema))

    tools: list[dict[str, Any]] = []
    dispatch_names: dict[str, str] = {}

    def add_service_tools(namespace: str, requested_function: str | None = None) -> None:
        for function_name, schema in schemas_by_namespace.get(namespace, []):
            if requested_function is not None and function_name.replace("-", "_") != requested_function:
                continue
            service_name = f"{namespace}-{function_name}"
            _add_tool(
                tools,
                dispatch_names,
                {
                    "name": service_name,
                    "description": str(schema.get("description") or ""),
                    "parameters": schema.get("parameters") or {"type": "object", "properties": {}},
                },
                service_name,
            )

    for namespace in task.get("needed_mcp_servers") or []:
        add_service_tools(str(namespace))
    for local_name in task.get("needed_local_tools") or []:
        normalized = str(local_name).replace("-", "_")
        virtual_schemas = schemas_for_groups([normalized])
        if virtual_schemas:
            for schema in virtual_schemas:
                function = schema["function"]
                name = str(function["name"])
                _add_tool(tools, dispatch_names, function, f"virtual:{name}")
        else:
            add_service_tools("local", normalized)
    if not tools:
        raise RuntimeError(f"No bundled tools matched task {task.get('task_id')}")
    return tools, dispatch_names


def _build_live_tools(
    task: dict[str, Any],
    schemas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    virtual_schemas = {
        str(schema["function"]["name"]): schema
        for schema in schemas_for_groups([str(name).replace("-", "_") for name in task.get("needed_local_tools") or []])
    }
    tools: list[dict[str, Any]] = []
    dispatch_names: dict[str, str] = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            raise ValueError(f"Malformed live tool schema: {schema!r}")
        if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
            function = dict(schema["function"])
        else:
            function = {
                "name": schema.get("name"),
                "description": schema.get("description") or "",
                "parameters": schema.get("parameters")
                or schema.get("inputSchema")
                or schema.get("input_schema")
                or {"type": "object", "properties": {}},
            }
        raw_name = str(function.get("name") or "")
        if not raw_name:
            raise ValueError(f"Live tool schema has no name: {schema!r}")
        if raw_name in virtual_schemas:
            _add_tool(tools, dispatch_names, virtual_schemas[raw_name]["function"], f"virtual:{raw_name}")
        else:
            _add_tool(tools, dispatch_names, function, raw_name)
    for raw_name, schema in virtual_schemas.items():
        model_name = _model_tool_name(raw_name)
        if model_name not in dispatch_names:
            _add_tool(tools, dispatch_names, schema["function"], f"virtual:{raw_name}")
    if not tools:
        raise RuntimeError("The live Toolathlon task exposed no tools")
    return tools, dispatch_names


def _task_description(catalog_row: dict[str, Any]) -> str:
    description = catalog_row.get("description")
    if not isinstance(description, str) or not description.strip():
        raise RuntimeError(f"No task description bundled for {catalog_row.get('task_id')}")
    return description


def _effective_task(
    execution: Execution,
    catalog_row: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    historical_task = dict(catalog_row)
    live_task: dict[str, Any] | None = None
    for payload in (execution.start_payload, execution.ready_payload):
        candidate = payload.get("task")
        if isinstance(candidate, dict):
            live_task = candidate

    drift: dict[str, Any] = {"live_task_available": live_task is not None}
    if live_task is None:
        return historical_task, drift

    live_description = live_task.get("description")
    historical_description = historical_task.get("description")
    if isinstance(live_description, str) and isinstance(historical_description, str):
        historical_ports = re.findall(r"localhost:(\d+)", historical_description)
        live_ports = re.findall(r"localhost:(\d+)", live_description)
        if historical_ports:
            if len(historical_ports) != len(live_ports):
                raise RuntimeError(
                    f"Cannot map live localhost ports for {historical_task.get('task_id')}: "
                    f"historical={historical_ports}, live={live_ports}"
                )
            effective_description = historical_description
            port_rewrites: list[dict[str, str]] = []
            for historical_port, live_port in zip(historical_ports, live_ports):
                effective_description = effective_description.replace(
                    f"localhost:{historical_port}",
                    f"localhost:{live_port}",
                    1,
                )
                if historical_port != live_port:
                    port_rewrites.append({"historical": historical_port, "live": live_port})
            historical_task["description"] = effective_description
            drift["port_rewrites"] = port_rewrites

    historical_system = historical_task.get("system_prompt_template")
    live_system = live_task.get("system_prompt") or live_task.get("system_prompt_template")
    drift.update(
        {
            "description_changed": live_description != historical_description,
            "mcp_servers_changed": live_task.get("needed_mcp_servers") != historical_task.get("needed_mcp_servers"),
            "local_tools_changed": live_task.get("needed_local_tools") != historical_task.get("needed_local_tools"),
            "system_prompt_changed": live_system not in (None, historical_system),
        }
    )
    return historical_task, drift


def _grade_passed(grade: dict[str, Any]) -> bool:
    score = grade.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return score == 1
    status = grade.get("status")
    if isinstance(status, str):
        return status.lower() == "pass"
    for key in ("passed", "pass"):
        if grade.get(key) is True:
            return True
    result = grade.get("result")
    if result is True or result == 1:
        return True
    if isinstance(result, str):
        return result.lower() in {"pass", "passed", "success", "true"}
    if isinstance(result, dict):
        return _grade_passed(result)
    evaluation = grade.get("evaluation")
    return isinstance(evaluation, dict) and _grade_passed(evaluation)


def _system_prompt(task: dict[str, Any], dispatch_names: dict[str, str]) -> str:
    prompt = str(task["system_prompt_template"])
    workspace = "/workspace/dumps/workspace"
    replacements = {
        "!!<<<<||||current_working_dir||||>>>>!!": "/workspace",
        "!!<<<<||||workspace_dir||||>>>>!!": workspace,
        "!!<<<<||||workspace_dir_rela||||>>>>!!": "dumps/workspace",
        "!!<<<<||||time||||>>>>!!": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %A"),
    }
    for marker, value in replacements.items():
        prompt = prompt.replace(marker, value)
    aliases = {
        dispatch_name.removeprefix("virtual:"): model_name
        for model_name, dispatch_name in dispatch_names.items()
        if dispatch_name.removeprefix("virtual:").startswith("local-")
    }
    aliases["local-claim-done"] = "local_claim_done"
    for raw_name, model_name in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(?<![A-Za-z0-9_-]){re.escape(raw_name)}(?![A-Za-z0-9_-])"
        prompt = re.sub(pattern, lambda _: model_name, prompt)
    prompt += (
        "\nPlease complete the given task independently. Do not seek confirmation or "
        "additional feedback from the user. You should handle all situations on your "
        "own, as the user will not provide any further information."
    )
    return prompt


def _model_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized + "/chat/completions"
    return normalized + "/v1/chat/completions"


def _model_completion(
    endpoint: dict[str, Any],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    config: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": endpoint["model"],
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": int(config.get("max_tokens", 8192)),
        "stream": False,
    }
    if "parallel_tool_calls" in config:
        payload["parallel_tool_calls"] = bool(config["parallel_tool_calls"])
    for name in ("temperature", "top_p"):
        if name in config:
            payload[name] = config[name]
    if config.get("thinking") is not None:
        thinking_key = str(config.get("thinking_template_key", "thinking"))
        payload["chat_template_kwargs"] = {thinking_key: bool(config["thinking"])}
    if extra_template_kwargs := config.get("chat_template_kwargs"):
        payload.setdefault("chat_template_kwargs", {}).update(extra_template_kwargs)
    headers = {
        "Authorization": f"Bearer {endpoint['api_key']}",
        "Content-Type": "application/json",
    }
    if bool(config.get("sticky_session", True)):
        session_header = str(config.get("sticky_session_header", "x-litellm-session-id"))
        headers[session_header] = session_id
    last_error: BaseException | None = None
    attempts = max(1, int(config.get("request_retries", 10)))
    retry_delay = float(config.get("request_retry_delay_seconds", 10))
    for attempt in range(attempts):
        try:
            response = _json_request(
                "POST",
                _model_url(str(endpoint["base_url"])),
                payload=payload,
                headers=headers,
                timeout=float(config.get("request_timeout_seconds", 1200)),
            )
            choices = response.get("choices")
            if not isinstance(choices, list) or not choices:
                raise RuntimeError(f"Model response has no choices: {response}")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise RuntimeError(f"Model response has no message: {response}")
            return {"message": message, "usage": response.get("usage", {})}
        except (json.JSONDecodeError, RetryableRolloutError, HTTPStatusError) as error:
            last_error = error
            if isinstance(error, HTTPStatusError):
                body = error.body.lower()
                if any(pattern in body for pattern in _CONTEXT_WINDOW_ERROR_PATTERNS):
                    raise ContextWindowExceeded(str(error)) from error
                if 400 <= error.status < 500 and error.status not in {408, 409, 429}:
                    raise ModelProviderError(str(error)) from error
            if attempt < attempts - 1:
                time.sleep(retry_delay)
    raise ModelProviderError(f"Model request failed after {attempts} attempts: {last_error}")


def _assistant_message(raw: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if raw.get("content") is not None:
        message["content"] = raw["content"]
    reasoning = raw.get("reasoning_content")
    if reasoning is None:
        reasoning = raw.get("reasoning")
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    if raw.get("tool_calls"):
        message["tool_calls"] = raw["tool_calls"]
    return message


def _invoke_tool_call(
    service: ToolathlonService,
    execution: Execution,
    tool_call: dict[str, Any],
    dispatch_names: dict[str, str],
    input_schemas: dict[str, dict[str, Any]],
    max_observation_chars: int,
    local_tools: HistoricalLocalTools,
    active_turn_count: int,
    accept_legacy_tool_names: bool,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    call_id = str(tool_call.get("id", ""))
    function = tool_call.get("function") or {}
    exposed_name = str(function.get("name", ""))
    service_name = _resolve_dispatch_name(
        exposed_name,
        dispatch_names,
        accept_legacy_names=accept_legacy_tool_names,
    )
    arguments_value = function.get("arguments") or "{}"
    arguments_text = (
        arguments_value
        if isinstance(arguments_value, str)
        else json.dumps(arguments_value, ensure_ascii=False, default=str)
    )
    try:
        if service_name is None:
            content = f"Tool {exposed_name} not found in agent Assistant"
            tool_result = {"is_error": True, "result": content}
            message = {
                "role": "tool",
                "tool_call_id": call_id,
                "content": content,
            }
            record = {
                "tool_call_id": call_id,
                "exposed_name": exposed_name,
                "service_name": None,
                "arguments": arguments_text,
                "result": tool_result,
                "content": content,
                "message": message,
            }
            return message, record, False
        if isinstance(arguments_value, dict):
            arguments = arguments_value
        elif isinstance(arguments_value, str):
            arguments = json.loads(arguments_text)
        else:
            raise ValueError(f"arguments must be a JSON string or object, got {type(arguments_value).__name__}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must decode to an object")
        if service_name.startswith("virtual:"):
            result = local_tools.invoke(service_name.removeprefix("virtual:"), arguments, active_turn_count)
            tool_result = {"is_error": False, "result": result}
            content = str(result)
        else:
            if not service_name.startswith("local-"):
                input_schema = input_schemas.get(exposed_name) or input_schemas.get(
                    _model_tool_name(exposed_name),
                    {},
                )
                arguments = _coerce_stringified_json_value(arguments, input_schema)
            tool_result = service.call_tool(execution, service_name, arguments)
            if service_name.startswith("local-"):
                content = str(tool_result.get("result", ""))
            else:
                result = tool_result.get("result", "")
                text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
                model_payload = {
                    "result": json.dumps(
                        {"type": "text", "text": text, "annotations": None},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                }
                content = local_tools.format_tool_output(model_payload, max_observation_chars)
    except (json.JSONDecodeError, ValueError) as error:
        tool_result = {"is_error": True, "result": f"Invalid tool arguments: {error}"}
        content = str(tool_result["result"])
    except HTTPStatusError as error:
        if not 400 <= error.status < 500:
            raise
        tool_result = {"is_error": True, "result": str(error)}
        content = str(error)
    message = {
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
    }
    record = {
        "tool_call_id": call_id,
        "exposed_name": exposed_name,
        "service_name": service_name,
        "arguments": arguments_text,
        "result": tool_result,
        "content": content,
        "message": message,
    }
    claimed_done = service_name in {"local-claim_done", "local__claim_done"}
    return message, record, claimed_done


def _active_messages(
    system_prompt: str,
    sequence_user_message: str | None,
    active_turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if sequence_user_message is not None:
        messages.append({"role": "user", "content": sequence_user_message})
    for turn in active_turns:
        messages.append(turn["assistant"])
        messages.extend(record["message"] for record in turn.get("tool_results") or [])
    return messages


def run_rollout(request: dict[str, Any]) -> dict[str, Any]:
    started_at = time.time()
    task_id = str(request["task_id"])
    service = ToolathlonService(request["service"])
    task = request["task"]
    schemas = json.loads(Path(request["tool_schemas_path"]).read_text())
    execution: Execution | None = None
    messages: list[dict[str, Any]] = []
    trajectory: list[dict[str, Any]] = []
    active_turns: list[dict[str, Any]] = []
    context_resets: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        execution = service.start(
            task_id,
            {
                "runner": "prime-rl-toolathlon-vmvm",
                "trial": request.get("trial", 0),
                "attempt": request.get("attempt", 1),
            },
        )
        task, task_drift = _effective_task(execution, task)
        live_tools = _find_field(
            [execution.ready_payload, execution.start_payload],
            ("tools", "tool_schemas", "available_tools"),
        )
        if request["benchmark"].get("tool_source") == "live":
            if not isinstance(live_tools, list):
                raise RuntimeError(f"Toolathlon service returned no live tools for {task_id}")
            tools, dispatch_names = _build_live_tools(task, live_tools)
            task_drift["tool_source"] = "live"
            task_drift["live_tool_count"] = len(live_tools)
            task_drift["missing_historical_tools"] = []
            task_drift["extra_live_tools"] = []
        else:
            tools, dispatch_names = _build_static_tools(task, schemas)
        input_schemas = {str(tool["function"]["name"]): tool["function"].get("parameters") or {} for tool in tools}
        if isinstance(live_tools, list) and request["benchmark"].get("tool_source") != "live":
            live_tool_names = {str(tool.get("name", "")) for tool in live_tools if isinstance(tool, dict)}
            historical_tool_names = {target for target in dispatch_names.values() if not target.startswith("virtual:")}
            task_drift["missing_historical_tools"] = sorted(historical_tool_names - live_tool_names)
            task_drift["extra_live_tools"] = sorted(live_tool_names - historical_tool_names)
        system_prompt = _system_prompt(task, dispatch_names)
        description = _task_description(task)
        sequence_user_message: str | None = description
        messages = _active_messages(system_prompt, sequence_user_message, active_turns)
        local_tools = HistoricalLocalTools(
            context_limit=int(request["model_settings"].get("context_window", 262144)),
            workspace=Path("/workspace/dumps/workspace"),
        )
        session_id = f"toolathlon-{task_id}-{request.get('trial', 0)}-{request.get('attempt', 1)}"
        termination_reason = "max_steps"
        for step in range(1, int(request["benchmark"]["max_steps"]) + 1):
            try:
                completion = _model_completion(
                    request["model"],
                    messages,
                    tools,
                    request["model_settings"],
                    session_id,
                )
            except ContextWindowExceeded as error:
                sequence_user_message = local_tools.forced_reset_message(
                    description,
                    str(error),
                    len(active_turns),
                )
                context_resets.append(
                    {
                        "step": step,
                        "active_turns": len(active_turns),
                        "reason": str(error),
                    }
                )
                active_turns = []
                messages = _active_messages(system_prompt, sequence_user_message, active_turns)
                continue
            raw_message = completion["message"]
            assistant = _assistant_message(raw_message)
            messages.append(assistant)
            local_tools.set_last_usage(completion.get("usage", {}))
            for key in usage:
                usage[key] += int(completion.get("usage", {}).get(key) or 0)
            turn = {
                "step": step,
                "assistant": assistant,
                "tool_results": [],
            }
            tool_calls = raw_message.get("tool_calls") or []
            if not tool_calls:
                trajectory.append(turn)
                termination_reason = "assistant_final"
                break
            invoke = functools.partial(
                _invoke_tool_call,
                service,
                execution,
                dispatch_names=dispatch_names,
                input_schemas=input_schemas,
                max_observation_chars=int(request["benchmark"].get("max_observation_chars", 100000)),
                local_tools=local_tools,
                active_turn_count=len(active_turns),
                accept_legacy_tool_names=bool(request["model_settings"].get("accept_legacy_tool_names", False)),
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
                outcomes = list(executor.map(invoke, tool_calls))
            claimed_done = False
            for tool_message, tool_record, tool_claimed_done in outcomes:
                messages.append(tool_message)
                turn["tool_results"].append(tool_record)
                claimed_done = claimed_done or tool_claimed_done
            trajectory.append(turn)
            local_tools.record_turn(turn)
            active_turns.append(turn)
            active_turns, preserve_user, truncation = local_tools.apply_pending_truncation(active_turns)
            if truncation is not None:
                if not preserve_user:
                    sequence_user_message = None
                messages = _active_messages(system_prompt, sequence_user_message, active_turns)
            if claimed_done:
                termination_reason = "claim_done"
                break
        grade = service.grade(execution)
        passed = _grade_passed(grade)
        return {
            "schema_version": 1,
            "status": "completed",
            "task_id": task_id,
            "trial": int(request.get("trial", 0)),
            "reward": int(passed),
            "grade": grade,
            "termination_reason": termination_reason,
            "usage": usage,
            "duration_seconds": time.time() - started_at,
            "trajectory": trajectory,
            "context": {
                "resets": context_resets,
                "truncation_history": local_tools.truncation_history,
            },
            "service": {
                "server_url": execution.server_url,
                "execution_id": execution.execution_id,
                "task": task,
                "task_drift": task_drift,
            },
            "config_fingerprint": request["config_fingerprint"],
        }
    finally:
        if execution is not None:
            service.delete(execution)


def inspect_task(task_id: str, service_config: dict[str, Any]) -> dict[str, Any]:
    service = ToolathlonService(service_config)
    execution: Execution | None = None
    try:
        execution = service.start(task_id, {"runner": "prime-rl-toolathlon-vmvm-inspect"})
        raw_tools = _find_field(
            [execution.ready_payload, execution.start_payload],
            ("tools", "tool_schemas", "available_tools"),
        )
        workspace_listing = service.call_tool(
            execution,
            "filesystem-list_directory",
            {"path": "/workspace/dumps/workspace"},
        )
        tool_names = {
            str(tool.get("name", "")) for tool in raw_tools if isinstance(raw_tools, list) and isinstance(tool, dict)
        }
        python_inspection = None
        if "local-python-execute" in tool_names:
            python_inspection = service.call_tool(
                execution,
                "local-python-execute",
                {
                    "code": """\
import json
import os
from pathlib import Path

roots = {}
for root in (Path.cwd(), Path('/workspace'), Path('/opt'), Path('/app')):
    try:
        roots[str(root)] = sorted(path.name for path in root.iterdir())[:200]
    except OSError as error:
        roots[str(root)] = f'{type(error).__name__}: {error}'
print(json.dumps({'cwd': os.getcwd(), 'roots': roots}, sort_keys=True))
""",
                    "filename": "inspect_environment.py",
                    "timeout": 30,
                },
            )
        claim_done = service.call_tool(execution, "local-claim_done", {})
        grade = service.grade(execution)
        return {
            "server_url": execution.server_url,
            "execution_id": execution.execution_id,
            "start_payload_keys": sorted(execution.start_payload),
            "ready_payload_keys": sorted(execution.ready_payload),
            "start_payload": {
                key: value
                for key, value in execution.start_payload.items()
                if key not in {"tools", "tool_schemas", "available_tools"}
            },
            "ready_payload": {
                key: value
                for key, value in execution.ready_payload.items()
                if key not in {"tools", "tool_schemas", "available_tools"}
            },
            "tool_count": len(raw_tools) if isinstance(raw_tools, list) else None,
            "tool_names": sorted(tool_names),
            "tool_sample": raw_tools[:3] if isinstance(raw_tools, list) else raw_tools,
            "workspace_listing": workspace_listing,
            "python_inspection": python_inspection,
            "claim_done": claim_done,
            "grade": grade,
        }
    finally:
        if execution is not None:
            service.delete(execution)


def probe_start_request(task_id: str, service_config: dict[str, Any]) -> dict[str, Any]:
    service = ToolathlonService(service_config)
    errors: dict[str, str] = {}
    for server_url in service.server_urls:
        execution: Execution | None = None
        try:
            start_payload = _json_request(
                "POST",
                f"{server_url}/v3/tasks/{task_id}/start",
                payload={
                    "model_name": service.model_name,
                    "debug": service.debug,
                    "metadata": {"runner": "prime-rl-toolathlon-vmvm-start-probe"},
                },
                timeout=30,
                opener=service.opener,
            )
            execution_id = str(start_payload.get("execution_id", ""))
            if not execution_id:
                raise RuntimeError("Start response had no execution_id")
            execution = Execution(
                server_url=server_url,
                execution_id=execution_id,
                task_id=task_id,
                start_payload=start_payload,
                ready_payload={},
            )
            return {"server_url": server_url, "start_payload": start_payload}
        except Exception as error:
            errors[server_url] = f"{type(error).__name__}: {error}"
        finally:
            if execution is not None:
                service.delete(execution)
    raise RuntimeError(f"No v3 endpoint accepted {task_id}: {errors}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--inspect-task")
    parser.add_argument("--probe-start-task")
    args = parser.parse_args()
    if args.inspect_task and args.probe_start_task:
        parser.error("--inspect-task and --probe-start-task are mutually exclusive")
    service_config = {
        "http_proxy_url": "http://47.253.57.66:8080",
        "server_urls": [
            "http://47.253.57.66:8080",
            "http://47.253.57.66:8082",
            "http://47.253.57.66:8084",
            "http://47.253.57.66:8086",
            "http://47.253.47.223:8080",
            "http://47.253.142.107:8082",
        ],
        "model_name": "Kimi-K2.6",
        "start_timeout_seconds": 1800,
    }
    if args.probe_start_task:
        print(
            json.dumps(
                probe_start_request(args.probe_start_task, service_config),
                indent=2,
                default=str,
            )
        )
        return 0
    if args.inspect_task:
        print(json.dumps(inspect_task(args.inspect_task, service_config), indent=2, default=str))
        return 0
    if args.request is None or args.result is None:
        parser.error("--request and --result are required unless --inspect-task is used")
    request = json.loads(args.request.read_text())

    def handle_timeout(_signum: int, _frame: Any) -> None:
        raise TaskWallclockTimeout(f"Task exceeded {request['benchmark']['task_timeout_seconds']} seconds")

    signal.signal(signal.SIGALRM, handle_timeout)
    signal.alarm(int(request["benchmark"]["task_timeout_seconds"]))
    try:
        result = run_rollout(request)
        exit_code = 0
    except TaskWallclockTimeout as error:
        result = {
            "schema_version": 1,
            "status": "model_timeout",
            "task_id": request.get("task_id"),
            "trial": request.get("trial", 0),
            "reward": 0,
            "config_fingerprint": request.get("config_fingerprint"),
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        }
        exit_code = 0
    except ModelProviderError as error:
        result = {
            "schema_version": 1,
            "status": "model_error",
            "task_id": request.get("task_id"),
            "trial": request.get("trial", 0),
            "reward": 0,
            "config_fingerprint": request.get("config_fingerprint"),
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        }
        exit_code = 0
    except RetryableRolloutError as error:
        result = {
            "schema_version": 1,
            "status": "retryable_error",
            "task_id": request.get("task_id"),
            "trial": request.get("trial", 0),
            "reward": None,
            "config_fingerprint": request.get("config_fingerprint"),
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        }
        exit_code = EXIT_RETRYABLE
    except HTTPStatusError as error:
        model_error = error.status in {400, 422}
        result = {
            "schema_version": 1,
            "status": "model_error" if model_error else "fatal_error",
            "task_id": request.get("task_id"),
            "trial": request.get("trial", 0),
            "reward": 0 if model_error else None,
            "config_fingerprint": request.get("config_fingerprint"),
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        }
        exit_code = 0 if model_error else EXIT_FATAL
    except Exception as error:
        result = {
            "schema_version": 1,
            "status": "fatal_error",
            "task_id": request.get("task_id"),
            "trial": request.get("trial", 0),
            "reward": None,
            "config_fingerprint": request.get("config_fingerprint"),
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        }
        exit_code = EXIT_FATAL
    finally:
        signal.alarm(0)
    _write_json(args.result, result)
    print(
        json.dumps({key: result.get(key) for key in ("status", "task_id", "trial", "reward")}),
        flush=True,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
