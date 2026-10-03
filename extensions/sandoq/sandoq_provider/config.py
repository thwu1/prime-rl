"""Env-var configuration for the sandoq sandbox provider shim.

All knobs are environment variables so a run opts in with ``VF_SANDBOX_PROVIDER=sandoq``
plus (optionally) these, without touching any config files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from sandoq_provider.utils import duration_seconds

# Default to the multi-cluster Cluster Gateway (recommended: it routes to the cluster
# hosting the env and follows blue/green cluster swaps). NOTE: an earlier gateway
# mis-route for this env (create-session hashed to `cua-eval-v2` -> 404) was fixed by
# the sandoq team and verified to route to eks-prod. To pin a single cluster, override
# SANDOQ_BASE_URL with a direct URL, e.g. https://sandoq.eks-prod.cf.aws.metafb.cloud
_DEFAULT_BASE_URL = "https://sandoq-gateway.eks-prod.cf.aws.metafb.cloud"
_DEFAULT_ENVIRONMENT = "ram-prime-rl-sandbox"

# start_commands that are pure keep-alives — nothing to replay for these.
_TRIVIAL_START_COMMANDS = frozenset({"", "tail -f /dev/null", "sleep infinity"})


def parse_duration_seconds(value: str | None, default: float) -> float:
    """Parse a Go-ish duration (``30m``, ``600s``, ``1h``, bare number = seconds)."""
    try:
        return duration_seconds(value, default)
    except ValueError:
        return default


@dataclass(frozen=True)
class SandoqConfig:
    base_url: str
    default_environment: str
    env_map: dict[str, str]
    lease_duration: str
    renew_margin_s: float
    create_deadline_s: float
    owner: str

    def resolve_environment(self, docker_image: str | None) -> str:
        """Map a verifiers ``docker_image`` onto a deployed sandoq Environment name.

        Precedence: exact match in ``SANDOQ_ENV_MAP`` -> ``"*"`` wildcard -> default.
        """
        img = docker_image or ""
        if img in self.env_map:
            return self.env_map[img]
        if "*" in self.env_map:
            return self.env_map["*"]
        return self.default_environment


def _load() -> SandoqConfig:
    env_map: dict[str, str] = {}
    raw_map = os.environ.get("SANDOQ_ENV_MAP", "").strip()
    if raw_map:
        try:
            parsed = json.loads(raw_map)
            if isinstance(parsed, dict):
                env_map = {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            env_map = {}
    return SandoqConfig(
        base_url=os.environ.get("SANDOQ_BASE_URL", _DEFAULT_BASE_URL).rstrip("/"),
        default_environment=os.environ.get("SANDOQ_DEFAULT_ENVIRONMENT", _DEFAULT_ENVIRONMENT),
        env_map=env_map,
        lease_duration=os.environ.get("SANDOQ_LEASE_DURATION", "30m"),
        renew_margin_s=parse_duration_seconds(os.environ.get("SANDOQ_RENEW_MARGIN"), 600.0),
        create_deadline_s=parse_duration_seconds(os.environ.get("SANDOQ_CREATE_DEADLINE"), 300.0),
        owner=os.environ.get("SANDOQ_OWNER") or os.environ.get("USER") or "prime-rl",
    )


_config: SandoqConfig | None = None


def get_config() -> SandoqConfig:
    global _config
    if _config is None:
        _config = _load()
    return _config


def reset_config_cache() -> None:
    """Drop the cached config (tests set env vars then re-read)."""
    global _config
    _config = None


def is_trivial_start_command(cmd: str | None) -> bool:
    return (cmd or "").strip() in _TRIVIAL_START_COMMANDS
