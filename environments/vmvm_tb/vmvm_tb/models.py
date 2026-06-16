# Data models for the Terminus-2 terminal-bench protocol.
# Extracted from amaia-collab apps/sea/envs/terminal/bash_base.py (snapshot 2026-06-15),
# dropping the amaia-coupled BashEnv/DialogEnv classes and the search/URL command
# variants (not used for terminal-bench). Pure pydantic/dataclass — no amaia deps.
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass
class TestResult:
    """Result of running tests in a bash environment."""

    outcome: Literal["env_error", "timeout", "pass", "fail"]
    message: str
    test_output: str
    exit_code: int | None = None
    instance_id: str | None = None
    report: dict[str, Any] | None = None
    # Structured infra-failure tag so every env_error records WHAT happened
    # (e.g. grade/upload_conn_lost, grade/test_run, grade/reward_raise).
    error_class: str | None = None
    error_detail: str | None = None


class Command(BaseModel):
    keystrokes: str = Field(
        description="Command to execute in the terminal. This should be a valid bash command."
    )
    is_blocking: bool = Field(
        description=(
            "Whether to wait for and return the terminal output after executing this command."
        )
    )
    timeout_sec: float = Field(
        description="The number of expected seconds to wait for the command to complete."
    )

    model_config = ConfigDict(extra="forbid")


class CommandBatchResponse(BaseModel):
    state_analysis: str = Field(description="Description of the current state of the terminal")
    explanation: str = Field(description="Brief explanation of what these commands will do")
    bash_commands: list[Command] = Field(
        description="List of shell interactions to execute in the Docker container"
    )
    is_task_complete: bool = Field(
        description="Whether the task is complete following the execution of these commands."
    )

    model_config = ConfigDict(extra="forbid")
