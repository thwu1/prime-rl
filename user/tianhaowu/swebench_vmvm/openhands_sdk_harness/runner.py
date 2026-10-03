#!/usr/bin/env python3

import argparse
import importlib.metadata
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from openhands.sdk import LLM, Agent, AgentContext, Conversation, Tool
from openhands.sdk.context import Skill
from openhands.sdk.event import ActionEvent, MessageEvent, ObservationEvent
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

DEFAULT_SKILL_PATHS = [
    "~/.openhands-sdk/skills",
    "~/.claude/skills",
    "~/.codex/skills",
    "~/.agents/skills",
    "~/.goose/skills",
    "~/.gemini/skills",
    "~/.factory/skills",
    "~/.opencode/skill",
]


class FlushRequested(BaseException):
    pass


def _handle_signal(signum: int, _frame: object) -> None:
    raise FlushRequested(f"signal {signum}")


def _load_skills() -> list[Skill]:
    skills = []
    seen = set()
    for raw_path in DEFAULT_SKILL_PATHS:
        base = Path(raw_path).expanduser()
        if not base.is_dir():
            continue
        for directory in base.iterdir():
            skill_path = directory / "SKILL.md"
            if not directory.is_dir() or not skill_path.is_file() or directory.name in seen:
                continue
            skills.append(
                Skill(
                    name=directory.name,
                    content=skill_path.read_text(),
                    source=str(skill_path),
                    trigger=None,
                )
            )
            seen.add(directory.name)
    return skills


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(getattr(item, "text", str(item)) for item in content if getattr(item, "text", None))
    return str(content) if content else ""


def _event_summary(event: Any) -> dict[str, Any] | None:
    if isinstance(event, MessageEvent):
        message = getattr(event, "llm_message", None)
        return {
            "type": "message",
            "source": str(event.source),
            "content": _text_content(getattr(message, "content", None)),
            "reasoning_content": getattr(event, "reasoning_content", None)
            or getattr(message, "reasoning_content", None),
            "timestamp": str(event.timestamp),
        }
    if isinstance(event, ActionEvent):
        return {
            "type": "action",
            "tool_call_id": event.tool_call_id,
            "tool_name": event.tool_name,
            "reasoning_content": getattr(event, "reasoning_content", None),
            "timestamp": str(event.timestamp),
        }
    if isinstance(event, ObservationEvent):
        observation = getattr(event, "observation", None)
        return {
            "type": "observation",
            "tool_call_id": event.tool_call_id,
            "content": _text_content(getattr(observation, "content", None))[:20_000],
            "timestamp": str(event.timestamp),
        }
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instruction", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    args = parser.parse_args()

    instruction = args.instruction.read_text()
    model = os.environ["LLM_MODEL"]
    api_key = os.environ["LLM_API_KEY"]
    base_url = os.environ["LLM_BASE_URL"]
    max_iterations = int(os.environ.get("MAX_ITERATIONS", "200"))
    request_timeout = int(os.environ.get("LLM_TIMEOUT", "3600"))

    llm = LLM(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=request_timeout,
    )
    tools = [
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        Tool(name=TaskTrackerTool.name),
    ]
    skills = _load_skills()
    agent = Agent(
        llm=llm,
        tools=tools,
        agent_context=AgentContext(skills=skills),
    )
    conversation = Conversation(
        agent=agent,
        workspace=os.getcwd(),
        max_iteration_per_run=max_iterations,
        stuck_detection=False,
        visualizer=None,
    )

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _handle_signal)

    started_at = time.time()
    exception = None
    try:
        conversation.send_message(instruction)
        conversation.run()
    except BaseException as error:
        exception = {
            "type": type(error).__name__,
            "message": str(error),
        }
        _write_json(Path("/tmp/openhands-sdk-agent-error.json"), exception)

    events = []
    for event in list(getattr(conversation.state, "events", []) or []):
        summary = _event_summary(event)
        if summary is not None:
            events.append(summary)
    _write_json(
        args.events,
        {
            "schema_version": 1,
            "events": events,
        },
    )

    usage = getattr(llm.metrics, "accumulated_token_usage", None)
    result = {
        "schema_version": 1,
        "openhands_sdk_version": importlib.metadata.version("openhands-sdk"),
        "openhands_tools_version": importlib.metadata.version("openhands-tools"),
        "max_iterations": max_iterations,
        "request_timeout_seconds": request_timeout,
        "workspace": os.getcwd(),
        "skills_loaded": [skill.name for skill in skills],
        "event_count": len(events),
        "message_events": sum(event["type"] == "message" for event in events),
        "action_events": sum(event["type"] == "action" for event in events),
        "observation_events": sum(event["type"] == "observation" for event in events),
        "tool_names": sorted({event["tool_name"] for event in events if event["type"] == "action"}),
        "execution_status": str(getattr(conversation.state, "execution_status", "unknown")),
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "cached_tokens": int(getattr(usage, "cache_read_tokens", 0) or 0),
        "exception": exception,
        "started_at": started_at,
        "finished_at": time.time(),
    }
    _write_json(args.result, result)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
