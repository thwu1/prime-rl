import json
import uuid
from pathlib import Path
from typing import Any

from pier.models.agent.context import AgentContext
from pier.models.trajectories import (
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from pier.utils.trajectory_metrics import (
    extra_with_context_metrics,
    peak_context_tokens_from_steps,
    populate_context_from_final_metrics,
)


def _tool_arguments(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {"value": value}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _usage_metrics(message: dict[str, Any]) -> Metrics | None:
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    extra = {
        key: usage[key]
        for key in ("reasoning_tokens", "context_window", "response_id")
        if usage.get(key) not in (None, "", 0)
    }
    return Metrics(
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        cached_tokens=usage.get("cache_read_tokens"),
        cost_usd=message.get("cost_usd"),
        extra=extra or None,
    )


def _tool_calls(message: dict[str, Any]) -> list[ToolCall] | None:
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return None
    calls = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            continue
        call_id = raw_call.get("id")
        name = raw_call.get("name")
        if not isinstance(call_id, str) or not isinstance(name, str):
            continue
        calls.append(
            ToolCall(
                tool_call_id=call_id,
                function_name=name,
                arguments=_tool_arguments(raw_call.get("arguments", "{}")),
            )
        )
    return calls or None


def _attach_observation(steps: list[Step], message: dict[str, Any]) -> None:
    call_id = message.get("tool_call_id")
    if not isinstance(call_id, str):
        raise ValueError("OpenHands tool message is missing tool_call_id")
    for step in reversed(steps):
        if step.source != "agent" or not step.tool_calls:
            continue
        if call_id not in {call.tool_call_id for call in step.tool_calls}:
            continue
        result = ObservationResult(
            source_call_id=call_id,
            content=str(message.get("content", "")),
            extra={"tool_name": message.get("name")} if message.get("name") else None,
        )
        if step.observation is None:
            step.observation = Observation(results=[result])
        else:
            step.observation.results.append(result)
        return
    raise ValueError(f"OpenHands tool result has no matching call: {call_id}")


def convert_openhands_trajectory(raw: dict[str, Any]) -> Trajectory:
    messages = raw.get("messages")
    if not isinstance(messages, list):
        raise TypeError("OpenHands trajectory messages must be a list")

    steps: list[Step] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            _attach_observation(steps, message)
            continue
        if role not in {"system", "user", "assistant"}:
            continue
        source = "agent" if role == "assistant" else role
        step_kwargs: dict[str, Any] = {
            "step_id": len(steps) + 1,
            "timestamp": message.get("timestamp"),
            "source": source,
            "message": str(message.get("content", "")),
        }
        if source == "agent":
            step_kwargs.update(
                {
                    "model_name": raw.get("model_name"),
                    "reasoning_content": message.get("reasoning_content"),
                    "tool_calls": _tool_calls(message),
                    "metrics": _usage_metrics(message),
                    "llm_call_count": 1,
                }
            )
        steps.append(Step(**step_kwargs))

    metrics = raw.get("metrics") or {}
    accumulated = metrics.get("accumulated_token_usage") or {}
    reasoning_messages = sum(
        1
        for message in messages
        if isinstance(message, dict)
        and message.get("role") == "assistant"
        and isinstance(message.get("reasoning_content"), str)
        and message["reasoning_content"].strip()
    )
    assistant_messages = sum(
        1 for message in messages if isinstance(message, dict) and message.get("role") == "assistant"
    )
    final_extra = extra_with_context_metrics(
        {
            "exit_status": raw.get("exit_status"),
            "reasoning_messages": reasoning_messages,
            "assistant_messages_missing_reasoning": assistant_messages - reasoning_messages,
            "reasoning_tokens": accumulated.get("reasoning_tokens", 0),
            "openhands_execution_status": raw.get("execution_status"),
        },
        peak_context_tokens=peak_context_tokens_from_steps(steps),
        summarization_count=0,
    )
    final_metrics = FinalMetrics(
        total_prompt_tokens=accumulated.get("prompt_tokens", 0),
        total_completion_tokens=accumulated.get("completion_tokens", 0),
        total_cached_tokens=accumulated.get("cache_read_tokens", 0),
        total_cost_usd=metrics.get("accumulated_cost"),
        total_steps=len(steps),
        extra=final_extra,
    )
    return Trajectory(
        schema_version="ATIF-v1.7",
        session_id=str(uuid.uuid4()),
        agent=Agent(
            name="openhands-sdk",
            version=str(raw.get("agent_version", "unknown")),
            model_name=raw.get("model_name"),
            extra={
                "original_format": raw.get("schema_version"),
                "max_iterations": raw.get("max_iterations"),
                "stuck_detection": raw.get("stuck_detection"),
                "terminal_type": raw.get("terminal_type"),
            },
        ),
        steps=steps,
        final_metrics=final_metrics,
        notes="Converted from the standalone DeepSWE OpenHands SDK harness",
    )


def convert_and_save_openhands_trajectory(
    source: Path,
    destination: Path,
) -> Trajectory:
    trajectory = convert_openhands_trajectory(json.loads(source.read_text()))
    destination.write_text(json.dumps(trajectory.to_json_dict(), indent=2) + "\n")
    return trajectory


def populate_context_from_openhands(
    context: AgentContext,
    trajectory: Trajectory,
) -> None:
    if trajectory.final_metrics is not None:
        populate_context_from_final_metrics(context, trajectory.final_metrics)
    context.n_agent_steps = sum(step.source == "agent" for step in trajectory.steps)
