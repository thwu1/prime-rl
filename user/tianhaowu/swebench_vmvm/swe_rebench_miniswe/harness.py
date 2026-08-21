import json

from pydantic import Field
from verifiers.v1.clients import RolloutContext
from verifiers.v1.harness import Harness, HarnessConfig
from verifiers.v1.harnesses.mini_swe_agent.harness import PROGRAM_SOURCE
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.trace import Trace

MODEL_REGISTRY_PATH = "/tmp/swe-rebench-model-registry.json"
MODEL_REGISTRY = {
    "Qwen/Qwen3.6-27B": {
        "max_tokens": 81920,
        "max_input_tokens": 131072,
        "max_output_tokens": 81920,
        "input_cost_per_token": 0.00000015,
        "cache_read_input_token_cost": 0.000000015,
        "output_cost_per_token": 0.0000012,
        "litellm_provider": "openai",
        "mode": "chat",
    }
}


class SWERebenchMiniSWEConfig(HarnessConfig):
    version: str = "1.14.4"
    config_file: str = "swebench.yaml"
    config_overrides: list[str] = Field(default_factory=list)


class SWERebenchMiniSWEHarness(Harness[SWERebenchMiniSWEConfig]):
    APPENDS_SYSTEM_PROMPT = False
    SUPPORTS_MCP = False

    async def setup(self, runtime: Runtime) -> None:
        source = PROGRAM_SOURCE.replace("{version}", self.config.version)
        await runtime.write(MODEL_REGISTRY_PATH, json.dumps(MODEL_REGISTRY).encode())
        await runtime.prepare_uv_script(source, self.config.env)

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
            raise ValueError("mini-swe-agent does not support disabling tools")
        if mcp_urls:
            raise ValueError("mini-swe-agent does not support MCP tools")
        _, prompt = self.resolve_prompt(trace.task)
        source = PROGRAM_SOURCE.replace("{version}", self.config.version)
        args = [
            "--model",
            ctx.model,
            "--model-class",
            "litellm",
            "--task",
            prompt,
            "--exit-immediately",
            "--yolo",
            "--vf-config-file",
            self.config.config_file,
            "--vf-config-override",
            "model.model_kwargs.custom_llm_provider=openai",
            "--vf-config-override",
            f"model.model_kwargs.api_base={endpoint}",
            "--vf-config-override",
            f"model.model_kwargs.api_key={secret}",
            "--vf-config-override",
            f"model.litellm_model_registry={MODEL_REGISTRY_PATH}",
        ]
        for override in self.config.config_overrides:
            args.extend(["--vf-config-override", override])
        env = {
            **self.config.env,
            "MSWEA_CONFIGURED": "true",
            "MSWEA_SILENT_STARTUP": "true",
        }
        program = await runtime.prepare_uv_script(source, self.config.env)
        result = await runtime.run_program([*program, *args], env)
        combined = f"{result.stdout}\n{result.stderr}"
        if result.exit_code == 0 and "Error running agent:" in combined:
            return ProgramResult(1, result.stdout, result.stderr)
        return result
