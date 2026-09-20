from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import migrate_qwen_serving_generation as generation
import prepare_qwen_sandoq_catalog_plan as prepare
import pytest
import terminal_bench_vmvm.offline_verifier_catalog_materializer as materializer
from materialize_qwen_provider_union import DEPLOYMENT_NAMESPACE, _canonical_json
from terminal_bench_vmvm.source_wheels import canonical_json
from terminal_bench_vmvm.taskset import TerminalBenchVMVMTaskset


def _sha(payload: bytes | str) -> str:
    if isinstance(payload, str):
        payload = payload.encode()
    return hashlib.sha256(payload).hexdigest()


def _private_file(path: Path, payload: bytes, mode: int = 0o600) -> Path:
    path.write_bytes(payload)
    path.chmod(mode)
    return path


def _task(
    dataset: Path,
    name: str,
    image_digest: str,
    *,
    public: bool = False,
    declared_image: str | None = None,
) -> None:
    task = dataset / name
    (task / "environment").mkdir(parents=True)
    (task / "tests").mkdir()
    network = "public" if public else "no-network"
    declared = f'docker_image = "{declared_image}"\n' if declared_image is not None else ""
    (task / "task.toml").write_text(
        "[environment]\n"
        f"{declared}"
        f'network_mode = "{network}"\n'
        "[verifier]\n"
        'environment_mode = "shared"\n'
        f'network_mode = "{network}"\n'
    )
    # The plan extractor intentionally never opens the task instruction.
    instruction = task / "instruction.md"
    instruction.write_text("private instruction must remain unopened\n")
    instruction.chmod(0)
    (task / "tests" / "test.sh").write_text("python3 -m pip install pytest==8.3.4\n")
    assert len(image_digest) == 64


def _config(
    dataset: Path,
    tasks: Path,
    task_sha256: str,
    image_manifest: Path,
    image_manifest_sha256: str,
    dataset_revision: str,
    count: int,
    *,
    use_declared_images: bool = False,
) -> bytes:
    quote = json.dumps
    return (
        'model = "Qwen3.8-2.4T-A95B"\n'
        f"num_tasks = {count}\n"
        "num_rollouts = 1\n"
        "max_concurrent = 64\n"
        "max_turns = 200\n"
        "max_input_tokens = 262144\n"
        "max_output_tokens = 262144\n"
        "max_total_tokens = 262144\n"
        "multiplex = 64\n"
        "retain_traces = false\n"
        "[client]\n"
        'type = "eval"\n'
        "capture_model_io = true\n"
        'outbound_body_denylist = ["logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"]\n'
        'base_url = "http://127.0.0.1:8000/v1"\n'
        'api_key_var = "OPENAI_API_KEY"\n'
        "timeout = 7200\n"
        "connect_timeout = 30\n"
        "max_connections = 32\n"
        "max_keepalive_connections = 32\n"
        "[sampling]\n"
        'reasoning_effort = "high"\n'
        "temperature = 0.7\n"
        "top_p = 0.95\n"
        "top_k = 20\n"
        "max_tokens = 32768\n"
        "chat_template_kwargs = { enable_thinking = true, preserve_thinking = true }\n"
        "[taskset]\n"
        'id = "terminal-bench-vmvm"\n'
        f"dataset_dir = {quote(str(dataset))}\n"
        f"dataset_revision = {quote(dataset_revision)}\n"
        f"task_file = {quote(str(tasks))}\n"
        f"task_file_sha256 = {quote(task_sha256)}\n"
        f"image_manifest = {quote(str(image_manifest))}\n"
        f"image_manifest_sha256 = {quote(image_manifest_sha256)}\n"
        f"use_declared_images = {str(use_declared_images).lower()}\n"
        "ignore_dockerfile = true\n"
        "verifier_runtime_retries = 0\n"
        "[harness]\n"
        'id = "terminal-bench-sandoq-host"\n'
        "command_timeout_seconds = 240\n"
        "command_kill_grace_seconds = 10\n"
        "max_command_output_chars = 100000\n"
        "request_timeout_seconds = 15000\n"
        "[harness.runtime]\n"
        'type = "sandoq"\n'
        'mode = "oci-runner"\n'
        "session_timeout = 43200\n"
        "network_access = false\n"
        'host_tunnel = "none"\n'
        'expected_environment = "oci-runner-firecracker"\n'
        "[timeout]\n"
        "setup = 3600\n"
        "rollout = 36000\n"
        "finalize = 3600\n"
        "scoring = 21600\n"
        "[retries.rollout]\n"
        "max_retries = 0\n"
    ).encode()


