from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
import qwen_2499_error_retry as retry


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _write_private(path: Path, body: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(0o600)


def _trace(slug: str, index: int, outcome: str) -> dict:
    value = {
        "id": f"trace-{slug}",
        "task": {"idx": index, "name": f"suite/{slug}"},
        "errors": [],
        "rewards": {"solved": 0},
        "is_completed": True,
        "stop_condition": "synthetic_complete",
    }
    if outcome == "positive":
        value["rewards"] = {"solved": 1}
    elif outcome == "error":
        value["errors"] = [{"type": "SyntheticError", "message": "private"}]
        value["rewards"] = {}
        value.pop("is_completed")
        value.pop("stop_condition")
    return value


def _jsonl(rows: list[dict]) -> bytes:
    return b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows)


def _template() -> bytes:
    path = Path(__file__).resolve().parents[1] / "configs/eval/shared_qwen38_2p4t/qwen_2499_error_retry_sandoq_firecracker.template.toml"
    text = path.read_text().replace("num_tasks = 64", f"num_tasks = {retry.ERROR_RETRY_COUNT}", 1)
    return text.encode()


def _profile() -> bytes:
    return retry._canonical_json(
        {
            "base_url": "https://sandoq.eks-prod.cf.aws.metafb.cloud",
            "cluster_identifier": "use2",
            "effective_task_network": "public",
            "environment": "oci-runner-firecracker-small",
            "provider_token_file": "/private/token",
            "schema_version": 3,
            "task_network": "host",
            "transport_mode": "auto",
        }
    )


