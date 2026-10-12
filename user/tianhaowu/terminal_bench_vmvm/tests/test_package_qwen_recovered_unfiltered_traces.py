from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1]
PACKAGER = WORKFLOW / "package_qwen_recovered_unfiltered_traces.sh"
PACKAGING_GUIDE = WORKFLOW / "QWEN_RECOVERED_TRACE_PACKAGING.md"
PACKAGE_WORKER = WORKFLOW / "package_qwen_recovered_unfiltered_traces.sbatch"
LAUNCHER = WORKFLOW / "launch_qwen_recovered_unfiltered_trace_package.sh"
PREVIOUS_MANIFEST = WORKFLOW / "trace_packages/qwen-2499-unfiltered-1ae8855f-v1/manifest.json"
SELECTION_SHA256 = "5369194fc1bea5dd72c20457a8fd1fac906144c8beb4bc20d77727fb77c8b228"
CANONICAL_SHA256 = "5b2ed7c5b166a6570b46d3dacff680c5ba6ff22f7e02e57e273eb442e6842b8c"
PREDECESSOR_REVISION = "d9a4eb07de3b769899c0e77eedf5da5f6c35ab61"
POSTPROCESSOR_REVISION = "108b713af332b6865c49c3b146f3fa2158fe790a"
SOURCE_JOB = "1579607"
PREDECESSOR_RETRY_MODULE_SHA256 = "09b7f757ad64c1a49aac5cf4dd34d09ea495734192101a2001a6cb205dcacba0"
PREDECESSOR_EXPORTER_SHA256 = "7254c193464213651c0005d7ebbc731d44f0c96552086a1879556a2397349a18"
SUPERSEDING_EXPORTER_SHA256 = "d6386bc08eec676ec1e48913aca37e934cf65c90dabbd0fa99ee5221d5118fbb"
SUPERSESSION_MODULE_SHA256 = "33d090437237bc94cea514856cb0d45b04e16edfafdd9772a5b36b5d4b12fae9"
AUDIT_TRACES_SHA256 = "7b20a4e600cdff8213b9be322029087962e700df87dd06f1c702cb4278970ad3"
VERIFIER_REVISION = "3df6efa9e9f6bdc8a013df7759a03074aec79111"
RENDERER_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
MODEL_IO_CONTRACT_ID = "qwen3-a95b"
MODEL_IO_CONTRACT_SHA256 = "338772c5840f201851c30a29df1f3986af414b1fa22c325aff5783cb8b460a84"
PRIVATE_MARKER = "SYNTHETIC_PRIVATE_TRACE_CONTENT_MUST_NOT_BE_LOGGED"


@pytest.mark.parametrize(
    "variable",
    [
        "QWEN_V6_PACKAGE_EXPECTED_RETRY_MODULE_SHA256",
        "QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_EXPORTER_SHA256",
        "QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_EXPORTER_SHA256",
        "QWEN_V6_PACKAGE_EXPECTED_SUPERSESSION_MODULE_SHA256",
        "QWEN_V6_PACKAGE_EXPECTED_AUDIT_TRACES_SHA256",
        "QWEN_V6_PACKAGE_EXPECTED_VERIFIER_REVISION",
        "QWEN_V6_PACKAGE_EXPECTED_RENDERER_REVISION",
        "QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_ID",
        "QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_SHA256",
    ],
)
def test_packaging_guide_exports_required_provenance(variable: str) -> None:
    assert f"export {variable}=" in PACKAGING_GUIDE.read_text()


