from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from deployment_proxy_policy import (
    DeploymentProxyPolicyError,
    load_deployment_proxy_policy,
    revalidate_deployment_proxy_policy,
    validate_proxy_policy_binding,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(tmp_path: Path) -> tuple[Path, Path]:
    spec = tmp_path / "spec.yaml"
    spec.write_text("spec:\n  proxy:\n    config:\n      request_timeout: 7200\n      num_retries: 0\n")
    generated = tmp_path / "proxy_litellm_config.yaml"
    generated.write_text(
        "model_list: []\n"
        "litellm_settings:\n"
        "  request_timeout: 7200\n"
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
        "request_timeout": 7200,
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

    assert binding["request_timeout"] == 7200
    assert binding["num_retries"] == 0


@pytest.mark.parametrize(
    "replacement",
    [
        "request_timeout: 600",
        'request_timeout: "7200"',
        "request_timeout: 07200",
        "num_retries: 2",
        "num_retries: false",
    ],
)
def test_spec_rejects_wrong_or_untyped_policy(tmp_path: Path, replacement: str) -> None:
    spec, _ = _files(tmp_path)
    key = "request_timeout: 7200" if replacement.startswith("request_timeout") else "num_retries: 0"
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


@pytest.mark.parametrize(
    "duplicate",
    [
        '      "request_timeout": 7200\n',
        "      !!str request_timeout: 7200\n",
        "      ? request_timeout\n      : 7200\n",
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
        '  "request_timeout": 7200\n',
        "  !!str request_timeout: 7200\n",
        "  ? request_timeout\n  : 7200\n",
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
                f"{indent}request_timeout: 7200\n",
                f"{indent}<<: {{unrelated: true}}\n{indent}request_timeout: 7200\n",
            )
        )
    else:
        target.write_text(
            target.read_text().replace(
                f"{indent}request_timeout: 7200\n",
                f"{indent}unrelated: &shared true\n{indent}another: *shared\n{indent}request_timeout: 7200\n",
            )
        )
    expected = "generated_proxy_policy_invalid" if generated else "deployment_proxy_policy_invalid"

    with pytest.raises(DeploymentProxyPolicyError, match=expected):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


@pytest.mark.parametrize(
    "replacement",
    [
        "request_timeout: 600",
        'request_timeout: "7200"',
        "request_timeout: false",
        "num_retries: 2",
        'num_retries: "0"',
        "num_retries: false",
    ],
)
def test_generated_rejects_wrong_or_untyped_policy(tmp_path: Path, replacement: str) -> None:
    spec, generated = _files(tmp_path)
    key = "request_timeout: 7200" if replacement.startswith("request_timeout") else "num_retries: 0"
    generated.write_text(generated.read_text().replace(key, replacement))

    with pytest.raises(DeploymentProxyPolicyError, match="generated_proxy_policy_invalid"):
        load_deployment_proxy_policy(spec, expected_spec_sha256=_sha256(spec))


@pytest.mark.parametrize(
    ("generated", "replacement"),
    [
        (False, "    config: []\n"),
        (False, "    config:\n      request_timeout: 7200\n"),
        (True, "litellm_settings: []\n"),
        (True, "litellm_settings:\n  request_timeout: 7200\n"),
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
        "litellm_settings:\n  request_timeout: 7200\n  num_retries: 0\n"
        if generated
        else "    config:\n      request_timeout: 7200\n      num_retries: 0\n"
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
