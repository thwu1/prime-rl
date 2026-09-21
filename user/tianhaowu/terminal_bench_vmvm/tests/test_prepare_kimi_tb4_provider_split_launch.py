import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path

import kimi_tb4_provider_split as split
import prepare_kimi_tb4_provider_split_launch as prepare
import pytest


def _task_toml(*, cpu: int, memory_mb: int, storage_mb: int, gpu: int, digest: str) -> bytes:
    return f"""
[verifier]
environment_mode = "separate"

[verifier.environment]
cpus = {cpu}
memory_mb = {memory_mb}
storage_mb = {storage_mb}
gpus = {gpu}
docker_image = "source.example/verifier@sha256:{digest}"

[environment]
cpus = {cpu}
memory_mb = {memory_mb}
storage_mb = {storage_mb}
gpus = {gpu}
docker_image = "source.example/agent@sha256:{digest}"
""".encode()


def _base_config(task_file_sha256: str, image_manifest_sha256: str) -> dict:
    return {
        "model": "Kimi-K3",
        "num_tasks": 66,
        "num_rollouts": 1,
        "max_concurrent": 24,
        "max_turns": 200,
        "max_input_tokens": 262144,
        "max_output_tokens": 262144,
        "max_total_tokens": 262144,
        "multiplex": 24,
        "rich": False,
        "retain_traces": False,
        "client": {
            "type": "eval",
            "capture_model_io": True,
            "outbound_body_denylist": ["logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"],
            "base_url": "http://127.0.0.1:8000/v1",
            "api_key_var": "OPENAI_API_KEY",
            "timeout": 43200,
            "connect_timeout": 120,
            "max_connections": 24,
            "max_keepalive_connections": 24,
        },
        "sampling": {
            "temperature": 1.0,
            "top_p": 1.0,
            "max_tokens": 32768,
            "reasoning_effort": "max",
            "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
        },
        "taskset": {
            "id": "terminal-bench-vmvm",
            "dataset_dir": "/dataset",
            "task_file": "/tasks",
            "task_file_sha256": task_file_sha256,
            "image_manifest": "/images",
            "image_manifest_sha256": image_manifest_sha256,
            "ignore_dockerfile": True,
            "use_declared_images": True,
            "enable_compose": True,
            "verifier_runtime_retries": 0,
            "timeout_multiplier": 2.0,
            "resource_multiplier": 2.0,
        },
        "harness": {
            "id": "terminal-bench-sandoq-host",
            "command_timeout_seconds": 240,
            "command_kill_grace_seconds": 10,
            "max_command_output_chars": 100000,
            "request_timeout_seconds": 15000,
            "runtime": {
                "type": "sandoq",
                "mode": "oci-runner",
                "session_timeout": 43200,
                "network_access": True,
                "host_tunnel": "none",
                "expected_environment": "oci-runner",
                "ecr_token_file": "/private/token",
            },
        },
        "timeout": {"setup": 3600, "rollout": 36000, "finalize": 3600, "scoring": 21600},
        "retries": {
            "rollout": {
                "max_retries": 0,
                "include": ["ProviderError", "SandboxError", "TunnelError", "InterceptionError"],
            }
        },
    }


