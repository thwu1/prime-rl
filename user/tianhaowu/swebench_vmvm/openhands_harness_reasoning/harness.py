import json
import shlex
from pathlib import Path

from openhands_harness.harness import (
    ZSTD,
    OpenHandsHarness,
    archive_digest,
    serve_archive,
)
from verifiers.v1.clients import RolloutContext
from verifiers.v1.runtimes import ProgramResult, Runtime
from verifiers.v1.trace import Trace

ASSET_DIR = Path(__file__).resolve().parent
NEMO_GYM_CLIENT = ASSET_DIR / "nemo_gym_client.py"


class OpenHandsReasoningHarness(OpenHandsHarness):
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
        result = await super().launch(ctx, trace, runtime, endpoint, secret, mcp_urls)
        trace.info["openhands_reasoning_history"] = json.loads(
            (await runtime.read("/tmp/openhands-reasoning-audit.json")).decode()
        )
        return result
