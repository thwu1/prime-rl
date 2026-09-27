from __future__ import annotations

import argparse
import hashlib
import json
import os
import tomllib
from pathlib import Path

import eval_run_identity
import finalize_kimi_tb4_sandoq_small_full as finalize
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_sandoq_small_full as small
import pytest


def _resource(*, gpu: int = 0) -> dict[str, int]:
    return {
        "cpu_count": 4,
        "memory_bytes": 8 * split.GIB,
        "disk_bytes": 20 * split.GIB,
        "gpu_count": gpu,
    }


def _manifest(monkeypatch: pytest.MonkeyPatch) -> tuple[bytes, bytes]:
    digest = "a" * 64
    entries = []
    for index in range(split.TOTAL_TASKS):
        gpu = index >= 63
        compose = 52 <= index < 63
        resources = _resource(gpu=int(gpu))
        entries.append(
            {
                "task_id": f"opaque-case-{index:02d}",
                "images": {
                    "agent": f"registry.example/agent@sha256:{digest}",
                    "verifier": f"registry.example/verifier@sha256:{digest}",
                },
                "agent_resources": resources,
                "verifier_resources": dict(resources),
                "verifier_mode": "shared",
                "runtime_requirements": {"compose": compose},
            }
        )
    selector_body = ("\n".join(entry["task_id"] for entry in entries) + "\n").encode()
    image_body = split.canonical_json(
        {
            "images": {entry["task_id"]: entry["images"] for entry in entries},
            "schema_version": 1,
            "source": "terminal-bench-prebuilt-v4.0.0-approved-66",
        }
    )
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", hashlib.sha256(selector_body).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", hashlib.sha256(image_body).hexdigest())
    value = {
        "schema_version": split.MANIFEST_SCHEMA_VERSION,
        "kind": split.MANIFEST_KIND,
        "source": {
            "dataset_archive_sha256": split.CANONICAL_DATASET_ARCHIVE_SHA256,
            "dataset_content_sha256": split.CANONICAL_DATASET_CONTENT_SHA256,
            "image_manifest_sha256": hashlib.sha256(image_body).hexdigest(),
            "task_file_sha256": hashlib.sha256(selector_body).hexdigest(),
        },
        "entries": entries,
    }
    return split.canonical_json(value), image_body