def _certificate(continuation_results: bytes) -> bytes:
    value = {
        "schema_version": 1,
        "kind": "qwen-sandoq-source-continuation-pass-only",
        "state": "passed",
        "certification_scope": "pass-only-positive-trace-eligibility",
        "all_outcomes_trainability_claimed": False,
        "run": {
            "task_count": retry.CONTINUATION_TRACE_COUNT,
            "task_file_sha256": retry.CONTINUATION_TASK_FILE_SHA256,
            "results": {"bytes": len(continuation_results), "sha256": _sha256(continuation_results)},
        },
        "coverage_audit": {
            "input_traces": retry.CONTINUATION_TRACE_COUNT,
            "covered_tasks": retry.CONTINUATION_TRACE_COUNT,
            "error_traces_nonexported": retry.ERROR_RETRY_COUNT,
            "positive_reward_traces": retry.CONTINUATION_POSITIVE_COUNT,
            "positive_traces_trainable": retry.CONTINUATION_POSITIVE_COUNT,
            "zero_reward_traces_nonexported": retry.CONTINUATION_ZERO_COUNT,
            "exact_task_coverage": True,
            "results": {"bytes": len(continuation_results), "sha256": _sha256(continuation_results)},
        },
        "lineage": {
            "selection": {"task_file_sha256": retry.CONTINUATION_TASK_FILE_SHA256},
            "epoch3_source": {
                "artifacts": {
                    "results.jsonl": {"sha256": retry.ORIGINAL_RESULTS_SHA256},
                    "inputs/task_file.txt": {"sha256": retry.CANONICAL_SOURCE_TASK_FILE_SHA256},
                }
            },
        },
        "merge_contract": {
            "canonical_sandoq_coverage_tasks": retry.CANONICAL_UNIVERSE_COUNT,
            "continuation_coverage_tasks": retry.CONTINUATION_TRACE_COUNT,
            "retained_coverage_tasks": retry.RETAINED_ORIGINAL_COUNT,
            "disjoint_coverage": True,
            "exhaustive_coverage": True,
            "original_order_required": True,
        },
    }
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path | str]:
    tmp_path.chmod(0o700)
    original_rows = [
        _trace("a", 0, "positive"),
        _trace("b", 1, "error"),
        _trace("c", 2, "zero"),
        _trace("hidden", 3, "zero"),
    ]
    continuation_rows = [_trace("b", 0, "error"), _trace("d", 1, "positive")]
    original_body = _jsonl(original_rows)
    continuation_body = _jsonl(continuation_rows)
    continuation_tasks = b"b\nd\n"
    universe_tasks = b"a\nb\nc\nd\n"

    monkeypatch.setattr(retry, "CANONICAL_SOURCE_COUNT", 5)
    monkeypatch.setattr(retry, "CANONICAL_UNIVERSE_COUNT", 4)
    monkeypatch.setattr(retry, "ORIGINAL_TRACE_COUNT", 4)
    monkeypatch.setattr(retry, "CONTINUATION_TRACE_COUNT", 2)
    monkeypatch.setattr(retry, "RETAINED_ORIGINAL_COUNT", 2)
    monkeypatch.setattr(retry, "ORIGINAL_CONTINUATION_OVERLAP_COUNT", 1)
    monkeypatch.setattr(retry, "ERROR_RETRY_COUNT", 1)
    monkeypatch.setattr(retry, "BASE_POSITIVE_COUNT", 2)
    monkeypatch.setattr(retry, "BASE_ZERO_COUNT", 1)
    monkeypatch.setattr(retry, "BASE_ERROR_COUNT", 1)
    monkeypatch.setattr(retry, "CONTINUATION_POSITIVE_COUNT", 1)
    monkeypatch.setattr(retry, "CONTINUATION_ZERO_COUNT", 0)
    monkeypatch.setattr(retry, "CONTINUATION_RESULTS_BYTES", len(continuation_body))
    monkeypatch.setattr(retry, "ORIGINAL_RESULTS_SHA256", _sha256(original_body))
    monkeypatch.setattr(retry, "CONTINUATION_RESULTS_SHA256", _sha256(continuation_body))
    monkeypatch.setattr(retry, "CONTINUATION_TASK_FILE_SHA256", _sha256(continuation_tasks))
    monkeypatch.setattr(retry, "CANONICAL_UNIVERSE_TASK_FILE_SHA256", _sha256(universe_tasks))

    original = tmp_path / "original.jsonl"
    continuation = tmp_path / "continuation.jsonl"
    continuation_task_file = tmp_path / "continuation.tasks"
    universe = tmp_path / "universe.tasks"
    certificate = tmp_path / "predecessor.json"
    template = tmp_path / "template.toml"
    profile = tmp_path / "profile.json"
    for path, body in (
        (original, original_body),
        (continuation, continuation_body),
        (continuation_task_file, continuation_tasks),
        (universe, universe_tasks),
    ):
        _write_private(path, body)
    certificate_body = _certificate(continuation_body)
    _write_private(certificate, certificate_body)
    monkeypatch.setattr(retry, "CONTINUATION_CERTIFICATE_SHA256", _sha256(certificate_body))
    template_body = _template()
    template.write_bytes(template_body)
    profile_body = _profile()
    profile.write_bytes(profile_body)
    monkeypatch.setattr(retry, "RETRY_CONFIG_TEMPLATE_SHA256", _sha256(template_body))
    monkeypatch.setattr(retry, "RETRY_PROVIDER_PROFILE_SHA256", _sha256(profile_body))
    expected_run = tmp_path / "run"
    output = tmp_path / "selection"
    result = retry.select(
        original_results=original,
        original_results_sha256=_sha256(original_body),
        continuation_results=continuation,
        continuation_results_sha256=_sha256(continuation_body),
        continuation_certificate=certificate,
        continuation_certificate_sha256=_sha256(certificate_body),
        continuation_task_file=continuation_task_file,
        continuation_task_file_sha256=_sha256(continuation_tasks),
        canonical_universe_task_file=universe,
        canonical_universe_task_file_sha256=_sha256(universe_tasks),
        config_template=template,
        config_template_sha256=_sha256(template_body),
        provider_profile=profile,
        provider_profile_sha256=_sha256(profile_body),
        expected_run_dir=expected_run,
        output_dir=output,
    )
    return {
        "certificate": certificate,
        "config": output / retry.CONFIG_FILENAME,
        "continuation": continuation,
        "continuation_task_file": continuation_task_file,
        "contract": output / retry.SELECTION_FILENAME,
        "contract_sha256": result["contract_sha256"],
        "expected_run": expected_run,
        "original": original,
        "output": output,
        "profile": profile,
        "task_file": output / retry.TASK_FILENAME,
        "template": template,
        "universe": universe,
    }


