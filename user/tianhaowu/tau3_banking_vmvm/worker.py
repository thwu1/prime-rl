from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

EXIT_FATAL = 70


class JudgeFormatError(RuntimeError):
    pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temporary, path)


def _llm_args(
    endpoint: str,
    role: str,
    trial_key: str,
    attempt: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "api_base": endpoint,
        "api_key": "vmvm-proxy",
        "temperature": config["temperature"],
        "num_retries": 0,
        "timeout": config["request_timeout_seconds"],
        "extra_headers": {
            "x-tau3-role": role,
            "x-tau3-trial": trial_key,
            "x-tau3-attempt": str(attempt),
            "x-litellm-session-id": f"tau3-{trial_key}-{role}",
        },
    }
    for key in ("top_p", "max_tokens"):
        if config.get(key) is not None:
            arguments[key] = config[key]
    extra_body: dict[str, Any] = {}
    if config.get("thinking") is not None:
        template_key = config.get("thinking_template_key", "enable_thinking")
        extra_body["chat_template_kwargs"] = {template_key: config["thinking"]}
    if config.get("skip_special_tokens") is not None:
        extra_body["skip_special_tokens"] = config["skip_special_tokens"]
    if extra_body:
        arguments["extra_body"] = extra_body
    return arguments


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and (status_code == 429 or status_code >= 500):
        return True
    retryable_names = {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "InternalServerError",
        "PoolTimeout",
        "RateLimitError",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "ServiceUnavailableError",
        "Timeout",
        "TransportError",
    }
    if type(error).__name__ in retryable_names:
        return True
    message = str(error).lower()
    return any(
        fragment in message
        for fragment in (
            "connection reset",
            "connection refused",
            "proxy transport failure",
            "service unavailable",
            "temporarily unavailable",
            "timed out",
            "timeout",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
        )
    )


def _is_model_output_error(error: BaseException) -> bool:
    if isinstance(error, (AssertionError, json.JSONDecodeError)):
        return True
    message = str(error).lower()
    if isinstance(error, ValueError) and "must have either content or tool_calls" in message:
        return True
    if type(error).__name__ == "ContextWindowExceededError":
        return True
    if type(error).__name__ != "BadRequestError":
        return False
    return "maximum context length" in message or "context_length_exceeded" in message