def _body(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _write(path: Path, value: object) -> tuple[int, str]:
    payload = _body(value)
    path.write_bytes(payload)
    path.chmod(0o600)
    return len(payload), hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(project: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[dict[str, str], Path]:
    project = tmp_path / "project"
    workflow = project / "user/tianhaowu/terminal_bench_vmvm"
    workflow.mkdir(parents=True)
    copied_packager = workflow / PACKAGER.name
    copied_worker = workflow / PACKAGE_WORKER.name
    shutil.copy2(PACKAGER, copied_packager)
    shutil.copy2(PACKAGE_WORKER, copied_worker)
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(
        project,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    project_revision = _git(project, "rev-parse", "HEAD")

    unfiltered = tmp_path / "unfiltered"
    run = tmp_path / "run"
    postrun = tmp_path / "postrun"
    output_parent = tmp_path / "outputs"
    for directory in (unfiltered, run, postrun, output_parent):
        directory.mkdir(mode=0o700)

    results = unfiltered / "results.jsonl"
    row = _body({"private": PRIVATE_MARKER})
    results.write_bytes(row * 2499)
    results.chmod(0o600)
    results_artifact = {
        "bytes": results.stat().st_size,
        "path": str(results),
        "sha256": _sha256(results),
    }
    outcomes = {"error": 24, "positive": 1588, "zero": 887}
    replacements = {"clean_model_bearing": 40, "positive": 26, "zero": 14}
    code = {
        "audit_traces_sha256": AUDIT_TRACES_SHA256,
        "exporter_sha256": SUPERSEDING_EXPORTER_SHA256,
        "qwen_2499_error_retry_sha256": PREDECESSOR_RETRY_MODULE_SHA256,
        "repository_revision": POSTPROCESSOR_REVISION,
        "submodules": {
            "deps/renderers": "044d9e2541f6a911cacae9da353fc063911ef1f8",
            "deps/verifiers": "3df6efa9e9f6bdc8a013df7759a03074aec79111",
        },
        "supersession_module_sha256": SUPERSESSION_MODULE_SHA256,
    }
    run_evidence = {
        name: {
            "bytes": index + 1,
            "path": str(run / name),
            "sha256": hashlib.sha256(name.encode()).hexdigest(),
        }
        for index, name in enumerate(("cleanup", "eval_run_identity", "resolved_config", "results", "worker_manifest"))
    }
    runtime = {
        "cleanup_failures": 0,
        "eval_run_identity_sha256": "1" * 64,
        "provider_concurrency": 32,
        "router_policy": "consistent_hash",
        "worker_count": 24,
    }
    accepted_empty = {
        "canonical_indices_sha256": "2" * 64,
        "count": 0,
        "predicate": "reward-one-and-exact-model-io-and-sft-trainable",
        "row_sha256_set_sha256": "3" * 64,
    }

    retry = run / "qwen_2499_error_retry_run_certificate.json"
    retry_bytes, retry_sha256 = _write(
        retry,
        {
            "accepted": accepted_empty,
            "code": {"module_sha256": PREDECESSOR_RETRY_MODULE_SHA256},
            "schema_version": 1,
            "kind": "qwen-2499-exact-error-retry-run",
            "state": "passed",
            "selection_contract_sha256": SELECTION_SHA256,
            "run": run_evidence,
            "runtime": runtime,
            "retry_outcomes": {
                "accepted_positive": 0,
                "error": 24,
                "invalid_positive": 26,
                "retained_original": 64,
                "total": 64,
                "zero": 14,
            },
            "trace_contract": {
                "id": "qwen3-a95b",
                "max_sequence_tokens": 262144,
                "sha256": MODEL_IO_CONTRACT_SHA256,
            },
        },
    )
    superseding_outcomes = {
        "clean_model_bearing": 40,
        "error": 24,
        "invalid_positive": 0,
        "invalid_zero": 0,
        "positive": 26,
        "total": 64,
        "zero": 14,
    }
    superseding = run / "qwen_2499_error_retry_superseding_certificate.json"
    _, superseding_sha256 = _write(
        superseding,
        {
            "accepted": {
                "pass_only": {
                    "canonical_indices_sha256": "4" * 64,
                    "count": 26,
                    "predicate": "reward-one-and-exact-model-io-and-sft-trainable",
                    "row_sha256_set_sha256": "5" * 64,
                },
                "unfiltered": {
                    "canonical_indices_sha256": "6" * 64,
                    "count": 40,
                    "predicate": "binary-reward-and-exact-model-io-and-sft-structurally-valid",
                    "row_sha256_set_sha256": "7" * 64,
                },
            },
            "code": code,
            "schema_version": 1,
            "kind": "qwen-2499-error-retry-superseding-certificate",
            "state": "passed",
            "selection_contract_sha256": SELECTION_SHA256,
            "predecessor": {
                "accepted_positive": 0,
                "artifact": {"bytes": retry_bytes, "sha256": retry_sha256},
                "exporter_sha256": PREDECESSOR_EXPORTER_SHA256,
                "kind": "qwen-2499-exact-error-retry-run",
                "module_sha256": PREDECESSOR_RETRY_MODULE_SHA256,
                "repository_revision": PREDECESSOR_REVISION,
                "sha256": retry_sha256,
            },
            "migration": {
                "compatibility_id": "openai-null-wire-fields-v1",
                "policy": "permit-standard-null-openai-wire-fields-only",
            },
            "run": run_evidence,
            "runtime": runtime,
            "outcomes": superseding_outcomes,
            "trace_contract": {
                "id": "qwen3-a95b",
                "max_sequence_tokens": 262144,
                "require_exact_provider_json": True,
                "require_model_io": True,
                "require_reasoning": True,
                "require_request_graph_match": True,
                "sha256": MODEL_IO_CONTRACT_SHA256,
            },
        },
    )
    recovered = unfiltered / "qwen_2499_recovered_results_certificate.json"
    recovered_value = {
        "schema_version": 1,
        "kind": "qwen-2499-error-retry-recovered-results",
        "state": "passed",
        "mode": "unfiltered",
        "coverage": {
            "canonical_order": True,
            "exact": True,
            "exhaustive": True,
            "task_count": 2499,
            "universe_task_file_sha256": CANONICAL_SHA256,
        },
        "lineage": {
            "selection_contract_sha256": SELECTION_SHA256,
            "superseding_certificate_sha256": superseding_sha256,
        },
        "outcomes": outcomes,
        "replacements": replacements,
        "results": results_artifact,
        "trace_contract": {
            "max_sequence_tokens": 262144,
            "replacement_rows_have_model_io": True,
            "replacement_rows_have_reasoning": True,
            "replacement_rows_request_graph_valid": True,
        },
        "code": code,
    }
    recovered_bytes, recovered_sha256 = _write(recovered, recovered_value)
    merge = unfiltered / "merge_manifest.json"
    merge_bytes, merge_sha256 = _write(
        merge,
        {
            "schema_version": 1,
            "kind": "qwen-2499-error-retry-recovered-results-manifest",
            "state": "ready",
            "mode": "unfiltered",
            "artifacts": {
                "results": results_artifact,
                "certificate": {
                    "bytes": recovered_bytes,
                    "path": str(recovered),
                    "sha256": recovered_sha256,
                },
            },
            "lineage": recovered_value["lineage"],
            "outcomes": outcomes,
            "sft_selection": None,
        },
    )
    receipt = postrun / "postrun_receipt-src108b713af-v6.json"
    _write(
        receipt,
        {
            "schema_version": 1,
            "kind": "qwen-2499-unfiltered-recovered-results-postrun",
            "state": "certified",
            "mode": "unfiltered",
            "task_count": 2499,
            "artifact": {
                "results": {
                    "bytes": results.stat().st_size,
                    "sha256": _sha256(results),
                },
                "certificate": {"bytes": recovered_bytes, "sha256": recovered_sha256},
                "manifest": {"bytes": merge_bytes, "sha256": merge_sha256},
            },
            "capture": {
                "model_bearing_traces": outcomes["positive"] + outcomes["zero"],
                "sampled_nodes": 3000,
                "model_io_nodes": 3000,
                "reasoning_nodes": 3000,
            },
            "code": code,
            "lineage": {
                "retry_run_certificate_sha256": retry_sha256,
                "run_repository_revision": PREDECESSOR_REVISION,
                "selection_contract_sha256": SELECTION_SHA256,
                "source_job": int(SOURCE_JOB),
                "superseding_certificate_sha256": superseding_sha256,
            },
            "outcomes": outcomes,
            "replacements": replacements,
        },
    )
    previous = tmp_path / "previous-manifest.json"
    shutil.copy2(PREVIOUS_MANIFEST, previous)
    # Ordinary Git worktrees materialize this already-published, non-secret
    # manifest as 0644.  The generated postrun artifacts remain private 0600.
    previous.chmod(0o644)
    postrun_worker = tmp_path / "postrun-worker.sbatch"
    postrun_worker.write_text("#!/bin/bash\nexit 0\n")
    postrun_worker.chmod(0o500)

    environment = {
        **os.environ,
        "QWEN_V6_PACKAGE_PROJECT_DIR": str(project),
        "QWEN_V6_PACKAGE_EXPECTED_PROJECT_REVISION": project_revision,
        "QWEN_V6_PACKAGE_EXPECTED_POSTPROCESSOR_REVISION": POSTPROCESSOR_REVISION,
        "QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_REVISION": PREDECESSOR_REVISION,
        "QWEN_V6_PACKAGE_EXPECTED_RETRY_MODULE_SHA256": PREDECESSOR_RETRY_MODULE_SHA256,
        "QWEN_V6_PACKAGE_EXPECTED_PREDECESSOR_EXPORTER_SHA256": PREDECESSOR_EXPORTER_SHA256,
        "QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_EXPORTER_SHA256": SUPERSEDING_EXPORTER_SHA256,
        "QWEN_V6_PACKAGE_EXPECTED_SUPERSESSION_MODULE_SHA256": SUPERSESSION_MODULE_SHA256,
        "QWEN_V6_PACKAGE_EXPECTED_AUDIT_TRACES_SHA256": AUDIT_TRACES_SHA256,
        "QWEN_V6_PACKAGE_EXPECTED_VERIFIER_REVISION": VERIFIER_REVISION,
        "QWEN_V6_PACKAGE_EXPECTED_RENDERER_REVISION": RENDERER_REVISION,
        "QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_ID": MODEL_IO_CONTRACT_ID,
        "QWEN_V6_PACKAGE_EXPECTED_MODEL_IO_CONTRACT_SHA256": MODEL_IO_CONTRACT_SHA256,
        "QWEN_V6_PACKAGE_EXPECTED_SOURCE_JOB": SOURCE_JOB,
        "QWEN_V6_PACKAGE_SELECTION_CONTRACT_SHA256": SELECTION_SHA256,
        "QWEN_V6_PACKAGE_PACKAGER_SHA256": _sha256(copied_packager),
        "QWEN_V6_PACKAGE_WORKER_SHA256": _sha256(copied_worker),
        "QWEN_V6_PACKAGE_CANONICAL_TASK_FILE_SHA256": CANONICAL_SHA256,
        "QWEN_V6_PACKAGE_POSTRUN_WORKER": str(postrun_worker),
        "QWEN_V6_PACKAGE_POSTRUN_WORKER_SHA256": _sha256(postrun_worker),
        "QWEN_V6_PACKAGE_UNFILTERED_DIR": str(unfiltered),
        "QWEN_V6_PACKAGE_RETRY_CERTIFICATE": str(retry),
        "QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE": str(superseding),
        "QWEN_V6_PACKAGE_POSTRUN_RECEIPT": str(receipt),
        "QWEN_V6_PACKAGE_PREVIOUS_MANIFEST": str(previous),
        "QWEN_V6_PACKAGE_PREVIOUS_MANIFEST_SHA256": _sha256(previous),
        "QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256": _sha256(results),
        "QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256": _sha256(recovered),
        "QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256": _sha256(merge),
        "QWEN_V6_PACKAGE_EXPECTED_RETRY_CERTIFICATE_SHA256": _sha256(retry),
        "QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256": _sha256(superseding),
        "QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256": _sha256(receipt),
        "QWEN_V6_PACKAGE_POSTRUN_JOB_ID": "2000001",
        "QWEN_V6_PACKAGE_OUTPUT_DIR": str(output_parent / "package-a"),
        "QWEN_V6_PACKAGE_CHUNK_BYTES": "1000",
        "QWEN_V6_PACKAGE_ZSTD_LEVEL": "1",
    }
    return environment, copied_packager


def _run(packager: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(packager)],
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file()}


def _refresh_superseding_chain(environment: dict[str, str]) -> None:
    superseding = Path(environment["QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE"])
    recovered = Path(environment["QWEN_V6_PACKAGE_UNFILTERED_DIR"]) / ("qwen_2499_recovered_results_certificate.json")
    merge = Path(environment["QWEN_V6_PACKAGE_UNFILTERED_DIR"]) / "merge_manifest.json"
    receipt = Path(environment["QWEN_V6_PACKAGE_POSTRUN_RECEIPT"])

    superseding_sha256 = _sha256(superseding)
    recovered_value = json.loads(recovered.read_bytes())
    recovered_value["lineage"]["superseding_certificate_sha256"] = superseding_sha256
    recovered_bytes, recovered_sha256 = _write(recovered, recovered_value)

    merge_value = json.loads(merge.read_bytes())
    merge_value["lineage"] = recovered_value["lineage"]
    merge_value["artifacts"]["certificate"] = {
        "bytes": recovered_bytes,
        "path": str(recovered),
        "sha256": recovered_sha256,
    }
    merge_bytes, merge_sha256 = _write(merge, merge_value)

    receipt_value = json.loads(receipt.read_bytes())
    receipt_value["lineage"]["superseding_certificate_sha256"] = superseding_sha256
    receipt_value["artifact"]["certificate"] = {
        "bytes": recovered_bytes,
        "sha256": recovered_sha256,
    }
    receipt_value["artifact"]["manifest"] = {
        "bytes": merge_bytes,
        "sha256": merge_sha256,
    }
    _write(receipt, receipt_value)

    environment["QWEN_V6_PACKAGE_EXPECTED_SUPERSEDING_CERTIFICATE_SHA256"] = superseding_sha256
    environment["QWEN_V6_PACKAGE_EXPECTED_RECOVERED_CERTIFICATE_SHA256"] = recovered_sha256
    environment["QWEN_V6_PACKAGE_EXPECTED_MERGE_MANIFEST_SHA256"] = merge_sha256
    environment["QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256"] = _sha256(receipt)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o700)


def _launcher_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    environment, _packager = _fixture(tmp_path)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "sbatch-calls.txt"
    _write_executable(
        stubs / "tmux",
        "#!/bin/bash\nprintf '%s\\n' 'swebench_vmvm:Launcher.0'\n",
    )
    _write_executable(
        stubs / "sacct",
        "#!/bin/bash\nprintf '%s\\n' '1579999|COMPLETED|0:0'\n",
    )
    _write_executable(
        stubs / "sbatch",
        "#!/bin/bash\n"
        'printf \'%s\\n\' "$*" >>"$SBATCH_CALLS"\n'
        '/bin/sleep "${SBATCH_SLEEP:-0}"\n'
        "printf '%s\\n' \"${SBATCH_RESULT:-2000002}\"\n",
    )
    environment.update(
        {
            "PATH": f"{stubs}:{environment['PATH']}",
            "SBATCH_CALLS": str(calls),
            "TMUX": "test",
            "TMUX_PANE": "%1",
            "QWEN_V6_PACKAGE_JOBID_FILE": str(tmp_path / "package.jobid"),
        }
    )
    return environment, calls, Path(environment["QWEN_V6_PACKAGE_JOBID_FILE"])


def test_recovered_package_is_deterministic_and_fail_closed(tmp_path: Path) -> None:
    environment, packager = _fixture(tmp_path)
    first = _run(packager, environment)
    assert first.returncode == 0, first.stderr
    first_output = Path(environment["QWEN_V6_PACKAGE_OUTPUT_DIR"])
    first_manifest = json.loads((first_output / "manifest.json").read_bytes())
    assert json.loads(first.stdout)["state"] == "packaged"
    assert PRIVATE_MARKER not in first.stdout
    assert PRIVATE_MARKER not in first.stderr
    assert first_manifest["state"] == "ready"
    assert first_manifest["coverage"]["canonical_tasks"] == 2499
    assert first_manifest["archive"]["compression"] == "zstd-1-long31"
    assert first_manifest["lineage"]["selection_contract_sha256"] == SELECTION_SHA256
    assert first_manifest["lineage"]["predecessor_revision"] == PREDECESSOR_REVISION
    assert first_manifest["lineage"]["source_job"] == int(SOURCE_JOB)
    assert first_manifest["lineage"]["postrun_job_id"] == 2000001
    assert first_manifest["package_worker"]["sha256"] == environment["QWEN_V6_PACKAGE_WORKER_SHA256"]
    assert first_manifest["inputs"]["results"]["sha256"] == environment["QWEN_V6_PACKAGE_EXPECTED_RESULTS_SHA256"]
    assert first_manifest["archive"]["member_count"] == 7
    assert len(first_manifest["archive"]["members"]) == 7
    assert all(chunk["bytes"] < 100_000_000 for chunk in first_manifest["chunks"])
    compressed = b"".join((first_output / "chunks" / chunk["name"]).read_bytes() for chunk in first_manifest["chunks"])
    decoded = subprocess.run(
        ["zstd", "-q", "--long=31", "-dc"],
        input=compressed,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(decoded), mode="r:") as archive:
        assert archive.getnames() == [member["name"] for member in first_manifest["archive"]["members"]]
        for member in first_manifest["archive"]["members"]:
            extracted = archive.extractfile(member["name"])
            assert extracted is not None
            body = extracted.read()
            assert len(body) == member["bytes"]
            assert hashlib.sha256(body).hexdigest() == member["sha256"]

    second_environment = {
        **environment,
        "QWEN_V6_PACKAGE_OUTPUT_DIR": str(tmp_path / "outputs/package-b"),
    }
    second = _run(packager, second_environment)
    assert second.returncode == 0, second.stderr
    second_output = Path(second_environment["QWEN_V6_PACKAGE_OUTPUT_DIR"])
    assert _tree_hashes(first_output) == _tree_hashes(second_output)

    boundary_environment = {
        **environment,
        "QWEN_V6_PACKAGE_OUTPUT_DIR": str(tmp_path / "outputs/boundary"),
        "QWEN_V6_PACKAGE_CHUNK_BYTES": "100000000",
    }
    boundary = _run(packager, boundary_environment)
    assert boundary.returncode == 2
    assert json.loads(boundary.stderr) == {"code": "package_configuration_invalid", "state": "error"}
    assert not Path(boundary_environment["QWEN_V6_PACKAGE_OUTPUT_DIR"]).exists()

    receipt = Path(environment["QWEN_V6_PACKAGE_POSTRUN_RECEIPT"])
    bad_receipt = json.loads(receipt.read_bytes())
    bad_receipt["lineage"]["superseding_certificate_sha256"] = "c" * 64
    receipt.write_bytes(_body(bad_receipt))
    bad_environment = {
        **environment,
        "QWEN_V6_PACKAGE_OUTPUT_DIR": str(tmp_path / "outputs/bad-lineage"),
        "QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256": _sha256(receipt),
    }
    rejected = _run(packager, bad_environment)
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr) == {"code": "source_contract_invalid", "state": "error"}
    assert not Path(bad_environment["QWEN_V6_PACKAGE_OUTPUT_DIR"]).exists()


