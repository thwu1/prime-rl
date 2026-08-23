from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from stirrup import Agent
from stirrup.constants import DEFAULT_FINISH_TOOL_NAME
from stirrup.core.agent import SessionAgent
from stirrup.core.models import Tool, ToolCall, ToolMessage, ToolResult, ToolUseCountMetadata, UserMessage
from stirrup.tools.finish import _validating_finish_executor


class CoercingFinishParams(BaseModel):
    reason: Annotated[str, Field(description="Brief summary of the completed work.")]
    paths: Annotated[
        list[str],
        Field(description="Absolute paths of the files to submit. Do not include directories."),
    ]

    @field_validator("paths", mode="before")
    @classmethod
    def coerce_paths(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [str(path) for path in value]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return [str(path) for path in parsed]
            return [stripped] if stripped else []
        return value


FINISH_TOOL: Tool[CoercingFinishParams, ToolUseCountMetadata] = Tool(
    name=DEFAULT_FINISH_TOOL_NAME,
    description=(
        "Signal task completion with a brief summary and the absolute paths of all files to submit. "
        "You need a separate turn to call this tool."
    ),
    parameters=CoercingFinishParams,
    executor=_validating_finish_executor,
)


class AbandonFinishParams(BaseModel):
    reason: Annotated[str, Field(description="Brief reason the task cannot be completed.")]


async def _abandon(params: AbandonFinishParams) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=params.reason, metadata=ToolUseCountMetadata(), success=True)


ABANDON_FINISH_TOOL: Tool[AbandonFinishParams, ToolUseCountMetadata] = Tool(
    name="abandon_task_finish",
    description=(
        "Abandon only when required inputs are missing, a hard dependency is unavailable, or the task is "
        "incoherent. Do not use this tool merely because the assignment is difficult."
    ),
    parameters=AbandonFinishParams,
    executor=_abandon,
)


class ToolResultUserMessage(UserMessage):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    success: bool = False
    args_was_valid: bool = True
    tool_call_id: str | None = None
    tool_start_time: float | None = None
    tool_end_time: float | None = None


ToolResultUserMessage.model_rebuild()


class GDPValAgent(Agent):
    """Stirrup agent with the tool-message behavior used by NVIDIA Gym."""

    async def run_tool(self, tool_call: ToolCall, run_metadata: dict[str, list[Any]]) -> ToolMessage:
        message = await super().run_tool(tool_call, run_metadata)
        if not getattr(message, "args_was_valid", True) and message.content == "Tool arguments are not valid":
            tool = self._active_tools.get(tool_call.name)
            if tool is not None:
                arguments = tool_call.arguments if tool_call.arguments and tool_call.arguments.strip() else "{}"
                try:
                    tool.parameters.model_validate_json(arguments)
                except ValidationError as error:
                    detail = "; ".join(
                        f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']} "
                        f"(type={item.get('type', '?')})"
                        for item in error.errors()
                    )
                    message = message.model_copy(
                        update={
                            "content": (
                                f"Tool arguments are not valid: {detail}. "
                                f"Submitted arguments (first 500 chars): {(tool_call.arguments or '')[:500]!r}"
                            )
                        }
                    )
        return ToolResultUserMessage(  # type: ignore[return-value]
            content=message.content,
            name=message.name,
            success=message.success,
            args_was_valid=getattr(message, "args_was_valid", True),
            tool_call_id=message.tool_call_id,
            tool_start_time=getattr(message, "tool_start_time", None),
            tool_end_time=getattr(message, "tool_end_time", None),
        )

    def _build_system_prompt(self) -> str:
        from stirrup.core.agent import _SESSION_STATE

        state = _SESSION_STATE.get(None)
        uploaded = state.uploaded_file_paths if state else []
        if state:
            state.uploaded_file_paths = []
        try:
            return super()._build_system_prompt()
        finally:
            if state:
                state.uploaded_file_paths = uploaded

    async def __aenter__(self):  # type: ignore[override]
        session = await super().__aenter__()
        session.__class__ = GDPValSessionAgent
        return session


class GDPValSessionAgent(SessionAgent, GDPValAgent):
    pass
