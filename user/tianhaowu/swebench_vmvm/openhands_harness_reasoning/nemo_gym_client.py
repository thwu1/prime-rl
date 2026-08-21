import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from litellm import ChatCompletionToolParam
    from openhands.core.message import Message
    from openhands.llm.llm import LLM, ModelResponse


class NemoGymClient:
    def __init__(self, llm: "LLM") -> None:
        self.llm = llm
        self.cookies = httpx.Cookies()
        self.client_id = str(uuid.uuid4())
        self.reasoning_by_tool_call: dict[str, tuple[str, object]] = {}
        self.reasoning_by_generation: dict[tuple[int, ...], tuple[str, object]] = {}
        self.audit = {
            "model_calls": 0,
            "responses_with_reasoning": 0,
            "restored_history_messages": 0,
            "restored_by_tool_call": 0,
            "restored_by_generation_ids": 0,
        }

    async def model_call(
        self,
        messages: list["Message"],
        tools: "list[ChatCompletionToolParam] | None" = None,
    ) -> "ModelResponse":
        start_time = time.time()
        response = await self._post_completion(messages, tools)
        self._update_model_call_time(start_time)
        return response

    async def _post_completion(
        self,
        messages: list["Message"],
        tools: "list[ChatCompletionToolParam] | None" = None,
    ) -> "ModelResponse":
        from openhands.llm.llm import ModelResponse

        message_dicts = [message.model_dump() for message in messages]
        self._restore_reasoning(message_dicts)
        self._strip_token_fields(message_dicts)
        params = {
            "messages": message_dicts,
            **self.llm._nemo_gym_llm_kwargs,
            "return_token_ids": True,
        }
        params = {key: value for key, value in params.items() if value is not None}
        if "max_completion_tokens" in params:
            params["max_tokens"] = params.pop("max_completion_tokens")
        top_k = params.get("top_k")
        if isinstance(top_k, float) and top_k.is_integer():
            params["top_k"] = int(top_k)
        if tools:
            params["tools"] = tools

        api_key = self.llm.config.api_key
        headers = {
            "Authorization": f"Bearer {api_key.get_secret_value() if api_key else ''}",
            "X-Client-ID": self.client_id,
        }
        url = self.llm.config.base_url.rstrip("/") + "/chat/completions"
        latency_start = time.perf_counter()
        async with httpx.AsyncClient(
            cookies=self.cookies,
            timeout=self.llm.config.timeout or 7200,
            trust_env=False,
        ) as client:
            raw_response = await client.post(url, headers=headers, json=params)
            raw_response.raise_for_status()
            self.cookies.update(raw_response.cookies)
        response_json = raw_response.json()
        latency = time.perf_counter() - latency_start
        self.audit["model_calls"] += 1

        response_id = response_json.get("id", "unknown")
        timestamp = datetime.now(timezone.utc).isoformat()
        self.llm.metrics.add_response_latency(latency, response_id, timestamp=timestamp)
        self._record_usage(response_json, response_id)

        choice = response_json["choices"][0]
        response_message = choice["message"]
        original_content = response_message.get("content")
        reasoning = response_message.get("reasoning_content") or response_message.get("reasoning")
        generation_ids = choice.get("token_ids") or response_message.get("generation_token_ids")
        if isinstance(reasoning, str) and reasoning.strip():
            self.audit["responses_with_reasoning"] += 1
            record = (reasoning, original_content)
            for tool_call in response_message.get("tool_calls") or []:
                call_id = tool_call.get("id")
                if call_id:
                    self.reasoning_by_tool_call[call_id] = record
            if generation_ids:
                self.reasoning_by_generation[tuple(generation_ids)] = record
        self._fold_reasoning_into_content(response_message)

        response = ModelResponse.model_validate(response_json)
        prompt_ids = response_json.get("prompt_token_ids") or response_message.get("prompt_token_ids")
        if prompt_ids or generation_ids:
            response._provider_specific_fields = {
                "prompt_token_ids": prompt_ids,
                "generation_token_ids": generation_ids,
            }
        self._write_audit()
        self._log_completion(messages, response_json, params)
        return response

    def _restore_reasoning(self, messages: list[dict]) -> None:
        for message in messages:
            if message.get("role") != "assistant":
                continue
            record = None
            for tool_call in message.get("tool_calls") or []:
                record = self.reasoning_by_tool_call.get(tool_call.get("id"))
                if record is not None:
                    self.audit["restored_by_tool_call"] += 1
                    break
            generation_ids = message.get("generation_token_ids")
            if record is None and generation_ids:
                record = self.reasoning_by_generation.get(tuple(generation_ids))
                if record is not None:
                    self.audit["restored_by_generation_ids"] += 1
            if record is None:
                continue
            reasoning, original_content = record
            message["reasoning_content"] = reasoning
            message["content"] = original_content
            self.audit["restored_history_messages"] += 1

    @staticmethod
    def _strip_token_fields(messages: list[dict]) -> None:
        for message in messages:
            for field in (
                "prompt_token_ids",
                "generation_token_ids",
                "generation_log_probs",
            ):
                message.pop(field, None)

    @staticmethod
    def _fold_reasoning_into_content(message: dict) -> None:
        if message.get("content"):
            return
        for field in ("reasoning_content", "reasoning"):
            reasoning = message.get(field)
            if isinstance(reasoning, str) and reasoning.strip():
                message["content"] = reasoning
                return

    def _record_usage(self, response: dict, response_id: str) -> None:
        usage = response.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        choice = response["choices"][0]
        message = choice["message"]
        prompt_ids = response.get("prompt_token_ids") or message.get("prompt_token_ids") or []
        generation_ids = choice.get("token_ids") or message.get("generation_token_ids") or []
        self.llm.metrics.add_token_usage(
            prompt_tokens=usage.get("prompt_tokens", len(prompt_ids)),
            completion_tokens=usage.get("completion_tokens", len(generation_ids)),
            cache_read_tokens=details.get("cached_tokens", 0),
            cache_write_tokens=0,
            context_window=0,
            response_id=response_id,
        )

    def _write_audit(self) -> None:
        target = "/tmp/openhands-reasoning-audit.json"
        descriptor, temporary = tempfile.mkstemp(dir="/tmp")
        with os.fdopen(descriptor, "w") as file:
            json.dump(self.audit, file)
        os.replace(temporary, target)

    def _log_completion(
        self,
        messages: list["Message"],
        response: dict,
        params: dict,
    ) -> None:
        folder = self.llm.config.log_completions_folder
        if not folder:
            return
        os.makedirs(folder, exist_ok=True)
        filename = f"{self.llm.config.model.replace('/', '__')}-{time.time()}.json"
        target = os.path.join(folder, filename)
        payload = {
            "messages": [message.model_dump() for message in messages],
            "response": response,
            "kwargs": {key: value for key, value in params.items() if key != "messages"},
            "timestamp": time.time(),
        }
        descriptor, temporary = tempfile.mkstemp(dir=folder)
        with os.fdopen(descriptor, "w") as file:
            json.dump(payload, file)
        os.replace(temporary, target)

    @staticmethod
    def _update_model_call_time(start_time: float) -> None:
        metrics_path = os.environ["NEMO_GYM_METRICS_FPATH"]
        with open(metrics_path) as file:
            metrics = json.load(file)
        metrics["total_model_call_time"] = metrics.get("total_model_call_time", 0.0) + (time.time() - start_time)
        with open(metrics_path, "w") as file:
            json.dump(metrics, file)