def _inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    count = 2
    dataset_revision = "a" * 40
    monkeypatch.setattr(prepare, "EXPECTED_REPAIR_COUNT", count)
    monkeypatch.setattr(prepare, "EXPECTED_SANDOQ_COUNT", count)
    monkeypatch.setattr(prepare, "CANONICAL_DATASET_REVISION", dataset_revision)
    monkeypatch.setattr(
        generation,
        "_load_contract",
        lambda: {"repair": {"repair_union_count": count}},
    )
    monkeypatch.setattr(
        prepare.provider_union,
        "validate_materialization",
        lambda **_kwargs: {
            "partition": {
                "disjoint": True,
                "exhaustive": True,
                "sandoq_count": count,
                "vmvm_count": 0,
                "total_count": count,
            }
        },
    )
    monkeypatch.setattr(TerminalBenchVMVMTaskset, "_validate_dataset_revision", lambda *_args: None)

    expected_environment_sha256 = _sha("environment")
    expected_recovery_scope_sha256 = _sha("recovery")
    expected_materializer_sha256 = _sha("materializer")
    expected_consumer_sha256 = _sha("consumer")
    expected_extractor_sha256 = _sha("extractor")
    monkeypatch.setattr(prepare, "worker_environment_sha256", lambda _names: expected_environment_sha256)
    monkeypatch.setattr(materializer, "worker_environment_sha256", lambda _names: expected_environment_sha256)
    monkeypatch.setattr(
        prepare,
        "worker_recovery_scope_sha256",
        lambda _environment: expected_recovery_scope_sha256,
    )
    monkeypatch.setattr(
        materializer,
        "worker_recovery_scope_sha256",
        lambda _environment: expected_recovery_scope_sha256,
    )
    monkeypatch.setattr(prepare, "materializer_controller_code_sha256", lambda: expected_materializer_sha256)
    monkeypatch.setattr(materializer, "materializer_controller_code_sha256", lambda: expected_materializer_sha256)
    monkeypatch.setattr(prepare, "catalog_consumer_code_sha256", lambda: expected_consumer_sha256)
    monkeypatch.setattr(materializer, "catalog_consumer_code_sha256", lambda: expected_consumer_sha256)
    monkeypatch.setattr(prepare, "offline_requirements_extractor_sha256", lambda: expected_extractor_sha256)

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    members = ("opaque-a", "opaque-b")
    _task(dataset, members[0], "1" * 64)
    _task(dataset, members[1], "2" * 64)
    images = {
        "images": {
            members[0]: {"agent": f"registry.invalid/a@sha256:{'1' * 64}"},
            members[1]: {"agent": f"registry.invalid/b@sha256:{'2' * 64}"},
        }
    }
    image_manifest = tmp_path / "images.json"
    image_manifest.write_bytes(canonical_json(images))
    image_manifest_sha256 = _sha(image_manifest.read_bytes())

    private_root = tmp_path / DEPLOYMENT_NAMESPACE
    private_root.mkdir(mode=0o700)
    tasks = _private_file(
        private_root / "repair-sandoq.tasks.txt",
        "".join(f"{member}\n" for member in members).encode(),
    )
    task_sha256 = _sha(tasks.read_bytes())
    config = _private_file(
        private_root / "repair-sandoq.toml",
        _config(
            dataset,
            tasks,
            task_sha256,
            image_manifest,
            image_manifest_sha256,
            dataset_revision,
            count,
        ),
    )
    provider_receipt = _private_file(
        private_root / "provider-receipt.json",
        canonical_json({"private": True}),
    )
    provider_receipt_sha256 = _sha(provider_receipt.read_bytes())
    worker = _private_file(private_root / "worker", b"#!/bin/sh\nexit 1\n", mode=0o500)
    worker_sha256 = _sha(worker.read_bytes())
    environment_names = tuple(
        sorted(
            {
                *materializer._REQUIRED_SANDOQ_ENVIRONMENT_NAMES,
                "OCI_RUNNER_ECR_TOKEN_FILE",
                "OCI_RUNNER_ECR_TOKEN_METADATA_PATH",
            }
        )
    )
    worker_contract_value = {
        "schema_version": 1,
        "worker_protocol_version": materializer.WORKER_PROTOCOL_VERSION,
        "provider_commit": prepare.PINNED_PROVIDER_COMMIT,
        "provider_tree": prepare.PINNED_PROVIDER_TREE,
        "provider_source_sha256": prepare.PINNED_PROVIDER_SOURCE_SHA256,
        "sandoq_client_version": prepare.PINNED_SANDOQ_CLIENT,
        "worker_runtime_sha256": _sha("runtime"),
        "python_runtime_manifest_sha256": _sha("python-runtime"),
        "worker_provision_identity_sha256": _sha("provision"),
        "worker_site_manifest_sha256": _sha("worker-site"),
        "cleanup_receipt_verifier_sha256": _sha("cleanup"),
        "inventory_probe_code_sha256": _sha("probe-code"),
        "inventory_probe_environment_sha256": _sha("probe-environment"),
        "required_environment_names": list(environment_names),
        "runtime_invariants": dict(sorted(prepare.REQUIRED_WORKER_RUNTIME_INVARIANTS.items())),
    }
    worker_contract = _private_file(
        private_root / "worker-contract.json",
        canonical_json(worker_contract_value),
    )
    worker_contract_sha256 = _sha(worker_contract.read_bytes())
    policy_path = private_root / "catalog-policy.json"
    generator_sha256 = _sha(Path(prepare.__file__).read_bytes())
    policy_value = {
        "schema_version": 1,
        "kind": prepare.KIND,
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "expected_counts": {"repair": count, "sandoq": count, "vmvm": 0},
        "generator_sha256": generator_sha256,
        "provider_materialization_receipt_sha256": provider_receipt_sha256,
        "worker_contract_sha256": worker_contract_sha256,
        "worker": {
            "executable_sha256": worker_sha256,
            "runtime_sha256": worker_contract_value["worker_runtime_sha256"],
            "materializer_code_sha256": expected_materializer_sha256,
            "cleanup_receipt_verifier_sha256": worker_contract_value[
                "cleanup_receipt_verifier_sha256"
            ],
            "environment_sha256": expected_environment_sha256,
            "recovery_scope_sha256": expected_recovery_scope_sha256,
            "ecr_rotator_sha256": _sha("rotator"),
            "environment_names": list(environment_names),
            "timeouts_seconds": {
                "recover": 60,
                "probe": 120,
                "build": 300,
                "validate": 120,
            },
            "concurrency": {"probe": 24, "build": 4, "validate": 24},
        },
        "catalog_policy": {
            "inventory_probe_code_sha256": worker_contract_value[
                "inventory_probe_code_sha256"
            ],
            "inventory_probe_environment_sha256": worker_contract_value[
                "inventory_probe_environment_sha256"
            ],
            "inventory_probe_approval_sha256": _sha("probe-approval"),
            "catalog_consumer_code_sha256": expected_consumer_sha256,
            "requirements_extractor_sha256": expected_extractor_sha256,
            "source_policy_sha256": _sha("source-policy"),
            "source_policy_approval_sha256": _sha("source-approval"),
            "approved_binary_artifacts": [],
            "approved_source_attestations": [],
            "approved_toolchains": [_sha("toolchain")],
        },
    }
    _private_file(policy_path, _canonical_json(policy_value))

    placeholders = {}
    for name in (
        "source",
        "sandoq_template",
        "vmvm_template",
        "repair_selection_manifest",
        "historical_source_dir",
    ):
        placeholders[name] = tmp_path / name
    placeholders["vmvm_tasks"] = private_root / "repair-vmvm.tasks.txt"
    placeholders["vmvm_config"] = private_root / "repair-vmvm.toml"
    return {
        **placeholders,
        "dataset": dataset,
        "repair_selection_manifest_sha256": _sha("selection"),
        "sandoq_tasks": tasks,
        "sandoq_config": config,
        "provider_receipt": provider_receipt,
        "provider_receipt_sha256": provider_receipt_sha256,
        "private_output_root": private_root,
        "policy": policy_path,
        "policy_sha256": _sha(policy_path.read_bytes()),
        "worker_contract": worker_contract,
        "worker_contract_sha256": worker_contract_sha256,
        "worker": worker,
        "plan": private_root / "catalog-plan.json",
        "plan_receipt": private_root / "catalog-plan-receipt.json",
        "members": members,
        "image_manifest": image_manifest,
    }


