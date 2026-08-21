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
        self._strip_old_token_fields(message_dicts)
        params = {
            "messages": message_dicts,
            **self.llm._nemo_gym_llm_kwargs,
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

        response_id = response_json.get("id", "unknown")
        timestamp = datetime.now(timezone.utc).isoformat()
        self.llm.metrics.add_response_latency(latency, response_id, timestamp=timestamp)
        self._record_usage(response_json, response_id)

        response_message = response_json["choices"][0]["message"]
        self._fold_reasoning_into_content(response_message)
        response = ModelResponse.model_validate(response_json)
        provider_fields = {}
        if response_message.get("prompt_token_ids"):
            provider_fields = {
                "prompt_token_ids": response_message["prompt_token_ids"],
                "generation_token_ids": response_message["generation_token_ids"],
                "generation_log_probs": response_message["generation_log_probs"],
            }
            response._provider_specific_fields = provider_fields
        self._log_completion(messages, response_json, provider_fields, params)
        return response

    @staticmethod
    def _fold_reasoning_into_content(message: dict) -> None:
        if message.get("content"):
            return
        for field in ("reasoning_content", "reasoning"):
            reasoning = message.get(field)
            if isinstance(reasoning, str) and reasoning.strip():
                message["content"] = reasoning
                return

    @staticmethod
    def _strip_old_token_fields(messages: list[dict]) -> None:
        fields = (
            "prompt_token_ids",
            "generation_token_ids",
            "generation_log_probs",
        )
        found_latest = False
        for message in reversed(messages):
            if found_latest:
                for field in fields:
                    message.pop(field, None)
            elif all(field in message for field in fields):
                found_latest = True

    def _record_usage(self, response: dict, response_id: str) -> None:
        usage = response.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        message = response["choices"][0]["message"]
        prompt_ids = message.get("prompt_token_ids") or []
        generation_ids = message.get("generation_token_ids") or []
        self.llm.metrics.add_token_usage(
            prompt_tokens=usage.get("prompt_tokens", len(prompt_ids)),
            completion_tokens=usage.get("completion_tokens", len(generation_ids)),
            cache_read_tokens=details.get("cached_tokens", 0),
            cache_write_tokens=0,
            context_window=0,
            response_id=response_id,
        )

    def _log_completion(
        self,
        messages: list["Message"],
        response: dict,
        provider_fields: dict,
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
            "provider_specific_fields": provider_fields,
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