def test_builds_exact_resource_partition_without_emitting_members(
    tmp_path: Path,
    monkeypatch,
) -> None:
    digest = "a" * 64
    identifiers = tuple(f"opaque-case-{index:02d}" for index in range(split.TOTAL_TASKS))
    task_payload = split._selector_payload(identifiers)
    task_file = tmp_path / "tasks.txt"
    task_file.write_bytes(task_payload)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    images = {}
    for index, task_id in enumerate(identifiers):
        if index < split.LEGACY_SANDOQ_TASKS + 4:
            resources = (2, 4096, 10240, 0)
        elif index < split.CPU_TASKS:
            resources = (16, 16384, 51200, 0)
        else:
            resources = (16, 32768, 1024000, 1)
        task_dir = dataset / task_id
        task_dir.mkdir()
        if split.LEGACY_SANDOQ_TASKS <= index < split.LEGACY_SANDOQ_TASKS + split.COMPOSE_CPU_TASKS:
            environment_dir = task_dir / "environment"
            environment_dir.mkdir()
            (environment_dir / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        resource_values = dict(zip(("cpu", "memory_mb", "storage_mb", "gpu"), resources))
        (task_dir / "task.toml").write_bytes(_task_toml(**resource_values, digest=digest))
        images[task_id] = {
            "agent": f"target.example/agent@sha256:{digest}",
            "verifier": f"target.example/verifier@sha256:{digest}",
        }
    image_value = {
        "images": images,
        "schema_version": 1,
        "source": "terminal-bench-prebuilt-v4.0.0-approved-66",
    }
    image_payload = split.canonical_json(image_value)
    image_manifest = tmp_path / "images.json"
    image_manifest.write_bytes(image_payload)
    archive = tmp_path / "dataset.tar.gz"
    archive.write_bytes(b"archive")
    content_sha256 = "b" * 64
    monkeypatch.setattr(split, "CANONICAL_TASK_FILE_SHA256", hashlib.sha256(task_payload).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_IMAGE_MANIFEST_SHA256", hashlib.sha256(image_payload).hexdigest())
    monkeypatch.setattr(split, "CANONICAL_DATASET_ARCHIVE_SHA256", hashlib.sha256(b"archive").hexdigest())
    monkeypatch.setattr(split, "CANONICAL_DATASET_CONTENT_SHA256", content_sha256)
    monkeypatch.setattr(prepare, "_tree_digest", lambda _path: content_sha256)
    monkeypatch.setattr(prepare, "_archive_tasks_tree_digest", lambda _path: content_sha256)

    payload, partition = prepare.build_resource_manifest(
        task_file=task_file,
        dataset_dir=dataset,
        dataset_archive=archive,
        image_manifest=image_manifest,
    )

    value = json.loads(payload)
    assert len(value["entries"]) == split.TOTAL_TASKS
    assert (
        len(partition.legacy_sandoq),
        len(partition.large_provider),
        len(partition.gpu_unsupported),
    ) == (
        split.LEGACY_SANDOQ_TASKS,
        split.LARGE_PROVIDER_TASKS,
        split.GPU_UNSUPPORTED_TASKS,
    )
    assert sum(entry["runtime_requirements"]["compose"] for entry in value["entries"]) == split.COMPOSE_CPU_TASKS
    assert set(partition.compose_required).isdisjoint(partition.legacy_sandoq)
    assert set(partition.compose_required).issubset(partition.large_provider)
    assert all(identifier.encode() in payload for identifier in identifiers)


def test_generated_lane_configs_are_merge_compatible_and_diagnostic_contract() -> None:
    base = _base_config(split.CANONICAL_TASK_FILE_SHA256, split.CANONICAL_IMAGE_MANIFEST_SHA256)
    legacy = prepare._lane_config(
        base,
        role="legacy_sandoq",
        selector=Path("/private/legacy.tasks.txt"),
        selector_sha256="a" * 64,
        image_manifest=Path("/private/images.json"),
        dataset_dir=Path("/dataset"),
        concurrency=24,
    )
    large = prepare._lane_config(
        base,
        role="large_provider",
        selector=Path("/private/large.tasks.txt"),
        selector_sha256="b" * 64,
        image_manifest=Path("/private/images.json"),
        dataset_dir=Path("/dataset"),
        concurrency=4,
    )

    assert legacy["num_tasks"] == split.LEGACY_SANDOQ_TASKS
    assert large["num_tasks"] == split.LARGE_PROVIDER_TASKS
    assert legacy["taskset"]["resource_multiplier"] == 1.0
    assert large["taskset"]["resource_multiplier"] == 2.0
    assert legacy["harness"]["runtime"]["type"] == "sandoq"
    assert large["harness"]["runtime"]["type"] == "vmvm"
    assert legacy["client"]["capture_model_io"] is True
    assert large["client"]["max_retries"] == 0
    assert large["retries"]["rollout"]["max_retries"] == 0
    assert split._provider_neutral_config(legacy) == split._provider_neutral_config(large)
    assert tomllib.loads(prepare._render_toml(legacy).decode()) == legacy
    assert tomllib.loads(prepare._render_toml(large).decode()) == large


def test_base_config_requires_compose_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _base_config(split.CANONICAL_TASK_FILE_SHA256, split.CANONICAL_IMAGE_MANIFEST_SHA256)
    value["taskset"]["enable_compose"] = False
    payload = prepare._render_toml(value)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(prepare, "APPROVED_BASE_CONFIG_SHA256", digest)

    with pytest.raises(prepare.PreparationError, match="^base_config_contract_mismatch$"):
        prepare._base_config(payload, digest)


def test_verify_tsv_returns_exact_lane_count_and_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result: dict[str, str | int] = {
        "role": "legacy_sandoq",
        "stage": "provider-split-legacy",
        "provider": "sandoq",
        "config": "/private/legacy.toml",
        "selector": "/private/legacy.tasks",
        "selector_sha256": "a" * 64,
        "count": split.LEGACY_SANDOQ_TASKS,
        "concurrency": prepare.DEFAULT_LEGACY_CONCURRENCY,
        "output_dir": "/private/output",
        "manifest": "/private/manifest.json",
        "manifest_sha256": "b" * 64,
        "partition_dir": "/private/partition",
        "base_config": "/private/base.toml",
    }
    monkeypatch.setattr(prepare, "verify_launch_plan", lambda *_args: result)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_kimi_tb4_provider_split_launch.py",
            "verify",
            "--launch-plan",
            str(tmp_path / "launch-plan.json"),
            "--launch-plan-sha256",
            "c" * 64,
            "--role",
            "legacy_sandoq",
            "--format",
            "tsv",
        ],
    )

    prepare.main()

    fields = capsys.readouterr().out.rstrip("\n").split("\t")
    assert fields[5:7] == [str(split.LEGACY_SANDOQ_TASKS), str(prepare.DEFAULT_LEGACY_CONCURRENCY)]


def test_compose_detection_rejects_nonregular_metadata(tmp_path: Path) -> None:
    task_dir = tmp_path / "opaque-case"
    environment_dir = task_dir / "environment"
    environment_dir.mkdir(parents=True)
    target = tmp_path / "compose-source.yaml"
    target.write_text("services: {}\n", encoding="utf-8")
    (environment_dir / "compose.yaml").symlink_to(target)

    with pytest.raises(prepare.PreparationError, match="^task_runtime_requirement_invalid$"):
        prepare._requires_compose(task_dir)


def test_committed_bundle_marker_is_required_and_exact(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    bundle = tmp_path / "bundle"
    files = {"one.json": b"{}\n", "two.toml": b"value = true\n"}
    split._publish_private_bundle(bundle, files)

    prepare._verify_committed_bundle(bundle, files, code="bundle_invalid")

    os.unlink(bundle / split.BUNDLE_COMMIT)
    with pytest.raises(prepare.PreparationError, match="bundle_invalid"):
        prepare._verify_committed_bundle(bundle, files, code="bundle_invalid")
