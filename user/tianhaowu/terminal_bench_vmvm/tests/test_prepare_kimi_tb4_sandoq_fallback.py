from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_provider_split_launch as common
import prepare_kimi_tb4_sandoq_fallback as fallback
import pytest


def _request(*, memory_gib: int, gpu: int = 0) -> split.ResourceRequest:
    return split.ResourceRequest(
        cpu_count=2,
        memory_bytes=memory_gib * split.GIB,
        disk_bytes=10 * split.GIB,
        gpu_count=gpu,
    )


def _fixture_partition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    entries = []
    groups: dict[str, list[str]] = {
        "low": [],
        "memory_8g": [],
        "memory_16g": [],
        "compose": [],
        "gpu": [],
    }
    specifications = (
        ("low", 31, 4, False, 0),
        ("memory_8g", 17, 8, False, 0),
        ("memory_16g", 4, 16, False, 0),
        ("compose", 11, 4, True, 0),
        ("gpu", 3, 16, False, 1),
    )
    index = 0
    for group, count, memory_gib, requires_compose, gpu in specifications:
        for _ in range(count):
            task_id = f"synthetic-case-{index:02d}"
            index += 1
            environment = tmp_path / task_id / "environment"
            environment.mkdir(parents=True)
            if requires_compose:
                (environment / "compose.yaml").write_text("services: {}\n")
            request = _request(memory_gib=memory_gib, gpu=gpu)
            entries.append(
                SimpleNamespace(
                    task_id=task_id,
                    agent_resources=request,
                    verifier_resources=request,
                    verifier_mode="separate",
                    requires_compose=requires_compose,
                )
            )
            groups[group].append(task_id)
    provider_partition = SimpleNamespace(
        legacy_sandoq=tuple(groups["low"]),
        large_provider=tuple(groups["memory_8g"] + groups["memory_16g"] + groups["compose"]),
        gpu_unsupported=tuple(groups["gpu"]),
    )
    monkeypatch.setattr(split, "derive_partition", lambda _entries: provider_partition)
    return tuple(entries), groups


def test_fallback_partition_is_exact_and_compose_is_independently_checked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries, groups = _fixture_partition(tmp_path, monkeypatch)

    observed = fallback.derive_fallback_partition(entries, tmp_path)

    assert observed.low_resource == tuple(groups["low"])
    assert observed.memory_8g == tuple(groups["memory_8g"])
    assert observed.memory_16g == tuple(groups["memory_16g"])
    assert observed.compose_excluded == tuple(groups["compose"])
    assert observed.gpu_unsupported == tuple(groups["gpu"])
    assert fallback.TOTAL_CONCURRENCY == 8
    assert fallback._admissible_with_memory_multiplier(entries[31], 0.75)
    assert fallback._admissible_with_memory_multiplier(entries[48], 0.375)

    mismatched = list(entries)
    mismatched[0] = SimpleNamespace(**{**vars(mismatched[0]), "requires_compose": True})
    with pytest.raises(fallback.FallbackPreparationError, match="compose_declaration_mismatch"):
        fallback.derive_fallback_partition(tuple(mismatched), tmp_path)


@pytest.mark.parametrize(
    ("count", "concurrency", "multiplier"),
    ((17, 6, 0.75), (4, 2, 0.375)),
)
def test_fallback_configs_preserve_capture_and_reasoning_contract(
    count: int,
    concurrency: int,
    multiplier: float,
) -> None:
    base_path = Path(__file__).parents[1] / "configs/eval/servers/cpu-132-021_8103/tb4_kimi_k3_sandoq_pass1.toml"
    base = common._base_config(base_path.read_bytes(), common.APPROVED_BASE_CONFIG_SHA256)

    config = fallback._fallback_config(
        base,
        count=count,
        concurrency=concurrency,
        memory_multiplier=multiplier,
        selector=Path("/private/fallback.tasks.txt"),
        selector_sha256="a" * 64,
        image_manifest=Path("/private/images.json"),
        dataset_dir=Path("/dataset"),
    )

    assert config["num_tasks"] == count
    assert config["max_concurrent"] == concurrency
    assert config["multiplex"] == concurrency
    assert config["client"]["max_connections"] == concurrency
    assert config["client"]["max_keepalive_connections"] == concurrency
    assert config["client"]["capture_model_io"] is True
    assert config["client"]["max_retries"] == 0
    assert config["retries"]["rollout"]["max_retries"] == 0
    assert config["taskset"]["resource_multiplier"] == 1.0
    assert config["taskset"]["memory_resource_multiplier"] == multiplier
    assert config["taskset"]["enable_compose"] is False
    assert config["harness"]["runtime"]["type"] == "sandoq"
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["sampling"]["chat_template_kwargs"]["preserve_thinking"] is True
    assert (config["max_input_tokens"], config["max_output_tokens"], config["max_total_tokens"]) == (
        262_144,
        262_144,
        262_144,
    )


