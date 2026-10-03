from pathlib import Path

from pydantic import Field
from verifiers.v1.clients import RolloutContext
from verifiers.v1.harness import Harness, HarnessConfig
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.trace import Trace

ASSET_DIR = Path(__file__).parent
PROGRAM_SOURCE = (ASSET_DIR / "program.py").read_text()
SYSTEM_PROMPT = (ASSET_DIR / "system_prompt.txt").read_bytes()


class SWERebenchReactConfig(HarnessConfig):
    max_steps: int = Field(250, ge=1)
    command_timeout: int = Field(300, ge=1)
    output_limit: int = Field(20_000, ge=1_000)


class SWERebenchReactHarness(Harness[SWERebenchReactConfig]):
    APPENDS_SYSTEM_PROMPT = True
    SUPPORTS_MCP = False

    async def setup(self, runtime: Runtime) -> None:
        await runtime.write("/tmp/swe-rebench-system-prompt.txt", SYSTEM_PROMPT)
        await runtime.prepare_uv_script(PROGRAM_SOURCE, self.config.env)

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
            raise ValueError("SWE-rebench ReAct does not support disabling tools")
        if mcp_urls:
            raise ValueError("SWE-rebench ReAct does not support MCP tools")
        _, prompt = self.resolve_prompt(trace.task)
        if not isinstance(prompt, str):
            raise ValueError("SWE-rebench ReAct requires a string task prompt")
        await runtime.write("/tmp/swe-rebench-issue.txt", prompt.encode())
        program = await runtime.prepare_uv_script(PROGRAM_SOURCE, self.config.env)
        args = [
            *program,
            "--base-url",
            endpoint,
            f"--api-key={secret}",
            "--model",
            ctx.model,
            "--system-prompt",
            "/tmp/swe-rebench-system-prompt.txt",
            "--issue",
            "/tmp/swe-rebench-issue.txt",
            "--max-steps",
            str(self.config.max_steps),
            "--command-timeout",
            str(self.config.command_timeout),
            "--output-limit",
            str(self.config.output_limit),
        ]
        return await runtime.run_program(args, self.config.env)
