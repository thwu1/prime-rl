from pier.agents.installed.base import NonZeroAgentExitCodeError
from pier.agents.installed.mini_swe_agent import MiniSweAgent
from pier.environments.base import BaseEnvironment
from pier.models.agent.context import AgentContext

_VALIDATE_AGENT_EXIT_COMMAND = """
trajectory=/logs/agent/mini-swe-agent.trajectory.json
test -s "$trajectory"
if grep -Eq '"exit_status"[[:space:]]*:[[:space:]]*"Submitted"' "$trajectory"; then
    exit 0
fi
if grep -Eq '"exit_status"[[:space:]]*:[[:space:]]*"LimitsExceeded"' "$trajectory"; then
    printf 'accepted_exit_status=LimitsExceeded\n' \
        | tee /logs/agent/submission-exit.txt
    exit 0
fi
if grep -Eq '"exit_status"[[:space:]]*:[[:space:]]*"(BadRequestError|ContextWindowExceededError)"' "$trajectory" && \
   grep -Fq "exceeds the model's maximum context length" "$trajectory"; then
    printf 'accepted_exit_status=ContextWindowExceeded\n' \
        | tee /logs/agent/submission-exit.txt
    exit 0
fi
echo 'mini-swe-agent did not submit or stop at the configured limit' >&2
exit 1
""".strip()

_SUBMISSION_COMMAND = """
before=$(git rev-parse HEAD)
git add -A
auto_committed=false
if ! git diff --cached --quiet; then
    git -c user.name=mini-swe-agent \
        -c user.email=mini-swe-agent@local \
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


class DeepSweMiniSweAgent(MiniSweAgent):
    """MiniSWE with a deterministic DeepSWE submission commit."""

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        try:
            await super().run(instruction, environment, context)
        except NonZeroAgentExitCodeError:
            pass
        await self.exec_as_agent(
            environment,
            command=_VALIDATE_AGENT_EXIT_COMMAND,
        )
        await self.exec_as_agent(
            environment,
            command=_SUBMISSION_COMMAND,
        )
