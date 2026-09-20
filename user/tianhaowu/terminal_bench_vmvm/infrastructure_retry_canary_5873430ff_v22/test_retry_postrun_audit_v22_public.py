#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import stat
import subprocess
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
AUDITOR_PATH = ROOT / "audit_infrastructure_retry_canary_v22.py"
LAUNCHER_PATH = ROOT / "launch_infrastructure_retry_canary_v22.py"


def load_auditor():
    canonical_root = Path(
        "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/"
        "infrastructure_retry_canary_5873430ff_v22"
    )
    if ROOT != canonical_root:
        module = types.ModuleType("retry_v22_auditor_public_test")
        module.__file__ = str(AUDITOR_PATH)
        source = (
            AUDITOR_PATH.read_text(encoding="utf-8")
            .replace(
                'BASE / "oracle/infrastructure_retry_canary_5873430ff_v22"',
                f'Path({str(ROOT)!r})',
                1,
            )
            .replace(
                "or stat.S_IMODE(before.st_mode) != 0o500",
                "or stat.S_IMODE(before.st_mode) not in {0o500, 0o700}",
                1,
            )
        )
        exec(compile(source, str(AUDITOR_PATH), "exec"), module.__dict__)  # noqa: S102
        module.LAUNCH.ARTIFACT_ROOT = ROOT
        module.LAUNCH.CANONICAL_SELF = LAUNCHER_PATH
        module.LAUNCH.GENERATOR = ROOT / "build_infrastructure_retry_selection_v22.py"
        module.LAUNCH.JOB_WRAPPER = ROOT / "run_infrastructure_retry_canary_v22.sbatch"
        module.LAUNCH.PACKAGING_SNAPSHOT = (
            ROOT / "packaging-26.3-py3-none-any.whl.snapshot.json"
        )
        return module
    spec = importlib.util.spec_from_file_location(
        "retry_v22_auditor_public_test", AUDITOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(candidate_valid: int = 6, control_valid: int = 4):
    candidates = {f"candidate-{index:02d}" for index in range(15)}
    controls = {f"control-{index:02d}" for index in range(4)}
    candidate_rows = [
        {
            "slug": slug,
            "valid": index < candidate_valid,
            "reason": "valid" if index < candidate_valid else "invalid",
            "error_type": None,
            "attempts": 1,
            "infrastructure_failures": [],
        }
        for index, slug in enumerate(sorted(candidates))
    ]
    control_rows = [
        {
            "slug": slug,
            "valid": index < control_valid,
            "reason": "valid" if index < control_valid else "invalid",
            "error_type": None,
            "attempts": 1,
            "infrastructure_failures": [],
        }
        for index, slug in enumerate(sorted(controls))
    ]
    return [*candidate_rows, *control_rows], candidates, controls


def test_acceptance_requires_all_controls_and_six_candidates() -> None:
    auditor = load_auditor()
    result_rows, candidates, controls = rows()
    assert auditor.acceptance_counts(result_rows, candidates, controls) == {
        "selected": 19,
        "completed": 19,
        "candidates": 15,
        "controls": 4,
        "candidate_valid": 6,
        "control_valid": 4,
        "total_valid": 10,
    }
    with pytest.raises(auditor.AuditError, match="recovery_threshold_not_met"):
        low_rows, low_candidates, low_controls = rows(candidate_valid=5)
        auditor.acceptance_counts(low_rows, low_candidates, low_controls)
    with pytest.raises(auditor.AuditError, match="control_regression"):
        bad_rows, bad_candidates, bad_controls = rows(control_valid=3)
        auditor.acceptance_counts(bad_rows, bad_candidates, bad_controls)


def test_attempt_audit_distinguishes_sandbox_retries_from_timeout() -> None:
    auditor = load_auditor()
    observed = auditor.validate_attempt_rows(
        [
            {
                "reason": "valid",
                "error_type": None,
                "attempts": 2,
                "infrastructure_failures": [
                    {"attempt": 1, "error_type": "SandboxError", "error": "public"}
                ],
            },
            {
                "reason": "timeout",
                "error_type": "TimeoutError",
                "attempts": 1,
                "infrastructure_failures": [],
            },
            {
                "reason": "infrastructure_error",
                "error_type": "SandboxError",
                "attempts": 5,
                "infrastructure_failures": [
                    {"attempt": index, "error_type": "SandboxError", "error": "public"}
                    for index in range(1, 6)
                ],
            },
        ]
    )
    assert observed == {
        "rows_with_sandbox_retries": 2,
        "sandbox_error_events": 6,
        "final_asyncio_timeout_rows": 1,
        "maximum_attempts_observed": 5,
    }
    with pytest.raises(auditor.AuditError, match="result_attempt_policy_invalid"):
        auditor.validate_attempt_rows(
            [
                {
                    "reason": "timeout",
                    "error_type": "TimeoutError",
                    "attempts": 2,
                    "infrastructure_failures": [
                        {"attempt": 1, "error_type": "TimeoutError", "error": "public"}
                    ],
                }
            ]
        )


def test_atomic_publication_is_write_once_and_fsynced_shape(tmp_path: Path) -> None:
    auditor = load_auditor()
    target = tmp_path / "certificate.json"
    raw = json.dumps({"state": "passed"}, sort_keys=True).encode() + b"\n"
    assert auditor.atomic_publish(target, raw, 0o400) == hashlib.sha256(raw).hexdigest()
    assert target.read_bytes() == raw
    assert stat.S_IMODE(target.stat().st_mode) == 0o400
    with pytest.raises(auditor.AuditError, match="audit_publication_failed"):
        auditor.atomic_publish(target, raw, 0o400)


def test_auditor_pins_exact_launcher_and_never_authorizes_promotion() -> None:
    auditor = load_auditor()
    assert (
        hashlib.sha256(LAUNCHER_PATH.read_bytes()).hexdigest()
        == auditor.LAUNCHER_SHA256
    )
    source = AUDITOR_PATH.read_text(encoding="utf-8")
    assert '"automatic_union_or_promotion": False' in source
    assert '"all_controls_valid": True' in source
    assert '"minimum_candidate_recoveries": 6' in source
    assert '"minimum_valid": 10' in source
    assert '"state": "COMPLETED"' in source
    assert '"exit_code": "0:0"' in source
    assert '"authorization_file_sha256": launch["authorization_file_sha"]' in source
    assert '"activation_permit_sha256": launch["activation_permit_sha"]' in source
    assert '"x2p_environment_sha256": launch["x2p_sha256"]' in source
    assert '"verifiers_revision": LAUNCH.VERIFIERS_REVISION' in source
    assert '"vmvm_tb_v2_sha256": LAUNCH.VMVM_SHA256' in source
    assert '"scheduler_lifecycle": launch["scheduler_lifecycle"]' in source
    launch_validation = inspect.getsource(auditor.validate_launch_artifacts)
    assert "authorization_bytes" in launch_validation
    assert "activation_permit_bytes" in launch_validation
    assert '"held_validation": submission_lifecycle["held_validation"]' in launch_validation
    assert '"release": submission_lifecycle["release"]' in launch_validation
    assert "FAILURE_CERTIFICATE.exists()" in launch_validation
    assert "authorization_path.name" in launch_validation
    assert "activation_permit_path.name" in launch_validation
    assert "parse_private_x2p_environment" in launch_validation
    assert "x2p_environment_sha256" in launch_validation


def test_auditor_cross_pins_packaging_dependency_snapshot() -> None:
    auditor = load_auditor()
    assert auditor.PACKAGING_SNAPSHOT == auditor.LAUNCH.PACKAGING_SNAPSHOT
    assert auditor.PACKAGING_SNAPSHOT_SHA256 == (
        auditor.LAUNCH.PACKAGING_SNAPSHOT_SHA256
    )
    assert auditor.expected_packaging_provenance() == (
        auditor.LAUNCH.expected_packaging_provenance()
    )


@pytest.mark.skipif(
    ROOT
    != Path(
        "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/"
        "infrastructure_retry_canary_5873430ff_v22"
    ),
    reason="requires the frozen artifact and detached source snapshots",
)
def test_auditor_uses_transactional_exact_bytes_without_source_tree_pyc_reads() -> None:
    auditor = load_auditor()
    program = f"""
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('retry_v22_auditor_isolated', {str(AUDITOR_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
source_root = str(module.LAUNCH.SOURCE_ROOT)
opened = []
def audit_hook(event, args):
    if event == 'open' and args and isinstance(args[0], str):
        opened.append(args[0])
sys.addaudithook(audit_hook)
original_path = list(sys.path)
original_modules = dict(sys.modules)
for _ in range(2):
    with module.load_audit_modules() as (audit, builder):
        assert audit.__file__
        assert builder.__file__
    assert sys.path == original_path
    assert sys.modules == original_modules
assert not [path for path in opened if path.startswith(source_root) and path.endswith('.pyc')]
print('source_tree_pyc_opens=0')
"""
    result = subprocess.run(
        [str(auditor.PYTHON_REAL), "-I", "-B", "-c", program],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={
            "HOME": "/storage/home/tianhaowu",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        timeout=60,
    )
    assert result.returncode == 0
    assert result.stdout == b"source_tree_pyc_opens=0\n"
    assert result.stderr == b""


def test_auditor_module_scope_revalidates_source_on_exit(monkeypatch) -> None:
    auditor = load_auditor()
    events: list[str] = []

    class SelectionError(RuntimeError):
        pass

    @contextmanager
    def module_scope(_v1):
        events.append("enter")
        yield ("audit", "builder")
        events.append("exit")

    generator = type(
        "Generator",
        (),
        {
            "SelectionV22Error": SelectionError,
            "load_v1": staticmethod(lambda: events.append("load") or object()),
            "validate_execution_source": staticmethod(
                lambda _v1: events.append("validate")
            ),
            "snapshot_module_scope": staticmethod(module_scope),
        },
    )()
    monkeypatch.setattr(auditor.LAUNCH, "load_generator", lambda: generator)
    with auditor.load_audit_modules() as modules:
        events.append("body")
        assert modules == ("audit", "builder")
    assert events == ["load", "validate", "enter", "body", "exit", "validate"]


def test_final_locked_snapshot_mutation_prevents_pass_certificate(monkeypatch) -> None:
    auditor = load_auditor()
    sealed = False

    @contextmanager
    def held_lock():
        yield

    def forbidden_seal(*_args, **_kwargs):
        nonlocal sealed
        sealed = True
        raise AssertionError("pass certificate must not be attempted")

    monkeypatch.setattr(auditor, "output_lock", held_lock)
    monkeypatch.setattr(
        auditor,
        "output_snapshot",
        lambda: {
            "top_level_sha256": {"results.jsonl": "2" * 64},
            "task_status_count": 19,
            "task_status_tree_sha256": "3" * 64,
        },
    )
    monkeypatch.setattr(auditor, "seal_terminal", forbidden_seal)
    with pytest.raises(auditor.AuditError, match="output_changed_before_publication"):
        auditor.publish_after_final_revalidation(
            launch={"job_id": "1", "job_name": "mirc-" + "4" * 24},
            output={
                "artifact_snapshot": {
                    "top_level_sha256": {"results.jsonl": "1" * 64},
                    "task_status_count": 19,
                    "task_status_tree_sha256": "3" * 64,
                }
            },
            body={"state": "passed"},
        )
    assert sealed is False
