from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import run_oracle_repair_canary_audit as controller

SOURCE_REVISION = "a" * 40
SOURCE_VERIFIERS_REVISION = "b" * 40
SOURCE_VMVM_SHA256 = "c" * 64
EXECUTION_REVISION = "d" * 40
EXECUTION_VERIFIERS_REVISION = "e" * 40
EXECUTION_VMVM_SHA256 = "f" * 64
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()


def _git(root: Path, *arguments: str) -> bytes:
    environment = {
        **os.environ,
        "GIT_AUTHOR_EMAIL": "tests@example.invalid",
        "GIT_AUTHOR_NAME": "Oracle Audit Tests",
        "GIT_COMMITTER_EMAIL": "tests@example.invalid",
        "GIT_COMMITTER_NAME": "Oracle Audit Tests",
    }
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        env=environment,
    ).stdout


def _write(path: Path, body: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(mode)


def _make_repository(
    tmp_path: Path,
    name: str,
    *,
    with_gitlink: bool = True,
    with_scripts: bool = False,
    launcher_body: bytes | None = None,
) -> tuple[Path, str, str | None]:
    root = tmp_path / name
    root.mkdir()
    _git(root, "init", "-q")
    _write(root / controller.SOURCE_VMVM_ROOT / "client.py", b"VALUE = 'one'\n", 0o644)
    _write(root / controller.SOURCE_VMVM_ROOT / "transport.py", b"VALUE = 'two'\n", 0o644)
    _write(root / "arbitrary_runtime.py", b"VALUE = 'runtime-one'\n", 0o644)
    (root / "runtime-link").symlink_to("arbitrary_runtime.py")
    if with_scripts:
        _write(root / controller.CONTROLLER_RELATIVE_PATH, b"# synthetic controller\n", 0o644)
        _write(root / controller.AUDITOR_RELATIVE_PATH, b"# synthetic auditor\n", 0o644)
        _write(root / controller.BUILDER_RELATIVE_PATH, b"# synthetic builder\n", 0o644)
        _write(root / controller.EXPORTER_RELATIVE_PATH, b"# synthetic exporter\n", 0o644)
        _write(root / controller.LAUNCHER_RELATIVE_PATH, launcher_body or b"#!/bin/bash\n", 0o755)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")

    verifier_revision: str | None = None
    if with_gitlink:
        verifier_origin = tmp_path / f"{name}-verifier-origin"
        verifier_origin.mkdir()
        _git(verifier_origin, "init", "-q")
        _write(verifier_origin / "verifier.py", b"VALUE = 'verifier'\n", 0o644)
        _git(verifier_origin, "add", ".")
        _git(verifier_origin, "commit", "-qm", "verifier")
        verifier_revision = _git(verifier_origin, "rev-parse", "HEAD").decode().strip()
        _git(
            root,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(verifier_origin),
            "deps/verifiers",
        )
        _git(root, "add", ".gitmodules", "deps/verifiers")
        _git(root, "commit", "-qm", "pin verifier")
        _git(root / "deps/verifiers", "checkout", "--detach", "-q", verifier_revision)

    revision = _git(root, "rev-parse", "HEAD").decode().strip()
    _git(root, "checkout", "--detach", "-q", revision)
    assert not _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    return root.resolve(), revision, verifier_revision


def _attestation(root: Path, *, source: bool) -> controller.CheckoutAttestation:
    metadata = root.stat()
    verifiers = root / "deps/verifiers"
    verifiers_metadata = verifiers.stat() if verifiers.exists() else metadata
    if source:
        revision = SOURCE_REVISION
        verifier_revision = SOURCE_VERIFIERS_REVISION
        vmvm = SOURCE_VMVM_SHA256
        tracked: tuple[tuple[str, str, str], ...] = ()
    else:
        revision = EXECUTION_REVISION
        verifier_revision = EXECUTION_VERIFIERS_REVISION
        vmvm = EXECUTION_VMVM_SHA256
        tracked = (
            (controller.AUDITOR_RELATIVE_PATH.as_posix(), "1" * 40, "2" * 64),
            (controller.BUILDER_RELATIVE_PATH.as_posix(), "7" * 40, "8" * 64),
            (controller.CONTROLLER_RELATIVE_PATH.as_posix(), "3" * 40, "4" * 64),
            (controller.EXPORTER_RELATIVE_PATH.as_posix(), "9" * 40, "0" * 64),
            (controller.LAUNCHER_RELATIVE_PATH.as_posix(), "5" * 40, "6" * 64),
        )
    return controller.CheckoutAttestation(
        root=root,
        root_device=metadata.st_dev,
        root_inode=metadata.st_ino,
        revision=revision,
        verifiers_revision=verifier_revision,
        verifiers_device=verifiers_metadata.st_dev,
        verifiers_inode=verifiers_metadata.st_ino,
        vmvm_tb_v2_sha256=vmvm,
        tracked_tree_sha256="7" * 64,
        tracked_entry_count=10,
        verifiers_tree_sha256="8" * 64,
        verifiers_entry_count=2,
        tracked_files=tracked,
    )


def _layout(
    tmp_path: Path,
) -> tuple[controller.ControllerOptions, controller.CheckoutAttestation, controller.CheckoutAttestation]:
    source_project = (tmp_path / "checkouts" / "source").resolve()
    execution_project = (tmp_path / "checkouts" / "execution").resolve()
    source_project.mkdir(parents=True)
    execution_project.mkdir(parents=True)
    source_oracle = (tmp_path / "oracle" / "source").resolve()
    canary = (tmp_path / "oracle" / "canary").resolve()
    source_oracle.mkdir(parents=True)
    canary.mkdir(parents=True)
    artifacts = (tmp_path / "private" / "builder").resolve()
    artifacts.mkdir(parents=True)
    receipt = artifacts / "receipt.json"
    task_file = artifacts / "tasks.txt"
    _write(receipt, b"opaque receipt\n")
    _write(task_file, b"opaque tasks\n")
    runtime_root = (tmp_path / "private" / "runtime").resolve()
    certificate_root = (tmp_path / "private" / "certificates").resolve()
    runtime_root.mkdir(parents=True)
    certificate_root.mkdir(parents=True)
    options = controller.ControllerOptions(
        source_project_dir=source_project,
        expected_source_revision=SOURCE_REVISION,
        execution_project_dir=execution_project,
        expected_execution_revision=EXECUTION_REVISION,
        source_oracle_dir=source_oracle,
        builder_receipt=receipt,
        task_file=task_file,
        canary_dir=canary,
        runtime_root=runtime_root,
        runtime_dir=runtime_root / "attempt",
        certificate_root=certificate_root,
        certificate=certificate_root / "certificate.json",
        expected_total=8,
        controls=2,
        minimum_recovered=2,
        seed="fixed-seed",
    )
    return options, _attestation(source_project, source=True), _attestation(execution_project, source=False)


def _source_contract(attestation: controller.CheckoutAttestation) -> dict[str, str]:
    return {
        "prime_rl_commit": attestation.revision,
        "prime_rl_tree_sha256": CLEAN_TREE_SHA256,
        "verifiers_commit": attestation.verifiers_revision,
        "vmvm_tb_v2_sha256": attestation.vmvm_tb_v2_sha256,
    }


def _child_output(
    staged_certificate: Path,
    source: controller.CheckoutAttestation,
    execution: controller.CheckoutAttestation,
    *,
    mutate_contract: tuple[str, str] | None = None,
    expected_source_wheel_policy_sha256: str | None = None,
    expected_source_wheel_attestations: int | None = None,
) -> controller.ChildResult:
    source_contract = _source_contract(source)
    execution_contract = _source_contract(execution)
    if mutate_contract is not None:
        target, key = mutate_contract
        contract = source_contract if target == "source" else execution_contract
        width = 40 if key.endswith("commit") else 64
        contract[key] = "9" * width
    audit = {
        "artifact_type": "terminal_bench_vmvm_oracle_repair_canary_audit",
        "contracts": {
            "canary_source": execution_contract,
            "source_oracle_source": source_contract,
        },
        "gates": {
            "expected_source_wheel_attestations": expected_source_wheel_attestations,
            "expected_source_wheel_policy_sha256": expected_source_wheel_policy_sha256,
        },
        "ok": True,
        "state": "passed",
    }
    audit_sha256 = controller._canonical_json_sha256(audit)
    envelope = {"audit": audit, "audit_sha256": audit_sha256, "schema_version": 1}
    _write(staged_certificate, controller._canonical_json_bytes(envelope))
    summary = {
        "audit_sha256": audit_sha256,
        "control_regressions": 0,
        "controls": 2,
        "minimum_recovered": 2,
        "ok": True,
        "published": True,
        "reason_counts": {},
        "recovered": 2,
        "repair_candidates": 3,
        "source_wheel_attestations": expected_source_wheel_attestations or 0,
        "state": "passed",
        "transitions": {},
        "unrecovered": 1,
    }
    return controller.ChildResult(0, controller._canonical_json_bytes(summary), b"")


def _validator(
    source: controller.CheckoutAttestation,
    execution: controller.CheckoutAttestation,
) -> controller.CheckoutValidator:
    def validate(root: Path, revision: str, role: str) -> controller.CheckoutAttestation:
        expected = source if role == "source" else execution
        assert root == expected.root
        assert revision == expected.revision
        return expected

    return validate


def _staged_certificate(command: list[str] | tuple[str, ...]) -> Path:
    return Path(command[6])


def test_controller_passes_all_six_independently_derived_pins_and_keeps_artifacts_private(tmp_path: Path) -> None:
    options, source, execution = _layout(tmp_path)
    observed_command: tuple[str, ...] | None = None

    def runner(command: Any, working_directory: Path) -> controller.ChildResult:
        nonlocal observed_command
        observed_command = tuple(command)
        assert working_directory == execution.root
        return _child_output(_staged_certificate(command), source, execution)

    summary = controller.run_controller(
        options,
        checkout_validator=_validator(source, execution),
        child_runner=runner,
    )

    assert observed_command is not None
    expected = {
        "--expected-source-prime-rl-commit": SOURCE_REVISION,
        "--expected-source-verifiers-commit": SOURCE_VERIFIERS_REVISION,
        "--expected-source-vmvm-tb-v2-sha256": SOURCE_VMVM_SHA256,
        "--expected-prime-rl-commit": EXECUTION_REVISION,
        "--expected-verifiers-commit": EXECUTION_VERIFIERS_REVISION,
        "--expected-vmvm-tb-v2-sha256": EXECUTION_VMVM_SHA256,
    }
    assert set(expected) == set(controller.PROVENANCE_FLAGS)
    for flag, value in expected.items():
        assert observed_command.count(flag) == 1
        assert observed_command[observed_command.index(flag) + 1] == value
    assert summary["ok"] is True
    assert summary["source"]["prime_rl_commit"] == SOURCE_REVISION
    assert summary["execution"]["prime_rl_commit"] == EXECUTION_REVISION
    assert stat.S_IMODE(options.runtime_dir.stat().st_mode) == 0o700
    private_files = [
        options.certificate,
        options.runtime_dir / controller.ATTESTATION_FILENAME,
        options.runtime_dir / controller.AUDITOR_STDOUT_FILENAME,
        options.runtime_dir / controller.AUDITOR_STDERR_FILENAME,
        options.runtime_dir / controller.STAGED_CERTIFICATE_FILENAME,
        options.runtime_dir / "controller_summary.json",
    ]
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in private_files)


