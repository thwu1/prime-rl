from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_v1_runtime_uses_sandoq_client_without_prime_credentials() -> None:
    extension = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop("PRIME_API_KEY", None)
    env["VF_SANDBOX_PROVIDER"] = "oci-runner"
    env["PYTHONPATH"] = str(extension)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "import prime_sandboxes",
                    "from verifiers.v1.runtimes.prime import PrimeConfig, PrimeRuntime, ensure_prime_auth",
                    "runtime = PrimeRuntime(PrimeConfig())",
                    "assert type(runtime).__name__ == 'PrimeRuntime'",
                    "assert prime_sandboxes.AsyncSandboxClient.__module__ == 'sandoq_provider.oci_client'",
                    "assert ensure_prime_auth.__module__ == 'sandoq_provider'",
                ]
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
