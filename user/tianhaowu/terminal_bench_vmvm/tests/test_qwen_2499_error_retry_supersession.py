from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import qwen_2499_error_retry as retry
import qwen_2499_error_retry_supersession as supersession


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _predecessor(evidence: dict, runtime: dict) -> dict:
    return {
        "accepted": {
            "canonical_indices_sha256": "1" * 64,
            "count": 0,
            "predicate": "reward-one-and-exact-model-io-and-sft-trainable",
            "row_sha256_set_sha256": "2" * 64,
        },
        "code": {"module_sha256": supersession.PREDECESSOR_RETRY_MODULE_SHA256},
        "kind": retry.RETRY_CERTIFICATE_KIND,
        "retry_outcomes": {
            "accepted_positive": 0,
            "error": 2,
            "invalid_positive": 3,
            "retained_original": 64,
            "total": 64,
            "zero": 59,
        },
        "run": evidence,
        "runtime": runtime,
        "schema_version": retry.SCHEMA_VERSION,
        "selection_contract_sha256": "3" * 64,
        "state": "passed",
        "trace_contract": {
            "id": retry.RETRY_MODEL_IO_CONTRACT_ID,
            "max_sequence_tokens": retry.MAX_SEQUENCE_TOKENS,
            "sha256": retry.audit_traces.model_io_contract_sha256(retry.RETRY_MODEL_IO_CONTRACT),
        },
    }


def test_predecessor_validation_binds_run_evidence() -> None:
    evidence = {"results": {"bytes": 1, "sha256": "4" * 64}}
    runtime = {"cleanup_failures": 0}
    value = _predecessor(evidence, runtime)

    supersession._validate_predecessor_value(
        value,
        contract_sha256="3" * 64,
        evidence=evidence,
        runtime=runtime,
    )

    tampered = copy.deepcopy(value)
    tampered["run"]["results"]["sha256"] = "5" * 64
    with pytest.raises(supersession.SupersessionError, match="^predecessor_certificate_invalid$"):
        supersession._validate_predecessor_value(
            tampered,
            contract_sha256="3" * 64,
            evidence=evidence,
            runtime=runtime,
        )


def test_predecessor_validation_requires_explicit_updated_producer_pin() -> None:
    evidence = {"results": {"bytes": 1, "sha256": "4" * 64}}
    runtime = {"cleanup_failures": 0}
    updated_sha256 = "9" * 64
    value = _predecessor(evidence, runtime)
    value["code"] = {"module_sha256": updated_sha256}

    with pytest.raises(supersession.SupersessionError, match="^predecessor_certificate_invalid$"):
        supersession._validate_predecessor_value(
            value,
            contract_sha256="3" * 64,
            evidence=evidence,
            runtime=runtime,
        )
    supersession._validate_predecessor_value(
        value,
        contract_sha256="3" * 64,
        evidence=evidence,
        runtime=runtime,
        expected_retry_module_sha256=updated_sha256,
    )