def test_controller_forwards_and_verifies_external_source_wheel_contract(
    tmp_path: Path,
) -> None:
    options, source, execution = _layout(tmp_path)
    policy_sha256 = "1" * 64
    options = replace(
        options,
        expected_source_wheel_policy_sha256=policy_sha256,
        expected_source_wheel_attestations=9,
    )
    observed_command: tuple[str, ...] | None = None

    def runner(command: Any, _working_directory: Path) -> controller.ChildResult:
        nonlocal observed_command
        observed_command = tuple(command)
        return _child_output(
            _staged_certificate(command),
            source,
            execution,
            expected_source_wheel_policy_sha256=policy_sha256,
            expected_source_wheel_attestations=9,
        )

    summary = controller.run_controller(
        options,
        checkout_validator=_validator(source, execution),
        child_runner=runner,
    )

    assert observed_command is not None
    for flag, value in (
        ("--expected-source-wheel-policy-sha256", policy_sha256),
        ("--expected-source-wheel-attestations", "9"),
    ):
        assert observed_command.count(flag) == 1
        assert observed_command[observed_command.index(flag) + 1] == value
    assert summary["source_wheel_attestations"] == 9


@pytest.mark.parametrize(
    ("policy_sha256", "attestations"),
    [("1" * 64, None), (None, 1), ("not-a-digest", 1), ("1" * 64, 0)],
)
def test_rejects_incomplete_or_invalid_external_source_wheel_contract(
    tmp_path: Path,
    policy_sha256: str | None,
    attestations: int | None,
) -> None:
    options, _source, _execution = _layout(tmp_path)

    with pytest.raises(
        controller.OracleAuditControllerError,
        match="^expected_source_wheel_contract_invalid$",
    ):
        controller._validate_options(
            replace(
                options,
                expected_source_wheel_policy_sha256=policy_sha256,
                expected_source_wheel_attestations=attestations,
            )
        )


