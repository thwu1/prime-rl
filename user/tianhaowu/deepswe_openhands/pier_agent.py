import json
from pathlib import Path

from pier.agents.installed.base import (
    BaseInstalledAgent,
    NonZeroAgentExitCodeError,
    with_prompt_template,
)
from pier.agents.network import allowlist_from_urls
from pier.environments.base import BaseEnvironment
from pier.models.agent.context import AgentContext
from pier.models.agent.install import AgentInstallSpec, InstallStep
from pier.models.agent.network import NetworkAllowlist
from verifiers.v1.errors import SandboxError

from user.tianhaowu.deepswe_openhands.trajectory import (
    convert_and_save_openhands_trajectory,
    populate_context_from_openhands,
)

RUNNER = Path(__file__).with_name("runner.py")
VENV = "$HOME/.local/share/deepswe-openhands/venv"

_CLASSIFY_AGENT_TRANSPORT_EXIT_COMMAND = r"""
report=/logs/agent/openhands-exit.json
if test -s "$report" && \
   grep -Eq '"exit_status"[[:space:]]*:[[:space:]]*"FatalError"' "$report" && \
   grep -Eiq 'RemoteProtocolError|APIConnectionError|APITimeoutError|BadGatewayError|Connection error|Connection refused|Server disconnected|incomplete message body|Error code:[[:space:]]*50[234]|502 Bad Gateway|503 Service Unavailable|504 Gateway Time-out|RateLimitError' "$report"; then
    printf 'model_transport_error\n'
else
    printf 'non_transport_exit\n'
fi
""".strip()

_VALIDATE_AGENT_EXIT_COMMAND = """
report=/logs/agent/openhands-exit.json
test -s "$report"
if grep -Eq '"exit_status"[[:space:]]*:[[:space:]]*"Submitted"' "$report"; then
    exit 0
fi
if grep -Eq '"exit_status"[[:space:]]*:[[:space:]]*"(LimitsExceeded|ContextWindowExceeded)"' "$report"; then
    grep -E '"exit_status"' "$report" | tee /logs/agent/submission-exit.txt
    exit 0
fi
echo 'OpenHands did not submit or stop at an accepted limit' >&2
exit 1
""".strip()

_PREPARE_REPOSITORY_COMMAND = "git config core.fileMode false"

_SUBMISSION_COMMAND = """
before=$(git rev-parse HEAD)
git add -A
auto_committed=false
if ! git diff --cached --quiet; then
    git -c user.name=openhands-sdk \
        -c user.email=openhands-sdk@local \
        commit -q --no-verify -m 'Submit DeepSWE solution'
    auto_committed=true
fi
after=$(git rev-parse HEAD)
status=$(git status --porcelain=v1)
printf 'before=%s\nafter=%s\nauto_committed=%s\nstatus=%s\n' \
    "$before" "$after" "$auto_committed" "$status" \
    | tee /logs/agent/submission-commit.txt
test -z "$status"
""".strip()