def test_select_is_exact_private_and_identifier_blind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    output = fixture["output"]
    assert isinstance(output, Path)
    assert (output / retry.TASK_FILENAME).read_bytes() == b"b\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    for name in (retry.TASK_FILENAME, retry.CONFIG_FILENAME, retry.SELECTION_FILENAME):
        assert stat.S_IMODE((output / name).stat().st_mode) == 0o600
    manifest_body = (output / retry.SELECTION_FILENAME).read_bytes()
    manifest = json.loads(manifest_body)
    assert manifest["selection"]["count"] == 1
    assert manifest["canonical_coverage"]["canonical_universe_count"] == 4
    assert manifest["privacy"]["excluded_singleton_disclosed"] is False
    assert manifest["execution"]["sandbox"] == {
        "environment": "oci-runner-firecracker-small",
        "provider": "sandoq",
        "resource_caps": {
            "cpu": 2,
            "memory_mb": 4_096,
            "policy": "min-declared-and-provider-cap",
            "storage_mb": 10_240,
        },
        "task_network": "public",
    }
    assert manifest["trace_contract"]["require_exact_provider_json"] is True
    assert all(identifier not in manifest_body.decode() for identifier in ("trace-a", "suite/a", "hidden"))

    summary = retry.verify_launch(
        contract=fixture["contract"],
        contract_sha256=fixture["contract_sha256"],
        task_file=fixture["task_file"],
        task_file_sha256=_sha256((output / retry.TASK_FILENAME).read_bytes()),
        config=fixture["config"],
        config_sha256=_sha256((output / retry.CONFIG_FILENAME).read_bytes()),
        provider_profile=fixture["profile"],
        provider_profile_sha256=_sha256(fixture["profile"].read_bytes()),
        run_dir=fixture["expected_run"],
    )
    assert summary["state"] == "launch-verified"
    assert summary["retry_count"] == 1
    assert '"b"' not in json.dumps(summary)


def _select_again(
    fixture: dict[str, Path | str],
    *,
    template: Path,
    profile: Path,
    output: Path,
) -> dict[str, object]:
    return retry.select(
        original_results=fixture["original"],
        original_results_sha256=retry.ORIGINAL_RESULTS_SHA256,
        continuation_results=fixture["continuation"],
        continuation_results_sha256=retry.CONTINUATION_RESULTS_SHA256,
        continuation_certificate=fixture["certificate"],
        continuation_certificate_sha256=retry.CONTINUATION_CERTIFICATE_SHA256,
        continuation_task_file=fixture["continuation_task_file"],
        continuation_task_file_sha256=retry.CONTINUATION_TASK_FILE_SHA256,
        canonical_universe_task_file=fixture["universe"],
        canonical_universe_task_file_sha256=retry.CANONICAL_UNIVERSE_TASK_FILE_SHA256,
        config_template=template,
        config_template_sha256=_sha256(template.read_bytes()),
        provider_profile=profile,
        provider_profile_sha256=_sha256(profile.read_bytes()),
        expected_run_dir=fixture["expected_run"],
        output_dir=output,
    )


def test_selection_rejects_caller_rehashed_template_and_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    template = fixture["template"]
    profile = fixture["profile"]
    assert isinstance(template, Path) and isinstance(profile, Path)
    altered_template = tmp_path / "altered-template.toml"
    altered_profile = tmp_path / "altered-profile.json"
    altered_template.write_bytes(template.read_bytes() + b"\n# unreviewed drift\n")
    altered_profile.write_bytes(profile.read_bytes() + b"\n")
    monkeypatch.setattr(
        retry,
        "_scan_results",
        lambda *_args, **_kwargs: pytest.fail("pinned-input drift reached result scanning"),
    )

    with pytest.raises(retry.QwenRetryError, match="^config_template_digest_invalid$"):
        _select_again(
            fixture,
            template=altered_template,
            profile=profile,
            output=tmp_path / "altered-template-output",
        )
    with pytest.raises(retry.QwenRetryError, match="^provider_profile_digest_invalid$"):
        _select_again(
            fixture,
            template=template,
            profile=altered_profile,
            output=tmp_path / "altered-profile-output",
        )