@pytest.mark.parametrize(
    ("target", "key"),
    [
        ("source", "prime_rl_commit"),
        ("source", "verifiers_commit"),
        ("source", "vmvm_tb_v2_sha256"),
        ("execution", "prime_rl_commit"),
        ("execution", "verifiers_commit"),
        ("execution", "vmvm_tb_v2_sha256"),
    ],
)
def test_rejects_each_auditor_certificate_pin_mismatch(tmp_path: Path, target: str, key: str) -> None:
    options, source, execution = _layout(tmp_path)

    def runner(command: Any, _working_directory: Path) -> controller.ChildResult:
        return _child_output(
            _staged_certificate(command),
            source,
            execution,
            mutate_contract=(target, key),
        )

    with pytest.raises(
        controller.OracleAuditControllerError,
        match="^auditor_certificate_provenance_mismatch$",
    ):
        controller.run_controller(
            options,
            checkout_validator=_validator(source, execution),
            child_runner=runner,
        )
    assert not options.certificate.exists()


def test_rejects_swapped_source_and_canary_pins(tmp_path: Path) -> None:
    options, source, execution = _layout(tmp_path)

    def runner(command: Any, _working_directory: Path) -> controller.ChildResult:
        staged = _staged_certificate(command)
        audit = {
            "contracts": {
                "canary_source": _source_contract(source),
                "source_oracle_source": _source_contract(execution),
            },
            "ok": True,
            "state": "passed",
        }
        audit_sha256 = controller._canonical_json_sha256(audit)
        _write(
            staged,
            controller._canonical_json_bytes({"audit": audit, "audit_sha256": audit_sha256, "schema_version": 1}),
        )
        summary = {
            "audit_sha256": audit_sha256,
            "control_regressions": 0,
            "controls": 2,
            "minimum_recovered": 2,
            "ok": True,
            "published": True,
            "reason_counts": {},
            "recovered": 2,
            "repair_candidates": 3,
            "source_wheel_attestations": 0,
            "state": "passed",
            "transitions": {},
            "unrecovered": 1,
        }
        return controller.ChildResult(0, controller._canonical_json_bytes(summary), b"")

    with pytest.raises(
        controller.OracleAuditControllerError,
        match="^auditor_certificate_provenance_mismatch$",
    ):
        controller.run_controller(
            options,
            checkout_validator=_validator(source, execution),
            child_runner=runner,
        )
    assert not options.certificate.exists()


