import json

from openhands_harness.harness import APPLY_PATCH, RUNNER, instance_data
from openhands_harness_reasoning.harness import OpenHandsReasoningHarness
from verifiers.v1.clients import RolloutContext
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.trace import Trace


def public_llm_config(ctx: RolloutContext, endpoint: str, secret: str) -> str:
    values = {
        "model": ctx.model,
        "base_url": endpoint,
        "api_key": secret,
    }
    lines = ["[llm.model]"]
    lines.extend(f"{key} = {json.dumps(value)}" for key, value in values.items())
    lines.extend(
        [
            'custom_llm_provider = "openai"',
            "native_tool_calling = true",
            "temperature = 1.0",
            "top_p = 0.95",
            "max_output_tokens = 32768",
        ]
    )
    return "\n".join(lines) + "\n"


class OpenHandsPublicDefaultsHarness(OpenHandsReasoningHarness):
    async def launch(
        self,
        ctx: RolloutContext,
        trace: Trace,
        runtime: Runtime,
        endpoint: str,
        secret: str,
        mcp_urls: dict[str, str],
    ) -> ProgramResult:
        if mcp_urls:
            raise ValueError("OpenHands SWE-bench harness does not support MCP tools")
        instance = instance_data(trace)
        await runtime.write(
            "/tmp/swebench-instance.jsonl",
            (json.dumps(instance) + "\n").encode(),
        )
        await runtime.write(
            "/tmp/openhands-config.toml",
            public_llm_config(ctx, endpoint, secret).encode(),
        )
        await runtime.write("/tmp/run-openhands.sh", RUNNER.read_bytes())
        await runtime.write("/tmp/apply-openhands-patch.py", APPLY_PATCH.read_bytes())

        env = {
            "OPENHANDS_AGENT_CLASS": self.config.agent_class,
            "OPENHANDS_COMMIT": self.config.commit,
            "OPENHANDS_COMMAND_TIMEOUT": str(self.config.command_timeout),
            "OPENHANDS_INSTANCE_ID": instance["instance_id"],
            "OPENHANDS_MAX_ITERATIONS": str(self.config.max_iterations),
            "OPENHANDS_MEMORY_LIMIT_MB": str(self.config.memory_limit_mb),
        }
        result = await runtime.run(["bash", "/tmp/run-openhands.sh"], env)
        if result.exit_code != 0:
            output = result.stdout + result.stderr
            raise RuntimeError(f"OpenHands launch failed: {output[-8000:]}")
        trace.info["openhands_patch"] = json.loads((await runtime.read("/tmp/openhands-patch.json")).decode())
        trace.info["openhands_reasoning_history"] = json.loads(
            (await runtime.read("/tmp/openhands-reasoning-audit.json")).decode()
        )
        return result