def test_project_code_pins_superseding_exporter_and_auditor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[4]
    revision = "a" * 40
    submodule_revision = "b" * 40

    def fake_git(path: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(project)
        if arguments == ("rev-parse", "HEAD"):
            return revision if path == project else submodule_revision
        if arguments == ("status", "--porcelain=v1", "--untracked-files=all"):
            return ""
        if arguments[:3] == ("ls-tree", "HEAD", "--"):
            relative = arguments[3]
            return f"160000 commit {submodule_revision}\t{relative}"
        raise AssertionError(arguments)

    monkeypatch.setattr(supersession, "_git", fake_git)
    retry_sha256 = hashlib.sha256(
        (project / "user/tianhaowu/terminal_bench_vmvm/qwen_2499_error_retry.py").read_bytes()
    ).hexdigest()
    code = supersession._project_code(
        project,
        revision,
        expected_retry_module_sha256=retry_sha256,
    )
    assert code["exporter_sha256"] == supersession.SUPERSEDING_EXPORTER_SHA256
    assert code["audit_traces_sha256"] == supersession.AUDIT_TRACES_SHA256

    monkeypatch.setattr(supersession, "SUPERSEDING_EXPORTER_SHA256", "0" * 64)
    with pytest.raises(supersession.SupersessionError, match="^project_code_invalid$"):
        supersession._project_code(
            project,
            revision,
            expected_retry_module_sha256=retry_sha256,
        )


def test_frozen_replay_rejects_structurally_consistent_predecessor_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "predecessor-project"
    workflow = project / "user" / "tianhaowu" / "terminal_bench_vmvm"
    workflow.mkdir(parents=True)
    for relative in ("deps/verifiers", "deps/renderers", "deps/pydantic-config/src", "environments/vmvm_tb_v2"):
        (project / relative).mkdir(parents=True)
    for name in ("qwen_2499_error_retry.py", "export_sft.py", "audit_traces.py"):
        (workflow / name).write_bytes(name.encode())

    evidence = {"results": {"bytes": 1, "sha256": "4" * 64}}
    runtime = {"cleanup_failures": 0}
    predecessor = _predecessor(evidence, runtime)
    original_body = retry._canonical_json(predecessor)
    certificate = tmp_path / "predecessor.json"
    certificate.write_bytes(original_body)
    certificate.chmod(0o600)
    original_sha256 = hashlib.sha256(original_body).hexdigest()

    def fake_git(path: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "--show-toplevel"):
            return str(project)
        if arguments == ("rev-parse", "HEAD"):
            if path == project:
                return supersession.PREDECESSOR_REPOSITORY_REVISION
            relative = path.relative_to(project).as_posix()
            return supersession.PREDECESSOR_SUBMODULES[relative]
        if arguments == ("status", "--porcelain=v1", "--untracked-files=all"):
            return ""
        if arguments[:3] == ("ls-tree", "HEAD", "--"):
            relative = arguments[3]
            return f"160000 commit {supersession.PREDECESSOR_SUBMODULES[relative]}\t{relative}"
        raise AssertionError((path, arguments))

    def fake_artifact(path: Path, _code: str, **_kwargs) -> retry.Artifact:
        values = {
            "qwen_2499_error_retry.py": supersession.PREDECESSOR_RETRY_MODULE_SHA256,
            "export_sft.py": supersession.PREDECESSOR_EXPORTER_SHA256,
            "audit_traces.py": supersession.AUDIT_TRACES_SHA256,
        }
        return retry.Artifact(path.stat().st_size, values[path.name])

    def frozen_replay(command: list[str], **_kwargs) -> subprocess.CompletedProcess[bytes]:
        observed = Path(command[-2]).read_bytes()
        supplied_sha256 = command[-1]
        if observed != original_body or supplied_sha256 != original_sha256:
            return subprocess.CompletedProcess(command, 2, b"", b"")
        summary = json.dumps(
            {"certificate_sha256": original_sha256, "state": "verified"},
            sort_keys=True,
        ).encode()
        return subprocess.CompletedProcess(command, 0, summary + b"\n", b"")

    monkeypatch.setattr(supersession, "_git", fake_git)
    monkeypatch.setattr(supersession.retry, "_artifact", fake_artifact)
    monkeypatch.setattr(supersession.subprocess, "run", frozen_replay)
    arguments = {
        "project_dir": project,
        "expected_project_revision": supersession.PREDECESSOR_REPOSITORY_REVISION,
        "contract": tmp_path / "selection.json",
        "contract_sha256": "3" * 64,
        "run_dir": tmp_path / "run",
        "predecessor_certificate": certificate,
        "predecessor_certificate_sha256": original_sha256,
    }
    supersession._validate_predecessor_with_frozen_code(**arguments)

    tampered = copy.deepcopy(predecessor)
    tampered["accepted"]["count"] = 1
    tampered["retry_outcomes"]["accepted_positive"] = 1
    tampered["retry_outcomes"]["invalid_positive"] = 2
    tampered["retry_outcomes"]["retained_original"] = 63
    supersession._validate_predecessor_value(
        tampered,
        contract_sha256="3" * 64,
        evidence=evidence,
        runtime=runtime,
    )
    tampered_body = retry._canonical_json(tampered)
    certificate.write_bytes(tampered_body)
    arguments["predecessor_certificate_sha256"] = hashlib.sha256(tampered_body).hexdigest()
    with pytest.raises(supersession.SupersessionError, match="^predecessor_replay_failed$"):
        supersession._validate_predecessor_with_frozen_code(**arguments)


def _wire_trace(*, nullable_value: object = None) -> dict:
    tool = {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "run command",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    request_body = {
        "model": "synthetic",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
        ],
        "tools": [tool],
    }
    raw_message = {
        "role": "assistant",
        "content": "answer",
        "reasoning": "retained reasoning",
        "annotations": nullable_value,
        "audio": None,
        "function_call": None,
        "refusal": None,
    }
    response_body = {
        "id": "synthetic",
        "object": "chat.completion",
        "created": 1,
        "model": "synthetic",
        "choices": [{"index": 0, "message": raw_message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
    }
    return {
        "id": "synthetic-trace",
        "task": {"idx": 0, "name": "suite/synthetic", "slug": "synthetic"},
        "nodes": [
            {
                "parent": None,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "system", "content": "system"},
            },
            {
                "parent": 0,
                "sampled": False,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "message": {"role": "user", "content": "question"},
            },
            {
                "parent": 1,
                "sampled": True,
                "token_ids": [],
                "mask": [],
                "logprobs": [],
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "retained reasoning",
                },
                "usage": {"prompt_tokens": 2, "completion_tokens": 2},
                "model_io": {
                    "provider_route": "/chat/completions",
                    "request": {"kind": "full", "sha256": _sha256(request_body), "body": request_body},
                    "response": {
                        "kind": "exact_provider_json",
                        "sha256": _sha256(response_body),
                        "body": response_body,
                    },
                },
            },
        ],
        "rewards": {"solved": 1},
        "metrics": {},
        "info": {},
        "is_completed": True,
        "stop_condition": "agent_completed",
        "errors": [],
        "timing": {},
    }


def test_null_wire_field_positive_is_clean_but_nonnull_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supersession.audit_traces, "_audit_trace", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(supersession.export_sft, "_audit_trace", lambda *_args, **_kwargs: [])

    assert supersession._trace_is_trainable(_wire_trace(), 1.0) is True
    assert supersession._trace_is_trainable(_wire_trace(nullable_value="unexpected"), 1.0) is False


def test_merge_modes_keep_pass_only_and_unfiltered_acceptance_distinct() -> None:
    scan = retry.TraceScan(artifact=retry.Artifact(0, "0" * 64), rows={}, counts={})
    classification = supersession.Classification(
        scan=scan,
        positive=frozenset({"positive"}),
        zero=frozenset({"zero"}),
        invalid_positive=frozenset({"invalid-positive"}),
        invalid_zero=frozenset({"invalid-zero"}),
        error=frozenset({"error"}),
    )

    assert classification.accepted("pass-only") == frozenset({"positive"})
    assert classification.accepted("unfiltered") == frozenset({"positive", "zero"})
    assert classification.counts() == {
        "clean_model_bearing": 2,
        "error": 1,
        "invalid_positive": 1,
        "invalid_zero": 1,
        "positive": 1,
        "total": 5,
        "zero": 1,
    }


def _write_rows(path: Path, rows: list[dict]) -> tuple[bytes, dict[str, retry.TraceRecord]]:
    body = b""
    records: dict[str, retry.TraceRecord] = {}
    for row in rows:
        encoded = (json.dumps(row, sort_keys=True) + "\n").encode()
        slug = row["task"]["slug"]
        reward = row.get("rewards", {}).get("solved")
        outcome = "error" if row.get("errors") else "positive" if reward == 1 else "zero"
        records[slug] = retry.TraceRecord(len(body), len(encoded), hashlib.sha256(encoded).hexdigest(), outcome)
        body += encoded
    path.write_bytes(body)
    path.chmod(0o600)
    return body, records


def test_unfiltered_merge_replaces_clean_zero_while_pass_only_retains_base_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    original_path = tmp_path / "original.jsonl"
    continuation_path = tmp_path / "continuation.jsonl"
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    retry_path = run / "results.jsonl"
    original_body, original_records = _write_rows(
        original_path,
        [
            {"task": {"slug": "a"}, "errors": [], "rewards": {"solved": 1}},
            {"task": {"slug": "c"}, "errors": [], "rewards": {"solved": 0}},
        ],
    )
    continuation_body, continuation_records = _write_rows(
        continuation_path,
        [
            {"task": {"slug": "b"}, "errors": [{"type": "Synthetic"}], "rewards": {}},
            {"task": {"slug": "d"}, "errors": [], "rewards": {"solved": 1}},
        ],
    )
    retry_body, retry_records = _write_rows(
        retry_path,
        [{"task": {"slug": "b"}, "errors": [], "rewards": {"solved": 0}}],
    )
    context = retry.SelectionContext(
        original_results=original_path,
        continuation_results=continuation_path,
        continuation_certificate=tmp_path / "unused-certificate",
        continuation_task_file=tmp_path / "unused-continuation-tasks",
        canonical_universe_task_file=tmp_path / "unused-universe",
        config_template=tmp_path / "unused-template",
        provider_profile=tmp_path / "unused-profile",
        expected_run_dir=run,
        universe_members=("a", "b", "c", "d"),
        continuation_members=("b", "d"),
        retry_members=("b",),
        original_scan=retry.TraceScan(
            artifact=retry.Artifact(len(original_body), hashlib.sha256(original_body).hexdigest()),
            rows=original_records,
            counts={},
        ),
        continuation_scan=retry.TraceScan(
            artifact=retry.Artifact(len(continuation_body), hashlib.sha256(continuation_body).hexdigest()),
            rows=continuation_records,
            counts={},
        ),
        source_artifacts={},
        template_body=b"",
        profile_body=b"",
    )
    classification = supersession.Classification(
        scan=retry.TraceScan(
            artifact=retry.Artifact(len(retry_body), hashlib.sha256(retry_body).hexdigest()),
            rows=retry_records,
            counts={"zero": 1},
        ),
        positive=frozenset(),
        zero=frozenset({"b"}),
        invalid_positive=frozenset(),
        invalid_zero=frozenset(),
        error=frozenset(),
    )
    monkeypatch.setattr(retry, "CANONICAL_UNIVERSE_COUNT", 4)

    pass_output = tmp_path / "pass.jsonl"
    _pass_artifact, pass_counts = supersession._write_recovered_results(
        pass_output,
        context=context,
        classification=classification,
        accepted=classification.accepted("pass-only"),
    )
    unfiltered_output = tmp_path / "unfiltered.jsonl"
    _unfiltered_artifact, unfiltered_counts = supersession._write_recovered_results(
        unfiltered_output,
        context=context,
        classification=classification,
        accepted=classification.accepted("unfiltered"),
    )

    pass_rows = [json.loads(line) for line in pass_output.read_text().splitlines()]
    unfiltered_rows = [json.loads(line) for line in unfiltered_output.read_text().splitlines()]
    assert pass_counts == {"error": 1, "positive": 2, "zero": 1}
    assert unfiltered_counts == {"error": 0, "positive": 2, "zero": 2}
    assert pass_rows[1]["errors"]
    assert unfiltered_rows[1]["errors"] == []
    assert [row["task"]["slug"] for row in unfiltered_rows] == ["a", "b", "c", "d"]


def _integration_row(slug: str, index: int, outcome: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": f"trace-{slug}",
        "task": {"idx": index, "name": f"suite/{slug}", "slug": slug},
        "errors": [],
        "rewards": {"solved": 1 if outcome == "positive" else 0},
        "is_completed": True,
        "stop_condition": "agent_completed",
    }
    if outcome == "error":
        value["errors"] = [{"type": "SyntheticError", "message": "private"}]
        value["rewards"] = {}
        value.pop("is_completed")
        value.pop("stop_condition")
    return value


def test_certify_and_both_merges_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    (run / ".writer.lock").touch(mode=0o600)
    original_path = tmp_path / "original.jsonl"
    continuation_path = tmp_path / "continuation.jsonl"
    retry_path = run / "results.jsonl"
    original_body, original_records = _write_rows(
        original_path,
        [
            _integration_row("base-positive", 0, "positive"),
            _integration_row("base-zero", 1, "zero"),
        ],
    )
    continuation_body, continuation_records = _write_rows(
        continuation_path,
        [
            _integration_row("retry-positive", 0, "error"),
            _integration_row("retry-zero", 1, "error"),
            _integration_row("retry-error", 2, "error"),
        ],
    )
    retry_body, retry_records = _write_rows(
        retry_path,
        [
            _integration_row("retry-positive", 0, "positive"),
            _integration_row("retry-zero", 1, "zero"),
            _integration_row("retry-error", 2, "error"),
        ],
    )
    context = retry.SelectionContext(
        original_results=original_path,
        continuation_results=continuation_path,
        continuation_certificate=tmp_path / "unused-certificate",
        continuation_task_file=tmp_path / "unused-continuation-tasks",
        canonical_universe_task_file=tmp_path / "unused-universe",
        config_template=tmp_path / "unused-template",
        provider_profile=tmp_path / "unused-profile",
        expected_run_dir=run,
        universe_members=("base-positive", "retry-positive", "base-zero", "retry-zero", "retry-error"),
        continuation_members=("retry-positive", "retry-zero", "retry-error"),
        retry_members=("retry-positive", "retry-zero", "retry-error"),
        original_scan=retry.TraceScan(
            artifact=retry.Artifact(len(original_body), hashlib.sha256(original_body).hexdigest()),
            rows=original_records,
            counts={"positive": 1, "zero": 1},
        ),
        continuation_scan=retry.TraceScan(
            artifact=retry.Artifact(len(continuation_body), hashlib.sha256(continuation_body).hexdigest()),
            rows=continuation_records,
            counts={"error": 3},
        ),
        source_artifacts={},
        template_body=b"",
        profile_body=b"",
    )
    scan = retry.TraceScan(
        artifact=retry.Artifact(len(retry_body), hashlib.sha256(retry_body).hexdigest()),
        rows=retry_records,
        counts={"positive": 1, "zero": 1, "error": 1},
    )
    evidence = {"results": scan.artifact.value(path=retry_path)}
    runtime = {"cleanup_failures": 0}
    contract_sha256 = "3" * 64
    predecessor = _predecessor(evidence, runtime)
    predecessor["selection_contract_sha256"] = contract_sha256
    predecessor["retry_outcomes"] = {
        "accepted_positive": 0,
        "error": 1,
        "invalid_positive": 1,
        "retained_original": 3,
        "total": 3,
        "zero": 1,
    }
    predecessor_path = run / retry.RETRY_CERTIFICATE_FILENAME
    predecessor_body = retry._canonical_json(predecessor)
    predecessor_path.write_bytes(predecessor_body)
    predecessor_path.chmod(0o600)
    predecessor_sha256 = hashlib.sha256(predecessor_body).hexdigest()
    code = {
        "audit_traces_sha256": supersession.AUDIT_TRACES_SHA256,
        "exporter_sha256": supersession.SUPERSEDING_EXPORTER_SHA256,
        "qwen_2499_error_retry_sha256": supersession.PREDECESSOR_RETRY_MODULE_SHA256,
        "repository_revision": "a" * 40,
        "submodules": {"deps/renderers": "b" * 40, "deps/verifiers": "c" * 40},
        "supersession_module_sha256": "d" * 64,
    }
    monkeypatch.setattr(retry, "ERROR_RETRY_COUNT", 3)
    monkeypatch.setattr(retry, "CANONICAL_UNIVERSE_COUNT", 5)
    monkeypatch.setattr(retry, "CANONICAL_UNIVERSE_TASK_FILE_SHA256", "e" * 64)
    monkeypatch.setattr(retry, "BASE_POSITIVE_COUNT", 1)
    monkeypatch.setattr(retry, "BASE_ZERO_COUNT", 1)
    monkeypatch.setattr(retry, "BASE_ERROR_COUNT", 3)
    monkeypatch.setattr(
        supersession,
        "_load_context_and_run",
        lambda *_args, **_kwargs: ({}, context, scan, evidence, runtime),
    )
    monkeypatch.setattr(supersession, "_project_code", lambda *_args, **_kwargs: code)
    replay_calls = 0

    def assert_replay_lock_is_free(**_kwargs: object) -> None:
        nonlocal replay_calls
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDWR); "
                "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); os.close(fd)",
                str(run / ".writer.lock"),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert completed.returncode == 0
        replay_calls += 1

    monkeypatch.setattr(
        supersession,
        "_validate_predecessor_with_frozen_code",
        assert_replay_lock_is_free,
    )
    monkeypatch.setattr(
        supersession,
        "_trace_is_trainable",
        lambda trace, _reward: not bool(trace.get("errors")),
    )

    certificate_path = run / supersession.SUPERSEDING_CERTIFICATE_FILENAME
    summary = supersession.certify(
        contract=tmp_path / "selection.json",
        contract_sha256=contract_sha256,
        run_dir=run,
        predecessor_certificate=predecessor_path,
        predecessor_certificate_sha256=predecessor_sha256,
        predecessor_project_dir=tmp_path,
        expected_predecessor_project_revision=supersession.PREDECESSOR_REPOSITORY_REVISION,
        project_dir=tmp_path,
        expected_project_revision="a" * 40,
        output=certificate_path,
    )
    assert summary["state"] == "superseded"
    assert summary["positive"] == 1
    assert summary["zero"] == 1
    assert summary["error"] == 1
    certificate_sha256 = summary["superseding_certificate_sha256"]
    public = certificate_path.read_text()
    assert all(slug not in public for slug in context.retry_members)

    original_certificate_body = certificate_path.read_bytes()
    tampered = json.loads(original_certificate_body)
    tampered["outcomes"]["positive"] = 2
    tampered_body = supersession._json_bytes(tampered)
    certificate_path.write_bytes(tampered_body)
    with pytest.raises(supersession.SupersessionError, match="^superseding_certificate_evidence_mismatch$"):
        supersession.merge(
            contract=tmp_path / "selection.json",
            contract_sha256=contract_sha256,
            run_dir=run,
            predecessor_certificate=predecessor_path,
            predecessor_certificate_sha256=predecessor_sha256,
            predecessor_project_dir=tmp_path,
            expected_predecessor_project_revision=supersession.PREDECESSOR_REPOSITORY_REVISION,
            superseding_certificate=certificate_path,
            superseding_certificate_sha256=hashlib.sha256(tampered_body).hexdigest(),
            project_dir=tmp_path,
            expected_project_revision="a" * 40,
            mode="pass-only",
            output_dir=tmp_path / "tampered-output",
        )
    certificate_path.write_bytes(original_certificate_body)
    certificate_path.chmod(0o600)

    summaries = {}
    for mode in ("pass-only", "unfiltered"):
        output = tmp_path / mode
        summaries[mode] = supersession.merge(
            contract=tmp_path / "selection.json",
            contract_sha256=contract_sha256,
            run_dir=run,
            predecessor_certificate=predecessor_path,
            predecessor_certificate_sha256=predecessor_sha256,
            predecessor_project_dir=tmp_path,
            expected_predecessor_project_revision=supersession.PREDECESSOR_REPOSITORY_REVISION,
            superseding_certificate=certificate_path,
            superseding_certificate_sha256=certificate_sha256,
            project_dir=tmp_path,
            expected_project_revision="a" * 40,
            mode=mode,
            output_dir=output,
        )
        rows = [json.loads(line) for line in (output / supersession.RESULTS_FILENAME).read_text().splitlines()]
        assert [row["task"]["slug"] for row in rows] == list(context.universe_members)
        manifest = json.loads((output / supersession.MERGE_MANIFEST_FILENAME).read_bytes())
        recovered = json.loads((output / supersession.RECOVERED_CERTIFICATE_FILENAME).read_bytes())
        assert manifest["mode"] == mode
        assert recovered["mode"] == mode
        assert all(slug not in json.dumps({"summary": summaries[mode], "manifest": manifest, "certificate": recovered}) for slug in context.retry_members)

    assert summaries["pass-only"] == {
        "certificate_sha256": summaries["pass-only"]["certificate_sha256"],
        "error": 2,
        "manifest_sha256": summaries["pass-only"]["manifest_sha256"],
        "mode": "pass-only",
        "positive": 2,
        "replaced": 1,
        "state": "merged",
        "task_count": 5,
        "zero": 1,
    }
    assert summaries["unfiltered"]["error"] == 1
    assert summaries["unfiltered"]["positive"] == 2
    assert summaries["unfiltered"]["zero"] == 2
    assert summaries["unfiltered"]["replaced"] == 2
    assert replay_calls == 4