@pytest.mark.parametrize("omitted", controller.PROVENANCE_FLAGS)
def test_rejects_caller_omission_of_any_provenance_flag(omitted: str) -> None:
    command = ["python", "auditor.py"]
    for flag in controller.PROVENANCE_FLAGS:
        if flag != omitted:
            command.extend((flag, "a" * 40))

    with pytest.raises(
        controller.OracleAuditControllerError,
        match="^auditor_provenance_argument_omitted$",
    ):
        controller._validate_provenance_arguments(command)


def test_rejects_dirty_checkout(tmp_path: Path) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "dirty")
    _write(root / "untracked-secret", b"opaque\n")

    with pytest.raises(controller.OracleAuditControllerError, match="^source_worktree_not_clean$"):
        controller._attest_checkout(root, revision, "source")


def test_rejects_moved_or_noncanonical_checkout(tmp_path: Path) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "canonical")
    alias = tmp_path / "moved-source"
    alias.symlink_to(root, target_is_directory=True)

    with pytest.raises(controller.OracleAuditControllerError, match="^source_project_path_unsafe$"):
        controller._attest_checkout(alias.absolute(), revision, "source")


def test_rejects_checkout_moved_to_a_different_revision(tmp_path: Path) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "revision-moved")
    _git(root, "switch", "-c", "replacement", "-q")
    _write(root / "new-file", b"new\n", 0o644)
    _git(root, "add", "new-file")
    _git(root, "commit", "-qm", "move head")
    moved = _git(root, "rev-parse", "HEAD").decode().strip()
    _git(root, "checkout", "--detach", "-q", moved)

    with pytest.raises(controller.OracleAuditControllerError, match="^source_revision_mismatch$"):
        controller._attest_checkout(root, revision, "source")


