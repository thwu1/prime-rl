import argparse
import json
import os
from pathlib import Path
from typing import Any

from openhands.sdk import LLM, Agent, Conversation, LLMConvertibleEvent, Tool
from openhands.sdk.conversation.exceptions import ConversationRunError
from openhands.sdk.conversation.state import ConversationExecutionStatus
from openhands.sdk.event.conversation_error import ConversationErrorEvent
from openhands.sdk.llm import Message, TextContent, content_to_str
from openhands.sdk.llm.exceptions import LLMContextWindowExceedError
from openhands.sdk.llm.utils.model_features import SEND_REASONING_CONTENT_MODELS
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool
from pydantic import SecretStr

LOGS_DIR = Path(os.environ.get("DEEPSWE_OPENHANDS_LOGS_DIR", "/logs/agent"))
ACCEPTED_EXIT_STATUSES = {"Submitted", "LimitsExceeded", "ContextWindowExceeded"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    return parser.parse_args()


def _context_window_error(error: BaseException | None) -> bool:
    current = error
    while current is not None:
        if isinstance(current, LLMContextWindowExceedError):
            return True
        text = str(current).lower()
        if (
            "contextwindowexceeded" in text
            or ("maximum context length" in text and ("exceed" in text or "requested" in text))
            or ("context window" in text and "exceed" in text)
        ):
            return True
        if isinstance(current, ConversationRunError):
            current = current.original_exception
        else:
            current = current.__cause__
    return False


def _configure_reasoning_history(model: str, preserve_previous: bool) -> None:
    if preserve_previous:
        if model not in SEND_REASONING_CONTENT_MODELS:
            SEND_REASONING_CONTENT_MODELS.append(model)
        return
    while model in SEND_REASONING_CONTENT_MODELS:
        SEND_REASONING_CONTENT_MODELS.remove(model)


def _serializer_contract(llm: LLM, truncate_history_thinking: bool) -> dict[str, Any]:
    marker = "DEEPSWE_OPENHANDS_REASONING_HISTORY_MARKER"
    messages = [
        Message(role="system", content=[TextContent(text="system")]),
        Message(role="user", content=[TextContent(text="turn one")]),
        Message(
            role="assistant",
            content=[TextContent(text="tool call")],
            reasoning_content=marker,
        ),
        Message(role="user", content=[TextContent(text="turn two")]),
    ]
    formatted = llm.format_messages_for_llm(messages)
    preserved = formatted[2].get("reasoning_content") == marker
    expected_preserved = not truncate_history_thinking
    template_kwargs = llm.litellm_extra_body.get("chat_template_kwargs")
    expected = {
        "enable_thinking": True,
        "truncate_history_thinking": truncate_history_thinking,
    }
    report = {
        "model": llm.model,
        "reasoning_history_serialized": preserved,
        "expected_reasoning_history_serialized": expected_preserved,
        "chat_template_kwargs": template_kwargs,
        "expected_chat_template_kwargs": expected,
    }
    if preserved != expected_preserved or template_kwargs != expected:
        raise RuntimeError(f"OpenHands reasoning serializer contract failed: {report}")
    return report


def _serialize_messages(events: list[Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    convertible = [event for event in events if isinstance(event, LLMConvertibleEvent)]
    messages = LLMConvertibleEvent.events_to_messages(convertible)
    usages = metrics.get("token_usages") or []
    costs = metrics.get("costs") or []
    assistant_index = 0
    serialized = []
    for message in messages:
        item: dict[str, Any] = {
            "role": message.role,
            "content": "\n".join(content_to_str(message.content)),
        }
        if message.reasoning_content is not None:
            item["reasoning_content"] = message.reasoning_content
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
                for tool_call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            item["tool_call_id"] = message.tool_call_id
        if message.name is not None:
            item["name"] = message.name
        if message.role == "assistant":
            if assistant_index < len(usages):
                item["usage"] = usages[assistant_index]
            if assistant_index < len(costs):
                item["cost_usd"] = costs[assistant_index].get("cost")
            assistant_index += 1
        serialized.append(item)
    return serialized


def _classify_exit(events: list[Any], execution_status: str, error: BaseException | None) -> str:
    if execution_status == ConversationExecutionStatus.FINISHED.value:
        return "Submitted"
    if any(isinstance(event, ConversationErrorEvent) and event.code == "MaxIterationsReached" for event in events):
        return "LimitsExceeded"
    if _context_window_error(error):
        return "ContextWindowExceeded"
    return "FatalError"


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text())
    model = config["model_name"]
    truncate_history_thinking = config["truncate_history_thinking"]
    _configure_reasoning_history(model, preserve_previous=not truncate_history_thinking)

    llm_kwargs: dict[str, Any] = {
        "usage_id": "deepswe-openhands",
        "model": model,
        "base_url": os.environ["LLM_BASE_URL"],
        "api_key": SecretStr(os.environ["LLM_API_KEY"]),
        "api_mode": "chat",
        "native_tool_calling": True,
        "force_string_serializer": True,
        "disable_vision": True,
        "caching_prompt": False,
        "reasoning_effort": None,
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "max_input_tokens": config["max_input_tokens"],
        "max_output_tokens": config["max_output_tokens"],
        "num_retries": config["llm_retries"],
        "timeout": config["request_timeout_sec"],
        "drop_params": True,
        "capability_overrides": {
            "supports_responses_api": False,
            "supports_sampling_params": True,
            "supports_vision": False,
            "thinking_mode": "unknown",
        },
        "litellm_extra_body": {
            "top_k": config["top_k"],
            "chat_template_kwargs": {
                "enable_thinking": True,
                "truncate_history_thinking": truncate_history_thinking,
            },
        },
        "log_completions": True,
        "log_completions_folder": str(LOGS_DIR / "openhands-completions"),
    }
    if config.get("seed") is not None:
        llm_kwargs["seed"] = config["seed"]
    llm = LLM(**llm_kwargs)
    serializer_report = _serializer_contract(llm, truncate_history_thinking)
    (LOGS_DIR / "serializer-contract.json").write_text(json.dumps(serializer_report, indent=2) + "\n")

    tools = [
        Tool(
            name=TerminalTool.name,
            params={
                "terminal_type": config["terminal_type"],
                "no_change_timeout_seconds": config["terminal_no_change_timeout_sec"],
            },
        ),
        Tool(name=FileEditorTool.name),
    ]
    agent = Agent(
        llm=llm,
        tools=tools,
        condenser=None,
        tool_concurrency_limit=1,
        system_prompt_kwargs={"cli_mode": True, "llm_security_analyzer": False},
    )
    conversation = Conversation(
        agent=agent,
        workspace=config.get("workspace", "/app"),
        persistence_dir=LOGS_DIR / "openhands-conversation",
        max_iteration_per_run=config["max_iterations"],
        stuck_detection=config["stuck_detection"],
        visualizer=None,
        delete_on_close=False,
    )
    conversation.send_message(config["instruction"])

    run_error: BaseException | None = None
    try:
        conversation.run()
    except ConversationRunError as error:
        run_error = error

    events = list(conversation.state.events)
    execution_status = conversation.state.execution_status.value
    metrics = llm.metrics.model_dump(mode="json", exclude_none=True)
    exit_status = _classify_exit(events, execution_status, run_error)
    trajectory = {
        "schema_version": "deepswe-openhands-v1",
        "agent_version": config["agent_version"],
        "model_name": model,
        "max_iterations": config["max_iterations"],
        "stuck_detection": config["stuck_detection"],
        "terminal_type": config["terminal_type"],
        "execution_status": execution_status,
        "exit_status": exit_status,
        "messages": _serialize_messages(events, metrics),
        "metrics": metrics,
    }
    (LOGS_DIR / "openhands-events.json").write_text(
        json.dumps(
            [event.model_dump(mode="json", exclude_none=True) for event in events],
            indent=2,
        )
        + "\n"
    )
    (LOGS_DIR / "openhands-trajectory.json").write_text(json.dumps(trajectory, indent=2) + "\n")
    (LOGS_DIR / "openhands-metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    exit_report = {
        "exit_status": exit_status,
        "execution_status": execution_status,
        "error_type": type(run_error).__name__ if run_error is not None else None,
        "error": str(run_error) if run_error is not None else None,
    }
    (LOGS_DIR / "openhands-exit.json").write_text(json.dumps(exit_report, indent=2) + "\n")

    if exit_status not in ACCEPTED_EXIT_STATUSES:
        if run_error is not None:
            raise run_error
        raise RuntimeError(f"OpenHands exited without a submission: {exit_report}")


if __name__ == "__main__":
    main()