def test_private_plan_binds_both_lanes_and_requires_commit_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    entries, groups = _fixture_partition(dataset, monkeypatch)
    manifest_payload = split.canonical_json({"schema_version": 2, "kind": "synthetic"})
    manifest_value = {"schema_version": 2}
    monkeypatch.setattr(
        common,
        "build_resource_manifest",
        lambda **_kwargs: (manifest_payload, SimpleNamespace()),
    )
    monkeypatch.setattr(split, "parse_manifest", lambda _payload, _digest: (manifest_value, entries))
    monkeypatch.setattr(common, "_tree_digest", lambda _path: split.CANONICAL_DATASET_CONTENT_SHA256)

    private_parent = tmp_path / "private"
    private_parent.mkdir(mode=0o700)
    eval_root = tmp_path / "evals"
    eval_root.mkdir()
    source_root = Path(__file__).parents[1]
    server_root = source_root / "configs/eval/servers/cpu-132-021_8103"
    image_manifest = server_root / "tb4_images.sandoq.json"
    base_config = server_root / "tb4_kimi_k3_sandoq_pass1.toml"
    args = argparse.Namespace(
        task_file=tmp_path / "unused.tasks.txt",
        dataset_dir=dataset,
        dataset_archive=tmp_path / "unused.tar.gz",
        image_manifest=image_manifest,
        base_config=base_config,
        base_config_sha256=common.APPROVED_BASE_CONFIG_SHA256,
        private_parent=private_parent,
        eval_root=eval_root,
        run_label="cpu132021-8103-test-v1",
    )

    result = fallback.prepare(args)
    launch_dir = private_parent / "cpu132021-8103-test-v1-launch"
    plan_path = launch_dir / fallback.PLAN
    plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    plan = json.loads(plan_path.read_bytes())

    assert result["fallback_memory_8g"] == 17
    assert result["fallback_memory_16g"] == 4
    assert result["resource_fidelity"] is False
    assert "manifest_sha256" not in result
    assert plan["schema_version"] == fallback.PLAN_SCHEMA_VERSION == 2
    aggregate_output = json.dumps(result, sort_keys=True)
    assert all(member not in aggregate_output for members in groups.values() for member in members)
    assert set(plan["lanes"]) == {"memory_8g", "memory_16g"}
    for lane_name, expected_members in (
        ("memory_8g", groups["memory_8g"]),
        ("memory_16g", groups["memory_16g"]),
    ):
        verified = fallback.verify(plan_path, plan_sha256, lane_name)
        assert verified["provider"] == "sandoq"
        config = tomllib.loads(Path(verified["config"]).read_text())
        assert config["num_tasks"] == len(expected_members)
        assert config["taskset"]["resource_multiplier"] == 1.0
        assert config["taskset"]["memory_resource_multiplier"] == plan["lanes"][lane_name]["memory_resource_multiplier"]

    cli_label = "cpu132021-8103-test-v2"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_kimi_tb4_sandoq_fallback.py",
            "--task-file",
            str(args.task_file),
            "--dataset-dir",
            str(dataset),
            "--dataset-archive",
            str(args.dataset_archive),
            "--image-manifest",
            str(image_manifest),
            "--base-config",
            str(base_config),
            "--base-config-sha256",
            common.APPROVED_BASE_CONFIG_SHA256,
            "--private-parent",
            str(private_parent),
            "--eval-root",
            str(eval_root),
            "--run-label",
            cli_label,
        ],
    )
    fallback.main()
    cli_output = capsys.readouterr().out
    cli_value = json.loads(cli_output)
    assert "manifest_sha256" not in cli_value
    assert all(member not in cli_output for members in groups.values() for member in members)

    first_output = Path(plan["lanes"]["memory_8g"]["output_dir"])
    first_output.mkdir()
    assert fallback.verify(plan_path, plan_sha256, "memory_16g")["provider"] == "sandoq"
    assert fallback.verify_completed(plan_path, plan_sha256, "memory_8g")["provider"] == "sandoq"
    with pytest.raises(fallback.FallbackPreparationError, match="fallback_lane_invalid"):
        fallback.verify(plan_path, plan_sha256, "memory_8g")

    os.unlink(launch_dir / split.BUNDLE_COMMIT)
    with pytest.raises(fallback.FallbackPreparationError, match="fallback_bundle_invalid"):
        fallback.verify(plan_path, plan_sha256, "memory_8g")


