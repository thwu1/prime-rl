from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from deployment_proxy_policy import (
    KIMI_REQUEST_TIMEOUT,
    DeploymentProxyPolicyError,
    deployment_proxy_policy_snapshot,
    deployment_spec_policy_snapshot,
    revalidate_deployment_proxy_policy,
    validate_deployment_proxy_policy_snapshot,
    validate_proxy_policy_binding,
)
from deployment_proxy_policy import (
    load_deployment_proxy_policy as _load_deployment_proxy_policy,
)


def load_deployment_proxy_policy(spec: Path, *, expected_spec_sha256: str):
    return _load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=expected_spec_sha256,
        expected_request_timeout=KIMI_REQUEST_TIMEOUT,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(tmp_path: Path) -> tuple[Path, Path]:
    spec = tmp_path / "spec.yaml"
    spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 43200\n      num_retries: 0\n")
    generated = tmp_path / "proxy_litellm_config.yaml"
    generated.write_text(
        "model_list: []\n"
        "litellm_settings:\n"
        "  request_timeout: 43200\n"
        "  num_retries: 0\n"
        "general_settings:\n"
        "  master_key: secret-that-must-not-be-copied\n"
    )
    return spec, generated


def test_policy_binds_only_typed_values_and_generated_file_hash(tmp_path: Path) -> None:
    spec, generated = _files(tmp_path)

    binding = load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))

    assert binding == {
        "schema_version": 1,
        "request_timeout": 43200,
        "num_retries": 0,
        "proxy_litellm_config": {
            "path": str(generated.resolve()),
            "sha256": _sha256(generated),
        },
    }
    assert "secret-that-must-not-be-copied" not in repr(binding)
    assert (
        revalidate_deployment_proxy_policy(
            spec,
            expected_spec_sha256=_sha256(spec),
            expected_binding=binding,
        )
        == binding
    )


def test_policy_timeout_is_explicitly_model_scoped(tmp_path: Path) -> None:
    spec, generated = _files(tmp_path)
    spec.write_text(spec.read_text().replace("request_timeout: 43200", "request_timeout: 7200"))
    generated.write_text(generated.read_text().replace("request_timeout: 43200", "request_timeout: 7200"))

    qwen = _load_deployment_proxy_policy(
        spec,
        expected_spec_sha256=_sha256(spec),
        expected_request_timeout=7_200,
    )
    assert qwen["request_timeout"] == 7_200
    qwen_spec_snapshot = tmp_path / "qwen-spec-policy.json"
    qwen_proxy_snapshot = tmp_path / "qwen-proxy-policy.json"
    qwen_spec_snapshot.write_bytes(deployment_spec_policy_snapshot(_sha256(spec), qwen))
    qwen_proxy_snapshot.write_bytes(deployment_proxy_policy_snapshot(qwen))
    assert (
        validate_deployment_proxy_policy_snapshot(
            qwen_spec_snapshot,
            qwen_proxy_snapshot,
            expected_spec_sha256=_sha256(spec),
            expected_binding=qwen,
        )
        == qwen
    )
    with pytest.raises(DeploymentProxyPolicyError, match="deployment_proxy_policy_invalid"):
        _load_deployment_proxy_policy(
            spec,
            expected_spec_sha256=_sha256(spec),
            expected_request_timeout=KIMI_REQUEST_TIMEOUT,
        )
    with pytest.raises(DeploymentProxyPolicyError, match="expected_request_timeout_invalid"):
        _load_deployment_proxy_policy(
            spec,
            expected_spec_sha256=_sha256(spec),
            expected_request_timeout=36_000,
        )


def test_unrelated_policy_siblings_are_allowed(tmp_path: Path) -> None:
    spec, generated = _files(tmp_path)
    spec.write_text(
        spec.read_text().replace(
            "      num_retries: 0\n",
            "      num_retries: 0\n      unrelated_spec_setting: true\n",
        )
    )
    generated.write_text(
        generated.read_text().replace(
            "  num_retries: 0\n",
            "  num_retries: 0\n  unrelated_generated_setting: true\n",
        )
    )

    binding = load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))

    assert binding["request_timeout"] == 43200
    assert binding["num_retries"] == 0


@pytest.mark.parametrize(
    "replacement",
    [
        "request_timeout: 600",
        'request_timeout: "43200"',
        "request_timeout: 07200",
        "num_retries: 2",
        "num_retries: false",
    ],
)
def test_spec_rejects_wrong_or_untyped_policy(tmp_path: Path, replacement: str) -> None:
    spec, _ = _files(tmp_path)
    key = "request_timeout: 43200" if replacement.startswith("request_timeout") else "num_retries: 0"
    spec.write_text(spec.read_text().replace(key, replacement))

    with pytest.raises(DeploymentProxyPolicyError, match="deployment_proxy_policy_invalid"):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


def test_generated_policy_and_hash_are_revalidated(tmp_path: Path) -> None:
    spec, generated = _files(tmp_path)
    binding = load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))
    generated.write_text(generated.read_text().replace("num_retries: 0", "num_retries: 2"))

    with pytest.raises(DeploymentProxyPolicyError, match="generated_proxy_policy_invalid"):
        revalidate_deployment_proxy_policy(
            spec,
            expected_spec_sha256=_sha256(spec),
            expected_binding=binding,
        )


