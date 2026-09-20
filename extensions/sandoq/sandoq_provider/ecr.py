"""ECR pull-through image resolution and short-lived credential vending."""

from __future__ import annotations

import os
import pwd
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from prime_sandboxes.exceptions import APIError

from sandoq_provider.secrets import read_secret_file
from sandoq_provider.utils import duration_seconds

_DEFAULT_PULL_THROUGH_PREFIX = "pt_dockerio"
_DOCKER_HUB_REGISTRIES = {"docker.io", "index.docker.io", "registry-1.docker.io"}
_REGISTRY = re.compile(r"^[a-zA-Z0-9.-]+(?::[0-9]+)?$")
_AWS_ECR_REGISTRY = re.compile(r"^(?P<account>[0-9]{12})\.dkr\.ecr\.(?P<region>[a-z0-9-]+)\.amazonaws\.com$")
_REGION = re.compile(r"^[a-z0-9-]+$")
_PREFIX = re.compile(r"^[a-z0-9][a-z0-9_./-]*$")


@dataclass(frozen=True)
class ECRConfig:
    registry: str | None
    region: str
    pull_through_prefix: str
    token_file: Path | None
    client_cert_path: Path | None
    ucloud_executable: str
    refresh_interval_s: float
    command_timeout_s: float
    auxiliary_registries: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.registry is not None

    @property
    def authenticated_registries(self) -> tuple[str, ...]:
        primary = (self.registry,) if self.registry is not None else ()
        return (*primary, *self.auxiliary_registries)

    @classmethod
    def from_env(cls) -> ECRConfig:
        registry = os.environ.get("OCI_RUNNER_ECR_REGISTRY", "").strip().removeprefix("https://").rstrip("/") or None
        region = os.environ.get("OCI_RUNNER_ECR_REGION", "us-east-2").strip()
        prefix = os.environ.get("OCI_RUNNER_ECR_PULL_THROUGH_PREFIX", _DEFAULT_PULL_THROUGH_PREFIX).strip().strip("/")
        token_path = os.environ.get("OCI_RUNNER_ECR_TOKEN_FILE", "").strip()
        client_cert_path = os.environ.get("OCI_RUNNER_ECR_CLIENT_CERT_PATH", "").strip()
        executable = os.environ.get("OCI_RUNNER_ECR_UCLOUD", "ucloud").strip()
        auxiliary = tuple(
            dict.fromkeys(
                value.strip()
                for value in os.environ.get("OCI_RUNNER_ECR_AUXILIARY_REGISTRIES", "").split(",")
                if value.strip()
            )
        )
        refresh_interval_s = duration_seconds(os.environ.get("OCI_RUNNER_ECR_REFRESH_INTERVAL"), 4 * 3600.0)
        command_timeout_s = duration_seconds(os.environ.get("OCI_RUNNER_ECR_CREDENTIAL_TIMEOUT"), 60.0)
        if registry is not None and not _REGISTRY.fullmatch(registry):
            raise APIError("OCI_RUNNER_ECR_REGISTRY must be a registry hostname without a path")
        if not _REGION.fullmatch(region):
            raise APIError("OCI_RUNNER_ECR_REGION contains unsupported characters")
        if not prefix or not _PREFIX.fullmatch(prefix):
            raise APIError("OCI_RUNNER_ECR_PULL_THROUGH_PREFIX is invalid")
        if not executable or "\n" in executable or "\r" in executable:
            raise APIError("OCI_RUNNER_ECR_UCLOUD must name one executable")
        for auxiliary_registry in auxiliary:
            if not _AWS_ECR_REGISTRY.fullmatch(auxiliary_registry):
                raise APIError("OCI_RUNNER_ECR_AUXILIARY_REGISTRIES must contain comma-separated AWS ECR hostnames")
        auxiliary = tuple(value for value in auxiliary if value != registry)
        if "\n" in client_cert_path or "\r" in client_cert_path:
            raise APIError("OCI_RUNNER_ECR_CLIENT_CERT_PATH contains unsupported characters")
        if not 0 < refresh_interval_s < 12 * 3600:
            raise APIError("OCI_RUNNER_ECR_REFRESH_INTERVAL must be greater than zero and less than 12h")
        if command_timeout_s <= 0:
            raise APIError("OCI_RUNNER_ECR_CREDENTIAL_TIMEOUT must be greater than zero")
        return cls(
            registry=registry,
            region=region,
            pull_through_prefix=prefix,
            token_file=Path(token_path).expanduser() if token_path else None,
            client_cert_path=Path(client_cert_path).expanduser() if client_cert_path else None,
            ucloud_executable=executable,
            refresh_interval_s=refresh_interval_s,
            command_timeout_s=command_timeout_s,
            auxiliary_registries=auxiliary,
        )


