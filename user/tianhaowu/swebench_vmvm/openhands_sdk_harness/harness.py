import hashlib
import json
import shlex
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jinja2 import Template
from pydantic import Field
from verifiers.v1.clients import RolloutContext
from verifiers.v1.harness import Harness, HarnessConfig
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.trace import Trace

ASSET_DIR = Path(__file__).resolve().parent
PROXY = ASSET_DIR / "proxy.py"
RUNNER = ASSET_DIR / "runner.py"
RUN_SCRIPT = ASSET_DIR / "run.sh"
SYSTEM_PROMPT = ASSET_DIR / "official_system_prompt.txt"
INSTRUCTION_TEMPLATE = ASSET_DIR / "official_instruction.j2"
ZSTD = Path("/usr/bin/zstd")
SETUP_ROOT = Path("/checkpoint/ram/tianhaowu/swebench_vmvm/openhands_sdk_setup")


class OpenHandsSDKHarnessConfig(HarnessConfig):
    archive_path: Path = SETUP_ROOT / "openhands-sdk-1.17.0.tar.zst"
    max_iterations: int = Field(200, ge=1)
    command_timeout: int = Field(1800, ge=1)
    request_timeout: int = Field(3600, ge=1)


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
def _serve_archive(path: Path) -> Iterator[int]:
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


def _archive_digest(path: Path) -> str:
    checksum = path.with_suffix(path.suffix + ".sha256")
    if checksum.is_file():
        digest = checksum.read_text().split()[0]
        if len(digest) != 64:
            raise ValueError(f"Invalid archive checksum in {checksum}")
        return digest
    with path.open("rb") as archive:
        return hashlib.file_digest(archive, "sha256").hexdigest()


def _render_instruction(trace: Trace) -> str:
    task_dir = Path(trace.task.task_dir)
    instance = json.loads((task_dir / "tests" / "config.json").read_text())
    instance["repo_language"] = "Python"
    instance["problem_statement"] = trace.task.prompt.strip()
    return Template(INSTRUCTION_TEMPLATE.read_text()).render(
        workspace_path=trace.task.workdir,
        instance=instance,
    )


class OpenHandsSDKHarness(Harness[OpenHandsSDKHarnessConfig]):
    APPENDS_SYSTEM_PROMPT = False
    SUPPORTS_MCP = False

    async def setup(self, runtime: Runtime) -> None:
        archive = self.config.archive_path.resolve()
        if not archive.is_file():
            raise FileNotFoundError(f"OpenHands SDK archive does not exist: {archive}")
        if not ZSTD.is_file():
            raise FileNotFoundError(f"zstd executable does not exist: {ZSTD}")

        digest = _archive_digest(archive)
        await runtime.write("/tmp/swebench-zstd", ZSTD.read_bytes())
        with _serve_archive(archive) as port:
            async with runtime.host_endpoint(port) as base_url:
                script = f"""
set -euo pipefail
archive=/tmp/openhands-sdk.tar.zst
setup_root={shlex.quote(str(SETUP_ROOT))}
python_bin=$(command -v python3 || command -v python)
"$python_bin" -c 'import shutil, sys, urllib.request; opener = urllib.request.build_opener(urllib.request.ProxyHandler({{}})); response = opener.open(sys.argv[1]); target = open(sys.argv[2], "wb"); shutil.copyfileobj(response, target); target.close(); response.close()' {shlex.quote(base_url + "/archive")} "$archive"
echo {shlex.quote(digest + "  /tmp/openhands-sdk.tar.zst")} | sha256sum -c -
chmod 755 /tmp/swebench-zstd
rm -rf "$setup_root"
mkdir -p "$setup_root"
/tmp/swebench-zstd -d -c "$archive" | tar -xf - -C "$setup_root"
test -x "$setup_root/.venv/bin/python"
test -f "$setup_root/manifest.json"
"$setup_root/.venv/bin/python" -c 'import importlib.metadata; assert importlib.metadata.version("openhands-sdk") == "1.17.0"'
""".strip()
                result = await runtime.run(["bash", "-lc", script], {})
        if result.exit_code != 0:
            output = result.stdout + result.stderr
            raise RuntimeError(f"OpenHands SDK setup failed: {output[-4000:]}")

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
            raise ValueError("The official OpenHands SDK SWE-bench harness does not support MCP tools")
        if self.config.command_timeout != 1800:
            raise ValueError("The published OpenHands SDK recipe requires command_timeout=1800")

        filemode = await runtime.run(
            ["git", "-C", trace.task.workdir, "config", "--local", "core.fileMode", "false"],
            {},
        )
        if filemode.exit_code != 0:
            output = filemode.stdout + filemode.stderr
            raise RuntimeError(f"disabling synthetic VMVM file-mode changes failed: {output[-4000:]}")
        verified_filemode = await runtime.run(
            ["git", "-C", trace.task.workdir, "config", "--local", "--bool", "core.fileMode"],
            {},
        )
        if verified_filemode.exit_code != 0 or verified_filemode.stdout.strip() != "false":
            output = verified_filemode.stdout + verified_filemode.stderr
            raise RuntimeError(f"verifying core.fileMode=false failed: {output[-4000:]}")

        instruction = _render_instruction(trace)
        await runtime.write("/tmp/openhands-sdk-instruction.txt", instruction.encode())
        await runtime.write("/tmp/openhands-sdk-system.txt", SYSTEM_PROMPT.read_bytes())
        await runtime.write("/tmp/openhands-sdk-proxy.py", PROXY.read_bytes())
        await runtime.write("/tmp/openhands-sdk-runner.py", RUNNER.read_bytes())
        await runtime.write("/tmp/run-openhands-sdk.sh", RUN_SCRIPT.read_bytes())

        env = {
            "OPENHANDS_MAX_ITERATIONS": str(self.config.max_iterations),
            "OPENHANDS_REQUEST_TIMEOUT": str(self.config.request_timeout),
            "OPENHANDS_UPSTREAM_SECRET": secret,
            "OPENHANDS_UPSTREAM_URL": endpoint,
            "OPENHANDS_WORKSPACE": trace.task.workdir,
            "LLM_MODEL": f"openai/{ctx.model}",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fileMode",
            "GIT_CONFIG_VALUE_0": "false",
        }
        result = await runtime.run(["bash", "/tmp/run-openhands-sdk.sh"], env)
        if result.exit_code != 0:
            output = result.stdout + result.stderr
            raise RuntimeError(f"OpenHands SDK launch failed: {output[-8000:]}")

        agent_result = json.loads((await runtime.read("/tmp/openhands-sdk-result.json")).decode())
        proxy_audit = json.loads((await runtime.read("/tmp/openhands-sdk-proxy-audit.json")).decode())
        manifest = json.loads((await runtime.read(str(SETUP_ROOT / "manifest.json"))).decode())
        if agent_result.get("openhands_sdk_version") != "1.17.0":
            raise RuntimeError(f"Unexpected OpenHands SDK version: {agent_result.get('openhands_sdk_version')}")
        if not proxy_audit.get("requests"):
            raise RuntimeError(f"OpenHands SDK made no model requests: {agent_result.get('exception')}")

        trace.info["openhands_sdk"] = {
            "agent": agent_result,
            "proxy": proxy_audit,
            "archive_manifest": manifest,
            "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
            "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.read_bytes()).hexdigest(),
        }
        return result