def test_recovered_package_rejects_coherent_but_incomplete_certificate_chain(
    tmp_path: Path,
) -> None:
    environment, packager = _fixture(tmp_path)
    superseding = Path(environment["QWEN_V6_PACKAGE_SUPERSEDING_CERTIFICATE"])
    value = json.loads(superseding.read_bytes())
    del value["migration"]
    _write(superseding, value)
    _refresh_superseding_chain(environment)

    rejected = _run(packager, environment)
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr) == {"code": "source_contract_invalid", "state": "error"}
    assert PRIVATE_MARKER not in rejected.stdout
    assert PRIVATE_MARKER not in rejected.stderr
    assert not Path(environment["QWEN_V6_PACKAGE_OUTPUT_DIR"]).exists()


def test_recovered_package_rejects_source_job_and_external_digest_changes(
    tmp_path: Path,
) -> None:
    environment, packager = _fixture(tmp_path)
    receipt = Path(environment["QWEN_V6_PACKAGE_POSTRUN_RECEIPT"])
    original = receipt.read_bytes()
    receipt.write_bytes(original + b" ")
    digest_rejected = _run(packager, environment)
    assert digest_rejected.returncode == 2
    assert json.loads(digest_rejected.stderr) == {
        "code": "pinned_artifact_digest_mismatch",
        "state": "error",
    }

    receipt.write_bytes(original)
    value = json.loads(receipt.read_bytes())
    value["lineage"]["source_job"] = int(SOURCE_JOB) + 1
    _write(receipt, value)
    source_environment = {
        **environment,
        "QWEN_V6_PACKAGE_EXPECTED_POSTRUN_RECEIPT_SHA256": _sha256(receipt),
        "QWEN_V6_PACKAGE_OUTPUT_DIR": str(tmp_path / "outputs/bad-source-job"),
    }
    source_rejected = _run(packager, source_environment)
    assert source_rejected.returncode == 2
    assert json.loads(source_rejected.stderr) == {
        "code": "source_contract_invalid",
        "state": "error",
    }