def test_historical_policy_snapshot_survives_live_file_replacement(tmp_path: Path) -> None:
    spec, generated = _files(tmp_path)
    spec.write_text(spec.read_text() + "credential_sibling: must-not-be-copied\n")
    source_spec_sha256 = _sha256(spec)
    binding = load_deployment_proxy_policy(spec, expected_spec_sha256=source_spec_sha256)
    snapshot_spec = tmp_path / "snapshot-spec.yaml"
    snapshot_generated = tmp_path / "snapshot-policy.json"
    snapshot_spec.write_bytes(deployment_spec_policy_snapshot(source_spec_sha256, binding))
    snapshot_generated.write_bytes(deployment_proxy_policy_snapshot(binding))
    assert b"secret-that-must-not-be-copied" not in snapshot_generated.read_bytes()
    assert b"must-not-be-copied" not in snapshot_spec.read_bytes()
    spec.write_text("spec:\n  num_endpoints: 24\n")
    generated.write_text("litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n  model_list: []\n")

    assert (
        validate_deployment_proxy_policy_snapshot(
            snapshot_spec,
            snapshot_generated,
            expected_spec_sha256=source_spec_sha256,
            expected_binding=binding,
        )
        == binding
    )
    snapshot_generated.write_bytes(snapshot_generated.read_bytes() + b"{}\n")
    with pytest.raises(
        DeploymentProxyPolicyError,
        match="proxy_policy_snapshot_mismatch",
    ):
        validate_deployment_proxy_policy_snapshot(
            snapshot_spec,
            snapshot_generated,
            expected_spec_sha256=source_spec_sha256,
            expected_binding=binding,
        )


@pytest.mark.parametrize(
    "duplicate",
    [
        '      "request_timeout": 43200\n',
        "      !!str request_timeout: 43200\n",
        "      ? request_timeout\n      : 43200\n",
    ],
)
def test_spec_rejects_semantic_duplicate_policy_keys(tmp_path: Path, duplicate: str) -> None:
    spec, _ = _files(tmp_path)
    spec.write_text(
        spec.read_text().replace(
            "      num_retries: 0\n",
            f"      num_retries: 0\n{duplicate}",
        )
    )

    with pytest.raises(DeploymentProxyPolicyError, match="deployment_proxy_policy_invalid"):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


@pytest.mark.parametrize(
    "duplicate",
    [
        '  "request_timeout": 43200\n',
        "  !!str request_timeout: 43200\n",
        "  ? request_timeout\n  : 43200\n",
    ],
)
def test_generated_rejects_semantic_duplicate_policy_keys(
    tmp_path: Path,
    duplicate: str,
) -> None:
    spec, generated = _files(tmp_path)
    generated.write_text(
        generated.read_text().replace(
            "  num_retries: 0\n",
            f"  num_retries: 0\n{duplicate}",
        )
    )

    with pytest.raises(DeploymentProxyPolicyError, match="generated_proxy_policy_invalid"):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


@pytest.mark.parametrize("generated", [False, True])
@pytest.mark.parametrize("ambiguous", ["merge", "alias"])
def test_policy_rejects_yaml_merge_and_alias_ambiguity(
    tmp_path: Path,
    generated: bool,
    ambiguous: str,
) -> None:
    spec, generated_path = _files(tmp_path)
    indent = "  " if generated else "      "
    target = generated_path if generated else spec
    if ambiguous == "merge":
        target.write_text(
            target.read_text().replace(
                f"{indent}request_timeout: 43200\n",
                f"{indent}<<: {{unrelated: true}}\n{indent}request_timeout: 43200\n",
            )
        )
    else:
        target.write_text(
            target.read_text().replace(
                f"{indent}request_timeout: 43200\n",
                f"{indent}unrelated: &shared true\n{indent}another: *shared\n{indent}request_timeout: 43200\n",
            )
        )
    expected = "generated_proxy_policy_invalid" if generated else "deployment_proxy_policy_invalid"

    with pytest.raises(DeploymentProxyPolicyError, match=expected):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


@pytest.mark.parametrize(
    "replacement",
    [
        "request_timeout: 600",
        'request_timeout: "43200"',
        "request_timeout: false",
        "num_retries: 2",
        'num_retries: "0"',
        "num_retries: false",
    ],
)
def test_generated_rejects_wrong_or_untyped_policy(tmp_path: Path, replacement: str) -> None:
    spec, generated = _files(tmp_path)
    key = "request_timeout: 43200" if replacement.startswith("request_timeout") else "num_retries: 0"
    generated.write_text(generated.read_text().replace(key, replacement))

    with pytest.raises(DeploymentProxyPolicyError, match="generated_proxy_policy_invalid"):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


@pytest.mark.parametrize(
    ("generated", "replacement"),
    [
        (False, "    config: []\n"),
        (False, "    config:\n      request_timeout: 43200\n"),
        (True, "litellm_settings: []\n"),
        (True, "litellm_settings:\n  request_timeout: 43200\n"),
    ],
)
def test_policy_requires_mapping_with_both_required_keys(
    tmp_path: Path,
    generated: bool,
    replacement: str,
) -> None:
    spec, generated_path = _files(tmp_path)
    target = generated_path if generated else spec
    original = (
        "litellm_settings:\n  request_timeout: 43200\n  num_retries: 0\n"
        if generated
        else "    config:\n      request_timeout: 43200\n      num_retries: 0\n"
    )
    target.write_text(target.read_text().replace(original, replacement))
    expected = "generated_proxy_policy_invalid" if generated else "deployment_proxy_policy_invalid"

    with pytest.raises(DeploymentProxyPolicyError, match=expected):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


def test_policy_binding_rejects_legacy_and_type_confusion(tmp_path: Path) -> None:
    spec, _ = _files(tmp_path)
    binding = load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))
    legacy = dict(binding)
    legacy.pop("proxy_litellm_config")
    with pytest.raises(DeploymentProxyPolicyError, match="proxy_policy_binding_invalid"):
        validate_proxy_policy_binding(legacy)
    confused = dict(binding)
    confused["schema_version"] = True
    with pytest.raises(DeploymentProxyPolicyError, match="proxy_policy_binding_invalid"):
        validate_proxy_policy_binding(confused)
