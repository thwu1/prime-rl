import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from terminal_bench_vmvm import sandoq_host_harness as host
from verifiers.v1.clients import RolloutContext
from verifiers.v1.loaders import default_harness_id, harness_class, harness_config_type
from verifiers.v1.runtimes import ProgramResult
from verifiers.v1.task import Task
from verifiers.v1.trace import Trace
from verifiers.v1.types import SamplingConfig


class FakeMessage:
    def __init__(
        self,
        *,
        content: str | None,
        tool_calls: list | None = None,
        wire: dict | None = None,
        model_extra: dict | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self._wire = wire or {"role": "assistant", "content": content}
        self.model_extra = model_extra or {}

    def model_dump(self, *, exclude_none: bool) -> dict:
        assert exclude_none is True
        return dict(self._wire)


def tool_call(arguments: str = '{"command":"true"}') -> SimpleNamespace:
    return SimpleNamespace(
        id="synthetic-call",
        function=SimpleNamespace(name="bash", arguments=arguments),
    )


def completion(message: FakeMessage) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeAsyncOpenAI:
    responses: list[SimpleNamespace] = []
    instances: list["FakeAsyncOpenAI"] = []

    def __init__(self, **kwargs) -> None:
        self.constructor_kwargs = kwargs
        self.requests: list[dict] = []
        self.closed = False
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )
        type(self).instances.append(self)

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        return type(self).responses.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeRuntime:
    descriptor = "synthetic-runtime"

    def __init__(self, result: ProgramResult | None = None) -> None:
        self.result = result or ProgramResult(exit_code=0, stdout="ok", stderr="")
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        self.calls.append((argv, env))
        return self.result


def make_harness() -> host.TerminalBenchSandoqHostHarness:
    return host.TerminalBenchSandoqHostHarness(host.TerminalBenchSandoqHostHarnessConfig(id=host.HARNESS_PLUGIN_ID))


def make_trace() -> Trace:
    return Trace(
        task=Task(
            idx=0,
            prompt="synthetic prompt",
            system_prompt="synthetic system prompt",
        )
    )


def make_context() -> RolloutContext:
    return RolloutContext(
        client=SimpleNamespace(),
        model="synthetic-model",
        sampling=SamplingConfig(
            temperature=0.2,
            top_p=0.9,
            max_tokens=4096,
            top_k=40,
            chat_template_kwargs={"enable_thinking": True},
        ),
    )


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch):
    FakeAsyncOpenAI.responses = []
    FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(host, "AsyncOpenAI", FakeAsyncOpenAI)


@pytest.mark.asyncio
async def test_host_loop_uses_one_bash_tool_and_preserves_reasoning(monkeypatch) -> None:
    first = FakeMessage(
        content=None,
        tool_calls=[tool_call()],
        wire={
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "synthetic-call",
                    "type": "function",
                    "function": {"name": "bash", "arguments": '{"command":"true"}'},
                }
            ],
            "provider_specific_fields": {"reasoning_content": "retained reasoning"},
        },
        model_extra={"provider_specific_fields": {"reasoning_content": "retained reasoning"}},
    )
    final = FakeMessage(content="finished", tool_calls=[])
    FakeAsyncOpenAI.responses = [completion(first), completion(final)]
    runtime = FakeRuntime()

    result = await make_harness().launch(
        make_context(),
        make_trace(),
        runtime,
        "http://127.0.0.1:4321/v1",
        "synthetic-secret",
        {},
    )

    assert result == ProgramResult(exit_code=0, stdout="finished", stderr="")
    client = FakeAsyncOpenAI.instances[0]
    assert client.constructor_kwargs == {
        "base_url": "http://127.0.0.1:4321/v1",
        "api_key": "synthetic-secret",
        "max_retries": 0,
        "timeout": 15_000,
    }
    assert client.closed is True
    assert len(client.requests) == 2
    for request in client.requests:
        assert set(request) == {
            "model",
            "messages",
            "tools",
            "parallel_tool_calls",
            "stream",
        }
        assert request["parallel_tool_calls"] is True
        assert request["stream"] is False
        assert len(request["tools"]) == 1
        assert request["tools"][0]["function"]["name"] == "bash"
        assert "top_k" not in request
        assert "chat_template_kwargs" not in request
        assert "temperature" not in request
        assert "max_tokens" not in request

    history = client.requests[1]["messages"]
    assert history[2]["reasoning_content"] == "retained reasoning"
    assert "provider_specific_fields" not in history[2]
    assert history[3]["role"] == "tool"
    assert history[3]["tool_call_id"] == "synthetic-call"
    assert history[3]["content"] == "ok\n[exit_code=0]"

    assert len(runtime.calls) == 1
    argv, env = runtime.calls[0]
    assert argv[0:2] == ["bash", "-lc"]
    assert argv[-1] == "true"
    assert env == host.MANAGED_ENV


