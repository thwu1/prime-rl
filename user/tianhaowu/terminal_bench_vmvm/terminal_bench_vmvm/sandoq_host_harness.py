"""Host-side OpenAI tool loop for Terminal-Bench tasks running in Sandoq.

The model loop stays in the controller so it can call the local Verifiers
interception server.  Bash is the sole tool and every task-side operation is
performed through the supplied remote ``Runtime``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any, NoReturn

from openai import AsyncOpenAI
from pydantic import Field
from verifiers.v1.clients import RolloutContext
from verifiers.v1.dialects.chat import message_to_wire
from verifiers.v1.errors import SandboxError
from verifiers.v1.harness import Harness, HarnessConfig
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.trace import Trace

HARNESS_PLUGIN_ID = "terminal-bench-sandoq-host"

MANAGED_ENV = {
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "MANPAGER": "cat",
    "LESS": "-R",
    "CI": "1",
    "PIP_PROGRESS_BAR": "off",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "TQDM_DISABLE": "1",
    "_JAVA_OPTIONS": "-Djava.net.preferIPv6Addresses=false",
    "PYTEST_XDIST_AUTO_NUM_WORKERS": "4",
    "OMP_NUM_THREADS": "4",
    "MKL_NUM_THREADS": "4",
    "OPENBLAS_NUM_THREADS": "4",
}

_BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": ("Run a bash command in the task repository and return its output and exit code."),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to run.",
                }
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

_REASONING_FIELDS = ("reasoning", "reasoning_content", "reasoning_details")
_TIMEOUT_MARKER = "SANDOQ_COMMAND_TIMEOUT=1"
_CLEANUP_UNVERIFIED_MARKER = "SANDOQ_COMMAND_CLEANUP_UNVERIFIED=1"


class TerminalBenchSandoqHostHarnessConfig(HarnessConfig):
    """Safety and output limits for the host-side Terminal-Bench tool loop."""

    command_timeout_seconds: int = Field(240, ge=1, le=240)
    command_kill_grace_seconds: int = Field(10, ge=1, le=30)
    max_command_output_chars: int = Field(100_000, ge=1)
    request_timeout_seconds: int = Field(15_000, ge=7_200, le=21_600)


class SandoqHostHarnessError(SandboxError):
    """A task-side command failed with stable Sandoq failure accounting."""

    def __init__(self, message: str, *, failure_reason: str, cause_stage: str) -> None:
        super().__init__(message)
        self.failure_reason = failure_reason
        self.cause_stage = cause_stage


def _error_chain(error: BaseException | None) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        chain.append(error)
        nested_arg = next((arg for arg in error.args if isinstance(arg, BaseException)), None)
        error = error.__cause__ or error.__context__ or nested_arg
    return chain


def _record_typed_failure(trace: Trace, error: BaseException) -> None:
    for item in _error_chain(error):
        failure_reason = getattr(item, "failure_reason", None)
        if failure_reason:
            trace.info["failure_reason"] = str(failure_reason)
            break
    for item in _error_chain(error):
        cause_stage = getattr(item, "cause_stage", None) or getattr(item, "stage", None)
        if cause_stage:
            trace.info["cause_stage"] = str(cause_stage)
            break
    for item in _error_chain(error):
        timeout_category = getattr(item, "timeout_category", None)
        if timeout_category:
            trace.info["timeout_category"] = str(timeout_category)
            break


def _has_failure_reason(error: BaseException, reason: str) -> bool:
    return any(getattr(item, "failure_reason", None) == reason for item in _error_chain(error))


def _poison_runtime(runtime: Runtime, reason: str, shell_status: str) -> None:
    """Mark the provider assignment unsafe so cleanup retires rather than reuses it."""

    try:
        from sandoq_provider import registry
    except (ImportError, ModuleNotFoundError) as error:
        raise SandoqHostHarnessError(
            "Sandoq assignment cleanup was uncertain and the provider registry is unavailable",
            failure_reason=reason,
            cause_stage="shell_exec",
        ) from error

    sandbox_id = getattr(runtime, "descriptor", None)
    session = registry.get(str(sandbox_id)) if sandbox_id is not None else None
    if session is None:
        raise SandoqHostHarnessError(
            "Sandoq assignment cleanup was uncertain and the assignment could not be poisoned",
            failure_reason=reason,
            cause_stage="shell_exec",
        )
    session.assignment_poisoned = True
    session.assignment_poison_reason = reason
    session.shell_failure_status = shell_status
    session.metadata.update(
        assignment_poisoned=True,
        assignment_poison_reason=reason,
        shell_failure_status=shell_status,
        failure_reason=reason,
    )


def _command_output(result: ProgramResult, limit: int) -> str:
    output = result.stdout
    if result.stderr:
        output += ("\n" if output and not output.endswith("\n") else "") + result.stderr
    output += ("\n" if output and not output.endswith("\n") else "") + f"[exit_code={result.exit_code}]"
    if len(output) <= limit:
        return output
    half = max((limit - 80) // 2, 1)
    return f"{output[:half]}\n...[command output truncated]...\n{output[-half:]}"


def _supervised_bash_argv(command: str, timeout_seconds: int, kill_grace_seconds: int) -> list[str]:
    """Build a command whose process group is killed and verified on timeout."""

    supervisor = "\n".join(
        [
            "set +e",
            "budget=$1",
            "grace=$2",
            "command=$3",
            'setsid bash -lc "$command" &',
            "child=$!",
            "deadline=$((SECONDS + budget))",
            'while kill -0 "$child" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do sleep 0.2; done',
            'if kill -0 "$child" 2>/dev/null; then',
            '  kill -TERM -- "-$child" 2>/dev/null',
            "  grace_deadline=$((SECONDS + grace))",
            '  while kill -0 -- "-$child" 2>/dev/null && [ "$SECONDS" -lt "$grace_deadline" ]; do sleep 0.2; done',
            '  if kill -0 -- "-$child" 2>/dev/null; then kill -KILL -- "-$child" 2>/dev/null; fi',
            '  wait "$child" 2>/dev/null',
            '  for _ in $(seq 1 20); do kill -0 -- "-$child" 2>/dev/null || break; sleep 0.1; done',
            '  if kill -0 -- "-$child" 2>/dev/null || ! bash -lc true; then',
            f"    printf '{_CLEANUP_UNVERIFIED_MARKER}\\n' >&2",
            "    exit 125",
            "  fi",
            f"  printf '{_TIMEOUT_MARKER}\\n' >&2",
            "  exit 124",
            "fi",
            'wait "$child"',
            "exit $?",
        ]
    )
    return [
        "bash",
        "-lc",
        supervisor,
        "sandoq-command-supervisor",
        str(timeout_seconds),
        str(kill_grace_seconds),
        command,
    ]


def _assistant_message_to_wire(message: Any) -> dict[str, Any]:
    """Serialize an SDK message while retaining provider reasoning extensions."""

    wire = dict(message.model_dump(exclude_none=True))
    extra = getattr(message, "model_extra", None)
    provider_fields = wire.pop("provider_specific_fields", None)
    if not isinstance(provider_fields, Mapping) and isinstance(extra, Mapping):
        provider_fields = extra.get("provider_specific_fields")
    for field in _REASONING_FIELDS:
        if wire.get(field) is not None:
            continue
        value = extra.get(field) if isinstance(extra, Mapping) else None
        if value is None and isinstance(provider_fields, Mapping):
            value = provider_fields.get(field)
        if value is not None:
            wire[field] = value
    return wire


def _raise_cleanup_unverified(trace: Trace, runtime: Runtime) -> NoReturn:
    reason = "command_timeout_cleanup_unverified"
    trace.info.update(
        failure_reason=reason,
        cause_stage="shell_exec",
        timeout_category=reason,
    )
    _poison_runtime(runtime, reason, "process_group_alive")
    trace.info["assignment_poisoned"] = True
    raise SandoqHostHarnessError(
        "timed-out command process group could not be verified stopped",
        failure_reason=reason,
        cause_stage="shell_exec",
    )


async def _run_supervised_bash(
    runtime: Runtime,
    trace: Trace,
    command: str,
    *,
    timeout_seconds: int,
    kill_grace_seconds: int,
) -> ProgramResult:
    """Run once and finish timeout cleanup even if the host coroutine is cancelled."""

    run_task = asyncio.create_task(
        runtime.run(
            _supervised_bash_argv(command, timeout_seconds, kill_grace_seconds),
            MANAGED_ENV,
        )
    )
    cancellation: asyncio.CancelledError | None = None
    while not run_task.done():
        try:
            await asyncio.shield(run_task)
        except asyncio.CancelledError as error:
            cancellation = cancellation or error
        except Exception:
            break

    try:
        result = run_task.result()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        _record_typed_failure(trace, error)
        if _has_failure_reason(error, "command_timeout_cleanup_unverified"):
            _poison_runtime(
                runtime,
                "command_timeout_cleanup_unverified",
                "process_group_cleanup_unverified",
            )
            trace.info["assignment_poisoned"] = True
        if cancellation is not None:
            raise cancellation from error
        raise

    if result.exit_code == 124 and _TIMEOUT_MARKER in result.stderr:
        trace.info["timeout_category"] = "command_budget_exhausted"
        trace.info["command_budget_exhausted_count"] = int(trace.info.get("command_budget_exhausted_count", 0)) + 1
    elif result.exit_code == 125 and _CLEANUP_UNVERIFIED_MARKER in result.stderr:
        if cancellation is not None:
            try:
                _raise_cleanup_unverified(trace, runtime)
            except SandoqHostHarnessError as error:
                raise cancellation from error
        _raise_cleanup_unverified(trace, runtime)

    if cancellation is not None:
        raise cancellation
    return result


class TerminalBenchSandoqHostHarness(Harness[TerminalBenchSandoqHostHarnessConfig]):
    """A non-streaming host model loop with one sandboxed Bash tool."""

    APPENDS_SYSTEM_PROMPT = True
    SUPPORTS_MCP = False
    SUPPORTS_USER_SIM = False
    SUPPORTS_MESSAGE_PROMPT = True
    RUNS_ON_HOST = True

    async def launch(
        self,
        ctx: RolloutContext,
        trace: Trace,
        runtime: Runtime,
        endpoint: str,
        secret: str,
        mcp_urls: dict[str, str],
    ) -> ProgramResult:
        if self.config.disabled_tools:
            raise ValueError("the Sandoq host-side harness requires its single bash tool")
        if mcp_urls:
            raise ValueError("the Sandoq host-side harness does not support MCP consumers")

        system_prompt, prompt = self.resolve_prompt(trace.task)
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
        elif prompt is not None:
            messages.extend(message_to_wire(message) for message in prompt)

        client = AsyncOpenAI(
            base_url=endpoint,
            api_key=secret,
            max_retries=0,
            timeout=self.config.request_timeout_seconds,
        )
        try:
            while True:
                try:
                    # Sampling is deliberately omitted here. The Verifiers interception
                    # layer owns and applies ctx.sampling, including provider extensions
                    # that are not accepted as keyword arguments by the OpenAI SDK.
                    response = await client.chat.completions.create(
                        model=ctx.model,
                        messages=list(messages),
                        tools=[_BASH_TOOL],
                        parallel_tool_calls=True,
                        stream=False,
                    )
                except Exception:
                    if trace.stop_condition is not None:
                        return ProgramResult(exit_code=0, stdout="", stderr="")
                    raise

                message = response.choices[0].message
                messages.append(_assistant_message_to_wire(message))
                tool_calls = message.tool_calls or []
                if not tool_calls:
                    return ProgramResult(exit_code=0, stdout=message.content or "", stderr="")

                for tool_call in tool_calls:
                    if tool_call.function.name != "bash":
                        content = f"Unsupported tool: {tool_call.function.name}"
                    else:
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                            command = arguments["command"]
                            if not isinstance(command, str):
                                raise TypeError("bash.command must be a string")
                        except (KeyError, TypeError, json.JSONDecodeError) as error:
                            content = f"Invalid bash arguments: {error}"
                        else:
                            result = await _run_supervised_bash(
                                runtime,
                                trace,
                                command,
                                timeout_seconds=self.config.command_timeout_seconds,
                                kill_grace_seconds=self.config.command_kill_grace_seconds,
                            )
                            content = _command_output(result, self.config.max_command_output_chars)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": content,
                        }
                    )
        finally:
            await client.close()


__all__ = [
    "HARNESS_PLUGIN_ID",
    "TerminalBenchSandoqHostHarness",
    "TerminalBenchSandoqHostHarnessConfig",
]