class DeepSweOpenHandsAgent(BaseInstalledAgent):
    """Standalone OpenHands SDK agent for DeepSWE tasks."""

    SUPPORTS_ATIF = True

    def __init__(
        self,
        *args,
        max_iterations: int = 200,
        stuck_detection: bool = False,
        terminal_type: str = "subprocess",
        terminal_no_change_timeout_sec: int = 600,
        request_timeout_sec: int = 7200,
        llm_retries: int = 5,
        max_input_tokens: int = 262144,
        max_output_tokens: int = 32768,
        temperature: float = 1.0,
        top_p: float = 0.95,
        top_k: int = 20,
        seed: int | None = None,
        truncate_history_thinking: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        if terminal_type not in {"subprocess", "tmux"}:
            raise ValueError("terminal_type must be 'subprocess' or 'tmux'")
        self.max_iterations = max_iterations
        self.stuck_detection = stuck_detection
        self.terminal_type = terminal_type
        self.terminal_no_change_timeout_sec = terminal_no_change_timeout_sec
        self.request_timeout_sec = request_timeout_sec
        self.llm_retries = llm_retries
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.seed = seed
        self.truncate_history_thinking = truncate_history_thinking

    @staticmethod
    def name() -> str:
        return "openhands-sdk"

    def get_version_command(self) -> str:
        return f"{VENV}/bin/python -c \"import importlib.metadata; print(importlib.metadata.version('openhands-sdk'))\""

    def install_spec(self) -> AgentInstallSpec:
        version_spec = f"=={self._version}" if self._version else ""
        return AgentInstallSpec(
            agent_name=self.name(),
            version=self._version,
            steps=[
                InstallStep(
                    user="root",
                    env={"DEBIAN_FRONTEND": "noninteractive"},
                    run=(
                        "if command -v apt-get >/dev/null 2>&1; then "
                        "apt-get update && apt-get install -y curl git build-essential; "
                        "fi"
                    ),
                ),
                InstallStep(
                    user="agent",
                    env={"UV_LINK_MODE": "copy"},
                    run=f"""
set -euo pipefail
curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh
. "$HOME/.local/bin/env"
uv venv {VENV} --python 3.12
uv pip install --python {VENV}/bin/python \
    openhands-sdk{version_spec} openhands-tools{version_spec} litellm==1.93.0
{self.get_version_command()}
""".strip(),
                ),
            ],
            verification_command=self.get_version_command(),
        )

    def network_allowlist(self) -> NetworkAllowlist:
        return allowlist_from_urls([self._get_env("OPENAI_BASE_URL")])

    def populate_context_post_run(self, context: AgentContext) -> None:
        source = self.logs_dir / "openhands-trajectory.json"
        if not source.is_file():
            return
        trajectory = convert_and_save_openhands_trajectory(
            source,
            self.logs_dir / "trajectory.json",
        )
        populate_context_from_openhands(context, trajectory)

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        if not self.model_name:
            raise ValueError("OpenHands requires a model_name")
        api_key = self._get_env("OPENAI_API_KEY")
        base_url = self._get_env("OPENAI_BASE_URL")
        if not api_key or not base_url:
            raise ValueError("OpenHands requires OPENAI_API_KEY and OPENAI_BASE_URL")

        await self.exec_as_agent(environment, command=_PREPARE_REPOSITORY_COMMAND)

        input_path = self.logs_dir / "openhands-input.json"
        input_path.write_text(
            json.dumps(
                {
                    "instruction": instruction,
                    "agent_version": self._version or "unknown",
                    "model_name": self.model_name,
                    "max_iterations": self.max_iterations,
                    "stuck_detection": self.stuck_detection,
                    "terminal_type": self.terminal_type,
                    "terminal_no_change_timeout_sec": self.terminal_no_change_timeout_sec,
                    "request_timeout_sec": self.request_timeout_sec,
                    "llm_retries": self.llm_retries,
                    "max_input_tokens": self.max_input_tokens,
                    "max_output_tokens": self.max_output_tokens,
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "top_k": self.top_k,
                    "seed": self.seed,
                    "truncate_history_thinking": self.truncate_history_thinking,
                },
                indent=2,
            )
            + "\n"
        )
        await environment.upload_file(RUNNER, "/tmp/deepswe-openhands-runner.py")
        await environment.upload_file(input_path, "/tmp/deepswe-openhands-input.json")
        env = self.build_process_env(
            {
                "LLM_API_KEY": api_key,
                "LLM_BASE_URL": base_url,
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                "NO_PROXY": "127.0.0.1,localhost",
                "OPENHANDS_SUPPRESS_BANNER": "1",
                "LMNR_PROJECT_API_KEY": "",
                "OTEL_ENDPOINT": "",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "",
            }
        )
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    f"{VENV}/bin/python /tmp/deepswe-openhands-runner.py "
                    "/tmp/deepswe-openhands-input.json "
                    "2>&1 | tee /logs/agent/openhands.txt"
                ),
                env=env,
            )
        except NonZeroAgentExitCodeError as error:
            classification = await self.exec_as_agent(
                environment,
                command=_CLASSIFY_AGENT_TRANSPORT_EXIT_COMMAND,
            )
            if classification.stdout.strip() == "model_transport_error":
                raise SandboxError("OpenHands model request transport failed after its internal retries") from error
        await self.exec_as_agent(environment, command=_VALIDATE_AGENT_EXIT_COMMAND)
        await self.exec_as_agent(environment, command=_SUBMISSION_COMMAND)