def test_recovered_package_has_one_winner_under_concurrent_publication(tmp_path: Path) -> None:
    environment, packager = _fixture(tmp_path)
    processes = [
        subprocess.Popen(
            ["bash", str(packager)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    completed = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=120)
        completed.append((process.returncode, stdout, stderr))

    assert sorted(code for code, _stdout, _stderr in completed) == [0, 2]
    loser = next((stdout, stderr) for code, stdout, stderr in completed if code == 2)
    assert json.loads(loser[1])["code"] in {"output_exists", "output_locked"}
    assert PRIVATE_MARKER not in "".join(stdout + stderr for _code, stdout, stderr in completed)
    output = Path(environment["QWEN_V6_PACKAGE_OUTPUT_DIR"])
    assert {path.name for path in output.iterdir()} == {
        "README.md",
        "SHA256SUMS",
        "chunks",
        "manifest.json",
    }


@pytest.mark.parametrize("value", ["0", "100000000", "95000000,INJECTED=value", "not-a-number"])
def test_recovered_package_rejects_invalid_chunk_settings(tmp_path: Path, value: str) -> None:
    environment, packager = _fixture(tmp_path)
    environment["QWEN_V6_PACKAGE_CHUNK_BYTES"] = value
    rejected = _run(packager, environment)
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr) == {"code": "package_configuration_invalid", "state": "error"}


def test_launcher_exports_only_validated_values_and_records_job(tmp_path: Path) -> None:
    environment, calls, jobid_file = _launcher_environment(tmp_path)
    environment["UNRELATED_PRIVATE_VALUE"] = PRIVATE_MARKER
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "1579999"],
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "dependency": 1579999,
        "job_id": 2000002,
        "state": "submitted",
    }
    assert jobid_file.read_text() == "2000002\n"
    assert not Path(f"{jobid_file}.lock").exists()
    arguments = calls.read_text()
    assert "--dependency=afterok:1579999" in arguments
    assert "QWEN_V6_PACKAGE_POSTRUN_JOB_ID=1579999" in arguments
    assert "UNRELATED_PRIVATE_VALUE" not in arguments
    assert PRIVATE_MARKER not in completed.stdout + completed.stderr + arguments


