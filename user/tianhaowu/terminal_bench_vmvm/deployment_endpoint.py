"""Strict, secret-free binding for a deployment-local proxy endpoint."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENDPOINT_SCHEMA_VERSION = 1
ENDPOINT_KIND = "deployment_local_proxy_info"
AUTHORITY_KIND = "deployment_endpoint_authority"
MAX_PROXY_INFO_BYTES = 1 << 20
DEPLOYMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PROXY_INFO_KEYS = frozenset(
    {
        "host",
        "port",
        "url",
        "api_key",
        "model",
        "proxy_jobid",
        "extras",
    }
)
ROUTING_EXTRA_KEYS = frozenset(
    {
        "connection_mode",
        "proxy_type",
        "redis_port",
        "routing_policy",
        "sticky",
        "sticky_ttl",
    }
)


class EndpointBindingError(ValueError):
    """A proxy endpoint could not be bound without ambiguity."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DeploymentEndpoint:
    proxy_info_path: Path
    proxy_info_sha256: str
    authority_sha256: str
    proxy_base_url: str = field(repr=False)
    client_base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    served_model: str
    proxy_job_id: str
    routing_metadata: dict[str, str | int | bool | None] = field(repr=False)

    @property
    def binding(self) -> dict[str, Any]:
        return {
            "schema_version": ENDPOINT_SCHEMA_VERSION,
            "kind": ENDPOINT_KIND,
            "proxy_info": {
                "path": str(self.proxy_info_path),
                "sha256": self.proxy_info_sha256,
            },
            "authority_sha256": self.authority_sha256,
        }


def _fail(reason: str) -> EndpointBindingError:
    return EndpointBindingError(reason)


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IFMT(value.st_mode),
    )