def _wait_for_proxy(api_base: str, timeout_seconds: float) -> bool:
    parsed = urllib.parse.urlsplit(api_base)
    health_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with opener.open(health_url, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if "</think>" in stripped:
        stripped = stripped.rsplit("</think>", maxsplit=1)[1].strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline < 0:
            raise json.JSONDecodeError("JSON code fence has no body", stripped, 0)
        stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
    object_start = stripped.find("{")
    if object_start < 0:
        raise json.JSONDecodeError("Judge response has no JSON object", stripped, 0)
    decoder = json.JSONDecoder()
    value, end = decoder.raw_decode(stripped[object_start:])
    trailing = stripped[object_start + end :].strip()
    if trailing and trailing != "```":
        raise json.JSONDecodeError("Unexpected content after judge JSON", stripped, object_start + end)
    if not isinstance(value, dict):
        raise json.JSONDecodeError("Judge response is not a JSON object", stripped, object_start)
    return json.dumps(value)


def _finish_reason(message: Any) -> str | None:
    try:
        return message.raw_data["choices"][0]["finish_reason"]
    except (AttributeError, IndexError, KeyError, TypeError):
        return None


def _generate_with_provider_retries(
    generate: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    retries: int,
    retry_delay_seconds: float,
    proxy_recovery_timeout_seconds: float,
    event_name: str,
) -> Any:
    for retry in range(retries + 1):
        try:
            return generate(*args, **kwargs)
        except Exception as error:
            if not _is_retryable(error) or retry == retries:
                raise
            api_base = kwargs.get("api_base")
            if isinstance(api_base, str):
                _wait_for_proxy(api_base, proxy_recovery_timeout_seconds)
            delay = retry_delay_seconds * (retry + 1)
            print(
                f"{event_name}_INFRA_RETRY attempt={retry + 1}/{retries} "
                f"delay={delay} error={type(error).__name__}: {error}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


def _install_empty_response_adapter(
    module: Any,
    attempts: int,
    provider_retries: int,
    retry_delay_seconds: float,
    proxy_recovery_timeout_seconds: float,
    event_name: str,
    *,
    retry_length: bool,
) -> None:
    original_generate = module.generate

    def generate_with_empty_retry(*args: Any, **kwargs: Any) -> Any:
        message = None
        for attempt in range(1, attempts + 1):
            message = _generate_with_provider_retries(
                original_generate,
                args,
                kwargs,
                provider_retries,
                retry_delay_seconds,
                proxy_recovery_timeout_seconds,
                event_name,
            )
            if message.has_content() or message.is_tool_call():
                return message
            finish_reason = _finish_reason(message)
            if finish_reason == "length" and not retry_length:
                return message
            event = "retry" if attempt < attempts else "hard_fail"
            print(
                f"{event_name} event={event} attempt={attempt}/{attempts} finish_reason={finish_reason}",
                file=sys.stderr,
                flush=True,
            )
        return message

    module.generate = generate_with_empty_retry


def _install_judge_adapter(
    module: Any,
    format_retries: int,
    provider_retries: int,
    retry_delay_seconds: float,
    proxy_recovery_timeout_seconds: float,
) -> None:
    original_generate = module.generate

    def generate_json(*args: Any, **kwargs: Any) -> Any:
        last_error: json.JSONDecodeError | None = None
        for attempt in range(1, format_retries + 1):
            message = _generate_with_provider_retries(
                original_generate,
                args,
                kwargs,
                provider_retries,
                retry_delay_seconds,
                proxy_recovery_timeout_seconds,
                "JUDGE",
            )
            try:
                message.content = _extract_json_object(message.content or "")
                return message
            except json.JSONDecodeError as error:
                last_error = error
                print(
                    f"JUDGE_FORMAT_RETRY attempt={attempt}/{format_retries} error={error}",
                    file=sys.stderr,
                    flush=True,
                )
        raise JudgeFormatError(f"Kimi judge returned invalid JSON after {format_retries} attempts: {last_error}")

    module.generate = generate_json


def run(request: dict[str, Any]) -> dict[str, Any]:
    os.environ["TAU2_DATA_DIR"] = request["tau2_data_dir"]

    from loguru import logger as tau_logger
    from tau2.agent import llm_agent as llm_agent_module
    from tau2.data_model.simulation import TextRunConfig
    from tau2.evaluator import evaluator_nl_assertions
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.runner.batch import run_single_task
    from tau2.runner.helpers import get_tasks
    from tau2.user import user_simulator as user_simulator_module

    tau_logger.remove()
    tau_logger.add(sys.stderr, level="CRITICAL")

    task_id = request["task_id"]
    trial = int(request["trial"])
    attempt = int(request["attempt"])
    trial_key = f"{task_id}.{trial}"
    policy = request["policy"]
    user = request["user"]
    judge = request["judge"]
    retry = request.get("retry", {})
    retry_delay_seconds = float(retry.get("provider_retry_delay_seconds", 1.0))
    proxy_recovery_timeout_seconds = float(retry.get("proxy_recovery_timeout_seconds", 300.0))

    tasks = get_tasks(
        task_set_name="banking_knowledge",
        task_split_name=None,
        task_ids=[task_id],
    )
    if len(tasks) != 1:
        raise ValueError(f"Expected exactly one task for {task_id}, found {len(tasks)}")

    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS = f"openai/{judge['model']}"
    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS = _llm_args(
        request["judge_base_url"], "judge", trial_key, attempt, judge
    )
    _install_empty_response_adapter(
        llm_agent_module,
        int(policy.get("empty_response_attempts", 1)),
        int(policy["request_retries"]),
        retry_delay_seconds,
        proxy_recovery_timeout_seconds,
        "EMPTY_AGENT_MESSAGE",
        retry_length=False,
    )
    _install_empty_response_adapter(
        user_simulator_module,
        int(user.get("empty_response_attempts", 1)),
        int(user["request_retries"]),
        retry_delay_seconds,
        proxy_recovery_timeout_seconds,
        "EMPTY_USER_MESSAGE",
        retry_length=True,
    )
    _install_judge_adapter(
        evaluator_nl_assertions,
        int(judge["format_retries"]),
        int(judge["request_retries"]),
        retry_delay_seconds,
        proxy_recovery_timeout_seconds,
    )

    run_config = TextRunConfig(
        domain="banking_knowledge",
        task_set_name="banking_knowledge",
        task_split_name=None,
        llm_agent=f"openai/{policy['model']}",
        llm_args_agent=_llm_args(request["policy_base_url"], "policy", trial_key, attempt, policy),
        llm_user=f"openai/{user['model']}",
        llm_args_user=_llm_args(request["user_base_url"], "user", trial_key, attempt, user),
        max_steps=request["benchmark"]["max_steps"],
        max_errors=request["benchmark"]["max_errors"],
        timeout=request["benchmark"]["simulation_timeout_seconds"],
        retrieval_config="bm25_grep",
        num_trials=1,
        max_concurrency=1,
        max_retries=0,
        hallucination_retries=0,
        seed=request["seed"],
        log_level="ERROR",
    )
    started_at = time.time()
    simulation = run_single_task(
        run_config,
        tasks[0],
        seed=request["seed"],
        evaluation_type=EvaluationType.ALL,
        verbose_logs=False,
    )
    simulation.trial = trial
    return {
        "schema_version": 1,
        "status": "completed",
        "task_id": task_id,
        "trial": trial,
        "seed": request["seed"],
        "reward": simulation.reward_info.reward,
        "termination_reason": simulation.termination_reason.value,
        "duration_seconds": time.time() - started_at,
        "source_commit": request["source_commit"],
        "config_fingerprint": request["config_fingerprint"],
        "simulation": simulation.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    try:
        result = run(request)
        exit_code = 0
    except Exception as error:
        provider_retries_exhausted = _is_retryable(error)
        model_error = provider_retries_exhausted or _is_model_output_error(error)
        status = "model_error" if model_error else "fatal_error"
        result = {
            "schema_version": 1,
            "status": status,
            "task_id": request.get("task_id"),
            "trial": request.get("trial"),
            "seed": request.get("seed"),
            "reward": 0.0 if model_error else None,
            "source_commit": request.get("source_commit"),
            "config_fingerprint": request.get("config_fingerprint"),
            "error": {
                "type": type(error).__name__,
                "module": type(error).__module__,
                "message": str(error),
                "provider_retries_exhausted": provider_retries_exhausted,
                "traceback": traceback.format_exc(),
            },
        }
        exit_code = 0 if model_error else EXIT_FATAL
    _write_json(args.result, result)
    print(json.dumps({key: result.get(key) for key in ("status", "task_id", "trial", "reward")}), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
