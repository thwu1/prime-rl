#!/usr/bin/env python3
"""Strict, secret-free binding for the required LiteLLM timeout policy."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

import yaml
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode

POLICY_SCHEMA_VERSION = 1
DEFAULT_REQUEST_TIMEOUT = 7_200
KIMI_REQUEST_TIMEOUT = 43_200
REQUIRED_NUM_RETRIES = 0
MAX_YAML_BYTES = 4 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SUPPORTED_REQUEST_TIMEOUTS = frozenset({DEFAULT_REQUEST_TIMEOUT, KIMI_REQUEST_TIMEOUT})
YAML_MERGE_TAG = "tag:yaml.org,2002:merge"


class DeploymentProxyPolicyError(ValueError):
    """The deployment does not have the exact required proxy policy."""


class _DuplicateRejectingSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            event = self.peek_event()
            raise ComposerError(None, None, "aliases are not allowed", event.start_mark)
        return super().compose_node(parent, index)


def _construct_unique_mapping(
    loader: _DuplicateRejectingSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    if not isinstance(node, MappingNode):
        raise ConstructorError(None, None, "expected a mapping node", node.start_mark)
    if any(key_node.tag == YAML_MERGE_TAG for key_node, _ in node.value):
        raise ConstructorError(
            "while constructing a mapping",
            node.start_mark,
            "merge keys are not allowed",
            node.start_mark,
        )
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateRejectingSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        stat.S_IFMT(value.st_mode),
    )


def _read_stable_yaml(path: Path, *, label: str) -> tuple[Path, str, str]:
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_YAML_BYTES:
            raise DeploymentProxyPolicyError(f"{label}_unreadable")
        raw = resolved.read_bytes()
        after = resolved.stat(follow_symlinks=False)
    except OSError as error:
        raise DeploymentProxyPolicyError(f"{label}_unreadable") from error
    if _stat_signature(before) != _stat_signature(after) or len(raw) != after.st_size:
        raise DeploymentProxyPolicyError(f"{label}_changed")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeploymentProxyPolicyError(f"{label}_invalid") from error
    if "\t" in value or "\x00" in value:
        raise DeploymentProxyPolicyError(f"{label}_invalid")
    return resolved, value, hashlib.sha256(raw).hexdigest()


def _load_yaml_mapping(text: str, *, label: str) -> dict[Any, Any]:
    try:
        value = yaml.load(text, Loader=_DuplicateRejectingSafeLoader)
    except (yaml.YAMLError, TypeError, ValueError) as error:
        raise DeploymentProxyPolicyError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise DeploymentProxyPolicyError(f"{label}_invalid")
    return value


def _nested_mapping(value: dict[Any, Any], key: str, *, label: str) -> dict[Any, Any]:
    nested = value.get(key)
    if not isinstance(nested, dict):
        raise DeploymentProxyPolicyError(f"{label}_invalid")
    return nested


def request_timeout_for_model(model: str) -> int:
    return KIMI_REQUEST_TIMEOUT if model == "Kimi-K3" else DEFAULT_REQUEST_TIMEOUT


def _require_supported_timeout(value: Any) -> int:
    if type(value) is not int or value not in SUPPORTED_REQUEST_TIMEOUTS:
        raise DeploymentProxyPolicyError("expected_request_timeout_invalid")
    return value


def _validate_exact_policy(
    value: dict[Any, Any],
    *,
    expected_request_timeout: int,
    label: str,
) -> None:
    expected_request_timeout = _require_supported_timeout(expected_request_timeout)
    for key, expected in {
        "request_timeout": expected_request_timeout,
        "num_retries": REQUIRED_NUM_RETRIES,
    }.items():
        if key not in value:
            raise DeploymentProxyPolicyError(f"{label}_invalid")
        observed = value.get(key)
        if type(observed) is not int or observed != expected:
            raise DeploymentProxyPolicyError(f"{label}_invalid")


def _validate_policy_text(
    text: str,
    *,
    generated: bool,
    expected_request_timeout: int,
    label: str,
) -> None:
    document = _load_yaml_mapping(text, label=label)
    if generated:
        config = _nested_mapping(document, "litellm_settings", label=label)
    else:
        spec = _nested_mapping(document, "spec", label=label)
        proxy = _nested_mapping(spec, "proxy", label=label)
        config = _nested_mapping(proxy, "config", label=label)
    _validate_exact_policy(
        config,
        expected_request_timeout=expected_request_timeout,
        label=label,
    )


def validate_deployment_spec_proxy_policy(
    deployment_spec: Path,
    *,
    expected_spec_sha256: str,
    expected_request_timeout: int,
) -> Path:
    """Validate the typed policy in spec.yaml and return its deployment directory."""

    if not isinstance(expected_spec_sha256, str) or SHA256_RE.fullmatch(expected_spec_sha256) is None:
        raise DeploymentProxyPolicyError("deployment_spec_sha256_invalid")
    resolved, text, observed_sha256 = _read_stable_yaml(deployment_spec, label="deployment_spec")
    if observed_sha256 != expected_spec_sha256:
        raise DeploymentProxyPolicyError("deployment_spec_sha256_mismatch")
    _validate_policy_text(
        text,
        generated=False,
        expected_request_timeout=expected_request_timeout,
        label="deployment_proxy_policy",
    )
    return resolved.parent


def load_deployment_proxy_policy(
    deployment_spec: Path,
    *,
    expected_spec_sha256: str,
    expected_request_timeout: int,
) -> dict[str, Any]:
    """Validate spec and generated config, returning only policy values and a file hash."""

    deployment_dir = validate_deployment_spec_proxy_policy(
        deployment_spec,
        expected_spec_sha256=expected_spec_sha256,
        expected_request_timeout=expected_request_timeout,
    )
    config_path, generated, generated_sha256 = _read_stable_yaml(
        deployment_dir / "proxy_litellm_config.yaml",
        label="proxy_litellm_config",
    )
    _validate_policy_text(
        generated,
        generated=True,
        expected_request_timeout=expected_request_timeout,
        label="generated_proxy_policy",
    )
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "request_timeout": expected_request_timeout,
        "num_retries": REQUIRED_NUM_RETRIES,
        "proxy_litellm_config": {
            "path": str(config_path),
            "sha256": generated_sha256,
        },
    }


def validate_proxy_policy_binding(
    value: Any,
    *,
    expected_request_timeout: int | None = None,
) -> dict[str, Any]:
    """Validate one persisted secret-free generated proxy policy binding."""

    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "request_timeout",
        "num_retries",
        "proxy_litellm_config",
    }:
        raise DeploymentProxyPolicyError("proxy_policy_binding_invalid")
    schema_version = value.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != POLICY_SCHEMA_VERSION
    ):
        raise DeploymentProxyPolicyError("proxy_policy_binding_invalid")
    if expected_request_timeout is not None:
        expected_request_timeout = _require_supported_timeout(expected_request_timeout)
    request_timeout = value.get("request_timeout")
    num_retries = value.get("num_retries")
    if (
        not isinstance(request_timeout, int)
        or isinstance(request_timeout, bool)
        or request_timeout not in SUPPORTED_REQUEST_TIMEOUTS
        or (expected_request_timeout is not None and request_timeout != expected_request_timeout)
        or not isinstance(num_retries, int)
        or isinstance(num_retries, bool)
        or num_retries != REQUIRED_NUM_RETRIES
    ):
        raise DeploymentProxyPolicyError("proxy_policy_binding_invalid")
    artifact = value.get("proxy_litellm_config")
    if (
        not isinstance(artifact, dict)
        or set(artifact) != {"path", "sha256"}
        or not isinstance(artifact.get("path"), str)
        or not artifact["path"]
        or not isinstance(artifact.get("sha256"), str)
        or SHA256_RE.fullmatch(artifact["sha256"]) is None
    ):
        raise DeploymentProxyPolicyError("proxy_policy_binding_invalid")
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "request_timeout": request_timeout,
        "num_retries": REQUIRED_NUM_RETRIES,
        "proxy_litellm_config": dict(artifact),
    }


def _private_snapshot(path: Path, *, expected_sha256: str, label: str) -> tuple[Path, str]:
    resolved, text, observed_sha256 = _read_stable_yaml(path, label=label)
    try:
        mode = stat.S_IMODE(resolved.stat(follow_symlinks=False).st_mode)
    except OSError as error:
        raise DeploymentProxyPolicyError(f"{label}_unreadable") from error
    if mode != 0o600 or observed_sha256 != expected_sha256:
        raise DeploymentProxyPolicyError(f"{label}_invalid")
    return resolved, text


def _worker_route_projection(
    text: str,
    *,
    expected_backends: list[str],
    label: str,
) -> bytes:
    """Canonicalize a generated config after replacing only worker URLs."""

    from inference_route_generation import canonical_backend_identifier

    document = _load_yaml_mapping(text, label=label)
    model_list = document.get("model_list")
    if not isinstance(model_list, list) or len(model_list) != len(expected_backends):
        raise DeploymentProxyPolicyError(f"{label}_invalid")
    projected_entries: list[dict[Any, Any]] = []
    observed_backends: list[str] = []
    for raw_entry in model_list:
        if not isinstance(raw_entry, dict):
            raise DeploymentProxyPolicyError(f"{label}_invalid")
        entry = copy.deepcopy(raw_entry)
        params = entry.get("litellm_params")
        if not isinstance(params, dict):
            raise DeploymentProxyPolicyError(f"{label}_invalid")
        api_base = params.get("api_base")
        if not isinstance(api_base, str) or not api_base:
            raise DeploymentProxyPolicyError(f"{label}_invalid")
        try:
            observed_backends.append(canonical_backend_identifier(api_base))
        except ValueError as error:
            raise DeploymentProxyPolicyError(f"{label}_invalid") from error
        params["api_base"] = "<worker-route>"
        projected_entries.append(entry)
    if sorted(observed_backends) != sorted(expected_backends):
        raise DeploymentProxyPolicyError(f"{label}_route_mismatch")
    try:
        projected_entries.sort(
            key=lambda value: json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        projected = copy.deepcopy(document)
        projected["model_list"] = projected_entries
        return json.dumps(
            projected,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise DeploymentProxyPolicyError(f"{label}_invalid") from error


def validate_worker_rotation_proxy_configs(
    *,
    source_snapshot: Path,
    source_binding: Any,
    source_backends: list[str],
    target_snapshot: Path,
    target_binding: Any,
    target_backends: list[str],
) -> str:
    """Prove two generated configs differ only in worker backend URLs.

    Snapshot files contain proxy credentials and therefore must be private
    mode-0600 files. Only the resulting secret-free projection digest may be
    placed in a bridge artifact.
    """

    source_policy = validate_proxy_policy_binding(source_binding)
    target_policy = validate_proxy_policy_binding(
        target_binding,
        expected_request_timeout=source_policy["request_timeout"],
    )
    if (
        source_policy["schema_version"] != target_policy["schema_version"]
        or source_policy["num_retries"] != target_policy["num_retries"]
        or source_policy["proxy_litellm_config"]["path"] != target_policy["proxy_litellm_config"]["path"]
        or len(source_backends) != len(target_backends)
    ):
        raise DeploymentProxyPolicyError("worker_rotation_proxy_policy_mismatch")
    _, source_text = _private_snapshot(
        source_snapshot,
        expected_sha256=source_policy["proxy_litellm_config"]["sha256"],
        label="source_proxy_config_snapshot",
    )
    _, target_text = _private_snapshot(
        target_snapshot,
        expected_sha256=target_policy["proxy_litellm_config"]["sha256"],
        label="target_proxy_config_snapshot",
    )
    _validate_policy_text(
        source_text,
        generated=True,
        expected_request_timeout=source_policy["request_timeout"],
        label="source_proxy_config_snapshot",
    )
    _validate_policy_text(
        target_text,
        generated=True,
        expected_request_timeout=target_policy["request_timeout"],
        label="target_proxy_config_snapshot",
    )
    source_projection = _worker_route_projection(
        source_text,
        expected_backends=source_backends,
        label="source_proxy_config_snapshot",
    )
    target_projection = _worker_route_projection(
        target_text,
        expected_backends=target_backends,
        label="target_proxy_config_snapshot",
    )
    if source_projection != target_projection:
        raise DeploymentProxyPolicyError("worker_rotation_proxy_config_mismatch")
    return hashlib.sha256(source_projection).hexdigest()


def revalidate_deployment_proxy_policy(
    deployment_spec: Path,
    *,
    expected_spec_sha256: str,
    expected_binding: Any,
    expected_request_timeout: int | None = None,
) -> dict[str, Any]:
    expected = validate_proxy_policy_binding(
        expected_binding,
        expected_request_timeout=expected_request_timeout,
    )
    observed = load_deployment_proxy_policy(
        deployment_spec,
        expected_spec_sha256=expected_spec_sha256,
        expected_request_timeout=expected["request_timeout"],
    )
    if observed != expected:
        raise DeploymentProxyPolicyError("proxy_policy_changed")
    return observed


def validate_deployment_proxy_policy_snapshot(
    deployment_spec_snapshot: Path,
    proxy_policy_snapshot: Path,
    *,
    expected_spec_sha256: str,
    expected_binding: Any,
) -> dict[str, Any]:
    """Validate immutable historical policy bytes without requiring their old live paths."""

    expected = validate_proxy_policy_binding(expected_binding)
    _, spec_snapshot_text, _ = _read_stable_yaml(
        deployment_spec_snapshot,
        label="deployment_spec_snapshot",
    )
    if spec_snapshot_text.encode() != deployment_spec_policy_snapshot(
        expected_spec_sha256,
        expected,
    ):
        raise DeploymentProxyPolicyError("deployment_spec_snapshot_mismatch")
    _, snapshot_text, _ = _read_stable_yaml(
        proxy_policy_snapshot,
        label="proxy_policy_snapshot",
    )
    if snapshot_text.encode() != deployment_proxy_policy_snapshot(expected):
        raise DeploymentProxyPolicyError("proxy_policy_snapshot_mismatch")
    return expected


def deployment_proxy_policy_snapshot(binding: Any) -> bytes:
    """Return secret-free canonical historical policy evidence."""

    policy = validate_proxy_policy_binding(binding)
    value = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "request_timeout": policy["request_timeout"],
        "num_retries": REQUIRED_NUM_RETRIES,
        "source_sha256": policy["proxy_litellm_config"]["sha256"],
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def deployment_spec_policy_snapshot(
    source_sha256: str,
    binding: Any,
) -> bytes:
    """Return canonical allowlisted spec evidence without copying arbitrary siblings."""

    if not isinstance(source_sha256, str) or SHA256_RE.fullmatch(source_sha256) is None:
        raise DeploymentProxyPolicyError("deployment_spec_sha256_invalid")
    policy = validate_proxy_policy_binding(binding)
    value = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "request_timeout": policy["request_timeout"],
        "num_retries": policy["num_retries"],
        "source_sha256": source_sha256,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