def resolve_pull_image(reference: str, config: ECRConfig) -> str:
    """Map a Docker Hub reference to the configured ECR pull-through path."""
    image = reference.strip()
    if not image or any(character.isspace() for character in image) or "://" in image:
        raise APIError(f"invalid OCI image reference: {reference!r}")
    if not config.enabled:
        return image
    assert config.registry is not None
    first, separator, remainder = image.partition("/")
    if first == config.registry:
        return image
    if first in _DOCKER_HUB_REGISTRIES:
        if not separator or not remainder:
            raise APIError(f"invalid Docker Hub image reference: {reference!r}")
        upstream = remainder
    elif separator and ("." in first or ":" in first or first == "localhost"):
        return image
    else:
        upstream = image
    if "/" not in upstream.split("@", 1)[0]:
        upstream = f"library/{upstream}"
    return f"{config.registry}/{config.pull_through_prefix}/{upstream}"


def is_configured_ecr_image(reference: str, config: ECRConfig) -> bool:
    return bool(config.registry and reference.partition("/")[0] == config.registry)


def authenticated_ecr_registry(reference: str, config: ECRConfig) -> str | None:
    """Return the configured ECR registry which can authenticate ``reference``."""

    registry = reference.partition("/")[0]
    return registry if registry in config.authenticated_registries else None


def _read_token_file(path: Path) -> str:
    return read_secret_file(path, "ECR token", APIError)


def _client_cert_environment(config: ECRConfig) -> dict[str, str]:
    """Build the ucloud-only environment without changing the host process."""
    environment = os.environ.copy()
    existing_cert = environment.pop("THRIFT_TLS_CL_CERT_PATH", "").strip()
    existing_key = environment.pop("THRIFT_TLS_CL_KEY_PATH", "").strip()

    if config.client_cert_path is not None:
        cert_path = config.client_cert_path
        if not cert_path.is_file():
            raise APIError(f"ECR client certificate file does not exist or is not regular: {cert_path}")
        environment["THRIFT_TLS_CL_CERT_PATH"] = str(cert_path)
        environment["THRIFT_TLS_CL_KEY_PATH"] = str(cert_path)
        return environment

    if existing_cert and existing_key:
        environment["THRIFT_TLS_CL_CERT_PATH"] = existing_cert
        environment["THRIFT_TLS_CL_KEY_PATH"] = existing_key
        return environment

    username = pwd.getpwuid(os.getuid()).pw_name
    discovered = Path("/var/facebook/credentials") / username / "x509" / f"{username}.pem"
    if discovered.is_file():
        environment["THRIFT_TLS_CL_CERT_PATH"] = str(discovered)
        environment["THRIFT_TLS_CL_KEY_PATH"] = str(discovered)
    return environment


class ECRCredentialCache:
    """Keep one credential in memory and refresh it well before ECR's 12h expiry."""

    def __init__(self, config: ECRConfig, registry: str | None = None) -> None:
        self.config = config
        self.registry = registry if registry is not None else config.registry
        if self.registry not in config.authenticated_registries:
            raise APIError(f"ECR registry is not configured for authentication: {self.registry!r}")
        self._lock = threading.Lock()
        self._password: str | None = None
        self._fetched_at = 0.0
        self._generation = 0

    def get(self) -> dict[str, object]:
        if self.registry is None:
            raise APIError("ECR authentication was requested without a registry")
        with self._lock:
            if self.config.token_file is not None and self.registry == self.config.registry:
                now = time.monotonic()
                password = _read_token_file(self.config.token_file)
                reused = password == self._password
                if not reused:
                    self._password = password
                    self._fetched_at = now
                    self._generation += 1
                source = "token_file"
            else:
                now = time.monotonic()
                reused = self._password is not None and now - self._fetched_at < self.config.refresh_interval_s
                if not reused:
                    self._password = self._fetch_with_ucloud()
                    self._fetched_at = now
                    self._generation += 1
                password = self._password
                source = "ucloud"
            assert password is not None
            return {
                "password": password,
                "source": source,
                "generation": self._generation,
                "reused": reused,
                "age_seconds": max(0.0, now - self._fetched_at),
            }

    def _fetch_with_ucloud(self) -> str:
        assert self.registry is not None
        command = [self.config.ucloud_executable, "ecr", "get-credentials"]
        if self.registry == self.config.registry:
            command.extend(("--prod", "--region", self.config.region))
        else:
            match = _AWS_ECR_REGISTRY.fullmatch(self.registry)
            if match is None:
                raise APIError(f"auxiliary ECR registry has an unsupported hostname: {self.registry!r}")
            command.extend(
                (
                    "--account",
                    match.group("account"),
                    "--region",
                    match.group("region"),
                    "--role",
                    "SSOContainerRegistryReadOnly",
                )
            )
        command.extend(("--log-level", "error"))
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.config.command_timeout_s,
                env=_client_cert_environment(self.config),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise APIError(f"could not execute ucloud ECR credential command: {type(exc).__name__}") from exc
        if completed.returncode != 0:
            raise APIError(f"ucloud ECR credential command failed with exit code {completed.returncode}")
        password = completed.stdout.strip()
        if not password or "\n" in password or "\r" in password:
            raise APIError("ucloud ECR credential command returned an invalid password")
        return password


__all__ = [
    "authenticated_ecr_registry",
    "ECRConfig",
    "ECRCredentialCache",
    "is_configured_ecr_image",
    "resolve_pull_image",
]