def test_launcher_reservation_allows_only_one_submission(tmp_path: Path) -> None:
    environment, calls, jobid_file = _launcher_environment(tmp_path)
    environment["SBATCH_SLEEP"] = "0.25"
    processes = [
        subprocess.Popen(
            ["bash", str(LAUNCHER), "1579999"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    completed = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        completed.append((process.returncode, stdout, stderr))

    assert sorted(code for code, _stdout, _stderr in completed) == [0, 2]
    assert len(calls.read_text().splitlines()) == 1
    assert jobid_file.read_text() == "2000002\n"
    assert not Path(f"{jobid_file}.lock").exists()


def test_launcher_normalizes_cluster_qualified_job_id(tmp_path: Path) -> None:
    environment, _calls, jobid_file = _launcher_environment(tmp_path)
    environment["SBATCH_RESULT"] = "2000002;cluster"
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "1579999"],
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert jobid_file.read_text() == "2000002\n"
    assert json.loads(completed.stdout)["job_id"] == 2000002


def test_launcher_rejects_successful_looking_sacct_output_with_failure(
    tmp_path: Path,
) -> None:
    environment, calls, jobid_file = _launcher_environment(tmp_path)
    sacct = Path(environment["PATH"].split(":", 1)[0]) / "sacct"
    _write_executable(
        sacct,
        "#!/bin/bash\nprintf '%s\\n' '1579999|COMPLETED|0:0'\nexit 17\n",
    )

    completed = subprocess.run(
        ["bash", str(LAUNCHER), "1579999"],
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stderr) == {
        "code": "postrun_job_accounting_invalid",
        "state": "error",
    }
    assert not calls.exists()
    assert not jobid_file.exists()
    assert not Path(f"{jobid_file}.lock").exists()


def test_launcher_term_during_submission_stops_and_preserves_reservation(tmp_path: Path) -> None:
    environment, calls, jobid_file = _launcher_environment(tmp_path)
    environment["SBATCH_SLEEP"] = "0.5"
    process = subprocess.Popen(
        ["bash", str(LAUNCHER), "1579999"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _attempt in range(100):
        if calls.exists():
            break
        time.sleep(0.01)
    assert calls.exists()
    process.terminate()
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 143
    assert stdout == ""
    assert stderr == ""
    assert not jobid_file.exists()
    assert Path(f"{jobid_file}.lock").is_dir()


def test_package_scripts_use_terminating_signal_handlers() -> None:
    for script in (PACKAGER, LAUNCHER):
        body = script.read_text()
        assert "trap cleanup EXIT INT TERM" not in body
        assert "trap cleanup EXIT\n" in body
        assert "trap 'exit 130' INT\n" in body
        assert "trap 'exit 143' TERM\n" in body


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("QWEN_V6_PACKAGE_CHUNK_BYTES", "95000000,INJECTED=value"),
        ("QWEN_V6_PACKAGE_ZSTD_LEVEL", "20"),
    ],
)
def test_launcher_rejects_unsafe_optional_exports(
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    environment, calls, jobid_file = _launcher_environment(tmp_path)
    environment[name] = value
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "1579999"],
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stderr) == {
        "code": "package_configuration_invalid",
        "state": "error",
    }
    assert not calls.exists()
    assert not jobid_file.exists()