def test_supervisor_kills_and_verifies_the_process_group() -> None:
    argv = host._supervised_bash_argv("synthetic command", 17, 3)
    supervisor = argv[2]

    assert argv[-3:] == ["17", "3", "synthetic command"]
    assert "setsid bash" in supervisor
    assert 'kill -TERM -- "-$child"' in supervisor
    assert 'kill -KILL -- "-$child"' in supervisor
    assert 'kill -0 -- "-$child"' in supervisor
    assert host._TIMEOUT_MARKER in supervisor
    assert host._CLEANUP_UNVERIFIED_MARKER in supervisor
    assert "bash -lc true" in supervisor


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "assistant", "content": None, "reasoning_content": "retained"},
        {
            "role": "assistant",
            "content": None,
            "provider_specific_fields": {"reasoning_content": "retained"},
        },
    ],
)
def test_pinned_openai_message_keeps_reasoning_for_the_next_turn(payload: dict) -> None:
    message = ChatCompletionMessage.model_validate(payload)

    wire = host._assistant_message_to_wire(message)

    assert wire["reasoning_content"] == "retained"
    assert "provider_specific_fields" not in wire


@pytest.mark.asyncio
async def test_verified_command_timeout_is_recorded_without_poison() -> None:
    trace = make_trace()
    runtime = FakeRuntime(ProgramResult(exit_code=124, stdout="", stderr=host._TIMEOUT_MARKER))

    result = await host._run_supervised_bash(
        runtime,
        trace,
        "synthetic command",
        timeout_seconds=1,
        kill_grace_seconds=1,
    )

    assert result.exit_code == 124
    assert trace.info == {
        "timeout_category": "command_budget_exhausted",
        "command_budget_exhausted_count": 1,
    }


@pytest.mark.asyncio
async def test_unverified_command_cleanup_poisons_assignment(monkeypatch) -> None:
    trace = make_trace()
    runtime = FakeRuntime(
        ProgramResult(
            exit_code=125,
            stdout="",
            stderr=host._CLEANUP_UNVERIFIED_MARKER,
        )
    )
    poisoned: list[tuple[object, str, str]] = []
    monkeypatch.setattr(
        host,
        "_poison_runtime",
        lambda runtime, reason, status: poisoned.append((runtime, reason, status)),
    )

    with pytest.raises(host.SandoqHostHarnessError) as caught:
        await host._run_supervised_bash(
            runtime,
            trace,
            "synthetic command",
            timeout_seconds=1,
            kill_grace_seconds=1,
        )

    assert caught.value.failure_reason == "command_timeout_cleanup_unverified"
    assert poisoned == [(runtime, "command_timeout_cleanup_unverified", "process_group_alive")]
    assert trace.info["assignment_poisoned"] is True


def test_poison_runtime_updates_authoritative_provider_registry(monkeypatch) -> None:
    session = SimpleNamespace(
        assignment_poisoned=False,
        assignment_poison_reason=None,
        shell_failure_status=None,
        metadata={},
    )
    provider = ModuleType("sandoq_provider")
    provider.registry = SimpleNamespace(get=lambda _sandbox_id: session)
    monkeypatch.setitem(sys.modules, "sandoq_provider", provider)

    host._poison_runtime(
        FakeRuntime(),
        "command_timeout_cleanup_unverified",
        "process_group_alive",
    )

    assert session.assignment_poisoned is True
    assert session.assignment_poison_reason == "command_timeout_cleanup_unverified"
    assert session.shell_failure_status == "process_group_alive"
    assert session.metadata["failure_reason"] == "command_timeout_cleanup_unverified"


class GatedRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = False

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        self.calls.append((argv, env))
        self.started.set()
        await self.release.wait()
        self.finished = True
        return self.result


@pytest.mark.asyncio
async def test_host_cancellation_does_not_detach_a_running_command() -> None:
    FakeAsyncOpenAI.responses = [
        completion(FakeMessage(content=None, tool_calls=[tool_call()])),
    ]
    runtime = GatedRuntime()
    task = asyncio.create_task(
        make_harness().launch(
            make_context(),
            make_trace(),
            runtime,
            "http://127.0.0.1:4321/v1",
            "synthetic-secret",
            {},
        )
    )
    await runtime.started.wait()

    task.cancel()
    await asyncio.sleep(0)
    assert task.done() is False
    assert runtime.finished is False

    runtime.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.finished is True
    assert FakeAsyncOpenAI.instances[0].closed is True


def test_requested_plugin_id_resolves_only_the_host_harness() -> None:
    assert host.TerminalBenchSandoqHostHarness.RUNS_ON_HOST is True
    assert harness_class(host.HARNESS_PLUGIN_ID) is host.TerminalBenchSandoqHostHarness
    assert harness_config_type(host.HARNESS_PLUGIN_ID) is host.TerminalBenchSandoqHostHarnessConfig
    assert default_harness_id("terminal-bench-vmvm") == "default"
