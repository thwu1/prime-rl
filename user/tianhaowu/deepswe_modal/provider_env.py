"""Environment wiring shared by DeepSWE sandbox providers."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sandoq_proxy import DirectConnectProxy

PROJECT_DIR = Path("/storage/home/tianhaowu/prime-rl")
SANDOQ_CLIENT_SITE = Path("/checkpoint/ram/tianhaowu/deepswe_eval/sandoq-client-site")
PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def provider_environment(
    provider: str,
    base: dict[str, str] | None = None,
    n_concurrent: int | None = None,
    startup_timeout_sec: int = 3600,
) -> dict[str, str]:
    if provider not in {"modal", "vmvm", "sandoq"}:
        raise ValueError(f"unsupported sandbox provider: {provider}")
    if n_concurrent is not None and (
        not isinstance(n_concurrent, int) or isinstance(n_concurrent, bool) or n_concurrent <= 0
    ):
        raise ValueError("n_concurrent must be positive")
    if (
        not isinstance(startup_timeout_sec, int)
        or isinstance(startup_timeout_sec, bool)
        or startup_timeout_sec <= 0
    ):
        raise ValueError("startup_timeout_sec must be positive")
    env = dict(base or os.environ)
    provider_paths = [
        str(PROJECT_DIR),
        str(PROJECT_DIR / "environments/vmvm_tb_v2"),
        str(PROJECT_DIR / "deps/sandoq-provider/extensions/sandoq"),
    ]
    if SANDOQ_CLIENT_SITE.is_dir():
        provider_paths.append(str(SANDOQ_CLIENT_SITE))
    if env.get("PYTHONPATH"):
        provider_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(provider_paths)
    env["MODAL_DISABLE_API_PROXY"] = "1"
    env.pop("VF_SANDBOX_PROVIDER", None)

    if provider == "vmvm":
        env.setdefault("VACLI_LEASE_RETRIES", "20")
        if n_concurrent is None:
            env.setdefault("VACLI_MAX_CONCURRENT_LEASES", "16")
        else:
            env["VACLI_MAX_CONCURRENT_LEASES"] = str(n_concurrent)
        env.setdefault("VACLI_MAX_PULL_RETRIES", "20")
        env.setdefault("VACLI_IMAGE_PULL_TIMEOUT_SECONDS", str(startup_timeout_sec))
    elif provider == "sandoq":
        for key in PROXY_ENV_KEYS:
            env.pop(key, None)
        if not SANDOQ_CLIENT_SITE.is_dir():
            raise RuntimeError(
                f"Sandoq client site is missing: {SANDOQ_CLIENT_SITE}; run setup_sandoq_client.sbatch first"
            )
        env.setdefault("OCI_RUNNER_OBSERVABILITY", "1")
        env.setdefault(
            "OCI_RUNNER_BASE_URL",
            "https://sandoq.eks-prod.cf.aws.metafb.cloud",
        )
        env.setdefault("OCI_RUNNER_ENVIRONMENT", "oci-runner")
        env.setdefault("OCI_RUNNER_LEASE_DURATION", "1h")
        env.setdefault(
            "OCI_RUNNER_TOKEN_FILE",
            "/home/tianhaowu/.config/oci-runner/token",
        )
        env.setdefault("OCI_RUNNER_SESSION_REUSE", "1")
        env.setdefault("OCI_RUNNER_POOL_MAX_REUSE_COUNT", "1")
        env.setdefault("OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES", "0")
        env.setdefault("OCI_RUNNER_PODMAN_FUSE_OVERLAYFS", "1")
        env.setdefault("OCI_RUNNER_FUSE_OVERLAYFS_PATH", "/usr/bin/fuse-overlayfs")
        env.setdefault("OCI_RUNNER_LIBFUSE3_PATH", "/lib/x86_64-linux-gnu/libfuse3.so.3")
        env.setdefault("OCI_RUNNER_PULL_TIMEOUT", f"{startup_timeout_sec}s")
        env.setdefault("OCI_RUNNER_PULL_POLL_MAX_ERRORS", "20")
        if n_concurrent is None:
            env.setdefault("OCI_RUNNER_POOL_SIZE", "16")
        else:
            env["OCI_RUNNER_POOL_SIZE"] = str(n_concurrent)
        env.setdefault("OCI_RUNNER_POOL_MIN_SIZE", "0")
    return env


@contextmanager
def provider_environment_context(
    provider: str,
    base: dict[str, str] | None = None,
    n_concurrent: int | None = None,
    startup_timeout_sec: int = 3600,
) -> Iterator[dict[str, str]]:
    env = provider_environment(provider, base, n_concurrent, startup_timeout_sec)
    if provider != "sandoq":
        yield env
        return
    with DirectConnectProxy() as proxy:
        env["HTTPS_PROXY"] = proxy.url
        env["https_proxy"] = proxy.url
        yield env