def test_prepares_and_revalidates_exact_private_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)

    first_plan, first_receipt, expected_counts, first_root = prepare._derive_plan(inputs)
    second_plan, second_receipt, repeated_counts, second_root = prepare._derive_plan(inputs)
    assert first_plan == second_plan
    assert first_receipt == second_receipt
    assert expected_counts == repeated_counts
    assert first_root == second_root

    summary = prepare.prepare(**inputs)
    assert summary == {
        "tasks": 2,
        "sandoq": 2,
        "vmvm": 0,
        "images": 2,
        "probe_groups": 2,
        "requirement_sets": 1,
        "shared_agent": 2,
        "separate_verifier": 0,
    }
    receipt_text = Path(inputs["plan_receipt"]).read_text()
    assert all(member not in receipt_text for member in inputs["members"])
    assert "registry.invalid" not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["private_set_commitments"]["assignments"]["unique_count"] == 2
    assert receipt["private_set_commitments"]["probe_groups"]["unique_count"] == 2
    assert receipt["private_set_commitments"]["requirement_sets"]["unique_count"] == 1
    assert prepare.validate(**inputs) == summary
    for name in ("plan", "plan_receipt"):
        status = Path(inputs[name]).stat()
        assert stat.S_IMODE(status.st_mode) == 0o600
        assert status.st_nlink == 1