def test_certification_fails_closed_on_invalid_completed_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = object()
    scan = retry.TraceScan(artifact=retry.Artifact(0, "0" * 64), rows={}, counts={})
    evidence: dict[str, Any] = {}
    runtime: dict[str, Any] = {}
    predecessor = _predecessor(evidence, runtime)
    monkeypatch.setattr(
        supersession,
        "_load_context_and_run",
        lambda *_args, **_kwargs: ({}, context, scan, evidence, runtime),
    )
    monkeypatch.setattr(
        supersession,
        "_load_predecessor",
        lambda *_args, **_kwargs: (predecessor, retry.Artifact(1, "1" * 64)),
    )
    monkeypatch.setattr(
        supersession,
        "_validate_predecessor_with_frozen_code",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        supersession,
        "_classify_retry_rows",
        lambda *_args, **_kwargs: supersession.Classification(
            scan=scan,
            positive=frozenset(),
            zero=frozenset(),
            invalid_positive=frozenset({"private"}),
            invalid_zero=frozenset(),
            error=frozenset(),
        ),
    )

    with pytest.raises(supersession.SupersessionError, match="^retry_row_invalid$"):
        supersession._build_superseding_certificate(
            contract=tmp_path / "selection.json",
            contract_sha256="3" * 64,
            run_dir=tmp_path / "run",
            predecessor_certificate=tmp_path / "predecessor.json",
            predecessor_certificate_sha256="1" * 64,
            predecessor_project_dir=tmp_path,
            expected_predecessor_project_revision=supersession.PREDECESSOR_REPOSITORY_REVISION,
            project_dir=tmp_path,
            expected_project_revision="a" * 40,
        )