def test_materialized_small_plan_preserves_full_generation_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    # Validate and retain the sealed base before this synthetic manifest replaces
    # the repository image-manifest digest for the rest of the test.
    sealed_base = small._load_base()
    manifest_body, image_body = _manifest(monkeypatch)
    monkeypatch.setattr(small, "_load_base", lambda: sealed_base)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(manifest_body)
    manifest.chmod(0o600)
    image_manifest = tmp_path / "images.json"
    image_manifest.write_bytes(image_body)
    dataset = tmp_path / "dataset"
    dataset.mkdir(mode=0o700)
    eval_root = tmp_path / "evals"
    eval_root.mkdir(mode=0o700)
    smoke = tmp_path / "smoke.json"
    smoke.write_bytes(
        split.canonical_json(
            {
                "cleanup": True,
                "harness_version": "2.4.6",
                "kind": "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic",
                "model_calls": 3,
                "reasoning_content_retained": True,
                "router_healthy": True,
                "sandbox_environment": "oci-runner-firecracker-small",
                "sandbox_lifecycle": True,
                "shell_execution": True,
                "status": "diagnostic_passed",
                "sticky_routing": True,
                "task_count": 1,
            }
        )
    )
    smoke.chmod(0o600)
    smoke_sha256 = hashlib.sha256(smoke.read_bytes()).hexdigest()
    monkeypatch.setattr(small, "SMOKE_RECEIPT_SHA256", smoke_sha256)
    output = tmp_path / "plan"
    args = argparse.Namespace(
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_body).hexdigest(),
        image_manifest=image_manifest,
        dataset_dir=dataset,
        output=output,
        eval_root=eval_root,
        run_label="test",
        smoke_receipt=smoke,
        smoke_receipt_sha256=smoke_sha256,
    )

    result = small.materialize(args)
    verified = small.verify(output / small.PLAN, result["plan_sha256"])
    config = tomllib.loads((output / small.CONFIG).read_text())

    assert result == {
        "state": "materialized",
        "executed_tasks": 52,
        "unsupported_tasks": 14,
        "denominator": 66,
        "concurrency": 24,
        "certification_eligible": False,
        "plan_sha256": result["plan_sha256"],
    }
    assert verified["count"] == 52
    assert verified["concurrency"] == 24
    assert Path(verified["full_output_dir"]).parent == Path(verified["output_dir"])
    assert config["max_turns"] == 200
    assert config["sampling"]["max_tokens"] == 32_768
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["max_total_tokens"] == 262_144
    assert config["client"]["max_retries"] == 0
    assert config["harness"]["env"]["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] == "1"
    assert config["harness"]["runtime"]["expected_environment"] == "oci-runner-firecracker-small"
    assert config["taskset"]["resource_cpu_cap"] == 1
    assert config["taskset"]["resource_memory_mb_cap"] == 2_048
    assert b"opaque-case" not in json.dumps(result, sort_keys=True).encode()
    plan = json.loads((output / small.PLAN).read_bytes())
    assert plan["contracts"]["model_io_response_kind"] == "normalized_stream_response"
    assert plan["contracts"]["reasoning_message_parity_required"] is True
    assert "exact_provider_json_required" not in plan["contracts"]

    original_verify = small.verify
    replacement = tmp_path / "replacement-plan.json"
    replacement.write_bytes(b"{}\n")
    replacement.chmod(0o600)

    def verify_then_swap(path: Path, expected_sha256: str) -> dict[str, object]:
        value = original_verify(path, expected_sha256)
        os.replace(replacement, path)
        return value

    monkeypatch.setattr(finalize.plan_module, "verify", verify_then_swap)
    loaded, reverified = finalize._verified_plan(output / small.PLAN, result["plan_sha256"])
    assert loaded == plan
    assert reverified == verified


def test_unsupported_rows_are_deterministic_explicit_zeroes() -> None:
    first = finalize._unsupported_row("opaque-case", "a" * 64, "compose")
    second = finalize._unsupported_row("opaque-case", "a" * 64, "compose")

    assert first == second
    assert first["rewards"] == {"solved": 0}
    assert first["stop_condition"] == "unsupported"
    assert first["nodes"] == []


def test_identity_validator_seals_small_full_contract() -> None:
    config, _body, _path = small._load_base()

    assert eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE != "kimi-direct-tb4-diagnostic"

    assert (
        eval_run_identity._direct_kimi_expected_concurrency(
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
            "sandoq",
            52,
            24,
        )
        == 24
    )
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_scope_invalid"):
        eval_run_identity._direct_kimi_expected_concurrency(
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
            "sandoq",
            51,
            24,
        )

    eval_run_identity._validate_direct_kimi_tb4_small_config(
        config,
        eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
    )
    config["sampling"]["max_tokens"] = 512
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_config_invalid"):
        eval_run_identity._validate_direct_kimi_tb4_small_config(
            config,
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
        )
    config, _body, _path = small._load_base()
    config["harness"]["runtime"]["expected_environment"] = "oci-runner"
    with pytest.raises(eval_run_identity.EvalIdentityError, match="direct_kimi_tb4_small_config_invalid"):
        eval_run_identity._validate_direct_kimi_tb4_small_config(
            config,
            eval_run_identity.KIMI_SMALL_TB4_DIAGNOSTIC_ROLE,
        )


def test_launchers_bind_small_diagnostic_and_zero_model_only_resume() -> None:
    workflow = Path(small.__file__).resolve().parent
    wrapper = (workflow / "run_kimi_tb4_miniswe246_sandoq_small_full.sbatch").read_text()
    launcher = (
        workflow
        / "configs/eval/servers/cpu-132-021_8103/"
        "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    ).read_text()
    stage = (workflow / "run_direct_kimi_sandoq_stage.sh").read_text()

    assert "tb4-miniswe246-sandoq-small-full" in wrapper
    assert "small-firecracker-diagnostic" in wrapper
    assert "DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS=1" in launcher
    assert "prepare_kimi_tb4_sandoq_small_full.py" in launcher
    assert "finalize_kimi_tb4_sandoq_small_full.py" in launcher
    assert launcher.index("setsid \"$x86_uv\"") < launcher.index("finalize_kimi_tb4_sandoq_small_full.py")
    assert launcher.index("direct_kimi_router_final.json") < launcher.rindex(
        "finalize_kimi_tb4_sandoq_small_full.py"
    )
    assert "prepare_kimi_tb4_sandoq_small_full.py" in stage