def _read_stable_file(path: Path) -> tuple[Path, bytes, str]:
    try:
        resolved = path.resolve(strict=True)
        before_path = resolved.stat(follow_symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise _fail("proxy_info_unreadable") from exc
    if not stat.S_ISREG(before_path.st_mode):
        raise _fail("proxy_info_unreadable")
    if before_path.st_size > MAX_PROXY_INFO_BYTES:
        raise _fail("proxy_info_malformed")

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise _fail("proxy_info_unreadable") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            before_fd = os.fstat(handle.fileno())
            if not stat.S_ISREG(before_fd.st_mode):
                raise _fail("proxy_info_unreadable")
            if before_fd.st_size > MAX_PROXY_INFO_BYTES:
                raise _fail("proxy_info_malformed")
            data = handle.read(MAX_PROXY_INFO_BYTES + 1)
            if len(data) > MAX_PROXY_INFO_BYTES:
                raise _fail("proxy_info_malformed")
            after_fd = os.fstat(handle.fileno())
    except EndpointBindingError:
        raise
    except OSError as exc:
        raise _fail("proxy_info_unreadable") from exc

    try:
        after_path = resolved.stat(follow_symlinks=False)
    except OSError as exc:
        raise _fail("proxy_info_unstable") from exc
    signatures = {
        _stat_signature(before_path),
        _stat_signature(before_fd),
        _stat_signature(after_fd),
        _stat_signature(after_path),
    }
    if len(signatures) != 1 or len(data) != after_fd.st_size:
        raise _fail("proxy_info_unstable")
    return resolved, data, hashlib.sha256(data).hexdigest()


def _reject_constant(_value: str) -> None:
    raise _fail("proxy_info_malformed")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("proxy_info_malformed")
        result[key] = value
    return result


def _load_strict_json(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except EndpointBindingError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _fail("proxy_info_malformed") from exc
    if not isinstance(value, dict) or set(value) != PROXY_INFO_KEYS:
        raise _fail("proxy_info_malformed")
    return value


def _nonempty_safe_string(value: Any) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise _fail("proxy_info_malformed")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise _fail("proxy_info_malformed")
    return value


def _validate_local_paths(
    proxy_info_path: Path,
    deployment_spec: Path,
    deployment_id: str,
) -> Path:
    try:
        resolved_spec = deployment_spec.resolve(strict=True)
        spec_stat = resolved_spec.stat(follow_symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise _fail("deployment_spec_unreadable") from exc
    if not stat.S_ISREG(spec_stat.st_mode):
        raise _fail("deployment_spec_unreadable")
    if (
        proxy_info_path.name != "proxy_info.json"
        or resolved_spec.name != "spec.yaml"
        or proxy_info_path.parent != resolved_spec.parent
        or proxy_info_path.parent.name != deployment_id
    ):
        raise _fail("proxy_info_not_deployment_local")
    return resolved_spec


def _validate_proxy_url(host: str, port: int, value: Any) -> str:
    url = _nonempty_safe_string(value)
    try:
        parsed = urllib.parse.urlsplit(url)
        parsed_port = parsed.port
    except ValueError as exc:
        raise _fail("proxy_info_malformed") from exc
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname != host
        or parsed_port != port
        or parsed.path
        or parsed.query
        or parsed.fragment
        or url != f"http://{host}:{port}"
    ):
        raise _fail("proxy_info_malformed")
    return url


def _validate_extras(value: Any) -> dict[str, str | int | bool | None]:
    if not isinstance(value, dict):
        raise _fail("proxy_info_malformed")
    for item in value.values():
        if not isinstance(item, (str, int, float, bool)):
            raise _fail("proxy_info_malformed")
        if isinstance(item, float) and not math.isfinite(item):
            raise _fail("proxy_info_malformed")

    for key in ("proxy_type", "connection_mode", "routing_policy"):
        if key in value:
            _nonempty_safe_string(value[key])
    for key in ("prometheus_port", "redis_port"):
        if key in value:
            item = value[key]
            if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 65535:
                raise _fail("proxy_info_malformed")
    if "sticky" in value and not isinstance(value["sticky"], bool):
        raise _fail("proxy_info_malformed")
    if "sticky_ttl" in value:
        item = value["sticky_ttl"]
        if not isinstance(item, int) or isinstance(item, bool) or item < 1:
            raise _fail("proxy_info_malformed")
    return {key: value[key] for key in sorted(value) if key in ROUTING_EXTRA_KEYS}


def _canonical_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _fail("proxy_info_malformed") from exc
    return hashlib.sha256(encoded).hexdigest()


def load_deployment_endpoint(
    proxy_info: Path,
    *,
    deployment_id: str,
    expected_model: str,
    deployment_spec: Path,
    expected_proxy_info_sha256: str | None = None,
) -> DeploymentEndpoint:
    """Load one stable proxy file and derive a secret-free endpoint binding."""

    if not isinstance(deployment_id, str) or DEPLOYMENT_RE.fullmatch(deployment_id) is None:
        raise _fail("invalid_deployment")
    if not isinstance(expected_model, str) or not expected_model.strip():
        raise _fail("invalid_model")
    if expected_proxy_info_sha256 is not None and (
        not isinstance(expected_proxy_info_sha256, str) or SHA256_RE.fullmatch(expected_proxy_info_sha256) is None
    ):
        raise _fail("invalid_expected_proxy_info_sha256")

    resolved_path, data, file_sha256 = _read_stable_file(proxy_info)
    _validate_local_paths(resolved_path, deployment_spec, deployment_id)
    if expected_proxy_info_sha256 is not None and file_sha256 != expected_proxy_info_sha256:
        raise _fail("proxy_info_sha256_mismatch")
    payload = _load_strict_json(data)

    host = _nonempty_safe_string(payload["host"])
    port = payload["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise _fail("proxy_info_malformed")
    proxy_base_url = _validate_proxy_url(host, port, payload["url"])
    client_base_url = f"{proxy_base_url}/v1"
    api_key = _nonempty_safe_string(payload["api_key"])
    served_model = _nonempty_safe_string(payload["model"])
    if served_model != expected_model:
        raise _fail("proxy_info_model_mismatch")
    proxy_job_id = _nonempty_safe_string(payload["proxy_jobid"])
    routing = _validate_extras(payload["extras"])

    authority_sha256 = _canonical_sha256(
        {
            "schema_version": ENDPOINT_SCHEMA_VERSION,
            "kind": AUTHORITY_KIND,
            "deployment": deployment_id,
            "model": served_model,
            "proxy_job_id": proxy_job_id,
            "client_url_sha256": hashlib.sha256(client_base_url.encode("utf-8")).hexdigest(),
            "routing": routing,
        }
    )
    return DeploymentEndpoint(
        proxy_info_path=resolved_path,
        proxy_info_sha256=file_sha256,
        authority_sha256=authority_sha256,
        proxy_base_url=proxy_base_url,
        client_base_url=client_base_url,
        api_key=api_key,
        served_model=served_model,
        proxy_job_id=proxy_job_id,
        routing_metadata=routing,
    )


def validate_endpoint_binding(value: object) -> dict[str, Any]:
    """Validate and normalize a persisted secret-free endpoint binding."""

    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "kind",
        "proxy_info",
        "authority_sha256",
    }:
        raise _fail("invalid_endpoint_binding")
    schema_version = value["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != ENDPOINT_SCHEMA_VERSION
        or value["kind"] != ENDPOINT_KIND
    ):
        raise _fail("invalid_endpoint_binding")
    proxy_info = value["proxy_info"]
    if not isinstance(proxy_info, dict) or set(proxy_info) != {"path", "sha256"}:
        raise _fail("invalid_endpoint_binding")
    path = proxy_info["path"]
    if (
        not isinstance(path, str)
        or not path
        or not Path(path).is_absolute()
        or ".." in Path(path).parts
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in path)
        or os.path.normpath(path) != path
        or Path(path).name != "proxy_info.json"
    ):
        raise _fail("invalid_endpoint_binding")
    if not isinstance(proxy_info["sha256"], str) or SHA256_RE.fullmatch(proxy_info["sha256"]) is None:
        raise _fail("invalid_endpoint_binding")
    authority_sha256 = value["authority_sha256"]
    if not isinstance(authority_sha256, str) or SHA256_RE.fullmatch(authority_sha256) is None:
        raise _fail("invalid_endpoint_binding")
    return {
        "schema_version": ENDPOINT_SCHEMA_VERSION,
        "kind": ENDPOINT_KIND,
        "proxy_info": {
            "path": path,
            "sha256": proxy_info["sha256"],
        },
        "authority_sha256": authority_sha256,
    }