def test_plan_rejects_nonprivate_or_hardlinked_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    policy = Path(inputs["policy"])
    policy.chmod(0o644)
    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_input"):
        prepare.prepare(**inputs)

    policy.chmod(0o600)
    os.link(policy, policy.with_name("policy-hardlink"))
    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_input"):
        prepare.prepare(**inputs)


def test_plan_rejects_public_dependency_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    task = Path(inputs["dataset"]) / "opaque-a" / "task.toml"
    task.write_text(task.read_text().replace('network_mode = "no-network"', 'network_mode = "public"'))
    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_runtime_binding_invalid"):
        prepare.prepare(**inputs)


def test_plan_rejects_stale_provider_partition_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        prepare.provider_union,
        "validate_materialization",
        lambda **_kwargs: {
            "partition": {
                "disjoint": True,
                "exhaustive": True,
                "sandoq_count": 1,
                "vmvm_count": 1,
                "total_count": 2,
            }
        },
    )
    with pytest.raises(prepare.CatalogPlanError, match="provider_materialization_invalid"):
        prepare.prepare(**inputs)


def test_manifest_image_precedes_declared_image_like_runtime_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    task = Path(inputs["dataset"]) / "opaque-a" / "task.toml"
    declared = f"registry.invalid/declared@sha256:{'9' * 64}"
    task.write_text(task.read_text().replace("[environment]\n", f'[environment]\ndocker_image = "{declared}"\n'))
    config = Path(inputs["sandoq_config"])
    config.write_text(config.read_text().replace("use_declared_images = false", "use_declared_images = true"))

    plan_payload, _, _, _ = prepare._derive_plan(inputs)
    tasks = json.loads(plan_payload)["tasks"]
    selected = next(item for item in tasks if item["task_key"] == "opaque-a")
    assert selected["image"] == f"registry.invalid/a@sha256:{'1' * 64}"
    assert selected["image"] != declared


def test_plan_rejects_policy_worker_contract_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    policy_path = Path(inputs["policy"])
    policy = json.loads(policy_path.read_bytes())
    policy["worker_contract_sha256"] = _sha("foreign-worker-contract")
    policy_path.write_bytes(_canonical_json(policy))
    inputs["policy_sha256"] = _sha(policy_path.read_bytes())

    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_policy_invalid"):
        prepare.prepare(**inputs)