def test_rejects_missing_verifier_gitlink(tmp_path: Path) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "no-gitlink", with_gitlink=False)

    with pytest.raises(controller.OracleAuditControllerError, match="^source_verifiers_gitlink_missing$"):
        controller._attest_checkout(root, revision, "source")


def test_git_attestation_ignores_hostile_path_and_repository_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "hostile-git-environment")
    fake_bin = tmp_path / "fake-bin"
    marker = tmp_path / "fake-git-ran"
    fake_bin.mkdir()
    _write(
        fake_bin / "git",
        f"#!/bin/bash\nprintf ran > {marker!s}\nexit 99\n".encode(),
        0o755,
    )
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "redirected.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "redirected-worktree"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "redirected-index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(tmp_path / "redirected-objects"))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(tmp_path / "alternate-objects"))
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(tmp_path / "redirected-config-worktree"))

    attestation = controller._attest_checkout(root, revision, "source")

    assert attestation.revision == revision
    assert not marker.exists()


def test_rejects_vmvm_digest_drift_hidden_from_git_status(tmp_path: Path) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "digest-drift")
    relative = controller.SOURCE_VMVM_ROOT / "client.py"
    _git(root, "update-index", "--assume-unchanged", relative.as_posix())
    _write(root / relative, b"VALUE = 'drifted'\n", 0o644)
    assert not _git(root, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(controller.OracleAuditControllerError, match="^source_index_flags_nondefault$"):
        controller._attest_checkout(root, revision, "source")
    with pytest.raises(controller.OracleAuditControllerError, match="^source_vmvm_digest_mismatch$"):
        controller._vmvm_tree(root, revision, "source")


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_rejects_nondefault_index_flags_on_arbitrary_tracked_runtime(
    tmp_path: Path,
    index_flag: str,
) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "runtime-index-flags")
    relative = Path("arbitrary_runtime.py")
    _git(root, "update-index", index_flag, relative.as_posix())
    _write(root / relative, b"VALUE = 'runtime-two'\n", 0o644)

    with pytest.raises(controller.OracleAuditControllerError, match="^source_index_flags_nondefault$"):
        controller._attest_checkout(root, revision, "source")


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_rejects_nondefault_index_flags_and_drift_in_verifier_checkout(
    tmp_path: Path,
    index_flag: str,
) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "verifier-index-flags")
    verifier_root = root / "deps/verifiers"
    _git(verifier_root, "update-index", index_flag, "verifier.py")
    _write(verifier_root / "verifier.py", b"VALUE = 'drifted-verifier'\n", 0o644)

    with pytest.raises(
        controller.OracleAuditControllerError,
        match="^source_verifiers_index_flags_nondefault$",
    ):
        controller._attest_checkout(root, revision, "source")


def test_rejects_arbitrary_tracked_runtime_drift_without_special_index_flags(tmp_path: Path) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "runtime-drift")
    _write(root / "arbitrary_runtime.py", b"VALUE = 'runtime-two'\n", 0o644)

    with pytest.raises(controller.OracleAuditControllerError, match="^source_tracked_worktree_mismatch$"):
        controller._attest_checkout(root, revision, "source")


def test_rejects_tracked_symlink_target_drift(tmp_path: Path) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "symlink-drift")
    link = root / "runtime-link"
    link.unlink()
    link.symlink_to("different-target")

    with pytest.raises(controller.OracleAuditControllerError, match="^source_tracked_worktree_mismatch$"):
        controller._attest_checkout(root, revision, "source")


def test_binds_execution_controller_and_auditor_to_exact_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, revision, verifier_revision = _make_repository(
        tmp_path,
        "execution",
        with_scripts=True,
    )
    monkeypatch.setattr(controller, "__file__", str(root / controller.CONTROLLER_RELATIVE_PATH))

    attestation = controller._attest_checkout(root, revision, "execution")

    assert attestation.revision == revision
    assert attestation.verifiers_revision == verifier_revision
    assert {path for path, _blob, _digest in attestation.tracked_files} == {
        controller.AUDITOR_RELATIVE_PATH.as_posix(),
        controller.BUILDER_RELATIVE_PATH.as_posix(),
        controller.CONTROLLER_RELATIVE_PATH.as_posix(),
        controller.EXPORTER_RELATIVE_PATH.as_posix(),
        controller.LAUNCHER_RELATIVE_PATH.as_posix(),
    }


