from __future__ import annotations

import asyncio
import json
import logging
from time import perf_counter
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from stirrup.clients.utils import to_openai_messages, to_openai_tools
from stirrup.core.exceptions import ContextOverflowError
from stirrup.core.models import (
    AssistantMessage,
    ChatMessage,
    LLMClient,
    Reasoning,
    TokenUsage,
    Tool,
    ToolCall,
    ToolMessage,
    UserMessage,
)

logger = logging.getLogger(__name__)


class ModelRequestError(RuntimeError):
    pass


class ModelFatalError(RuntimeError):
    pass


def _retryable(error: BaseException) -> bool:
    if isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)):
        return True
    return isinstance(error, APIStatusError) and (error.status_code in {408, 409, 429} or error.status_code >= 500)


def _terminal_generation_error(error: APIStatusError) -> bool:
    if error.status_code not in {400, 413, 422}:
        return False
    detail = str(error).lower()
    return any(
        marker in detail
        for marker in (
            "context length",
            "context window",
            "input length",
            "maximum context",
            "max_completion_tokens",
            "max_tokens",
            "too many tokens",
        )
    )


def _restore_tool_messages_for_model(messages: list[ChatMessage]) -> list[ChatMessage]:
    pending_tool_call_ids: set[str] = set()
    restored: list[ChatMessage] = []
    for message in messages:
        if isinstance(message, AssistantMessage):
            pending_tool_call_ids = {
                tool_call.tool_call_id for tool_call in message.tool_calls if tool_call.tool_call_id
            }
            restored.append(message)
            continue
        tool_call_id = getattr(message, "tool_call_id", None)
        if isinstance(message, UserMessage) and tool_call_id in pending_tool_call_ids:
            restored.append(
                ToolMessage(
                    content=message.content,
                    name=getattr(message, "name", None),
                    success=bool(getattr(message, "success", False)),
                    args_was_valid=bool(getattr(message, "args_was_valid", True)),
                    tool_call_id=tool_call_id,
                    tool_start_time=getattr(message, "tool_start_time", None),
                    tool_end_time=getattr(message, "tool_end_time", None),
                )
            )
            pending_tool_call_ids.discard(tool_call_id)
            continue
        restored.append(message)
    return restored


class GDPValPolicyClient(LLMClient):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        context_window: int,
        max_completion_tokens: int,
        completion_token_buffer: int,
        temperature: float,
        top_p: float,
        thinking: bool,
        request_retries: int,
        request_retry_delay_seconds: float,
        request_timeout_seconds: float,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        self._context_window = context_window
        self._max_completion_tokens = max_completion_tokens
        self._completion_token_buffer = completion_token_buffer
        self._temperature = temperature
        self._top_p = top_p
        self._thinking = thinking
        self._request_retries = request_retries
        self._request_retry_delay_seconds = request_retry_delay_seconds
        self._extra_headers = extra_headers or {}
        self._client = AsyncOpenAI(
            base_url=base_url.rstrip("/") + "/v1/",
            api_key=api_key,
            timeout=request_timeout_seconds,
            max_retries=0,
            http_client=httpx.AsyncClient(trust_env=False),
        )

    @property
    def max_tokens(self) -> int:
        return self._context_window

    @property
    def model_slug(self) -> str:
        return self._model

    @staticmethod
    def _estimate_input_tokens(messages: list[dict[str, Any]], tools: dict[str, Tool]) -> int:
        payload = {"messages": messages, "tools": to_openai_tools(tools) if tools else []}
        return max(1, len(json.dumps(payload, ensure_ascii=False, default=str)) // 3)

    async def generate(self, messages: list[ChatMessage], tools: dict[str, Tool]) -> AssistantMessage:
        provider_messages = to_openai_messages(_restore_tool_messages_for_model(messages))
        estimated_input = self._estimate_input_tokens(provider_messages, tools)
        available = self._context_window - estimated_input - self._completion_token_buffer
        completion_limit = min(self._max_completion_tokens, max(1024, available))
        request: dict[str, Any] = {
            "model": self._model,
            "messages": provider_messages,
            "temperature": self._temperature,
            "top_p": self._top_p,
            "max_completion_tokens": completion_limit,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": self._thinking}},
        }
        if self._extra_headers:
            request["extra_headers"] = self._extra_headers
        if tools:
            request["tools"] = to_openai_tools(tools)
            request["tool_choice"] = "auto"

        attempts = max(1, self._request_retries)
        start = perf_counter()
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.chat.completions.create(**request)
                if not response.choices:
                    raise ModelRequestError("Model response has no choices")
                choice = response.choices[0]
                message = choice.message
                break
            except Exception as error:
                if not _retryable(error):
                    if isinstance(error, APIStatusError) and _terminal_generation_error(error):
                        raise ContextOverflowError(
                            f"Model API reported a context overflow: HTTP {error.status_code}: {error}"
                        ) from error
                    if isinstance(error, APIStatusError):
                        raise ModelFatalError(
                            f"Deterministic model API failure: HTTP {error.status_code}: {error}"
                        ) from error
                    raise ModelRequestError(
                        f"Terminal model generation failure: {type(error).__name__}: {error}"
                    ) from error
                if attempt == attempts:
                    raise ModelRequestError(
                        f"Model request failed after {attempt} attempt(s): {type(error).__name__}: {error}"
                    ) from error
                await asyncio.sleep(self._request_retry_delay_seconds * attempt)
        else:
            raise AssertionError("unreachable")

        end = perf_counter()
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        reasoning_tokens = 0
        if usage and getattr(usage, "completion_tokens_details", None):
            reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0
        reasoning_value = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
        reasoning = Reasoning(content=str(reasoning_value)) if reasoning_value else None
        tool_calls = [
            ToolCall(
                tool_call_id=call.id,
                name=call.function.name,
                arguments=call.function.arguments or "",
            )
            for call in (message.tool_calls or [])
        ]
        return AssistantMessage(
            reasoning=reasoning,
            content=message.content or "",
            tool_calls=tool_calls,
            token_usage=TokenUsage(
                input=input_tokens,
                answer=max(0, output_tokens - reasoning_tokens),
                reasoning=reasoning_tokens,
            ),
            request_start_time=start,
            request_end_time=end,
        )
