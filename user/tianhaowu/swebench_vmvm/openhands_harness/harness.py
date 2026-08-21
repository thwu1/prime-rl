import hashlib
import json
import shlex
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import Field
from verifiers.v1.clients import RolloutContext
from verifiers.v1.harness import Harness, HarnessConfig
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.trace import Trace

ASSET_DIR = Path(__file__).resolve().parent
NEMO_GYM_CLIENT = ASSET_DIR / "nemo_gym_client.py"
RUNNER = ASSET_DIR / "run_openhands.sh"
APPLY_PATCH = ASSET_DIR / "apply_patch.py"
ZSTD = Path("/usr/bin/zstd")


class OpenHandsHarnessConfig(HarnessConfig):
    archive_path: Path = Path(
        "/checkpoint/ram/tianhaowu/swebench_vmvm/openhands_setup/openhands-v0.62.0-5f01800.tar.zst"
    )
    commit: str = "5f0180054732945df08ad2293903e6873f0492b6"
    agent_class: str = "CodeActAgent"
    max_iterations: int = Field(100, ge=1)
    command_timeout: int = Field(300, ge=1)
    memory_limit_mb: int = Field(32768, ge=1)


class _ArchiveHandler(BaseHTTPRequestHandler):
    archive_path: Path

    def do_GET(self) -> None:
        if self.path != "/archive":
            self.send_error(404)
            return
        size = self.archive_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/zstd")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with self.archive_path.open("rb") as archive:
            shutil.copyfileobj(archive, self.wfile)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def serve_archive(path: Path) -> Iterator[int]:
    handler = type("ArchiveHandler", (_ArchiveHandler,), {"archive_path": path})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def archive_digest(path: Path) -> str:
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if checksum_path.is_file():
        digest = checksum_path.read_text().split()[0]
        if len(digest) != 64:
            raise ValueError(f"Invalid archive checksum in {checksum_path}")
        return digest
    with path.open("rb") as archive:
        return hashlib.file_digest(archive, "sha256").hexdigest()


def instance_data(trace: Trace) -> dict:
    task_dir = Path(trace.task.task_dir)
    source = json.loads((task_dir / "tests" / "config.json").read_text())
    allowed = {
        "base_commit",
        "created_at",
        "difficulty",
        "environment_setup_commit",
        "hints_text",
        "instance_id",
        "problem_statement",
        "repo",
        "version",
    }
    return {key: value for key, value in source.items() if key in allowed}


def llm_config(ctx: RolloutContext, endpoint: str, secret: str) -> str:
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
            "max_input_tokens = 262144",
            "temperature = 1.0",
            "top_p = 0.95",
            "top_k = 20",
            "max_output_tokens = 32768",
            "timeout = 7200",
            "num_retries = 5",
            "drop_params = true",
            "completion_kwargs = { chat_template_kwargs = "
            "{ enable_thinking = true, truncate_history_thinking = false }, "
            "skip_special_tokens = false }",
        ]
    )
    return "\n".join(lines) + "\n"


class OpenHandsHarness(Harness[OpenHandsHarnessConfig]):
    APPENDS_SYSTEM_PROMPT = False
    SUPPORTS_MCP = False

    async def setup(self, runtime: Runtime) -> None:
        archive = self.config.archive_path.resolve()
        if not archive.is_file():
            raise FileNotFoundError(f"OpenHands archive does not exist: {archive}")
        if not ZSTD.is_file():
            raise FileNotFoundError(f"zstd executable does not exist: {ZSTD}")

        digest = archive_digest(archive)
        await runtime.write("/tmp/swebench-zstd", ZSTD.read_bytes())
        await runtime.write("/tmp/nemo_gym_client.py", NEMO_GYM_CLIENT.read_bytes())

        with serve_archive(archive) as port:
            async with runtime.host_endpoint(port) as base_url:
                url = f"{base_url}/archive"
                script = f"""
set -euo pipefail
archive=/tmp/openhands.tar.zst
setup_root=/checkpoint/ram/tianhaowu/swebench_vmvm/openhands_setup
python_bin=$(command -v python3 || command -v python)
"$python_bin" -c 'import shutil, sys, urllib.request; opener = urllib.request.build_opener(urllib.request.ProxyHandler({{}})); response = opener.open(sys.argv[1]); target = open(sys.argv[2], "wb"); shutil.copyfileobj(response, target); target.close(); response.close()' {shlex.quote(url)} "$archive"
echo {shlex.quote(digest + "  /tmp/openhands.tar.zst")} | sha256sum -c -
chmod 755 /tmp/swebench-zstd
mkdir -p "$setup_root"
/tmp/swebench-zstd -d -c "$archive" | tar -xf - -C "$setup_root"
cp /tmp/nemo_gym_client.py "$setup_root/OpenHands/openhands/agenthub/nemo_gym_client.py"
test -x "$setup_root/OpenHands/.venv/bin/python"
""".strip()
                result = await runtime.run(["bash", "-lc", script], {})
        if result.exit_code != 0:
            output = result.stdout + result.stderr
            raise RuntimeError(f"OpenHands setup failed: {output[-4000:]}")

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
            llm_config(ctx, endpoint, secret).encode(),
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
        return result