def test_selection_rejects_inline_task_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    template = fixture["template"]
    profile = fixture["profile"]
    assert isinstance(template, Path) and isinstance(profile, Path)
    altered = tmp_path / "inline-tasks-template.toml"
    altered.write_text(template.read_text().replace("[taskset]\n", '[taskset]\ntasks = ["opaque-extra"]\n', 1))
    monkeypatch.setattr(retry, "RETRY_CONFIG_TEMPLATE_SHA256", _sha256(altered.read_bytes()))

    with pytest.raises(retry.QwenRetryError, match="^retry_config_contract_invalid$"):
        _select_again(
            fixture,
            template=altered,
            profile=profile,
            output=tmp_path / "inline-tasks-output",
        )


def test_verify_launch_rejects_stale_run_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    run = fixture["expected_run"]
    assert isinstance(run, Path)
    run.mkdir(mode=0o700)
    _write_private(run / "results.jsonl", b"stale\n")
    with pytest.raises(retry.QwenRetryError, match="^run_dir_not_fresh$"):
        retry.verify_launch(
            contract=fixture["contract"],
            contract_sha256=fixture["contract_sha256"],
            task_file=fixture["task_file"],
            task_file_sha256=_sha256(fixture["task_file"].read_bytes()),
            config=fixture["config"],
            config_sha256=_sha256(fixture["config"].read_bytes()),
            provider_profile=fixture["profile"],
            provider_profile_sha256=_sha256(fixture["profile"].read_bytes()),
            run_dir=run,
        )


def test_verify_launch_allows_only_sealed_outer_wrapper_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    run = fixture["expected_run"]
    assert isinstance(run, Path)
    run.mkdir(mode=0o700)
    (run / "control").mkdir(mode=0o700)
    for name in (".direct_router.lock", "direct_router.log", "direct_workers.json"):
        _write_private(run / name, b"sealed\n")
    arguments = {
        "contract": fixture["contract"],
        "contract_sha256": fixture["contract_sha256"],
        "task_file": fixture["task_file"],
        "task_file_sha256": _sha256(fixture["task_file"].read_bytes()),
        "config": fixture["config"],
        "config_sha256": _sha256(fixture["config"].read_bytes()),
        "provider_profile": fixture["profile"],
        "provider_profile_sha256": _sha256(fixture["profile"].read_bytes()),
        "run_dir": run,
    }
    with pytest.raises(retry.QwenRetryError, match="^run_dir_not_fresh$"):
        retry.verify_launch(**arguments)
    assert retry.verify_launch(**arguments, allow_wrapper_artifacts=True)["state"] == "launch-verified"

    _write_private(run / "results.jsonl", b"stale\n")
    with pytest.raises(retry.QwenRetryError, match="^run_dir_not_fresh$"):
        retry.verify_launch(**arguments, allow_wrapper_artifacts=True)