def test_fallback_launcher_is_syntax_valid_and_noncertifying() -> None:
    workflow = Path(__file__).parents[1]
    wrapper = workflow / (
        "configs/eval/servers/cpu-132-021_8103/run_tb4_kimi_k3_sandoq_fallback_cpu-132-021_8103.sbatch"
    )
    stage = workflow / "run_direct_kimi_sandoq_stage.sh"
    main = workflow / ("configs/eval/servers/cpu-132-021_8103/run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch")

    subprocess.run(["bash", "-n", wrapper, stage, main], check=True)
    wrapper_body = wrapper.read_text()
    assert "KIMI_EXECUTION_MODE=sandoq-fallback-diagnostic" in wrapper_body
    assert "KIMI_SANDBOX_PROVIDER=sandoq" in wrapper_body
    assert "KIMI_SANDOQ_PREFLIGHT_ONLY=0" in wrapper_body
    assert "certification_eligible" in main.read_text()
    assert "sandoq_lease_profile=kimi-tb4-long" in main.read_text()
    assert '--lease-profile "$sandoq_lease_profile"' in main.read_text()
    assert '"$OCI_RUNNER_POOL_RENEW_INTERVAL" != 5m' in stage.read_text()


def test_prepare_cli_redacts_unexpected_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive = "synthetic-private-member:/private/dataset/member"
    monkeypatch.setattr(fallback, "prepare", lambda _args: (_ for _ in ()).throw(RuntimeError(sensitive)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_kimi_tb4_sandoq_fallback.py",
            "--task-file",
            "/private/tasks",
            "--dataset-dir",
            "/private/dataset",
            "--dataset-archive",
            "/private/archive",
            "--image-manifest",
            "/private/images",
            "--base-config",
            "/private/base",
            "--base-config-sha256",
            "a" * 64,
            "--private-parent",
            "/private/output",
            "--eval-root",
            "/private/evals",
            "--run-label",
            "test",
        ],
    )

    with pytest.raises(SystemExit):
        fallback.main()

    stderr = capsys.readouterr().err
    assert "fallback_preparation_failed" in stderr
    assert sensitive not in stderr
    assert "Traceback" not in stderr


