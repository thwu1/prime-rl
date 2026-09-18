from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
import tomllib
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct
import migrate_qwen_serving_generation as generation
import pytest


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _artifact(path: Path) -> dict[str, int | str]:
    body = path.read_bytes()
    return {"sha256": _digest(body), "size_bytes": len(body)}


def _worker(identity: int, metadata: int) -> direct.Worker:
    body = json.dumps({"host": f"node-{identity}", "port": 8_000 + identity, "started_at": f"g-{identity}"}).encode()
    return direct.Worker(f"{metadata}.json", _digest(body), f"node-{identity}", 8_000 + identity, f"g-{identity}")


def _layout(tmp_path: Path) -> tuple[generation.BundleInputs, Path, list[direct.Worker], generation.SelectionBinding]:
    source = tmp_path / "source"
    selection = tmp_path / "selection"
    deployment = tmp_path / "deployment"
    repair = tmp_path / "runs" / "repair"
    output = selection / generation.RUN_BUNDLE_DIRECTORY
    for path in (source / "inputs", selection, deployment, repair.parent):
        path.mkdir(parents=True)
    for name in (".direct_router.lock", ".writer.lock"):
        (source / name).touch()
    old = [_worker(index, index + 1) for index in range(16)]
    old_manifest = {
        "workers": [worker.__dict__ for worker in old],
        "opaque": "source validator owns the remaining schema",
    }
    source_bodies = {
        "config.toml": b"source config\n",
        "direct_workers.json": json.dumps(old_manifest, sort_keys=True).encode() + b"\n",
        "inputs/source_config.toml": b"source input config\n",
        "inputs/manifest.json": b"{}\n",
        "provenance.txt": b"slurm_job_id=123\n",
        "results.jsonl": b"".join(f'{{"row":{index}}}\n'.encode() for index in range(1_392)),
    }
    for relative, body in source_bodies.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    repair_tasks = "".join(f"test-task-{index}\n" for index in range(1_153)).encode()
    image_manifest = selection / "image_manifest.json"
    image_manifest.write_bytes(b"{}\n")
    template = (Path(generation.__file__).parent / "configs" / "eval" / "mobius_qwen_a95b_2500.toml").read_text()
    replacements = {
        "num_tasks": "1153",
        "task_file": json.dumps(str(selection / "repair_tasks.txt")),
        "task_file_sha256": json.dumps(_digest(repair_tasks)),
        "image_manifest": json.dumps(str(image_manifest)),
        "image_manifest_sha256": json.dumps(_digest(image_manifest.read_bytes())),
    }
    for key, value in replacements.items():
        template, count = re.subn(rf"(?m)^(\s*{key}\s*=\s*).*$", rf"\g<1>{value}", template)
        assert count == 1
    selection_bodies = {
        "repair_config.toml": template.encode(),
        "repair_manifest.json": b"{}\n",
        "repair_missing_or_errored_tasks.txt": b"missing\n",
        "repair_strict_invalid_pass_tasks.txt": b"strict\n",
        "repair_tasks.txt": repair_tasks,
    }
    for name, body in selection_bodies.items():
        path = selection / name
        path.write_bytes(body)
        path.chmod(0o600)
    target = sorted(
        [*[_worker(index, index + 1) for index in range(15)], *[_worker(index, index + 1) for index in range(16, 25)]],
        key=lambda worker: worker.metadata_file,
    )
    bundle_digest = hashlib.sha256(
        "".join(f"{worker.metadata_sha256}  {worker.metadata_file}\n" for worker in target).encode()
    ).hexdigest()
    contract = {
        "kind": "qwen-direct-repair-serving-generation-contract",
        "model": direct.EXPECTED_MODEL,
        "repair": {
            "approved_task_count": 2_500,
            "missing_or_errored_count": 1_151,
            "repair_union_count": 1_153,
            "strict_invalid_pass_count": 2,
        },
        "routing": {
            "capacity_smoke_requests": 96,
            "max_concurrent_requests": 48,
            "policy": "consistent_hash",
            "queue_size": 48,
            "request_id_headers": ["x-session-id"],
            "rollout_concurrency": 96,
            "vmvm_lease_concurrency": 4,
        },
        "schema_version": 1,
        "server_identifier": generation.SERVER_IDENTIFIER,
        "source_generation": {
            "canonical_path": str(source),
            "artifacts": {name: _artifact(source / name) for name in source_bodies},
            "endpoint_bundle_sha256": "2" * 64,
            "results_row_count": 1_392,
            "routing_epoch": 3,
            "spec_sha256": "1" * 64,
            "worker_count": 16,
        },
        "target_generation": {
            "deployment_root": str(deployment),
            "endpoint_bundle_sha256": bundle_digest,
            "expected_added_workers": 9,
            "expected_overlap_workers": 15,
            "expected_retired_workers": 1,
            "spec_sha256": "3" * 64,
            "worker_count": 24,
        },
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n")
    binding = generation.SelectionBinding(
        manifest_sha256=_artifact(selection / "repair_manifest.json")["sha256"],
        task_file_sha256=_artifact(selection / "repair_tasks.txt")["sha256"],
        union_indices_sha256="5" * 64,
        union_count=1_153,
        missing_count=1_151,
        strict_invalid_count=2,
        source_artifacts={},
    )
    return generation.BundleInputs(source, selection, deployment, repair, output), contract_path, target, binding


def _code() -> dict[str, Any]:
    return {
        "revision": "a" * 40,
        "tree": "b" * 40,
        "submodules": {
            "deps/pydantic-config": "c" * 40,
            "deps/renderers": "d" * 40,
            "deps/verifiers": "e" * 40,
        },
        "runtime_files": {name: "f" * 64 for name in generation.RUNTIME_FILES},
    }


def _summary(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "routing_epoch": 3,
        "endpoints": 16,
        "spec_sha256": contract["source_generation"]["spec_sha256"],
        "endpoint_bundle_sha256": contract["source_generation"]["endpoint_bundle_sha256"],
        "manifest_schema_version": 3,
        "provider_concurrency": 32,
        "queue_size": 32,
        "router_policy": "consistent_hash",
        "request_id_headers": ["x-session-id"],
    }


def _materialize(tmp_path: Path):
    inputs, contract_path, target, binding = _layout(tmp_path)
    contract = json.loads(contract_path.read_bytes())

    def load(_root: Path, **expected: Any):
        assert expected["expected_count"] == 24
        return target, expected["expected_spec_sha256"], expected["expected_bundle_sha256"]

    summary = generation.materialize(
        inputs,
        contract_path=contract_path,
        terminal_check=lambda _job: True,
        source_auditor=lambda _source: _summary(contract),
        worker_loader=load,
        worker_probe=lambda _workers: None,
        code_state=_code,
        source_manifest_validator=lambda path: json.loads(path.read_bytes()),
        selection_loader=lambda _path, _contract: binding,
    )
    return inputs, contract_path, target, binding, summary


def test_materialize_attests_exact_transition_without_row_or_task_content(tmp_path: Path) -> None:
    inputs, contract_path, _target, binding, summary = _materialize(tmp_path)
    assert summary["source_rows"] == 1_392
    assert summary["repair_union_count"] == 1_153
    assert (summary["overlap_workers"], summary["retired_workers"], summary["added_workers"]) == (15, 1, 9)
    config = tomllib.loads((inputs.output_dir / generation.GENERATION_CONFIG_FILENAME).read_text())
    assert (config["max_concurrent"], config["multiplex"]) == (96, 96)
    assert (config["client"]["max_connections"], config["client"]["max_keepalive_connections"]) == (48, 48)
    manifest = json.loads((inputs.output_dir / generation.TARGET_MANIFEST_FILENAME).read_bytes())
    assert manifest["admission"] == {
        "client_max_connections": 48,
        "client_max_keepalive_connections": 48,
        "rollout_concurrency": 96,
        "router_max_concurrent_requests": 48,
        "router_queue_size": 48,
        "schema_version": direct.ADMISSION_SCHEMA_VERSION,
    }
    transition = (inputs.output_dir / generation.TRANSITION_FILENAME).read_bytes()
    assert b'"row"' not in transition
    assert b"opaque" not in transition
    contract = generation._load_contract(contract_path)
    with generation.migration._source_locks(inputs.source_dir):
        generation._validate_bundle(
            inputs.output_dir,
            inputs,
            contract,
            contract_path=contract_path,
            code_state=_code,
            source_manifest_validator=lambda path: json.loads(path.read_bytes()),
            selection_loader=lambda _path, _contract: binding,
        )


def test_bundle_rejects_any_prefix_change(tmp_path: Path) -> None:
    inputs, contract_path, _target, binding, _summary_value = _materialize(tmp_path)
    with (inputs.source_dir / "results.jsonl").open("ab") as handle:
        handle.write(b'{"changed":true}\n')
    with pytest.raises(generation.GenerationMigrationError, match="source_artifact_mismatch"):
        generation._validate_bundle(
            inputs.output_dir,
            inputs,
            generation._load_contract(contract_path),
            contract_path=contract_path,
            code_state=_code,
            source_manifest_validator=lambda path: json.loads(path.read_bytes()),
            selection_loader=lambda _path, _contract: binding,
        )


def test_materialize_rejects_nonterminal_or_concurrent_source(tmp_path: Path) -> None:
    inputs, contract_path, target, binding = _layout(tmp_path)
    contract = json.loads(contract_path.read_bytes())

    def invoke(terminal: bool) -> None:
        generation.materialize(
            inputs,
            contract_path=contract_path,
            terminal_check=lambda _job: terminal,
            source_auditor=lambda _source: _summary(contract),
            worker_loader=lambda _root, **expected: (
                target,
                expected["expected_spec_sha256"],
                expected["expected_bundle_sha256"],
            ),
            worker_probe=lambda _workers: None,
            code_state=_code,
            source_manifest_validator=lambda path: json.loads(path.read_bytes()),
            selection_loader=lambda _path, _contract: binding,
        )

    with pytest.raises(generation.GenerationMigrationError, match="source_job_not_terminal"):
        invoke(False)
    with (inputs.source_dir / ".writer.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(generation.GenerationMigrationError, match="source_lock_busy"):
            invoke(True)


def test_materialize_sanitizes_target_probe_failure(tmp_path: Path) -> None:
    inputs, contract_path, target, binding = _layout(tmp_path)
    contract = json.loads(contract_path.read_bytes())

    def unavailable(_workers: list[direct.Worker]) -> None:
        raise direct.DirectWorkerError(
            "worker_unreachable:https://credential@worker.invalid/private-metadata.json:PermissionError"
        )

    with pytest.raises(generation.GenerationMigrationError) as raised:
        generation.materialize(
            inputs,
            contract_path=contract_path,
            terminal_check=lambda _job: True,
            source_auditor=lambda _source: _summary(contract),
            worker_loader=lambda _root, **expected: (
                target,
                expected["expected_spec_sha256"],
                expected["expected_bundle_sha256"],
            ),
            worker_probe=unavailable,
            code_state=_code,
            source_manifest_validator=lambda path: json.loads(path.read_bytes()),
            selection_loader=lambda _path, _contract: binding,
        )
    assert raised.value.code == "target_generation_unavailable"
    assert raised.value.category == "worker_unreachable"
    assert str(raised.value) == "target_generation_unavailable"
    assert not inputs.output_dir.exists()


def test_cli_sanitizes_unhandled_direct_worker_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "https://credential@worker.invalid/private-metadata.json"
    monkeypatch.setattr(
        generation,
        "materialize",
        lambda _inputs: (_ for _ in ()).throw(direct.DirectWorkerError(f"worker_unreachable:{secret}:PermissionError")),
    )
    monkeypatch.setattr(
        os.sys,
        "argv",
        [
            "migrate_qwen_serving_generation.py",
            "materialize",
            "--source-dir",
            str(tmp_path / "source"),
            "--selection-dir",
            str(tmp_path / "selection"),
            "--deployment-root",
            str(tmp_path / "deployment"),
            "--repair-run-dir",
            str(tmp_path / "repair"),
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )
    with pytest.raises(SystemExit) as raised:
        generation.main()
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "category": "worker_unreachable",
        "code": "generation_transition_failed",
        "status": "error",
    }
    assert secret not in captured.err
    assert "credential" not in captured.err
    assert "private-metadata" not in captured.err
    assert "Traceback" not in captured.err


def test_publication_failure_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs, contract_path, target, binding = _layout(tmp_path)
    contract = json.loads(contract_path.read_bytes())
    monkeypatch.setattr(
        generation,
        "_validate_bundle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(generation.GenerationMigrationError("injected")),
    )
    with pytest.raises(generation.GenerationMigrationError, match="injected"):
        generation.materialize(
            inputs,
            contract_path=contract_path,
            terminal_check=lambda _job: True,
            source_auditor=lambda _source: _summary(contract),
            worker_loader=lambda _root, **expected: (
                target,
                expected["expected_spec_sha256"],
                expected["expected_bundle_sha256"],
            ),
            worker_probe=lambda _workers: None,
            code_state=_code,
            source_manifest_validator=lambda path: json.loads(path.read_bytes()),
            selection_loader=lambda _path, _contract: binding,
        )
    assert not inputs.output_dir.exists()


def test_launch_commit_and_resume_are_bound_to_transition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs, contract_path, target, binding, summary = _materialize(tmp_path)
    contract = json.loads(contract_path.read_bytes())

    monkeypatch.setattr(generation, "_load_contract", lambda _path=generation.CONTRACT_PATH: contract)
    monkeypatch.setattr(generation, "_code_state", _code)
    monkeypatch.setattr(
        generation.direct,
        "validate_saved_manifest",
        lambda path: json.loads(path.read_bytes()),
    )
    monkeypatch.setattr(generation, "_load_selection", lambda _path, _contract: binding)
    monkeypatch.setattr(generation.migration, "slurm_job_is_terminal", lambda _job: True)
    monkeypatch.setattr(
        generation.direct,
        "load_workers",
        lambda _root, **expected: (
            target,
            expected["expected_spec_sha256"],
            expected["expected_bundle_sha256"],
        ),
    )
    monkeypatch.setattr(generation.direct, "probe_workers", lambda _workers: None)
    run = inputs.repair_run_dir
    run.mkdir()
    router_lock = run / ".direct_router.lock"
    router_lock.touch()
    router_fd = os.open(router_lock, os.O_RDWR | os.O_CLOEXEC)
    urls = tmp_path / "urls"
    ports = tmp_path / "ports"
    try:
        fcntl.flock(router_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepared = generation.prepare_launch(
            inputs.output_dir,
            run,
            urls,
            ports,
            lock_fd=router_fd,
            resume=False,
            contract_path=contract_path,
        )
        assert prepared == {
            "ok": True,
            "resume": False,
            "target_workers": 24,
            "transition_sha256": summary["transition_sha256"],
        }
        assert len(urls.read_text().splitlines()) == 24
        assert ports.read_text().splitlines()[2:] == [
            "48",
            "48",
            str(direct.ROUTER_QUEUE_TIMEOUT_SECONDS),
            "consistent_hash",
            "x-session-id",
            "24",
            summary["transition_sha256"],
        ]
        sessions: list[str] = []
        session_lock = threading.Lock()

        def request(_base_url: str, _payload: bytes, session_id: str, _timeout: float) -> str:
            with session_lock:
                sessions.append(session_id)
            return _digest(session_id.encode())

        smoke = generation.capacity_smoke(
            run,
            f"http://127.0.0.1:{ports.read_text().splitlines()[0]}/v1",
            str(summary["transition_sha256"]),
            router_lock_fd=router_fd,
            requester=request,
        )
        assert smoke["successful_requests"] == 96
        assert len(sessions) == len(set(sessions)) == 96
        capacity_sha256 = _artifact(run / generation.CAPACITY_SMOKE_FILENAME)["sha256"]
        certificate = json.loads((run / generation.CAPACITY_SMOKE_FILENAME).read_bytes())
        assert certificate["client_peak_in_flight"] == 96
        assert certificate["vmvm_lease_concurrency"] == 4
        assert "choices" not in certificate
        assert "content" not in certificate

        run_inputs = run / "inputs"
        run_inputs.mkdir()
        snapshots = {
            "config": (
                "source_config.toml",
                run / generation.RUN_BUNDLE_DIRECTORY / generation.GENERATION_CONFIG_FILENAME,
            ),
            "task_file": ("task_file.txt", inputs.selection_dir / "repair_tasks.txt"),
        }
        records: dict[str, dict[str, str]] = {}
        for name, (snapshot_name, source) in snapshots.items():
            snapshot = run_inputs / snapshot_name
            snapshot.write_bytes(source.read_bytes())
            records[name] = {
                "sha256": _artifact(snapshot)["sha256"],
                "snapshot": str(snapshot),
                "source": str(source),
            }
        (run_inputs / "manifest.json").write_text(json.dumps(records, sort_keys=True) + "\n")
        manifest = json.loads((run / "direct_workers.json").read_bytes())
        provenance = {
            "direct_qwen_manifest_sha256": _artifact(run / "direct_workers.json")["sha256"],
            "direct_qwen_provider_concurrency": "48",
            "direct_qwen_request_id_headers": "x-session-id",
            "direct_qwen_router_policy": "consistent_hash",
            "inference_base_url": f"http://127.0.0.1:{manifest['router']['port']}/v1",
            "inference_deployment_id": "",
            "prime_rl": _code()["revision"],
            "qwen_serving_generation_capacity_smoke_sha256": capacity_sha256,
            "qwen_serving_generation_transition_sha256": summary["transition_sha256"],
            "renderers": _code()["submodules"]["deps/renderers"],
            "verifiers": _code()["submodules"]["deps/verifiers"],
        }
        (run / "provenance.txt").write_text("".join(f"{key}={value}\n" for key, value in provenance.items()))
        writer_lock = run / ".writer.lock"
        writer_lock.touch()
        writer_fd = os.open(writer_lock, os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.flock(writer_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            records["task_file"]["sha256"] = "0" * 64
            (run_inputs / "manifest.json").write_text(json.dumps(records, sort_keys=True) + "\n")
            with pytest.raises(generation.GenerationMigrationError, match="run_inputs_invalid"):
                generation.commit_launch(
                    run,
                    str(summary["transition_sha256"]),
                    router_lock_fd=router_fd,
                    writer_lock_fd=writer_fd,
                    contract_path=contract_path,
                )
            assert (run / direct.MIGRATION_INCOMPLETE_FILENAME).is_file()
            records["task_file"]["sha256"] = str(_artifact(run_inputs / "task_file.txt")["sha256"])
            (run_inputs / "manifest.json").write_text(json.dumps(records, sort_keys=True) + "\n")
            generation.commit_launch(
                run,
                str(summary["transition_sha256"]),
                router_lock_fd=router_fd,
                writer_lock_fd=writer_fd,
                contract_path=contract_path,
            )
            (run / "config.toml").write_bytes(
                (run / generation.RUN_BUNDLE_DIRECTORY / generation.GENERATION_CONFIG_FILENAME).read_bytes()
            )
            (run / "results.jsonl").write_bytes(b'{"status":"opaque"}\n')
            with pytest.raises(generation.GenerationMigrationError, match="writer_lock_busy"):
                generation.prepare_launch(
                    run / generation.RUN_BUNDLE_DIRECTORY,
                    run,
                    urls,
                    ports,
                    lock_fd=router_fd,
                    resume=True,
                    contract_path=contract_path,
                )
        finally:
            os.close(writer_fd)

        audited = generation.audit_repair_run(run, contract_path=contract_path)
        assert audited["serving_generation"] == 2
        assert audited["endpoints"] == 24
        capacity_path = run / generation.CAPACITY_SMOKE_FILENAME
        capacity_body = capacity_path.read_bytes()
        capacity_path.write_bytes(capacity_body.replace(b'"successful_requests": 96', b'"successful_requests": 95'))
        with pytest.raises(generation.GenerationMigrationError, match="capacity_smoke_invalid"):
            generation.audit_repair_run(run, contract_path=contract_path)
        capacity_path.write_bytes(capacity_body)
        resumed = generation.prepare_launch(
            run / generation.RUN_BUNDLE_DIRECTORY,
            run,
            urls,
            ports,
            lock_fd=router_fd,
            resume=True,
            contract_path=contract_path,
        )
        assert resumed["resume"] is True
    finally:
        os.close(router_fd)