def test_certify_and_merge_replace_only_trainable_positive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    run = fixture["expected_run"]
    assert isinstance(run, Path)
    run.mkdir(mode=0o700)
    _write_private(run / ".writer.lock", b"")
    _write_private(run / "sandoq_cleanup_audit.json", b"{}\n")
    retry_body = _jsonl([_trace("b", 0, "positive")])
    _write_private(run / "results.jsonl", retry_body)
    retry_scan = retry.TraceScan(
        artifact=retry.Artifact(len(retry_body), _sha256(retry_body)),
        rows={"b": retry.TraceRecord(0, len(retry_body), _sha256(retry_body), "positive")},
        counts={"positive": 1},
    )
    evidence = {
        "cleanup": {"bytes": 1, "path": str(run / "sandoq_cleanup_audit.json"), "sha256": "1" * 64},
        "eval_run_identity": {"bytes": 1, "path": str(run / "eval_run_identity.json"), "sha256": "2" * 64},
        "resolved_config": {"bytes": 1, "path": str(run / "config.toml"), "sha256": "3" * 64},
        "results": retry_scan.artifact.value(path=run / "results.jsonl"),
        "worker_manifest": {"bytes": 1, "path": str(run / "direct_workers.json"), "sha256": "4" * 64},
    }
    runtime = {
        "cleanup_failures": 0,
        "eval_run_identity_sha256": "5" * 64,
        "provider_concurrency": 32,
        "router_policy": "consistent_hash",
        "worker_count": 24,
    }
    monkeypatch.setattr(retry, "_run_evidence", lambda *_args, **_kwargs: (retry_scan, evidence, runtime))
    retry_certificate_path = run / retry.RETRY_CERTIFICATE_FILENAME
    certified = retry.certify(
        contract=fixture["contract"],
        contract_sha256=fixture["contract_sha256"],
        run_dir=run,
        cleanup_audit=run / "sandoq_cleanup_audit.json",
        output=retry_certificate_path,
    )
    assert certified["accepted_positive"] == 1
    assert certified["retained_original"] == 0

    merged = tmp_path / "merged"
    summary = retry.merge(
        contract=fixture["contract"],
        contract_sha256=fixture["contract_sha256"],
        retry_certificate=retry_certificate_path,
        retry_certificate_sha256=certified["certificate_sha256"],
        run_dir=run,
        output_dir=merged,
    )
    assert summary == {
        "certificate_sha256": _sha256((merged / retry.MERGED_CERTIFICATE_FILENAME).read_bytes()),
        "error": 0,
        "manifest_sha256": _sha256((merged / retry.MERGE_MANIFEST_FILENAME).read_bytes()),
        "positive": 3,
        "state": "merged",
        "task_count": 4,
        "zero": 1,
    }
    rows = [json.loads(line) for line in (merged / retry.MERGED_RESULTS_FILENAME).read_text().splitlines()]
    assert [row["task"]["name"] for row in rows] == ["suite/a", "suite/b", "suite/c", "suite/d"]
    assert rows[1]["rewards"] == {"solved": 1}
    manifest = json.loads((merged / retry.MERGE_MANIFEST_FILENAME).read_bytes())
    assert manifest["package_inputs"]["results"]["sha256"] == summary["certificate_sha256"] or (
        manifest["package_inputs"]["results"]["sha256"]
        == _sha256((merged / retry.MERGED_RESULTS_FILENAME).read_bytes())
    )
    assert manifest["package_inputs"]["certificate"]["sha256"] == summary["certificate_sha256"]
    assert manifest["sft_export_inputs"]["task_count"] == 4
    for path in merged.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_retry_positive_that_is_not_trainable_is_not_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "retry.jsonl"
    body = _jsonl([_trace("only", 0, "positive")])
    _write_private(path, body)
    monkeypatch.setattr(retry, "_positive_trace_is_trainable", lambda _trace: False)
    scan = retry._scan_results(
        path,
        expected_sha256=_sha256(body),
        expected_count=1,
        evaluator_order=("only",),
        validate_positive=True,
        allowed_members=frozenset({"only"}),
    )
    assert scan.counts == {"invalid_positive": 1}


def test_positive_validation_requires_exact_provider_json(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def audit(_trace, **kwargs):
        observed.update(kwargs)
        return ["normalized_stream_response_disallowed"]

    monkeypatch.setattr(retry.audit_traces, "_audit_trace", audit)
    assert retry._positive_trace_is_trainable({}) is False
    assert observed["require_exact_provider_json"] is True
    assert observed["model_io_contract"] == retry.RETRY_MODEL_IO_CONTRACT


def test_pinned_source_hash_cannot_be_substituted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    with pytest.raises(retry.QwenRetryError, match="^original_results_digest_invalid$"):
        retry.select(
            original_results=fixture["original"],
            original_results_sha256="0" * 64,
            continuation_results=Path("/not/reached"),
            continuation_results_sha256=retry.CONTINUATION_RESULTS_SHA256,
            continuation_certificate=fixture["certificate"],
            continuation_certificate_sha256=retry.CONTINUATION_CERTIFICATE_SHA256,
            continuation_task_file=Path("/not/reached"),
            continuation_task_file_sha256=retry.CONTINUATION_TASK_FILE_SHA256,
            canonical_universe_task_file=Path("/not/reached"),
            canonical_universe_task_file_sha256=retry.CANONICAL_UNIVERSE_TASK_FILE_SHA256,
            config_template=Path("/not/reached"),
            config_template_sha256="0" * 64,
            provider_profile=Path("/not/reached"),
            provider_profile_sha256="0" * 64,
            expected_run_dir=Path("/not/reached"),
            output_dir=tmp_path / "not-created",
        )