@pytest.mark.parametrize(
    ("lane", "stage_name"),
    (("memory_8g", "sandoq-fallback-memory-8g"), ("memory_16g", "sandoq-fallback-memory-16g")),
)
def test_fallback_wrapper_executes_only_the_exact_diagnostic_pairing(
    tmp_path: Path,
    lane: str,
    stage_name: str,
) -> None:
    workflow = Path(__file__).parents[1]
    wrapper = workflow / (
        "configs/eval/servers/cpu-132-021_8103/run_tb4_kimi_k3_sandoq_fallback_cpu-132-021_8103.sbatch"
    )
    project = tmp_path / "project"
    target = project / (
        "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/"
        "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    )
    target.parent.mkdir(parents=True)
    evidence = tmp_path / "environment.txt"
    target.write_text(
        "printf '%s\\n' \"$KIMI_SANDOQ_STAGE|$KIMI_SANDBOX_PROVIDER|"
        '$KIMI_EXECUTION_MODE|$KIMI_SANDOQ_PREFLIGHT_ONLY" > "$FALLBACK_TEST_EVIDENCE"\n'
    )
    environment = {
        **os.environ,
        "PROJECT_DIR": str(project),
        "KIMI_SANDOQ_FALLBACK_LANE": lane,
        "KIMI_SANDOQ_FALLBACK_PLAN": "/private/plan.json",
        "KIMI_SANDOQ_FALLBACK_PLAN_SHA256": "a" * 64,
        "KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION": "b" * 40,
        "FALLBACK_TEST_EVIDENCE": str(evidence),
    }

    subprocess.run(["bash", wrapper], check=True, env=environment)

    assert evidence.read_text().strip() == f"{stage_name}|sandoq|sandoq-fallback-diagnostic|0"


def test_launch_consumers_bind_verified_count_and_concurrency() -> None:
    workflow = Path(__file__).parents[1]
    main = (
        workflow / "configs/eval/servers/cpu-132-021_8103/run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    ).read_text()
    stage = (workflow / "run_direct_kimi_sandoq_stage.sh").read_text()
    compact_main = " ".join(main.replace("\\\n", " ").split())
    compact_stage = " ".join(stage.replace("\\\n", " ").split())

    assert compact_main.count("eval_config_sha256 task_file task_sha256 verified_count verified_concurrency") == 2
    assert (
        compact_stage.count(
            "verified_config_sha256 verified_selector verified_selector_sha256 verified_count verified_concurrency"
        )
        == 2
    )
    assert main.count("task_count=$verified_count") == 2
    assert main.count("stage_capacity=$verified_concurrency") == 2
    assert 'DIRECT_KIMI_APPROVED_TASK_COUNT="$task_count"' in main
    assert 'DIRECT_KIMI_ROLLOUT_CONCURRENCY="$stage_capacity"' in main
    assert '"$approved_task_count" != "$verified_count"' in stage
    assert '"$rollout_concurrency" != "$verified_concurrency"' in stage
    assert "task_count=35" not in main
    assert "task_count=28" not in main


def _fake_verifier(tmp_path: Path) -> Path:
    fake_uv = tmp_path / "fake-uv"
    fake_uv.write_text("#!/bin/bash\nprintf '%s\\n' \"$FAKE_VERIFY_TSV\"\n")
    fake_uv.chmod(0o755)
    return fake_uv


def _fallback_tsv(tmp_path: Path, *, count: int, concurrency: int) -> str:
    fields = (
        "sandoq-fallback-memory-8g",
        "sandoq",
        str(tmp_path / "config.toml"),
        "c" * 64,
        str(tmp_path / "tasks.txt"),
        "a" * 64,
        str(count),
        str(concurrency),
        str(tmp_path / "existing-output"),
        str(tmp_path / "manifest.json"),
        "b" * 64,
        str(tmp_path / "partition"),
    )
    return "\t".join(fields)


@pytest.mark.parametrize(
    ("count", "concurrency", "approved_config_sha256", "expected_error"),
    (
        (18, 6, "c" * 64, "Fallback diagnostic launch plan binding failed"),
        (17, 7, "c" * 64, "Fallback diagnostic launch plan binding failed"),
        (17, 6, "d" * 64, "Fallback diagnostic launch plan binding failed"),
        (17, 6, "c" * 64, "Direct Kimi stage requires its exact sealed Sandoq context"),
    ),
)
def test_direct_stage_parses_exact_fallback_contract_and_rejects_mismatch(
    tmp_path: Path,
    count: int,
    concurrency: int,
    approved_config_sha256: str,
    expected_error: str,
) -> None:
    workflow = Path(__file__).parents[1]
    stage = workflow / "run_direct_kimi_sandoq_stage.sh"
    fake_uv = _fake_verifier(tmp_path)
    fields = _fallback_tsv(tmp_path, count=count, concurrency=concurrency).split("\t")
    environment = {
        **os.environ,
        "PROJECT_DIR": str(tmp_path / "project"),
        "PYTHON_SITE_X86_64": str(tmp_path / "python-site"),
        "SANDOQ_PYTHON_SITE_X86_64": str(tmp_path / "sandoq-site"),
        "UV_BIN_X86_64": str(fake_uv),
        "PYTHON_BIN_X86_64": "python3",
        "EVAL_CONFIG": fields[2],
        "OUTPUT_DIR": fields[8],
        "DIRECT_KIMI_ROLE": "kimi-direct-tb4-sandoq-fallback-diagnostic",
        "DIRECT_KIMI_EVAL_CONFIG_SHA256": approved_config_sha256,
        "DIRECT_KIMI_APPROVED_TASK_FILE": fields[4],
        "DIRECT_KIMI_APPROVED_TASK_FILE_SHA256": fields[5],
        "DIRECT_KIMI_APPROVED_TASK_COUNT": "17",
        "DIRECT_KIMI_ROLLOUT_CONCURRENCY": "6",
        "DIRECT_KIMI_WORKER_MANIFEST": str(tmp_path / "workers.json"),
        "DIRECT_KIMI_WORKER_MANIFEST_SHA256": "c" * 64,
        "DIRECT_KIMI_BASE_URL": "http://127.0.0.1:12345/v1",
        "DIRECT_KIMI_EXPECTED_PRIME_RL_REVISION": "d" * 40,
        "DIRECT_KIMI_PREFLIGHT_ONLY": "0",
        "DIRECT_KIMI_SANDBOX_PROVIDER": "sandoq",
        "DIRECT_KIMI_EXECUTION_MODE": "sandoq-fallback-diagnostic",
        "DIRECT_KIMI_FALLBACK_PLAN": str(tmp_path / "plan.json"),
        "DIRECT_KIMI_FALLBACK_PLAN_SHA256": "e" * 64,
        "DIRECT_KIMI_FALLBACK_LANE": "memory_8g",
        "DIRECT_KIMI_RESOURCE_MANIFEST": fields[9],
        "DIRECT_KIMI_RESOURCE_MANIFEST_SHA256": fields[10],
        "DIRECT_KIMI_PROVIDER_PARTITION_DIR": fields[11],
        "FAKE_VERIFY_TSV": "\t".join(fields),
        "SANDOQ_PROVIDER_CONTEXT_ACTIVE": "0",
        "SANDOQ_PROVIDER_CONTEXT_RECEIPT": str(tmp_path / "context.json"),
        "OCI_RUNNER_ENVIRONMENT": "oci-runner",
        "SANDOQ_EFFECTIVE_TASK_NETWORK": "public",
        "SANDOQ_LEASE_PROFILE": "kimi-tb4-long",
        "OCI_RUNNER_LEASE_DURATION": "12h",
        "OCI_RUNNER_POOL_RENEW_INTERVAL": "5m",
        "OCI_RUNNER_TASK_NETWORK": "",
        "SLURM_JOB_ID": "123",
    }

    result = subprocess.run(["bash", stage], env=environment, text=True, capture_output=True)

    assert result.returncode == 2
    assert expected_error in result.stderr


@pytest.mark.parametrize(
    ("count", "concurrency", "expected_error"),
    (
        (18, 6, "Fallback diagnostic launch plan binding failed"),
        (17, 7, "Fallback diagnostic launch plan binding failed"),
        (17, 6, "Direct Kimi output namespace is not fresh"),
    ),
)
def test_server_launcher_parses_exact_fallback_contract_and_rejects_mismatch(
    tmp_path: Path,
    count: int,
    concurrency: int,
    expected_error: str,
) -> None:
    workflow = Path(__file__).parents[1]
    launcher = workflow / (
        "configs/eval/servers/cpu-132-021_8103/run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
    )
    project = tmp_path / "project"
    server_dir = project / ("user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103")
    server_dir.mkdir(parents=True)
    profile = workflow / "configs/eval/servers/cpu-132-021_8103/sandoq_use2.json"
    (server_dir / "sandoq_use2.json").write_bytes(profile.read_bytes())
    subprocess.run(["git", "init", "-q", project], check=True)
    subprocess.run(["git", "-C", project, "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            project,
            "-c",
            "user.name=Fallback Test",
            "-c",
            "user.email=fallback@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", project, "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    fake_uv = _fake_verifier(tmp_path)
    python_site = tmp_path / "python-site" / "pydantic"
    sandoq_site = tmp_path / "sandoq-site" / "sandoq_client"
    python_site.mkdir(parents=True)
    sandoq_site.mkdir(parents=True)
    fields = _fallback_tsv(tmp_path, count=count, concurrency=concurrency).split("\t")
    Path(fields[8]).mkdir()
    environment = {
        **os.environ,
        "PROJECT_DIR": str(project),
        "KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION": revision,
        "KIMI_SANDOQ_STAGE": "sandoq-fallback-memory-8g",
        "KIMI_SANDBOX_PROVIDER": "sandoq",
        "KIMI_EXECUTION_MODE": "sandoq-fallback-diagnostic",
        "KIMI_SANDOQ_PREFLIGHT_ONLY": "0",
        "KIMI_SANDOQ_FALLBACK_PLAN": str(tmp_path / "plan.json"),
        "KIMI_SANDOQ_FALLBACK_PLAN_SHA256": "e" * 64,
        "PYTHON_SITE_X86_64": str(python_site.parent),
        "SANDOQ_PYTHON_SITE_X86_64": str(sandoq_site.parent),
        "UV_BIN_X86_64": str(fake_uv),
        "PYTHON_BIN_X86_64": "python3",
        "FAKE_VERIFY_TSV": "\t".join(fields),
        "SLURM_JOB_ID": "987654321",
    }

    result = subprocess.run(["bash", launcher], env=environment, text=True, capture_output=True)

    assert result.returncode == 2
    assert expected_error in result.stderr