def test_plan_rejects_unsafe_paths_and_hardlinked_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    inputs["plan"] = Path(inputs["private_output_root"]) / "nested" / "plan.json"
    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_path_invalid"):
        prepare.prepare(**inputs)

    second = tmp_path / "second"
    second.mkdir()
    inputs = _inputs(second, monkeypatch)
    image_manifest = Path(inputs["image_manifest"])
    os.link(image_manifest, image_manifest.with_name("images-hardlink.json"))
    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_input_invalid"):
        prepare.prepare(**inputs)


def test_cli_failure_is_aggregate_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "private-task-member"
    monkeypatch.setattr(
        prepare,
        "_parse_args",
        lambda: SimpleNamespace(validate=False),
    )
    monkeypatch.setattr(
        prepare,
        "prepare",
        lambda **_arguments: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    assert prepare.main() == 1
    output = capsys.readouterr()
    assert secret not in output.out
    assert secret not in output.err
    assert json.loads(output.out) == {"error": "catalog_plan_invalid", "state": "failed"}


def test_cli_argument_failure_is_aggregate_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "private-task-member"
    monkeypatch.setattr(sys, "argv", ["prepare", f"--{secret}"])
    assert prepare.main() == 1
    output = capsys.readouterr()
    assert secret not in output.out
    assert secret not in output.err
    assert json.loads(output.out) == {"error": "catalog_plan_invalid", "state": "failed"}


def test_prepare_rejects_private_root_replacement_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    derived = prepare._derive_plan(inputs)
    monkeypatch.setattr(
        prepare,
        "_derive_plan",
        lambda _arguments: (*derived[:3], (-1, -1)),
    )

    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_input_changed"):
        prepare.prepare(**inputs)
    assert not Path(inputs["plan"]).exists()
    assert not Path(inputs["plan_receipt"]).exists()


def test_plan_rejects_symlinked_dependency_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    task = Path(inputs["dataset"]) / "opaque-a"
    outside = tmp_path / "outside-tests"
    outside.mkdir()
    (outside / "test.sh").write_text("python3 -m pip install pytest==8.3.4\n")
    (task / "tests" / "test.sh").unlink()
    (task / "tests").rmdir()
    (task / "tests").symlink_to(outside, target_is_directory=True)

    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_dataset_invalid"):
        prepare.prepare(**inputs)


def test_plan_rejects_dependency_mutation_during_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    original = TerminalBenchVMVMTaskset._test_requirements
    changed = False

    def mutate_after_read(task: object) -> tuple[str, ...]:
        nonlocal changed
        requirements = original(task)  # type: ignore[arg-type]
        if not changed:
            changed = True
            script = Path(getattr(task, "task_dir")) / "tests" / "test.sh"
            script.write_text(script.read_text() + "python3 -m pip install pluggy==1.5.0\n")
        return requirements

    monkeypatch.setattr(
        TerminalBenchVMVMTaskset,
        "_test_requirements",
        staticmethod(mutate_after_read),
    )
    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_dataset_changed"):
        prepare.prepare(**inputs)


def test_plan_revalidates_dataset_revision_after_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    calls = 0

    def validate_revision(_taskset: object, _dataset: Path) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        TerminalBenchVMVMTaskset,
        "_validate_dataset_revision",
        validate_revision,
    )
    prepare._derive_plan(inputs)
    assert calls == 2


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("max_turns = 200", "max_turns = 199"),
        ("timeout = 7200", "timeout = 7199"),
        ("connect_timeout = 30", "connect_timeout = 29"),
        ("max_tokens = 32768", "max_tokens = 32767"),
        ("session_timeout = 43200", "session_timeout = 43199"),
        ("rollout = 36000", "rollout = 35999"),
        (
            'outbound_body_denylist = ["logprobs", "prompt_logprobs", "top_logprobs", "return_token_ids"]',
            'outbound_body_denylist = ["logprobs"]',
        ),
    ],
)
def test_plan_rejects_runtime_contract_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    before: str,
    after: str,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    config = Path(inputs["sandoq_config"])
    body = config.read_text()
    assert body.count(before) == 1
    config.write_text(body.replace(before, after))

    with pytest.raises(prepare.CatalogPlanError, match="catalog_plan_config_invalid"):
        prepare.prepare(**inputs)