def test_rejects_execution_script_origin_outside_frozen_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "wrong-origin", with_scripts=True)
    copied = tmp_path / "copied-controller.py"
    _write(copied, (root / controller.CONTROLLER_RELATIVE_PATH).read_bytes(), 0o644)
    monkeypatch.setattr(controller, "__file__", str(copied))

    with pytest.raises(controller.OracleAuditControllerError, match="^execution_script_origin_mismatch$"):
        controller._attest_checkout(root, revision, "execution")


def test_rejects_execution_script_drift_hidden_from_git_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, revision, _verifier = _make_repository(tmp_path, "script-drift", with_scripts=True)
    relative = controller.AUDITOR_RELATIVE_PATH
    _git(root, "update-index", "--assume-unchanged", relative.as_posix())
    _write(root / relative, b"# drifted auditor\n", 0o644)
    monkeypatch.setattr(controller, "__file__", str(root / controller.CONTROLLER_RELATIVE_PATH))
    assert not _git(root, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(controller.OracleAuditControllerError, match="^execution_index_flags_nondefault$"):
        controller._attest_checkout(root, revision, "execution")


@pytest.mark.parametrize("changed_role", ["source", "execution"])
def test_post_audit_toctou_change_blocks_authoritative_publication(tmp_path: Path, changed_role: str) -> None:
    options, source, execution = _layout(tmp_path)
    calls = {"source": 0, "execution": 0}

    def validator(root: Path, revision: str, role: str) -> controller.CheckoutAttestation:
        expected = source if role == "source" else execution
        assert root == expected.root
        assert revision == expected.revision
        calls[role] += 1
        if role == changed_role and calls[role] == 2:
            return replace(expected, root_inode=expected.root_inode + 1)
        return expected

    def runner(command: Any, _working_directory: Path) -> controller.ChildResult:
        return _child_output(_staged_certificate(command), source, execution)

    with pytest.raises(controller.OracleAuditControllerError, match=rf"^{changed_role}_checkout_changed$"):
        controller.run_controller(options, checkout_validator=validator, child_runner=runner)
    assert not options.certificate.exists()
    assert (options.runtime_dir / controller.STAGED_CERTIFICATE_FILENAME).exists()


def test_rejects_changed_private_input_after_audit(tmp_path: Path) -> None:
    options, source, execution = _layout(tmp_path)

    def runner(command: Any, _working_directory: Path) -> controller.ChildResult:
        result = _child_output(_staged_certificate(command), source, execution)
        _write(options.task_file, b"changed\n")
        return result

    with pytest.raises(controller.OracleAuditControllerError, match="^audit_input_changed$"):
        controller.run_controller(
            options,
            checkout_validator=_validator(source, execution),
            child_runner=runner,
        )
    assert not options.certificate.exists()


def test_rejects_public_builder_artifact_and_existing_certificate(tmp_path: Path) -> None:
    options, source, execution = _layout(tmp_path)
    options.task_file.chmod(0o644)
    with pytest.raises(controller.OracleAuditControllerError, match="^task_file_invalid$"):
        controller.run_controller(
            options,
            checkout_validator=_validator(source, execution),
            child_runner=lambda _command, _cwd: pytest.fail("auditor must not run"),
        )

    options.task_file.chmod(0o600)
    _write(options.certificate, b"preserve me\n")
    with pytest.raises(controller.OracleAuditControllerError, match="^certificate_path_unsafe$"):
        controller.run_controller(
            options,
            checkout_validator=_validator(source, execution),
            child_runner=lambda _command, _cwd: pytest.fail("auditor must not run"),
        )
    assert options.certificate.read_bytes() == b"preserve me\n"


def test_cli_rejects_omitted_checkout_authority_without_echoing_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert controller.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "oracle_repair_canary_controller_error:arguments_invalid\n"


def _wrapper_environment(root: Path, revision: str) -> dict[str, str]:
    return {
        "ORACLE_AUDIT_BUILDER_RECEIPT": "/private/receipt",
        "ORACLE_AUDIT_CANARY_DIR": "/private/canary",
        "ORACLE_AUDIT_CERTIFICATE": "/private/certificates/certificate.json",
        "ORACLE_AUDIT_CERTIFICATE_ROOT": "/private/certificates",
        "ORACLE_AUDIT_EXECUTION_PROJECT_DIR": str(root),
        "ORACLE_AUDIT_EXECUTION_REVISION": revision,
        "ORACLE_AUDIT_RUNTIME_DIR": "/private/runtime/attempt",
        "ORACLE_AUDIT_RUNTIME_ROOT": "/private/runtime",
        "ORACLE_AUDIT_SOURCE_DIR": "/private/source-oracle",
        "ORACLE_AUDIT_SOURCE_PROJECT_DIR": "/private/source-checkout",
        "ORACLE_AUDIT_SOURCE_REVISION": "a" * 40,
        "ORACLE_AUDIT_TASK_FILE": "/private/tasks",
        "SLURM_JOB_ID": "123",
    }


@pytest.mark.parametrize("launch_kind", ["copy", "symlink"])
def test_wrapper_rejects_copied_or_symlinked_launcher(tmp_path: Path, launch_kind: str) -> None:
    wrapper_body = Path(controller.__file__).with_name("run_oracle_repair_canary_audit.sbatch").read_bytes()
    root, revision, _verifier = _make_repository(
        tmp_path,
        "wrapper-origin",
        with_scripts=True,
        launcher_body=wrapper_body,
    )
    expected = root / controller.LAUNCHER_RELATIVE_PATH
    launched = tmp_path / f"{launch_kind}.sbatch"
    if launch_kind == "copy":
        _write(launched, wrapper_body, 0o755)
    else:
        launched.symlink_to(expected)

    result = subprocess.run(
        ["/bin/bash", str(launched)],
        check=False,
        capture_output=True,
        env=_wrapper_environment(root, revision),
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b'{"code":"launcher_origin_mismatch","status":"error"}\n'


def test_wrapper_uses_exact_launcher_and_scrubs_hostile_git_environment(tmp_path: Path) -> None:
    wrapper_body = Path(controller.__file__).with_name("run_oracle_repair_canary_audit.sbatch").read_bytes()
    root, revision, _verifier = _make_repository(
        tmp_path,
        "wrapper-environment",
        with_scripts=True,
        launcher_body=wrapper_body,
    )
    launcher = root / controller.LAUNCHER_RELATIVE_PATH
    fake_bin = tmp_path / "wrapper-fake-bin"
    marker = tmp_path / "wrapper-fake-git-ran"
    fake_bin.mkdir()
    _write(
        fake_bin / "git",
        f"#!/bin/bash\nprintf ran > {marker!s}\nexit 99\n".encode(),
        0o755,
    )
    environment = _wrapper_environment(root, revision)
    environment.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": str(tmp_path / "redirected-config-worktree"),
            "GIT_DIR": str(tmp_path / "redirected.git"),
            "GIT_INDEX_FILE": str(tmp_path / "redirected-index"),
            "GIT_OBJECT_DIRECTORY": str(tmp_path / "redirected-objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(tmp_path / "alternate-objects"),
            "GIT_OPTIONAL_LOCKS": "1",
            "GIT_WORK_TREE": str(tmp_path / "redirected-worktree"),
            "PATH": str(fake_bin),
        }
    )

    result = subprocess.run(
        ["/bin/bash", str(launcher)],
        check=False,
        capture_output=True,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""
    assert not marker.exists()


def test_sbatch_wrapper_requires_both_checkout_authorities_and_calls_controller() -> None:
    wrapper = Path(controller.__file__).with_name("run_oracle_repair_canary_audit.sbatch").read_text()
    for variable in (
        "ORACLE_AUDIT_SOURCE_PROJECT_DIR",
        "ORACLE_AUDIT_SOURCE_REVISION",
        "ORACLE_AUDIT_EXECUTION_PROJECT_DIR",
        "ORACLE_AUDIT_EXECUTION_REVISION",
    ):
        assert variable in wrapper
    assert "run_oracle_repair_canary_audit.py" in wrapper
    assert "symbolic-ref -q HEAD" in wrapper
    assert "status --porcelain=v1 --untracked-files=all" in wrapper
    assert 'ls-tree "$observed_revision"' in wrapper
    assert "hash-object" in wrapper
    assert "umask 077" in wrapper

    documentation = Path(controller.__file__).with_name("README.md").read_text()
    assert "Do not submit the launcher file directly with `sbatch`" in documentation
    assert "--wrap='exec /bin/bash <detached-execution-checkout>" in documentation
    assert "--dependency=afterany:<canary-job-id>" in documentation
