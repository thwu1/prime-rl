#!/usr/bin/env python3

from __future__ import annotations

import ast
import base64
import copy
import hashlib
import importlib.util
import inspect
import json
import py_compile
import re
import signal
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
LAUNCHER_PATH = ROOT / "launch_infrastructure_retry_canary_v22.py"
GENERATOR_PATH = ROOT / "build_infrastructure_retry_selection_v22.py"
AUDITOR_PATH = ROOT / "audit_infrastructure_retry_canary_v22.py"
JOB_PATH = ROOT / "run_infrastructure_retry_canary_v22.sbatch"
PACKAGING_SNAPSHOT_PATH = ROOT / "packaging-26.3-py3-none-any.whl.snapshot.json"
CANONICAL_ROOT = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/oracle/"
    "infrastructure_retry_canary_5873430ff_v22"
)
RUN_ORACLE_PATH = (
    Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-5873430ff-v22")
    / "user/tianhaowu/terminal_bench_vmvm/run_oracle.py"
    if ROOT == CANONICAL_ROOT
    else ROOT.parent / "run_oracle.py"
)


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeCredential:
    def __init__(
        self, environment_name: str, path: str, digest: str, inode: int
    ) -> None:
        self.environment_name = environment_name
        self.path = Path(path)
        self.sha256 = digest
        self.signature = (1, inode)
        self.pem_profile = "other"

    def revalidate(self) -> None:
        return None


def synthetic_tls_credentials(launcher):
    return {
        "THRIFT_TLS_CL_CERT_PATH": FakeCredential(
            "THRIFT_TLS_CL_CERT_PATH", "/private/tls/client.crt", "8" * 64, 1
        ),
        "THRIFT_TLS_CL_KEY_PATH": FakeCredential(
            "THRIFT_TLS_CL_KEY_PATH", "/private/tls/client.key", "9" * 64, 2
        ),
    }


def synthetic_tls_values() -> dict[str, str]:
    return {
        "THRIFT_TLS_CL_CERT_PATH": "/private/tls/client.crt",
        "THRIFT_TLS_CL_KEY_PATH": "/private/tls/client.key",
        "RETRY_THRIFT_TLS_CL_CERT_SHA256": "8" * 64,
        "RETRY_THRIFT_TLS_CL_KEY_SHA256": "9" * 64,
    }


def synthetic_x2p_values() -> dict[str, str]:
    return {
        "X2P_ENV": "synthetic-v22-environment",
        "X2P_CFG_ENV": "synthetic-v22-configuration",
        "X2P_PROXY_URL": "https://synthetic-v22.invalid:10054/private",
    }


def synthetic_x2p_sha256() -> dict[str, str]:
    return {
        name: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for name, value in synthetic_x2p_values().items()
    }


def canonical_packaging_provenance(launcher) -> dict[str, object]:
    provenance = launcher.expected_packaging_provenance()
    provenance["snapshot"]["path"] = str(
        CANONICAL_ROOT / "packaging-26.3-py3-none-any.whl.snapshot.json"
    )
    return provenance


def write_synthetic_tls_pair(tmp_path: Path) -> dict[str, str]:
    certificate = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    certificate.write_bytes(b"C" * 5580)
    key.write_bytes(b"K" * 5580)
    certificate.chmod(0o500)
    key.chmod(0o500)
    return {
        "THRIFT_TLS_CL_CERT_PATH": str(certificate),
        "THRIFT_TLS_CL_KEY_PATH": str(key),
    }


def fit_tls_size(raw: bytes) -> bytes:
    assert len(raw) <= 5580
    return raw + b"\n" * (5580 - len(raw))


def combined_pem_bytes(
    *, labels: tuple[bytes, ...] | None = None, gap: bytes = b"\n"
) -> bytes:
    selected = labels or (b"CERTIFICATE", b"CERTIFICATE", b"RSA PRIVATE KEY")
    blocks: list[bytes] = []
    for index, label in enumerate(selected, start=1):
        encoded = base64.b64encode(bytes([index]) * 900)
        lines = b"\n".join(
            encoded[offset : offset + 64] for offset in range(0, len(encoded), 64)
        )
        blocks.append(
            b"-----BEGIN "
            + label
            + b"-----\n"
            + lines
            + b"\n-----END "
            + label
            + b"-----"
        )
    raw = gap.join(blocks) + b"\n"
    return fit_tls_size(raw)


def malformed_delimiter_pem() -> bytes:
    raw = combined_pem_bytes().replace(
        b"-----END RSA PRIVATE KEY-----",
        b"-----END PRIVATE KEY-----",
        1,
    )
    return fit_tls_size(raw)


def malformed_base64_pem() -> bytes:
    raw = combined_pem_bytes()
    marker = b"-----BEGIN CERTIFICATE-----\n"
    offset = raw.index(marker) + len(marker)
    return raw[:offset] + b"!" + raw[offset + 1 :]


def nonwhitespace_gap_pem() -> bytes:
    raw = combined_pem_bytes()
    needle = b"-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----"
    changed = raw.replace(
        needle,
        b"-----END CERTIFICATE-----\nX-----BEGIN CERTIFICATE-----",
        1,
    )
    assert len(changed) == 5581 and changed.endswith(b"\n")
    return changed[:-1]


def write_combined_tls_alias(
    tmp_path: Path, *, raw: bytes | None = None
) -> tuple[dict[str, str], Path, Path]:
    canonical_parent = tmp_path / "canonical"
    canonical_parent.mkdir()
    bundle = canonical_parent / "client.pem"
    bundle.write_bytes(raw if raw is not None else combined_pem_bytes())
    bundle.chmod(0o500)
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(canonical_parent, target_is_directory=True)
    alias = alias_parent / "client.pem"
    return (
        {
            "THRIFT_TLS_CL_CERT_PATH": str(alias),
            "THRIFT_TLS_CL_KEY_PATH": str(alias),
        },
        bundle,
        alias_parent,
    )


def _bind_local_launcher(module):
    if module.CANONICAL_SELF == LAUNCHER_PATH:
        return module
    module.ARTIFACT_ROOT = ROOT
    module.CANONICAL_SELF = LAUNCHER_PATH
    module.GENERATOR = GENERATOR_PATH
    module.JOB_WRAPPER = JOB_PATH
    module.PACKAGING_SNAPSHOT = PACKAGING_SNAPSHOT_PATH

    def load_local_generator():
        spec = importlib.util.spec_from_file_location(
            "retry_canary_v22_frozen_generator", GENERATOR_PATH
        )
        assert spec is not None and spec.loader is not None
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        generator.ARTIFACT_ROOT = ROOT
        generator.SELF = GENERATOR_PATH
        generator.PACKAGING_SNAPSHOT = PACKAGING_SNAPSHOT_PATH
        return generator

    module.load_generator = load_local_generator
    return module


def load_launcher():
    spec = importlib.util.spec_from_file_location(
        "retry_v22_launcher_public_test", LAUNCHER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return _bind_local_launcher(module)


def load_module(path: Path, name: str):
    if path == AUDITOR_PATH and path.parent != CANONICAL_ROOT:
        module = types.ModuleType(name)
        module.__file__ = str(path)
        source = (
            path.read_text(encoding="utf-8")
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
        exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102
        module.LAUNCH = _bind_local_launcher(module.LAUNCH)
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_closed_artifact_root(tmp_path: Path, module) -> Path:
    root = tmp_path / "closed-artifact-root"
    root.mkdir(mode=0o700)
    for name, mode in module.ARTIFACT_ROOT_ENTRIES.items():
        path = root / name
        path.write_bytes(b"public synthetic artifact\n")
        path.chmod(mode)
    return root


@pytest.mark.parametrize(
    ("path", "name", "error_name"),
    (
        (GENERATOR_PATH, "retry_v22_inventory_generator", "SelectionV22Error"),
        (LAUNCHER_PATH, "retry_v22_inventory_launcher", "LauncherError"),
        (AUDITOR_PATH, "retry_v22_inventory_auditor", "AuditError"),
    ),
)
@pytest.mark.parametrize("extra_kind", ("file", "directory", "symlink"))
def test_closed_artifact_inventory_rejects_every_extra_entry_kind(
    tmp_path: Path,
    path: Path,
    name: str,
    error_name: str,
    extra_kind: str,
) -> None:
    module = load_module(path, name)
    root = _synthetic_closed_artifact_root(tmp_path, module)
    module.validate_artifact_root_inventory(root, module.ARTIFACT_ROOT_ENTRIES)
    extra = root / "unexpected"
    if extra_kind == "file":
        extra.write_bytes(b"unexpected\n")
        extra.chmod(0o500)
    elif extra_kind == "directory":
        extra.mkdir(mode=0o700)
    else:
        extra.symlink_to(root / "README.md")
    error_type = getattr(module, error_name)
    with pytest.raises(error_type, match="artifact_root_inventory_invalid"):
        module.validate_artifact_root_inventory(root, module.ARTIFACT_ROOT_ENTRIES)


def test_closed_artifact_inventory_is_exact_and_cross_entrypoint() -> None:
    launcher = load_launcher()
    generator = launcher.load_generator()
    auditor = load_module(AUDITOR_PATH, "retry_v22_inventory_crosspin_auditor")
    expected = {
        "README.md": 0o500,
        "audit_infrastructure_retry_canary_v22.py": 0o500,
        "build_infrastructure_retry_selection_v22.py": 0o500,
        "launch_infrastructure_retry_canary_v22.py": 0o500,
        "packaging-26.3-py3-none-any.whl.snapshot.json": 0o400,
        "run_infrastructure_retry_canary_v22.sbatch": 0o500,
        "test_retry_canary_v22_public.py": 0o500,
        "test_retry_launcher_v22_public.py": 0o500,
        "test_retry_postrun_audit_v22_public.py": 0o500,
    }
    assert generator.ARTIFACT_ROOT_ENTRIES == expected
    assert launcher.ARTIFACT_ROOT_ENTRIES == expected
    assert auditor.ARTIFACT_ROOT_ENTRIES == expected
    for module in (generator, launcher, auditor):
        assert inspect.getsource(module).count("validate_artifact_root_inventory()") >= 2


def scheduler_snapshot(
    status: str,
    state: str,
    mismatch_fields: tuple[str, ...] = (),
    step_signature: tuple[tuple[str, str], ...] = (),
    explicit_conflict_fields: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "snapshot_status": status,
        "state": state,
        "mismatch_fields": mismatch_fields,
        "explicit_conflict_fields": explicit_conflict_fields,
        "step_signature": step_signature,
    }


def allocation_category_counts(
    polls: int, *, held: bool
) -> dict[str, dict[str, int]]:
    return {
        "BatchHost": {
            "assigned_or_other": 0 if held else polls,
            "empty": 0,
            "missing": 0,
            "null_token": polls if held else 0,
        },
        "NodeList": {
            "assigned_or_other": 0 if held else polls,
            "empty": 0,
            "missing": polls if held else 0,
            "null_token": 0,
        },
        "NumNodes": {
            "expected_one": 0 if held else polls,
            "missing": 0,
            "other": polls if held else 0,
            "zero": 0,
        },
    }


def exact_held_allocation_categories() -> dict[str, str]:
    return {
        "BatchHost": "null_token",
        "NodeList": "missing",
        "NumNodes": "other",
    }


def exact_activation_allocation_categories() -> dict[str, str]:
    return {
        "BatchHost": "assigned_or_other",
        "NodeList": "assigned_or_other",
        "NumNodes": "expected_one",
    }


def held_details(accounting_status: str = "exact") -> dict[str, object]:
    return {
        "held_accounting_status": accounting_status,
        "scontrol_allocation_categories": exact_held_allocation_categories(),
    }


def activation_details() -> dict[str, object]:
    return {"scontrol_allocation_categories": exact_activation_allocation_categories()}


def exact_held_record(launcher, job_id: str, job_name: str) -> dict[str, str]:
    return {
        "JobId": job_id,
        "JobName": job_name,
        "Command": str(launcher.JOB_WRAPPER),
        "WorkDir": str(launcher.SOURCE_ROOT),
        "StdOut": str(launcher.LOG_ROOT / f"oracle_{job_id}.log"),
        "StdErr": str(launcher.LOG_ROOT / f"oracle_{job_id}.log"),
        "Account": "ram",
        "Partition": "cpu_x86",
        "QOS": "cpu_x86_lowest",
        "TimeLimit": "7-00:00:00",
        "NumCPUs": "8",
        "NumNodes": "1-1",
        "MinMemoryNode": "16G",
        "Dependency": "(null)",
        "Requeue": "0",
        "Restarts": "0",
        "UserId": "tianhaowu(656177)",
        "JobState": "PENDING",
        "Reason": "JobHeldUser",
        "Priority": "0",
        "StartTime": "Unknown",
        "BatchHost": "(null)",
    }


def exact_activation_record(launcher, job_id: str, job_name: str) -> dict[str, str]:
    record = exact_held_record(launcher, job_id, job_name)
    record.update(
        {
            "NumNodes": "1",
            "NodeList": "cpu-test-001",
            "BatchHost": "cpu-test-001",
            "JobState": "RUNNING",
            "Reason": "None",
            "Priority": "1",
            "StartTime": "2026-09-19T00:00:00",
        }
    )
    return record


def held_telemetry(launcher, *, polls: int = 2) -> dict[str, object]:
    return {
        "telemetry_schema": "deadline_poll_v1",
        "deadline_seconds": launcher.HELD_CONVERGENCE_TIMEOUT_SECONDS,
        "max_iterations": launcher.HELD_POLL_MAX_ITERATIONS,
        "converged": True,
        "identity_status": "converged",
        "explicit_conflict_fields": [],
        "polls": polls,
        "required_consecutive": 2,
        "consecutive_exact": 2,
        "elapsed_milliseconds": 1,
        "observed_mismatch_fields": [],
        "mismatch_field_count": 0,
        "mismatch_field_occurrences": {},
        "final_mismatch_fields": [],
        "held_accounting_status_counts": {
            "absent": 0,
            "exact": polls,
            "shape": 0,
            "unavailable": 0,
        },
        "final_held_accounting_status": "exact",
        "scontrol_allocation_category_counts": allocation_category_counts(
            polls, held=True
        ),
        "final_scontrol_allocation_categories": exact_held_allocation_categories(),
        "final_pre_authorization_mismatch_fields": [],
        "post_authorization_mismatch_fields": [],
    }


def activation_telemetry(launcher, *, polls: int = 2) -> dict[str, object]:
    return {
        "telemetry_schema": "deadline_poll_v1",
        "deadline_seconds": launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
        "max_iterations": launcher.ACTIVATION_POLL_MAX_ITERATIONS,
        "attempts": 1,
        "command_outcome": "completed",
        "converged": True,
        "identity_status": "converged",
        "explicit_conflict_fields": [],
        "polls": polls,
        "consecutive_exact": 2,
        "elapsed_milliseconds": 1,
        "observed_mismatch_fields": [],
        "mismatch_field_count": 0,
        "mismatch_field_occurrences": {},
        "final_mismatch_fields": [],
        "scontrol_allocation_category_counts": allocation_category_counts(
            polls, held=False
        ),
        "final_scontrol_allocation_categories": exact_activation_allocation_categories(),
        "state_class": "active",
        "observed_state": "PENDING",
    }


def failed_held_telemetry(launcher, *, polls: int = 13) -> dict[str, object]:
    value = held_telemetry(launcher, polls=polls)
    value.update(
        {
            "converged": False,
            "identity_status": "unavailable_or_incomplete",
            "consecutive_exact": 0,
            "elapsed_milliseconds": 982_000,
            "observed_mismatch_fields": ["held_accounting"],
            "mismatch_field_count": 1,
            "mismatch_field_occurrences": {"held_accounting": polls},
            "final_mismatch_fields": ["held_accounting"],
            "held_accounting_status_counts": {
                "absent": polls,
                "exact": 0,
                "shape": 0,
                "unavailable": 0,
            },
            "final_held_accounting_status": "absent",
        }
    )
    return value


def failed_activation_telemetry(launcher, *, polls: int = 13) -> dict[str, object]:
    value = activation_telemetry(launcher, polls=polls)
    value.update(
        {
            "converged": False,
            "identity_status": "unavailable_or_incomplete",
            "consecutive_exact": 0,
            "elapsed_milliseconds": 742_000,
            "observed_mismatch_fields": ["activation_accounting"],
            "mismatch_field_count": 1,
            "mismatch_field_occurrences": {"activation_accounting": polls},
            "final_mismatch_fields": ["activation_accounting"],
        }
    )
    return value


def selection_receipt(launcher):
    body = {
        "schema_version": 1,
        "artifact_type": "terminal_bench_vmvm_infrastructure_retry_selection_v22",
        "state": "prepared",
        "generator": {
            "path": str(launcher.GENERATOR),
            "sha256": launcher.GENERATOR_SHA256,
        },
        "execution_source": {
            "path": str(launcher.SOURCE_ROOT),
            "revision": launcher.SOURCE_REVISION,
            "tree": launcher.SOURCE_TREE,
            "verifiers_revision": launcher.VERIFIERS_REVISION,
            "vmvm_tb_v2_sha256": launcher.VMVM_SHA256,
        },
        "source_oracle": {},
        "prior_repair": {},
        "source_wheel_exclusion": {
            "input_entries": 9,
            "scope": "all_probe_entries",
            "recovered_valid": 0,
            "cardinality_receipt_sha256": (
                "7a9a73082231b6cbba1ce25ec83e362e40654f8b6471611795092717e4dcf1f8"
            ),
            "cardinality_completion_sha256": (
                "573b8e9f6c5ce0ae3457540f19702e57cb552d45324cdc1cae36ff7b292ee76a"
            ),
        },
        "selection": {
            "counts": {"retry_candidates": 15, "controls": 4, "selected": 19},
            "category_counts": {"image": 1, "network": 3, "timeout": 11},
            "task_file": {
                "path": str(launcher.TASK_FILE),
                "mode": "0600",
                "count": 19,
                "sha256": "1" * 64,
            },
            "role_file": {
                "path": str(launcher.ROLE_FILE),
                "mode": "0600",
                "candidate_count": 15,
                "control_count": 4,
                "sha256": "2" * 64,
            },
        },
        "launch_contract": {
            "infra_retries": 4,
            "max_concurrent": 4,
            "minimum_valid": 10,
            "setup_timeout_seconds": 7200,
            "validate_timeout_seconds": 21600,
            "session_timeout_seconds": 43200,
        },
        "final_union": {
            "base_valid_after_completed_repairs": 2494,
            "minimum_retry_recoveries": 6,
            "projected_minimum_valid": 2500,
            "required_minimum_valid": 2500,
        },
        "attempt_policy": launcher.ATTEMPT_POLICY,
        "module_import_closure": {
            "packaging": launcher.expected_packaging_provenance(),
        },
    }
    return {
        **body,
        "selection_receipt_sha256": hashlib.sha256(
            launcher.canonical_json(body)
        ).hexdigest(),
    }


def test_selection_and_submission_receipts_bind_policy_and_roles() -> None:
    launcher = load_launcher()
    receipt = selection_receipt(launcher)
    assert launcher.validate_selection_receipt(receipt) == (
        "1" * 64,
        "2" * 64,
        receipt["selection_receipt_sha256"],
    )
    for field in ("verifiers_revision", "vmvm_tb_v2_sha256"):
        drifted_selection = copy.deepcopy(receipt)
        drifted_selection["execution_source"][field] = "0" * (
            40 if field == "verifiers_revision" else 64
        )
        body = dict(drifted_selection)
        del body["selection_receipt_sha256"]
        drifted_selection["selection_receipt_sha256"] = hashlib.sha256(
            launcher.canonical_json(body)
        ).hexdigest()
        with pytest.raises(launcher.LauncherError, match="^selection_receipt_invalid$"):
            launcher.validate_selection_receipt(drifted_selection)

    submission_body = launcher.terminal_body(
        state="submitted",
        code=None,
        launcher_sha="3" * 64,
        intent_file_sha="4" * 64,
        environment_sha="5" * 64,
        task_sha="1" * 64,
        role_sha="2" * 64,
        receipt_file_sha="6" * 64,
        receipt_sha=receipt["selection_receipt_sha256"],
        job_id="123456",
        job_name="mirc-" + "7" * 24,
        token="7" * 24,
        authorization_path=launcher.RESERVATION
        / ("job_authorization_" + "7" * 24 + ".json"),
        authorization_sha="8" * 64,
        activation_permit_path=launcher.RESERVATION
        / ("activation_permit_" + "7" * 24 + ".json"),
        activation_permit_sha="9" * 64,
        x2p_sha256=synthetic_x2p_sha256(),
        held_validation=held_telemetry(launcher),
        release=activation_telemetry(launcher),
        cancellation=None,
    )
    submission = {
        **submission_body,
        "submission_receipt_sha256": hashlib.sha256(
            launcher.canonical_json(submission_body)
        ).hexdigest(),
    }
    observed = launcher.validate_submission_receipt(
        submission,
        launcher_sha="3" * 64,
        task_sha="1" * 64,
        role_sha="2" * 64,
        receipt_file_sha="6" * 64,
        receipt_sha=receipt["selection_receipt_sha256"],
        x2p_sha256=synthetic_x2p_sha256(),
    )
    assert observed == (
        "123456",
        "mirc-" + "7" * 24,
        "4" * 64,
        submission["submission_receipt_sha256"],
        launcher.RESERVATION / ("job_authorization_" + "7" * 24 + ".json"),
        "8" * 64,
        launcher.RESERVATION / ("activation_permit_" + "7" * 24 + ".json"),
        "9" * 64,
    )
    assert (
        submission_body["attempt_policy"]["asyncio_timeout_error"]["maximum_attempts"]
        == 1
    )
    assert (
        submission_body["attempt_policy"]["timeout_category_candidates"]["count"] == 11
    )
    assert submission_body["automatic_union_or_promotion"] is False
    assert submission_body["x2p_environment_sha256"] == synthetic_x2p_sha256()

    drifted = copy.deepcopy(submission_body)
    drifted["x2p_environment_sha256"]["X2P_PROXY_URL"] = "0" * 64
    drifted["submission_receipt_sha256"] = hashlib.sha256(
        launcher.canonical_json(drifted)
    ).hexdigest()
    with pytest.raises(launcher.LauncherError, match="^submission_receipt_invalid$"):
        launcher.validate_submission_receipt(
            drifted,
            launcher_sha="3" * 64,
            task_sha="1" * 64,
            role_sha="2" * 64,
            receipt_file_sha="6" * 64,
            receipt_sha=receipt["selection_receipt_sha256"],
            x2p_sha256=synthetic_x2p_sha256(),
        )


@pytest.mark.parametrize(
    "prior_version",
    (
        "v3",
        "v4",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9",
        "v10",
        "v11",
        "v12",
        "v13",
        "v14",
        "v15",
    ),
)
def test_selection_receipt_rejects_prior_version_type(prior_version: str) -> None:
    launcher = load_launcher()
    receipt = selection_receipt(launcher)
    receipt["artifact_type"] = (
        f"terminal_bench_vmvm_infrastructure_retry_selection_{prior_version}"
    )
    body = dict(receipt)
    del body["selection_receipt_sha256"]
    receipt["selection_receipt_sha256"] = hashlib.sha256(
        launcher.canonical_json(body)
    ).hexdigest()
    with pytest.raises(launcher.LauncherError, match="selection_receipt_invalid"):
        launcher.validate_selection_receipt(receipt)


def test_selection_receipt_rejects_resealed_packaging_dependency_mutation() -> None:
    launcher = load_launcher()
    receipt = selection_receipt(launcher)
    receipt["module_import_closure"]["packaging"]["wheel_sha256"] = "0" * 64
    body = dict(receipt)
    del body["selection_receipt_sha256"]
    receipt["selection_receipt_sha256"] = hashlib.sha256(
        launcher.canonical_json(body)
    ).hexdigest()
    with pytest.raises(launcher.LauncherError, match="selection_receipt_invalid"):
        launcher.validate_selection_receipt(receipt)


def test_launcher_cross_pins_packaging_snapshot_and_manifest() -> None:
    launcher = load_launcher()
    assert launcher.PACKAGING_SNAPSHOT.name.endswith(".whl.snapshot.json")
    assert hashlib.sha256(launcher.PACKAGING_SNAPSHOT.read_bytes()).hexdigest() == (
        launcher.PACKAGING_SNAPSHOT_SHA256
    )
    provenance = launcher.expected_packaging_provenance()
    assert provenance["version"] == "26.3"
    assert provenance["wheel_sha256"].startswith("d7193f7c")
    assert provenance["member_manifest_sha256"] == (
        launcher.PACKAGING_MEMBER_MANIFEST_SHA256
    )


def test_public_artifact_and_internal_module_versions_are_v22() -> None:
    paths = (
        ROOT / "build_infrastructure_retry_selection_v22.py",
        LAUNCHER_PATH,
        ROOT / "audit_infrastructure_retry_canary_v22.py",
        JOB_PATH,
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    public_labels = re.findall(
        r"terminal_bench_vmvm_infrastructure_retry(?:_selection)?_v[0-9]+"
        r"|mobius-infra-retry-v[0-9]+",
        text,
    )
    module_labels = re.findall(
        r"retry_(?:launcher|canary)_v[0-9]+_frozen(?:_generator)?",
        text,
    )
    assert public_labels and all("v22" in label for label in public_labels)
    assert set(module_labels) == {
        "retry_launcher_v1_frozen",
        "retry_launcher_v22_frozen",
        "retry_canary_v22_frozen_generator",
    }


def test_exhaustive_cross_file_hash_version_and_export_pins_match() -> None:
    launcher = load_launcher()
    generator = launcher.load_generator()
    auditor = load_module(AUDITOR_PATH, "retry_v22_cross_pin_auditor")
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (GENERATOR_PATH, LAUNCHER_PATH, AUDITOR_PATH, JOB_PATH)
    )
    actual_generator_sha = hashlib.sha256(GENERATOR_PATH.read_bytes()).hexdigest()
    actual_job_sha = hashlib.sha256(JOB_PATH.read_bytes()).hexdigest()
    actual_launcher_sha = hashlib.sha256(LAUNCHER_PATH.read_bytes()).hexdigest()
    actual_snapshot_sha = hashlib.sha256(
        PACKAGING_SNAPSHOT_PATH.read_bytes()
    ).hexdigest()

    assert generator.SELF == GENERATOR_PATH
    assert launcher.CANONICAL_SELF == LAUNCHER_PATH
    assert launcher.GENERATOR == GENERATOR_PATH
    assert launcher.JOB_WRAPPER == JOB_PATH
    assert auditor.CANONICAL_SELF == AUDITOR_PATH
    assert auditor.LAUNCHER == LAUNCHER_PATH
    assert launcher.GENERATOR_SHA256 == actual_generator_sha
    assert launcher.JOB_WRAPPER_SHA256 == actual_job_sha
    assert auditor.LAUNCHER_SHA256 == actual_launcher_sha

    batch_generator_pin = re.search(
        r'\$RETRY_GENERATOR_SHA256" != ([0-9a-f]{64})', wrapper
    )
    assert batch_generator_pin is not None
    assert batch_generator_pin.group(1) == actual_generator_sha
    assert 'require_file "$GENERATOR" 500 "$RETRY_GENERATOR_SHA256"' in wrapper
    assert 'require_file "$LAUNCHER" 500 "$RETRY_LAUNCHER_SHA256"' in wrapper
    assert '"${SHA_CAPTURE%%  *}" == "$RETRY_JOB_WRAPPER_SHA256"' in wrapper

    token = "4" * 24
    environment = launcher.slurm_environment(
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        launcher_sha=actual_launcher_sha,
        token=token,
        job_name=f"mirc-{token}",
        authorization_path=launcher.RESERVATION / f"job_authorization_{token}.json",
        authorization_sha="5" * 64,
        activation_permit_path=launcher.RESERVATION
        / f"activation_permit_{token}.json",
        activation_permit_sha="6" * 64,
        private_tls_values=synthetic_tls_values(),
        private_x2p_values=synthetic_x2p_values(),
    )
    assert environment["RETRY_GENERATOR_SHA256"] == actual_generator_sha
    assert environment["RETRY_JOB_WRAPPER_SHA256"] == actual_job_sha
    assert environment["RETRY_LAUNCHER_SHA256"] == actual_launcher_sha

    receipt = selection_receipt(launcher)
    assert receipt["artifact_type"].endswith("_v22")
    assert receipt["generator"] == {
        "path": str(GENERATOR_PATH),
        "sha256": actual_generator_sha,
    }
    assert generator.packaging_provenance() == launcher.expected_packaging_provenance()
    assert auditor.expected_packaging_provenance() == (
        launcher.expected_packaging_provenance()
    )
    for module in (generator, launcher, auditor):
        assert module.PACKAGING_SNAPSHOT == PACKAGING_SNAPSHOT_PATH
        assert module.PACKAGING_SNAPSHOT_SHA256 == actual_snapshot_sha
        assert module.PACKAGING_WHEEL_SHA256 == launcher.PACKAGING_WHEEL_SHA256
        assert (
            module.PACKAGING_MEMBER_MANIFEST_SHA256
            == launcher.PACKAGING_MEMBER_MANIFEST_SHA256
        )
    assert f"readonly PACKAGING_SNAPSHOT_SHA256={actual_snapshot_sha}" in wrapper

    v1 = generator.load_v1()
    assert v1.SOURCE_ROOT == launcher.SOURCE_ROOT == generator.SOURCE_ROOT
    assert v1.SOURCE_REVISION == launcher.SOURCE_REVISION == generator.SOURCE_REVISION
    assert v1.SOURCE_TREE == launcher.SOURCE_TREE == generator.SOURCE_TREE
    assert v1.VERIFIERS_REVISION == generator.VERIFIERS_REVISION
    assert v1.RENDERERS_REVISION == generator.RENDERERS_REVISION
    assert v1.PYDANTIC_CONFIG_REVISION == generator.PYDANTIC_CONFIG_REVISION
    assert v1.VMVM_SHA256 == generator.VMVM_SHA256
    assert v1.WORKFLOW == generator.WORKFLOW
    assert v1.PINNED_SOURCE_FILES == generator.PINNED_SOURCE_FILES
    assert generator.SOURCE_REVISION == "5873430ffbabc32672368c7df74f56023865d2b5"
    assert generator.SOURCE_TREE == "e7d9d5a8cf4ca06b9ff6496ea4318154c6fcd730"
    assert generator.VERIFIERS_REVISION == "615b1a30ee3d23cf8d835b64174229c19da887bc"
    assert generator.PINNED_SOURCE_FILES[
        generator.WORKFLOW / "terminal_bench_vmvm/taskset.py"
    ] == "94d12722279f11ccd34b00c28d00db545c4f254af907af4ee774b0e1c7079330"
    shell_40_pins = {
        "SOURCE_REVISION": launcher.SOURCE_REVISION,
        "SOURCE_TREE": launcher.SOURCE_TREE,
        "VERIFIERS_REVISION": v1.VERIFIERS_REVISION,
        "RENDERERS_REVISION": v1.RENDERERS_REVISION,
        "PYDANTIC_CONFIG_REVISION": v1.PYDANTIC_CONFIG_REVISION,
        "DATASET_REVISION_EXPECTED": launcher.DATASET_REVISION,
    }
    assert all(re.fullmatch(r"[0-9a-f]{40}", value) for value in shell_40_pins.values())
    for name, value in shell_40_pins.items():
        assert re.search(rf"^readonly {name}={value}$", wrapper, re.MULTILINE)
    assert re.search(
        rf"^readonly VMVM_SHA256={generator.VMVM_SHA256}$", wrapper, re.MULTILINE
    )

    stale_artifact_hashes = {
        "d3a78639e7a4c32eca711aba8b77eb365c508a439ade4df248eac559525e1233",
        "a5017ab08cccadb5ddc757a988e483d9f869d40c63f9de49a3fa22036941101f",
        "0a2334eb46da8686ae2997e3f4c26ba944b117cdb62c191f4926ea3a418b297c",
        "63dd643307bdde16435e7cd883fcb0ea7c86e85816e9ed4eeb28f9a913cb697b",
        "ba36a8c4e6e490f612e58495dc391f2ab3f816e8af253773ec10375656360ea3",
        "99bbab5a9ed0fa48234c52340a83040ef7e5821b18e8c92c16a82b3fa42c2b49",
        "6d978116442a8a1173e9a152bf9bc257fc38b6a843737f668c29b34d2f29bed7",
        "85227dcbb79d3a2ab8ae6cc37e982ad9386062534e95c658ad60afef14a09c2f",
        "36afb9be27aa59762c76d981922975358cf14ca9ea81891e97478aaf609c2628",
        "f2136f2fe16fecf221e7a8018e87528f36c6f1c8b1ea620666dee2e8e962a76c",
        "78008249a03f1133d80d8dca817ee609a894734d5c0c0fa97a2253351a622155",
        "05321356cfcb88ee4c7a3d85ade0b4a680226d2e1db05333f63f70c84eb3a332",
        "18476987d78a2daf54d554b1a4ff1d9d14c47b65f443bc68e1bb1754395499e4",
        "2cf63b39b22834c7bfe384f742167f09753d2dd6f85ac254ba3ddfa893e61a0f",
        "2af793a8e8c2f191de46eada28e875a42226a9908d1bb49f3f992d1fb359fa67",
        "978291021293a8578e3750bb64207f6953e8a5afc6bdf6acebbc56ca87a7dfec",
        "c670dcbb078ebe0d003ce41cb13bea30b42a7510927c0b1e4ece827cb448caee",
        "450cfbfcd267a1b0d4970296f2c229769ad0c1ebb179af48f67c97f3fa5bb218",
        "46ba84d8a80fdcfa4d75b98beb8c609341f20504716fafec3ecb33aeaf380f84",
        "0852602962bb2db2fadd68f1aa5b014e8cc9230d901c446564b95353a60bcd85",
        "aa3601965803322e778a7f4861b9e547bb48948d42de1a5894a116e9c4e2247c",
        "9c7bc00ed87937085068809be5e047280faf74eb5ea5189760866b64e6041e9e",
        "f1956dfd1f16b77e1aadae82c1c34e33736925e98e1a51b8575b46593cd18bff",
        "2a194db2dfc4eba760707f422f24a3e7afe36bb5e669126794aa501861dbf361",
        "1cef20e6a56544e11fc40c742d4ca655d75ac963dee6c11cc5a0eb75d42e4af6",
        "08a31dfc875f52ec8ae220d880331638a77ed8e277e48c91050bc70a9abde455",
        "8be2fb748d187366f10cce2422ea5a39db4b58b7616d58bede10f0c6440022f9",
        "f942cea514105b8c286daf3f7d961c5099e33f04f8fbdf475df20e6a690accc3",
        "8bc801cf7e77a05e80c949fe19aa0091d56355a34ff42cfd3cadeddec9d64f00",
        "aef61d0f4e93b3778141c50849bd9e71704ee7032fe19e3e94b320ddace83ec4",
        "44b30c80b03f4a225f749899bb9c9ecd140fad2926f7e85b8b58bf35943051c1",
        "7b74291592cfded391f5559769c298c2a700ec63e81f2f4f2342364907b9f0f4",
        "a254fcb4513f54577419c208a0357e4b11cc6ed4693f0b991834e16bb254e4fe",
    }
    assert stale_artifact_hashes.isdisjoint(
        re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", production_text)
    )
    assert not re.search(
        r"(?:infrastructure_retry_(?:canary|selection)|mobius_infrastructure_retry_"
        r"(?:selection|run|audit))[^\n]*_v(?:3|4|5|6|7|8|9|10|11|12|13|14|15|16|17|18|19|20|21)\b",
        production_text,
    )
    for source in (GENERATOR_PATH, LAUNCHER_PATH, AUDITOR_PATH):
        text = source.read_text(encoding="utf-8")
        assert "APPROVED_RETRY_" in text
        assert "stable_file(SELF" in text or "file_bytes(CANONICAL_SELF" in text


def test_v22_namespaces_are_fresh_and_bound_to_the_integrated_source() -> None:
    launcher = load_launcher()
    paths = {
        launcher.ARTIFACT_ROOT,
        launcher.SOURCE_ROOT,
        launcher.SELECTION_ROOT,
        launcher.OUTPUT_ROOT,
        launcher.RESERVATION,
        launcher.LOG_ROOT,
    }
    assert len(paths) == 6
    assert all("v22" in str(path) and "v21" not in str(path) for path in paths)
    assert launcher.SOURCE_ROOT.name == "prime-rl-5873430ff-v22"
    assert launcher.SOURCE_REVISION == "5873430ffbabc32672368c7df74f56023865d2b5"
    assert launcher.SOURCE_TREE == "e7d9d5a8cf4ca06b9ff6496ea4318154c6fcd730"
    assert launcher.VERIFIERS_REVISION == (
        "615b1a30ee3d23cf8d835b64174229c19da887bc"
    )


def test_slurm_environment_is_bounded_and_encodes_exception_scope() -> None:
    launcher = load_launcher()
    token = "4" * 24
    job_name = f"mirc-{token}"
    auth = launcher.RESERVATION / f"job_authorization_{token}.json"
    permit = launcher.RESERVATION / f"activation_permit_{token}.json"
    environment = launcher.slurm_environment(
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        launcher_sha="7" * 64,
        token=token,
        job_name=job_name,
        authorization_path=auth,
        authorization_sha="5" * 64,
        activation_permit_path=permit,
        activation_permit_sha="6" * 64,
        private_tls_values=synthetic_tls_values(),
        private_x2p_values=synthetic_x2p_values(),
    )
    assert environment["MAX_CONCURRENT"] == "4"
    assert environment["VACLI_MAX_CONCURRENT_LEASES"] == "2"
    assert environment["INFRA_RETRIES"] == "4"
    assert environment["SETUP_TIMEOUT"] == "7200"
    assert environment["VALIDATE_TIMEOUT"] == "21600"
    assert environment["SESSION_TIMEOUT"] == "43200"
    assert environment["RETRY_EXCEPTION_CLASS"] == "SandboxError"
    assert environment["ASYNCIO_TIMEOUT_MAX_ATTEMPTS"] == "1"
    assert environment["BROAD_HARNESS_ERROR_RETRY"] == "0"
    assert environment["MINIMUM_VALID"] == "10"
    assert environment["RERUN_INVALID"] == "0"
    assert environment["RETRY_EXPECTED_JOB_NAME"] == job_name
    assert environment["RETRY_AUTHORIZATION_FILE"] == str(auth)
    assert environment["RETRY_AUTHORIZATION_SHA256"] == "5" * 64
    assert environment["RETRY_ACTIVATION_PERMIT_FILE"] == str(permit)
    assert environment["RETRY_ACTIVATION_PERMIT_SHA256"] == "6" * 64
    assert {name: environment[name] for name in launcher.X2P_NAMES} == (
        synthetic_x2p_values()
    )
    assert {
        name: environment[launcher.X2P_DIGEST_ENV_NAMES[name]]
        for name in launcher.X2P_NAMES
    } == synthetic_x2p_sha256()
    assert environment["RETRY_LAUNCH_TOKEN"] == token
    assert environment["RETRY_LAUNCHER_SHA256"] == "7" * 64
    assert environment["RETRY_VERIFIERS_REVISION"] == launcher.VERIFIERS_REVISION
    assert environment["RETRY_VMVM_SHA256"] == launcher.VMVM_SHA256
    assert environment["SELECTION_RECEIPT_SHA256"] == "4" * 64
    assert {
        key: environment[key]
        for key in (
            "THRIFT_TLS_CL_CERT_PATH",
            "THRIFT_TLS_CL_KEY_PATH",
            "RETRY_THRIFT_TLS_CL_CERT_SHA256",
            "RETRY_THRIFT_TLS_CL_KEY_SHA256",
        )
    } == synthetic_tls_values()


def test_x2p_tuple_is_all_or_none_hash_bound_and_round_trips_privately() -> None:
    launcher = load_launcher()
    values = synthetic_x2p_values()
    commitments = synthetic_x2p_sha256()
    assert launcher.capture_x2p_environment(values) == values
    assert launcher.x2p_environment_sha256(values) == commitments
    private = launcher.private_x2p_environment(values)
    assert {name: private[name] for name in launcher.X2P_NAMES} == values
    assert {
        name: private[launcher.X2P_DIGEST_ENV_NAMES[name]]
        for name in launcher.X2P_NAMES
    } == commitments
    raw = launcher.environment_bytes({"PUBLIC": "fixed", **private})
    assert launcher.parse_private_x2p_environment(raw) == values

    for missing in launcher.X2P_NAMES:
        changed = dict(values)
        changed.pop(missing)
        with pytest.raises(launcher.LauncherError, match="^x2p_environment_invalid$"):
            launcher.capture_x2p_environment(changed)
    for invalid in ("", "line\nbreak", "carriage\rreturn", "x" * 4097):
        changed = {**values, "X2P_PROXY_URL": invalid}
        with pytest.raises(launcher.LauncherError, match="^x2p_environment_invalid$"):
            launcher.capture_x2p_environment(changed)

    drifted = dict(private)
    drifted[launcher.X2P_DIGEST_ENV_NAMES["X2P_PROXY_URL"]] = "0" * 64
    with pytest.raises(
        launcher.LauncherError, match="^x2p_environment_commitment_invalid$"
    ):
        launcher.parse_private_x2p_environment(
            launcher.environment_bytes({"PUBLIC": "fixed", **drifted})
        )


def test_sbatch_uses_one_complete_export_file_without_conflicting_export_flag(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    command = launcher.sbatch_command("mirc-" + "4" * 24)
    export_arguments = [argument for argument in command if argument.startswith("--export")]
    assert export_arguments == [f"--export-file={launcher.ENVIRONMENT_FILE}"]
    assert "--export=NONE" not in command
    assert "--export" not in command
    assert inspect.getsource(launcher.invoke_sbatch).count("env=clean_environment()") == 1
    assert all(value not in command for value in synthetic_x2p_values().values())

    observed: dict[str, object] = {}

    class CompletedProcess:
        returncode = 0

        def wait(self, timeout):
            observed["timeout"] = timeout
            return self.returncode

        def poll(self):
            return self.returncode

    def popen(arguments, **kwargs):
        observed["arguments"] = arguments
        observed["environment"] = kwargs["env"]
        observed["cwd"] = kwargs["cwd"]
        return CompletedProcess()

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    assert launcher.invoke_sbatch(command) == ("completed", 0, "")
    assert observed["arguments"] == command
    assert observed["environment"] == launcher.clean_environment()
    assert not set(launcher.X2P_NAMES) & set(observed["environment"])
    assert observed["cwd"] == launcher.SOURCE_ROOT


def test_tls_credential_capture_is_fd_stable_and_private(tmp_path: Path) -> None:
    launcher = load_launcher()
    environment = write_synthetic_tls_pair(tmp_path)
    bindings = launcher.capture_tls_credentials(environment)
    try:
        launcher.revalidate_tls_credentials(bindings)
        private = launcher.private_tls_environment(bindings)
        assert set(private) == {
            "THRIFT_TLS_CL_CERT_PATH",
            "THRIFT_TLS_CL_KEY_PATH",
            "RETRY_THRIFT_TLS_CL_CERT_SHA256",
            "RETRY_THRIFT_TLS_CL_KEY_SHA256",
        }
        assert all("private" in repr(binding) for binding in bindings.values())
        assert private["THRIFT_TLS_CL_CERT_PATH"] == environment[
            "THRIFT_TLS_CL_CERT_PATH"
        ]
        assert private["THRIFT_TLS_CL_KEY_PATH"] == environment[
            "THRIFT_TLS_CL_KEY_PATH"
        ]
        assert private["RETRY_THRIFT_TLS_CL_CERT_SHA256"] == hashlib.sha256(
            b"C" * 5580
        ).hexdigest()
        assert private["RETRY_THRIFT_TLS_CL_KEY_SHA256"] == hashlib.sha256(
            b"K" * 5580
        ).hexdigest()
    finally:
        launcher.close_tls_credentials(bindings)


def test_combined_tls_bundle_accepts_same_noncanonical_alias_and_exports_target(
    tmp_path: Path,
) -> None:
    launcher = load_launcher()
    environment, canonical_bundle, _alias_parent = write_combined_tls_alias(tmp_path)
    bindings = launcher.capture_tls_credentials(environment)
    try:
        launcher.revalidate_tls_credentials(bindings)
        private = launcher.private_tls_environment(bindings)
        assert private["THRIFT_TLS_CL_CERT_PATH"] == str(canonical_bundle)
        assert private["THRIFT_TLS_CL_KEY_PATH"] == str(canonical_bundle)
        assert (
            private["RETRY_THRIFT_TLS_CL_CERT_SHA256"]
            == private["RETRY_THRIFT_TLS_CL_KEY_SHA256"]
            == hashlib.sha256(combined_pem_bytes()).hexdigest()
        )
        assert {binding.pem_profile for binding in bindings.values()} == {"combined"}
        assert {
            binding.signature[:2] for binding in bindings.values()
        } == {bindings["THRIFT_TLS_CL_CERT_PATH"].signature[:2]}
    finally:
        launcher.close_tls_credentials(bindings)


def test_combined_tls_bundle_accepts_distinct_aliases_to_one_target(
    tmp_path: Path,
) -> None:
    launcher = load_launcher()
    environment, canonical_bundle, alias_parent = write_combined_tls_alias(tmp_path)
    second_alias_parent = tmp_path / "alias-two"
    second_alias_parent.symlink_to(canonical_bundle.parent, target_is_directory=True)
    environment["THRIFT_TLS_CL_KEY_PATH"] = str(second_alias_parent / canonical_bundle.name)
    bindings = launcher.capture_tls_credentials(environment)
    try:
        private = launcher.private_tls_environment(bindings)
        assert {private[name] for name in launcher.TLS_PATH_ENV_NAMES} == {
            str(canonical_bundle)
        }
        assert alias_parent.is_symlink() and second_alias_parent.is_symlink()
    finally:
        launcher.close_tls_credentials(bindings)


def test_combined_tls_bundle_accepts_whitespace_only_gaps(tmp_path: Path) -> None:
    launcher = load_launcher()
    environment, _bundle, _alias = write_combined_tls_alias(
        tmp_path, raw=combined_pem_bytes(gap=b"\n \t\r\n")
    )
    bindings = launcher.capture_tls_credentials(environment)
    try:
        launcher.revalidate_tls_credentials(bindings)
    finally:
        launcher.close_tls_credentials(bindings)


@pytest.mark.parametrize(
    "raw",
    (
        combined_pem_bytes(labels=(b"CERTIFICATE", b"RSA PRIVATE KEY")),
        combined_pem_bytes(
            labels=(b"CERTIFICATE", b"CERTIFICATE", b"CERTIFICATE")
        ),
        combined_pem_bytes(
            labels=(b"CERTIFICATE", b"CERTIFICATE", b"PRIVATE KEY")
        ),
        combined_pem_bytes(
            labels=(b"CERTIFICATE", b"CERTIFICATE", b"EC PRIVATE KEY")
        ),
        combined_pem_bytes(
            labels=(b"CERTIFICATE", b"CERTIFICATE", b"ENCRYPTED PRIVATE KEY")
        ),
        combined_pem_bytes(
            labels=(
                b"CERTIFICATE",
                b"CERTIFICATE",
                b"RSA PRIVATE KEY",
                b"CERTIFICATE",
            )
        ),
        combined_pem_bytes(
            labels=(
                b"CERTIFICATE",
                b"RSA PRIVATE KEY",
                b"CERTIFICATE",
                b"PRIVATE KEY",
            )
        ),
        malformed_delimiter_pem(),
        malformed_base64_pem(),
        nonwhitespace_gap_pem(),
    ),
)
def test_shared_tls_binding_rejects_malformed_or_wrong_pem_structure(
    tmp_path: Path, raw: bytes
) -> None:
    launcher = load_launcher()
    environment, _bundle, _alias = write_combined_tls_alias(tmp_path, raw=raw)
    with pytest.raises(launcher.LauncherError, match="^tls_credential_pair_invalid$"):
        launcher.capture_tls_credentials(environment)


def test_equal_tls_digest_on_distinct_inodes_is_rejected(tmp_path: Path) -> None:
    launcher = load_launcher()
    raw = combined_pem_bytes()
    certificate = tmp_path / "first.pem"
    key = tmp_path / "second.pem"
    for path in (certificate, key):
        path.write_bytes(raw)
        path.chmod(0o500)
    with pytest.raises(launcher.LauncherError, match="^tls_credential_pair_invalid$"):
        launcher.capture_tls_credentials(
            {
                "THRIFT_TLS_CL_CERT_PATH": str(certificate),
                "THRIFT_TLS_CL_KEY_PATH": str(key),
            }
        )


@pytest.mark.parametrize("mutation", ("parent_alias", "canonical_target"))
def test_combined_tls_binding_rejects_alias_and_target_swaps(
    tmp_path: Path, mutation: str
) -> None:
    launcher = load_launcher()
    environment, canonical_bundle, alias_parent = write_combined_tls_alias(tmp_path)
    bindings = launcher.capture_tls_credentials(environment)
    try:
        if mutation == "parent_alias":
            replacement_parent = tmp_path / "replacement"
            replacement_parent.mkdir()
            replacement = replacement_parent / canonical_bundle.name
            replacement.write_bytes(combined_pem_bytes())
            replacement.chmod(0o500)
            alias_parent.unlink()
            alias_parent.symlink_to(replacement_parent, target_is_directory=True)
        else:
            canonical_bundle.rename(canonical_bundle.with_suffix(".displaced"))
            canonical_bundle.write_bytes(combined_pem_bytes())
            canonical_bundle.chmod(0o500)
        with pytest.raises(launcher.LauncherError, match="^tls_credential_changed$"):
            launcher.revalidate_tls_credentials(bindings)
    finally:
        launcher.close_tls_credentials(bindings)


def test_combined_tls_capture_rejects_parent_alias_swap_mid_capture(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    environment, canonical_bundle, alias_parent = write_combined_tls_alias(tmp_path)
    replacement_parent = tmp_path / "replacement"
    replacement_parent.mkdir()
    replacement = replacement_parent / canonical_bundle.name
    replacement.write_bytes(combined_pem_bytes())
    replacement.chmod(0o500)
    real_readlink = launcher.os.readlink
    swapped = False

    def swap_after_descriptor_resolution(path):
        nonlocal swapped
        resolved = real_readlink(path)
        if not swapped and str(path).startswith("/proc/self/fd/"):
            swapped = True
            alias_parent.unlink()
            alias_parent.symlink_to(replacement_parent, target_is_directory=True)
        return resolved

    monkeypatch.setattr(launcher.os, "readlink", swap_after_descriptor_resolution)
    with pytest.raises(launcher.LauncherError, match="^tls_credential_changed$"):
        launcher.capture_tls_credentials(environment)
    assert swapped


@pytest.mark.parametrize("mutation", ("absent", "relative", "mode", "size", "symlink"))
def test_tls_credential_capture_rejects_invalid_input(
    tmp_path: Path, mutation: str
) -> None:
    launcher = load_launcher()
    environment = write_synthetic_tls_pair(tmp_path)
    certificate = Path(environment["THRIFT_TLS_CL_CERT_PATH"])
    if mutation == "absent":
        environment.pop("THRIFT_TLS_CL_KEY_PATH")
    elif mutation == "relative":
        environment["THRIFT_TLS_CL_KEY_PATH"] = "client.key"
    elif mutation == "mode":
        certificate.chmod(0o600)
    elif mutation == "size":
        certificate.chmod(0o700)
        certificate.write_bytes(b"C" * 5579)
        certificate.chmod(0o500)
    else:
        target = tmp_path / "target.crt"
        certificate.rename(target)
        certificate.symlink_to(target.name)
    with pytest.raises(
        launcher.LauncherError,
        match="^tls_credential_(?:environment_)?invalid$",
    ):
        launcher.capture_tls_credentials(environment)


@pytest.mark.parametrize("mutation", ("replace", "content", "mode", "parent"))
def test_tls_credential_revalidation_rejects_races(
    tmp_path: Path, mutation: str
) -> None:
    launcher = load_launcher()
    environment = write_synthetic_tls_pair(tmp_path)
    bindings = launcher.capture_tls_credentials(environment)
    certificate = Path(environment["THRIFT_TLS_CL_CERT_PATH"])
    try:
        if mutation == "replace":
            certificate.rename(tmp_path / "displaced.crt")
            certificate.write_bytes(b"C" * 5580)
            certificate.chmod(0o500)
        elif mutation == "content":
            certificate.chmod(0o700)
            certificate.write_bytes(b"X" * 5580)
            certificate.chmod(0o500)
        elif mutation == "mode":
            certificate.chmod(0o700)
        else:
            displaced = tmp_path.with_name(tmp_path.name + "-displaced")
            tmp_path.rename(displaced)
            tmp_path.mkdir()
        with pytest.raises(launcher.LauncherError, match="^tls_credential_changed$"):
            launcher.revalidate_tls_credentials(bindings)
    finally:
        launcher.close_tls_credentials(bindings)


def test_outer_environment_requires_exact_tls_and_x2p_allowlist() -> None:
    launcher = load_launcher()
    environment = {
        "APPROVED_RETRY_LAUNCHER_SHA256": "a" * 64,
        "HOME": "/storage/home/tianhaowu",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": "tianhaowu",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "THRIFT_TLS_CL_CERT_PATH": "/private/tls/client.crt",
        "THRIFT_TLS_CL_KEY_PATH": "/private/tls/client.key",
        **synthetic_x2p_values(),
        "TMUX": "/tmp/tmux,1,0",
        "TMUX_PANE": "%1",
        "USER": "tianhaowu",
    }
    launcher._validate_outer_environment(environment)
    for mutation in ("missing_tls", "missing_x2p", "empty_x2p", "extra"):
        changed = dict(environment)
        if mutation == "missing_tls":
            changed.pop("THRIFT_TLS_CL_KEY_PATH")
        elif mutation == "missing_x2p":
            changed.pop("X2P_PROXY_URL")
        elif mutation == "empty_x2p":
            changed["X2P_PROXY_URL"] = ""
        else:
            changed["PYTHONPATH"] = "/tmp/shadow"
        if mutation == "empty_x2p":
            launcher._validate_outer_environment(changed)
            with pytest.raises(launcher.LauncherError, match="^x2p_environment_invalid$"):
                launcher.capture_x2p_environment(changed)
        else:
            with pytest.raises(launcher.LauncherError, match="^outer_environment_invalid$"):
                launcher._validate_outer_environment(changed)


def test_tls_values_are_confined_to_private_export() -> None:
    launcher = load_launcher()
    token = "4" * 24
    auth_path, auth_raw, auth_sha = launcher.authorization_bytes(
        launcher_sha="7" * 64,
        token=token,
        job_name=f"mirc-{token}",
        task_sha="1" * 64,
        role_sha="2" * 64,
        receipt_file_sha="3" * 64,
        receipt_sha="4" * 64,
        x2p_sha256=synthetic_x2p_sha256(),
    )
    _permit_path, permit_raw, _permit_sha = launcher.activation_permit_bytes(
        token=token,
        job_name=f"mirc-{token}",
        authorization_sha=auth_sha,
    )
    terminal_raw = launcher.canonical_json(
        launcher.terminal_body(
            state="failed",
            code="synthetic_failure",
            launcher_sha="7" * 64,
            intent_file_sha="6" * 64,
            environment_sha="5" * 64,
            task_sha="1" * 64,
            role_sha="2" * 64,
            receipt_file_sha="3" * 64,
            receipt_sha="4" * 64,
            job_id=None,
            job_name=f"mirc-{token}",
            token=token,
            authorization_path=auth_path,
            authorization_sha=auth_sha,
            activation_permit_path=_permit_path,
            activation_permit_sha=_permit_sha,
            x2p_sha256=synthetic_x2p_sha256(),
            held_validation=None,
            release=None,
            cancellation=None,
        )
    )
    secrets = tuple(synthetic_tls_values().values()) + tuple(
        synthetic_x2p_values().values()
    ) + (
        "/canonical/private/combined.pem",
        "deadbeef" * 8,
    )
    assert all(value.encode() not in auth_raw for value in secrets)
    assert all(value.encode() not in permit_raw for value in secrets)
    assert all(value.encode() not in terminal_raw for value in secrets)
    assert b"THRIFT_TLS" not in auth_raw + permit_raw + terminal_raw
    assert all(
        digest.encode() in auth_raw + terminal_raw
        for digest in synthetic_x2p_sha256().values()
    )
    assert auth_path.parent == launcher.RESERVATION


def test_batch_revalidates_tls_under_exact_isolated_environment(tmp_path: Path) -> None:
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"/usr/bin/python3 -I -S -B - <<'PY' >/dev/null 2>/dev/null\n(.*?)\nPY",
        wrapper,
        re.DOTALL,
    )
    assert match is not None
    paths = write_synthetic_tls_pair(tmp_path)
    environment = {
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        **paths,
        "RETRY_THRIFT_TLS_CL_CERT_SHA256": hashlib.sha256(b"C" * 5580).hexdigest(),
        "RETRY_THRIFT_TLS_CL_KEY_SHA256": hashlib.sha256(b"K" * 5580).hexdigest(),
    }
    command = ["/usr/bin/python3", "-I", "-S", "-B", "-"]
    accepted = subprocess.run(
        command,
        check=False,
        input=match.group(1).encode(),
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert accepted.returncode == 0 and accepted.stdout == b"" and accepted.stderr == b""
    combined = tmp_path / "combined.pem"
    combined_raw = combined_pem_bytes()
    combined.write_bytes(combined_raw)
    combined.chmod(0o500)
    combined_digest = hashlib.sha256(combined_raw).hexdigest()
    combined_environment = {
        **environment,
        "THRIFT_TLS_CL_CERT_PATH": str(combined),
        "THRIFT_TLS_CL_KEY_PATH": str(combined),
        "RETRY_THRIFT_TLS_CL_CERT_SHA256": combined_digest,
        "RETRY_THRIFT_TLS_CL_KEY_SHA256": combined_digest,
    }
    combined_accepted = subprocess.run(
        command,
        check=False,
        input=match.group(1).encode(),
        capture_output=True,
        env=combined_environment,
        timeout=10,
    )
    assert (
        combined_accepted.returncode == 0
        and combined_accepted.stdout == b""
        and combined_accepted.stderr == b""
    )
    whitespace_raw = combined_pem_bytes(gap=b"\n \t\r\n")
    combined.chmod(0o700)
    combined.write_bytes(whitespace_raw)
    combined.chmod(0o500)
    whitespace_digest = hashlib.sha256(whitespace_raw).hexdigest()
    whitespace_environment = {
        **combined_environment,
        "RETRY_THRIFT_TLS_CL_CERT_SHA256": whitespace_digest,
        "RETRY_THRIFT_TLS_CL_KEY_SHA256": whitespace_digest,
    }
    whitespace_accepted = subprocess.run(
        command,
        check=False,
        input=match.group(1).encode(),
        capture_output=True,
        env=whitespace_environment,
        timeout=10,
    )
    assert (
        whitespace_accepted.returncode == 0
        and whitespace_accepted.stdout == b""
        and whitespace_accepted.stderr == b""
    )
    malformed_variants = (
        combined_pem_bytes(
            labels=(b"CERTIFICATE", b"CERTIFICATE", b"PRIVATE KEY")
        ),
        combined_pem_bytes(
            labels=(b"CERTIFICATE", b"CERTIFICATE", b"EC PRIVATE KEY")
        ),
        combined_pem_bytes(
            labels=(b"CERTIFICATE", b"CERTIFICATE", b"ENCRYPTED PRIVATE KEY")
        ),
        combined_pem_bytes(
            labels=(
                b"CERTIFICATE",
                b"CERTIFICATE",
                b"RSA PRIVATE KEY",
                b"CERTIFICATE",
            )
        ),
        combined_pem_bytes(
            labels=(
                b"CERTIFICATE",
                b"RSA PRIVATE KEY",
                b"CERTIFICATE",
                b"PRIVATE KEY",
            )
        ),
        malformed_delimiter_pem(),
        malformed_base64_pem(),
        nonwhitespace_gap_pem(),
    )
    for malformed_raw in malformed_variants:
        combined.chmod(0o700)
        combined.write_bytes(malformed_raw)
        combined.chmod(0o500)
        malformed_digest = hashlib.sha256(malformed_raw).hexdigest()
        malformed_environment = {
            **combined_environment,
            "RETRY_THRIFT_TLS_CL_CERT_SHA256": malformed_digest,
            "RETRY_THRIFT_TLS_CL_KEY_SHA256": malformed_digest,
        }
        malformed = subprocess.run(
            command,
            check=False,
            input=match.group(1).encode(),
            capture_output=True,
            env=malformed_environment,
            timeout=10,
        )
        assert malformed.returncode != 0
    for mutation in ("absent", "mode", "hash", "extra"):
        changed = dict(environment)
        certificate = Path(paths["THRIFT_TLS_CL_CERT_PATH"])
        certificate.chmod(0o500)
        if mutation == "absent":
            changed.pop("THRIFT_TLS_CL_KEY_PATH")
        elif mutation == "mode":
            certificate.chmod(0o600)
        elif mutation == "hash":
            changed["RETRY_THRIFT_TLS_CL_CERT_SHA256"] = "0" * 64
        else:
            changed["PYTHONPATH"] = "/tmp/shadow"
        rejected = subprocess.run(
            command,
            check=False,
            input=match.group(1).encode(),
            capture_output=True,
            env=changed,
            timeout=10,
        )
        assert rejected.returncode != 0
    assert wrapper.count("validate_tls_credentials || fail") == 2
    assert 'exec /bin/bash "$RUN_ORACLE"' in wrapper


def _batch_environment_gate_program() -> str:
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    prefix_start = wrapper.index("set -euo pipefail")
    prefix_end = wrapper.index("\nif (( $# != 0 )); then", prefix_start)
    gate_start = wrapper.index("pre_admission_stage=environment_binding")
    gate_marker = "pre_admission_stage=permit_wait"
    gate_end = wrapper.index(gate_marker, gate_start) + len(gate_marker)
    return (
        wrapper[prefix_start:prefix_end]
        + "\n"
        + wrapper[gate_start:gate_end]
        + "\n/usr/bin/printf 'stage=%s\\n' \"$pre_admission_stage\"\n"
    )


def test_launcher_export_reaches_batch_admission_wait_and_rejects_injection(
    tmp_path: Path,
) -> None:
    launcher = load_launcher()
    token = "4" * 24
    job_name = f"mirc-{token}"
    combined = tmp_path / "combined.pem"
    combined_raw = combined_pem_bytes()
    combined.write_bytes(combined_raw)
    combined.chmod(0o500)
    combined_digest = hashlib.sha256(combined_raw).hexdigest()
    tls_values = {
        "THRIFT_TLS_CL_CERT_PATH": str(combined),
        "THRIFT_TLS_CL_KEY_PATH": str(combined),
        "RETRY_THRIFT_TLS_CL_CERT_SHA256": combined_digest,
        "RETRY_THRIFT_TLS_CL_KEY_SHA256": combined_digest,
    }
    environment = launcher.slurm_environment(
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        launcher_sha="7" * 64,
        token=token,
        job_name=job_name,
        authorization_path=launcher.RESERVATION / f"job_authorization_{token}.json",
        authorization_sha="5" * 64,
        activation_permit_path=launcher.RESERVATION
        / f"activation_permit_{token}.json",
        activation_permit_sha="6" * 64,
        private_tls_values=tls_values,
        private_x2p_values=synthetic_x2p_values(),
    )
    environment["SLURM_JOB_NAME"] = job_name
    command = ["/bin/bash", "--noprofile", "--norc", "-p", "-c", _batch_environment_gate_program()]
    accepted = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=environment,
        timeout=15,
    )
    assert accepted.returncode == 0
    assert accepted.stdout == b"stage=permit_wait\n"
    assert accepted.stderr == b""

    mutations = (
        ("UV_BIN_X86_64", None),
        ("UV_BIN_X86_64", "/unapproved/uv"),
        ("UV_CONFIG_FILE", "/unapproved/uv.toml"),
        ("GIT_CONFIG_GLOBAL", "/unapproved/gitconfig"),
        ("PYTHON_BIN_X86_64", "python"),
        ("PYTHON_SITE_X86_64", "/unapproved/site"),
        ("PYTHONSAFEPATH", "1"),
        ("SLURM_EXPORT_ENV", "ALL"),
        ("TZ", "Etc/UTC"),
    )
    for key, value in mutations:
        changed = dict(environment)
        if value is None:
            changed.pop(key)
        else:
            changed[key] = value
        rejected = subprocess.run(
            command,
            check=False,
            capture_output=True,
            env=changed,
            timeout=15,
        )
        assert rejected.returncode == 2, key
        assert rejected.stdout == b"", key
        assert rejected.stderr == (
            b'{"code":"job_binding_failed","stage":"environment_binding"}\n'
        ), key

    for key, value in (
        ("X2P_ENV", None),
        ("X2P_CFG_ENV", ""),
        ("X2P_PROXY_URL", "rotated-private-value"),
        ("RETRY_X2P_ENV_SHA256", "0" * 64),
    ):
        changed = dict(environment)
        if value is None:
            changed.pop(key)
        else:
            changed[key] = value
        rejected = subprocess.run(
            command,
            check=False,
            capture_output=True,
            env=changed,
            timeout=15,
        )
        assert rejected.returncode == 2, key
        assert rejected.stdout == b"", key
        assert rejected.stderr == (
            b'{"code":"job_binding_failed","stage":"environment_binding"}\n'
        ), key
        assert str(combined).encode() not in rejected.stderr
        assert combined_digest.encode() not in rejected.stderr
        assert all(
            private.encode() not in rejected.stdout + rejected.stderr
            for private in synthetic_x2p_values().values()
        )


def test_batch_failure_telemetry_is_coarse_and_allowlisted() -> None:
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    prefix_start = wrapper.index("set -euo pipefail")
    prefix_end = wrapper.index("\nif (( $# != 0 )); then", prefix_start)
    prefix = wrapper[prefix_start:prefix_end]
    expected = b'{"code":"job_binding_failed","stage":"unknown"}\n'
    result = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-p",
            "-c",
            prefix
            + "\npre_admission_stage='private/value with spaces'\n"
            + "fail\n",
        ],
        check=False,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == expected
    assert b"private" not in result.stderr


def test_private_tls_pair_shape_accepts_only_coherent_alias_equality() -> None:
    launcher = load_launcher()
    combined = {
        "THRIFT_TLS_CL_CERT_PATH": "/canonical/private/combined.pem",
        "THRIFT_TLS_CL_KEY_PATH": "/canonical/private/combined.pem",
        "RETRY_THRIFT_TLS_CL_CERT_SHA256": "8" * 64,
        "RETRY_THRIFT_TLS_CL_KEY_SHA256": "8" * 64,
    }
    assert launcher.validate_private_tls_environment(combined) == combined
    for key, value in (
        ("THRIFT_TLS_CL_KEY_PATH", "/canonical/private/key.pem"),
        ("RETRY_THRIFT_TLS_CL_KEY_SHA256", "9" * 64),
    ):
        changed = dict(combined)
        changed[key] = value
        with pytest.raises(
            launcher.LauncherError, match="^tls_credential_binding_invalid$"
        ):
            launcher.validate_private_tls_environment(changed)


@pytest.mark.skipif(
    __import__("os").environ.get("RUN_V22_TLS_REAL_INPUT_REGRESSION") != "1",
    reason="requires separate approval and canonical env-i pane",
)
def test_gated_real_tls_binding_under_isolated_python() -> None:
    launcher = load_launcher()
    program = f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location('retry_v22_tls_gate', {str(LAUNCHER_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
bindings = module.capture_tls_credentials()
try:
    module.revalidate_tls_credentials(bindings)
    values = module.private_tls_environment(bindings)
    print(json.dumps({{'state':'validated_tls_inputs','credentials':len(bindings),'private_fields':len(values)}}, separators=(',',':'), sort_keys=True))
finally:
    module.close_tls_credentials(bindings)
"""
    result = subprocess.run(
        [str(launcher.PYTHON_REAL), "-I", "-S", "-B", "-c", program],
        check=False,
        capture_output=True,
        cwd="/storage/home/tianhaowu",
        env={
            "HOME": "/storage/home/tianhaowu",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "THRIFT_TLS_CL_CERT_PATH": __import__("os").environ[
                "THRIFT_TLS_CL_CERT_PATH"
            ],
            "THRIFT_TLS_CL_KEY_PATH": __import__("os").environ[
                "THRIFT_TLS_CL_KEY_PATH"
            ],
        },
        timeout=30,
    )
    assert result.returncode == 0 and result.stderr == b""
    assert result.stdout == (
        b'{"credentials":2,"private_fields":4,"state":"validated_tls_inputs"}\n'
    )


def test_reservation_is_parent_fsynced_and_export_is_readonly(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    oracle_parent = tmp_path / "oracle"
    logs_parent = tmp_path / "logs"
    oracle_parent.mkdir()
    logs_parent.mkdir()
    reservation = oracle_parent / "reservation"
    log_root = logs_parent / "run"
    output_root = oracle_parent / "output"
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "LOG_ROOT", log_root)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", output_root)
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    synced: list[Path] = []
    real_sync = launcher.V1.sync_directory

    def record_sync(path: Path) -> None:
        synced.append(path)
        real_sync(path)

    monkeypatch.setattr(launcher, "sync_directory", record_sync)
    _, environment_sha = launcher.acquire_reservation(
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        "5" * 64,
        "6" * 24,
        reservation / ("job_authorization_" + "6" * 24 + ".json"),
        "7" * 64,
        reservation / ("activation_permit_" + "6" * 24 + ".json"),
        "8" * 64,
        synthetic_x2p_sha256(),
        b"PUBLIC=1\0",
        "2026-09-19T00:00:00+00:00",
    )
    assert synced[:2] == [oracle_parent, logs_parent]
    assert stat.S_IMODE((reservation / "slurm_environment.bin").stat().st_mode) == 0o400
    assert environment_sha == hashlib.sha256(b"PUBLIC=1\0").hexdigest()


def test_submit_path_has_two_absence_gates_and_one_sbatch_call() -> None:
    launcher = load_launcher()
    tree = ast.parse(LAUNCHER_PATH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "invoke_sbatch"
    ]
    assert len(calls) == 1
    submit_source = inspect.getsource(launcher.submit_once)
    revalidation_source = inspect.getsource(launcher.immediate_pre_submit_revalidation)
    assert submit_source.index("scheduler_matches") < submit_source.index(
        "acquire_reservation"
    )
    assert submit_source.index(
        "immediate_pre_submit_revalidation"
    ) < submit_source.index("invoke_sbatch")
    assert revalidation_source.index("validate_selection") < revalidation_source.index(
        "scheduler_matches"
    )
    assert revalidation_source.index(
        "validate_launch_dependencies"
    ) < revalidation_source.index("scheduler_matches")
    assert revalidation_source.index("scheduler_matches") < revalidation_source.rindex(
        "JOB_WRAPPER"
    )


def test_final_gate_rehashes_mutated_job_wrapper_before_scheduler_query(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    launcher_path = tmp_path / "launcher.py"
    generator_path = tmp_path / "generator.py"
    job_path = tmp_path / "job.sbatch"
    reservation = tmp_path / "reservation"
    log_root = tmp_path / "logs"
    intent = reservation / "launch_intent.json"
    environment = reservation / "slurm_environment.bin"
    for path, raw in (
        (launcher_path, b"launcher\n"),
        (generator_path, b"generator\n"),
        (job_path, b"job-before\n"),
    ):
        path.write_bytes(raw)
        path.chmod(0o500)
    reservation.mkdir(mode=0o700)
    log_root.mkdir(mode=0o700)
    intent.write_bytes(b"intent\n")
    environment.write_bytes(b"ENV=1\0")
    intent.chmod(0o400)
    environment.chmod(0o400)

    monkeypatch.setattr(launcher, "CANONICAL_SELF", launcher_path)
    monkeypatch.setattr(launcher, "GENERATOR", generator_path)
    monkeypatch.setattr(launcher, "JOB_WRAPPER", job_path)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "LOG_ROOT", log_root)
    monkeypatch.setattr(launcher, "INTENT", intent)
    monkeypatch.setattr(launcher, "ENVIRONMENT_FILE", environment)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(
        launcher, "GENERATOR_SHA256", hashlib.sha256(b"generator\n").hexdigest()
    )
    monkeypatch.setattr(
        launcher, "JOB_WRAPPER_SHA256", hashlib.sha256(b"job-before\n").hexdigest()
    )
    monkeypatch.setattr(launcher, "validate_tmux_ancestry", lambda: None)
    monkeypatch.setattr(launcher, "verify_generation", lambda *_args: None)
    monkeypatch.setattr(
        launcher,
        "validate_selection",
        lambda: ("1" * 64, "2" * 64, "3" * 64, "4" * 64),
    )

    def mutate_after_expensive_checks(_generator) -> None:
        job_path.chmod(0o700)
        job_path.write_bytes(b"job-after\n")
        job_path.chmod(0o500)

    monkeypatch.setattr(
        launcher, "validate_launch_dependencies", mutate_after_expensive_checks
    )
    scheduler_queries = 0

    def scheduler_query(*_args):
        nonlocal scheduler_queries
        scheduler_queries += 1
        return set()

    monkeypatch.setattr(launcher, "scheduler_matches", scheduler_query)
    with pytest.raises(launcher.LauncherError, match="file_hash_mismatch"):
        launcher.immediate_pre_submit_revalidation(
            launcher_sha=hashlib.sha256(b"launcher\n").hexdigest(),
            generator=None,
            task_sha="1" * 64,
            role_sha="2" * 64,
            receipt_file_sha="3" * 64,
            receipt_sha="4" * 64,
            intent_sha=hashlib.sha256(b"intent\n").hexdigest(),
            environment_sha=hashlib.sha256(b"ENV=1\0").hexdigest(),
            environment_raw=b"ENV=1\0",
            authorization_raw=b"AUTH\n",
            authorization_sha=hashlib.sha256(b"AUTH\n").hexdigest(),
            activation_permit_raw=b"PERMIT\n",
            activation_permit_sha=hashlib.sha256(b"PERMIT\n").hexdigest(),
            job_name="mirc-" + "5" * 24,
            start_date="2026-09-19",
            tls_credentials=synthetic_tls_credentials(launcher),
        )
    assert scheduler_queries == 1


def test_job_gate_captures_git_rc_and_source_retry_semantics_are_narrow() -> None:
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    assert "GIT_NO_REPLACE_OBJECTS=1" in wrapper
    assert "GIT_ATTR_NOSYSTEM=1" in wrapper
    assert "GIT_RC=$?" in wrapper
    assert "$(clean_git" not in wrapper
    assert '"$IMAGE_MANIFEST" != "$IMAGE_MANIFEST"' not in wrapper
    assert wrapper.count('exec /bin/bash "$RUN_ORACLE"') == 1
    assert 'BASH_SOURCE[0]} != "$JOB_WRAPPER"' not in wrapper
    assert 'capture_sha256 "${BASH_SOURCE[0]}"' in wrapper
    assert '"${SHA_CAPTURE%%  *}" == "$RETRY_JOB_WRAPPER_SHA256"' in wrapper
    assert (
        'readonly PYCACHE_ROOT="/tmp/mobius-infrastructure-retry-v22-${SLURM_JOB_ID}.pycache"'
        in wrapper
    )
    assert '[[ ! -e "$PYCACHE_ROOT" && ! -L "$PYCACHE_ROOT" ]]' in wrapper
    assert '/usr/bin/chmod 0500 -- "$PYCACHE_ROOT"' in wrapper
    assert 'export PYTHONPYCACHEPREFIX="$PYCACHE_ROOT"' in wrapper
    assert "export PYTHONNOUSERSITE=1" in wrapper
    assert "export PYTHONSAFEPATH=1" in wrapper
    assert "export PYTHONDONTWRITEBYTECODE=1" in wrapper
    assert "unset PYTHONHOME PYTHONPATH" in wrapper

    tree = ast.parse(RUN_ORACLE_PATH.read_text(encoding="utf-8"))
    validate_one = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_validate_one"
    )
    handlers = [
        node for node in ast.walk(validate_one) if isinstance(node, ast.ExceptHandler)
    ]
    sandbox = next(
        node
        for node in handlers
        if isinstance(node.type, ast.Name) and node.type.id == "SandboxError"
    )
    timeout = next(
        node
        for node in handlers
        if isinstance(node.type, ast.Attribute)
        and isinstance(node.type.value, ast.Name)
        and node.type.value.id == "asyncio"
        and node.type.attr == "TimeoutError"
    )
    assert any(isinstance(node, ast.Await) for node in ast.walk(sandbox))
    assert any(isinstance(node, ast.Return) for node in ast.walk(timeout))
    assert not any(isinstance(node, ast.Await) for node in ast.walk(timeout))


def test_sealed_cache_prefix_prevents_source_tree_pyc_reads(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    module = source / "v22_probe_module.py"
    module.write_text("VALUE = 7\n")
    py_compile.compile(str(module), doraise=True)
    sealed_cache = tmp_path / "sealed-cache"
    sealed_cache.mkdir(mode=0o500)
    sealed_cache.chmod(0o500)
    program = f"""
import site
import sys
opened = []
def audit_hook(event, args):
    if event == 'open' and args and isinstance(args[0], str):
        opened.append(args[0])
sys.addaudithook(audit_hook)
import v22_probe_module
assert v22_probe_module.VALUE == 7
assert sys.flags.safe_path
assert sys.dont_write_bytecode
assert site.ENABLE_USER_SITE is False
source = {str(source)!r}
assert not [path for path in opened if path.startswith(source) and path.endswith('.pyc')]
print('source_tree_pyc_opens=0')
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={
            "HOME": str(tmp_path),
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(source),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPYCACHEPREFIX": str(sealed_cache),
            "PYTHONSAFEPATH": "1",
        },
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout == b"source_tree_pyc_opens=0\n"
    assert result.stderr == b""


def test_held_identity_requires_two_consecutive_exact_snapshots(monkeypatch) -> None:
    launcher = load_launcher()
    snapshots = iter(
        [
            (False, ("Command",), (), held_details("shape")),
            (True, (), (), held_details()),
            (True, (), (), held_details()),
        ]
    )
    monkeypatch.setattr(
        launcher, "held_snapshot", lambda *_args, **_kwargs: next(snapshots)
    )
    clock = FakeClock()
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    telemetry = launcher.poll_held_convergence("123", "mirc-" + "1" * 24)
    assert telemetry["converged"] is True
    assert telemetry["identity_status"] == "converged"
    assert telemetry["explicit_conflict_fields"] == []
    assert telemetry["polls"] == 3
    assert telemetry["consecutive_exact"] == 2
    assert telemetry["observed_mismatch_fields"] == ["Command"]
    assert telemetry["mismatch_field_count"] == 1
    assert telemetry["mismatch_field_occurrences"] == {"Command": 1}
    assert telemetry["final_mismatch_fields"] == []
    assert telemetry["held_accounting_status_counts"] == {
        "absent": 0,
        "exact": 2,
        "shape": 1,
        "unavailable": 0,
    }


def test_scheduler_polling_uses_one_monotonic_deadline_and_remaining_query_cap(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    observed_deadlines: list[float] = []
    monkeypatch.setattr(launcher.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)

    def snapshot(_job_id, _job_name, *, deadline):
        observed_deadlines.append(deadline)
        return True, "RUNNING", (), (), activation_details()

    monkeypatch.setattr(launcher, "post_release_snapshot", snapshot)
    telemetry, state = launcher.poll_activation("123", "mirc-" + "1" * 24)
    assert telemetry["converged"] is True and state == "RUNNING"
    assert observed_deadlines == [
        100.0 + launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
        100.0 + launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
    ]

    observed_timeouts: list[float] = []

    def run(_command, *, timeout):
        observed_timeouts.append(timeout)
        return type("Result", (), {"returncode": 1, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(launcher, "bounded_run", run)
    launcher._scheduler_record("123", deadline=105.0)
    assert observed_timeouts == [5.0]
    assert (
        launcher.invoke_control_once(
            ["/usr/bin/scontrol", "-M", launcher.CLUSTER, "release", "123"]
        )
        == "nonzero"
    )
    assert observed_timeouts == [5.0, 20]
    exact_minimum = (
        launcher.RELEASE_QUERY_MAX_SECONDS
        + launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS
        + launcher.ACTIVATION_PUBLICATION_SLACK_SECONDS
    )
    assert exact_minimum == 792
    assert 780 <= exact_minimum  # The rejected V9 bound cannot satisfy strict >.
    assert launcher.WRAPPER_GATE_TIMEOUT_SECONDS == 900
    assert launcher.WRAPPER_GATE_TIMEOUT_SECONDS > exact_minimum
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    assert '"$RETRY_WRAPPER_GATE_TIMEOUT_SECONDS" != 900' in wrapper


def test_poll_iteration_caps_are_deadline_derived_and_strictly_conservative() -> None:
    launcher = load_launcher()
    cases = (
        (
            launcher.HELD_CONVERGENCE_TIMEOUT_SECONDS,
            launcher.HELD_POLL_INTERVAL_SECONDS,
            launcher.HELD_POLL_MAX_ITERATIONS,
        ),
        (
            launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
            launcher.ACTIVATION_POLL_INTERVAL_SECONDS,
            launcher.ACTIVATION_POLL_MAX_ITERATIONS,
        ),
        (
            launcher.CANCEL_IDENTITY_CONVERGENCE_TIMEOUT_SECONDS,
            launcher.CANCEL_IDENTITY_POLL_INTERVAL_SECONDS,
            launcher.CANCEL_IDENTITY_POLL_MAX_ITERATIONS,
        ),
        (
            launcher.CANCEL_TERMINAL_CONVERGENCE_TIMEOUT_SECONDS,
            launcher.CANCEL_TERMINAL_POLL_INTERVAL_SECONDS,
            launcher.CANCEL_TERMINAL_POLL_MAX_ITERATIONS,
        ),
    )
    for timeout, interval, limit in cases:
        assert limit == launcher._deadline_iteration_bound(timeout, interval)
        assert limit > (timeout + interval - 1) // interval
    assert launcher.WRAPPER_GATE_TIMEOUT_SECONDS > (
        launcher.RELEASE_QUERY_MAX_SECONDS
        + launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS
        + launcher.ACTIVATION_PUBLICATION_SLACK_SECONDS
    )


def test_poll_telemetry_rejects_non_allowlisted_field_names_and_bad_counts() -> None:
    launcher = load_launcher()
    assert launcher._valid_poll_telemetry(
        failed_held_telemetry(launcher),
        deadline_seconds=launcher.HELD_CONVERGENCE_TIMEOUT_SECONDS,
        max_iterations=launcher.HELD_POLL_MAX_ITERATIONS,
        require_success=False,
        held=True,
    )
    assert launcher._valid_poll_telemetry(
        failed_activation_telemetry(launcher),
        deadline_seconds=launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
        max_iterations=launcher.ACTIVATION_POLL_MAX_ITERATIONS,
        require_success=False,
        held=False,
    )
    telemetry = held_telemetry(launcher)
    telemetry["observed_mismatch_fields"] = ["rawvalue123"]
    telemetry["mismatch_field_count"] = 1
    telemetry["mismatch_field_occurrences"] = {"rawvalue123": 1}
    assert not launcher._valid_poll_telemetry(
        telemetry,
        deadline_seconds=launcher.HELD_CONVERGENCE_TIMEOUT_SECONDS,
        max_iterations=launcher.HELD_POLL_MAX_ITERATIONS,
        require_success=True,
        held=True,
    )


def test_activation_nodelist_transition_is_allowlisted_without_raw_values() -> None:
    launcher = load_launcher()
    telemetry = activation_telemetry(launcher, polls=3)
    telemetry.update(
        {
            "observed_mismatch_fields": ["activation_NodeList"],
            "mismatch_field_count": 1,
            "mismatch_field_occurrences": {"activation_NodeList": 1},
        }
    )
    assert launcher._valid_poll_telemetry(
        telemetry,
        deadline_seconds=launcher.ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
        max_iterations=launcher.ACTIVATION_POLL_MAX_ITERATIONS,
        require_success=True,
        held=False,
    )
    assert '"activation_NodeList"' in JOB_PATH.read_text(encoding="utf-8")
    telemetry = held_telemetry(launcher)
    telemetry["scontrol_allocation_category_counts"]["NumNodes"][
        "expected_one"
    ] = 1
    assert not launcher._valid_poll_telemetry(
        telemetry,
        deadline_seconds=launcher.HELD_CONVERGENCE_TIMEOUT_SECONDS,
        max_iterations=launcher.HELD_POLL_MAX_ITERATIONS,
        require_success=True,
        held=True,
    )


def test_held_accounting_lag_can_converge_after_more_than_twelve_polls(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    clock = FakeClock()
    calls = 0

    def snapshot(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls <= 13:
            return False, ("held_accounting",), (), held_details("absent")
        return True, (), (), held_details("exact")

    monkeypatch.setattr(launcher, "held_snapshot", snapshot)
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    telemetry = launcher.poll_held_convergence("123", "mirc-" + "1" * 24)
    assert telemetry["converged"] is True
    assert telemetry["polls"] == 15
    assert telemetry["mismatch_field_occurrences"] == {"held_accounting": 13}
    assert telemetry["final_mismatch_fields"] == []
    assert telemetry["held_accounting_status_counts"] == {
        "absent": 13,
        "exact": 2,
        "shape": 0,
        "unavailable": 0,
    }


def test_activation_converges_after_more_than_twelve_polls_and_times_out_at_deadline(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    clock = FakeClock()
    calls = 0

    def delayed(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls <= 13:
            return (
                False,
                "PENDING",
                ("activation_accounting",),
                (),
                activation_details(),
            )
        return True, "PENDING", (), (), activation_details()

    monkeypatch.setattr(launcher, "post_release_snapshot", delayed)
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    telemetry, state = launcher.poll_activation("123", "mirc-" + "1" * 24)
    assert state == "PENDING" and telemetry["converged"] is True
    assert telemetry["polls"] == 15
    assert telemetry["mismatch_field_occurrences"] == {
        "activation_accounting": 13
    }
    assert telemetry["final_mismatch_fields"] == []

    timeout_clock = FakeClock()
    monkeypatch.setattr(
        launcher,
        "post_release_snapshot",
        lambda *_args, **_kwargs: (
            False,
            "PENDING",
            ("activation_accounting",),
            (),
            activation_details(),
        ),
    )
    monkeypatch.setattr(launcher.time, "monotonic", timeout_clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", timeout_clock.sleep)
    timed_out, _state = launcher.poll_activation("123", "mirc-" + "1" * 24)
    assert timed_out["converged"] is False
    assert timed_out["polls"] > 12
    assert timed_out["polls"] < launcher.ACTIVATION_POLL_MAX_ITERATIONS
    assert timed_out["elapsed_milliseconds"] >= 742_000


def test_cancel_identity_and_terminal_proof_converge_after_twelve_polls(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    job_name = "mirc-" + "1" * 24
    clock = FakeClock()
    identity_calls = 0

    def identity(*_args, **_kwargs):
        nonlocal identity_calls
        identity_calls += 1
        if identity_calls <= 13:
            return None, {"scontrol_unavailable"}
        return (
            {
                "JobId": "123",
                "JobName": job_name,
                "UserId": launcher.EXPECTED_USER_ID,
            },
            set(),
        )

    monkeypatch.setattr(launcher, "_scheduler_record", identity)
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    identity_proof = launcher.prove_candidate_identity(
        "123", job_name, "sbatch_stdout"
    )
    assert identity_proof["identity_converged"] is True
    assert identity_proof["identity_poll_attempts"] == 14
    assert identity_proof["mismatch_field_occurrences"] == {
        "scontrol_unavailable": 13
    }
    assert identity_proof["final_mismatch_fields"] == []

    monkeypatch.setattr(
        launcher, "prove_candidate_identity", lambda *_args: identity_proof
    )
    terminal_calls = 0

    def terminal(*_args, **_kwargs):
        nonlocal terminal_calls
        terminal_calls += 1
        if terminal_calls <= 14:  # one pre-control snapshot plus 13 proof polls
            return scheduler_snapshot(
                "active", "RUNNING", ("cancellation_allocation_state",)
            )
        return scheduler_snapshot(
            "terminal", "CANCELLED", (), (("123", "CANCELLED"),)
        )

    monkeypatch.setattr(launcher, "terminal_snapshot", terminal)
    monkeypatch.setattr(launcher, "invoke_control_once", lambda _command: "completed")
    proof = launcher.cancel_and_prove(
        "123", job_name, "2026-09-19", candidate_provenance="sbatch_stdout"
    )
    assert proof["proof_polls"] == 15
    assert proof["terminal_mismatch_field_occurrences"] == {
        "cancellation_allocation_state": 13
    }
    assert proof["final_terminal_mismatch_fields"] == []


def test_terminal_proof_persistent_lag_spans_declared_deadline(monkeypatch) -> None:
    launcher = load_launcher()
    clock = FakeClock()
    monkeypatch.setattr(
        launcher,
        "prove_candidate_identity",
        lambda *_args: {
            "identity_status": "converged",
            "identity_converged": True,
            "identity_poll_attempts": 1,
            "candidate_provenance": "sbatch_stdout",
            "observed_mismatch_fields": [],
            "mismatch_field_occurrences": {},
            "final_mismatch_fields": [],
            "explicit_conflict_fields": [],
            "identity_elapsed_milliseconds": 0,
            "telemetry_schema": "deadline_poll_v1",
            "identity_deadline_seconds": 180,
            "identity_max_iterations": launcher.CANCEL_IDENTITY_POLL_MAX_ITERATIONS,
        },
    )
    monkeypatch.setattr(
        launcher,
        "terminal_snapshot",
        lambda *_args, **_kwargs: scheduler_snapshot(
            "active", "RUNNING", ("cancellation_steps",)
        ),
    )
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    monkeypatch.setattr(launcher, "invoke_control_once", lambda _command: "completed")
    with pytest.raises(launcher.LifecycleFailure) as caught:
        launcher.cancel_and_prove(
            "123",
            "mirc-" + "1" * 24,
            "2026-09-19",
            candidate_provenance="sbatch_stdout",
        )
    cancellation = caught.value.cancellation
    assert cancellation is not None
    assert cancellation["proof_polls"] > 12
    assert cancellation["proof_polls"] < launcher.CANCEL_TERMINAL_POLL_MAX_ITERATIONS
    assert cancellation["elapsed_milliseconds"] >= 300_000
    assert cancellation["terminal_mismatch_field_occurrences"] == {
        "cancellation_steps": cancellation["proof_polls"]
    }


def test_held_snapshot_proves_no_start_allocation_or_steps(monkeypatch) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    record = exact_held_record(launcher, job_id, job_name)
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda _job_id, **_kwargs: (record, set())
    )

    def rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return [[job_id, job_name, "PENDING", "JobHeldUser"]]
        if "--allocations" in command:
            return [[job_id, job_name, "PENDING", "Unknown", "None assigned"]]
        return [[job_id, "PENDING"]]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    assert launcher.held_snapshot(job_id, job_name) == (
        True,
        (),
        (),
        held_details(),
    )
    record["StartTime"] = "2026-09-19T00:00:00"
    assert launcher.held_snapshot(job_id, job_name) == (
        False,
        ("held_StartTime",),
        (),
        held_details(),
    )


@pytest.mark.parametrize("node_list", ("None assigned", "(null)", "", "N/A"))
def test_held_accounting_accepts_only_current_unallocated_representations(
    node_list: str, monkeypatch
) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    monkeypatch.setattr(
        launcher,
        "_scheduler_record",
        lambda *_args, **_kwargs: (
            exact_held_record(launcher, job_id, job_name),
            set(),
        ),
    )

    def rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return [[job_id, job_name, "PENDING", "JobHeldUser"]]
        if "--allocations" in command:
            return [[job_id, job_name, "PENDING", "Unknown", node_list]]
        return [[job_id, "PENDING"]]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    exact, mismatches, conflicts, details = launcher.held_snapshot(job_id, job_name)
    assert exact is True and mismatches == () and conflicts == ()
    assert details["held_accounting_status"] == "exact"


@pytest.mark.parametrize(
    ("case", "expected_status"),
    (("unavailable", "unavailable"), ("absent", "absent"), ("shape", "shape")),
)
def test_held_accounting_failure_categories_are_distinct_and_sanitized(
    case: str, expected_status: str, monkeypatch
) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    monkeypatch.setattr(
        launcher,
        "_scheduler_record",
        lambda *_args, **_kwargs: (
            exact_held_record(launcher, job_id, job_name),
            set(),
        ),
    )

    def rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return [[job_id, job_name, "PENDING", "JobHeldUser"]]
        if "--allocations" in command:
            if case == "unavailable":
                raise launcher.LauncherError("held_accounting_unavailable")
            if case == "absent":
                return []
            return [[job_id, job_name, "RUNNING", "Unknown", "None assigned"]]
        return [[job_id, "PENDING"]]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    exact, mismatches, conflicts, details = launcher.held_snapshot(job_id, job_name)
    assert exact is False and conflicts == ()
    assert "held_accounting" in mismatches
    assert details["held_accounting_status"] == expected_status


@pytest.mark.parametrize(
    ("field", "value", "category", "mismatch"),
    (
        ("NumNodes", "1-1", "other", None),
        ("NumNodes", "1", "expected_one", "NumNodes"),
        ("NumNodes", "1-2", "other", "NumNodes"),
        ("NumNodes", "0", "zero", "NumNodes"),
        ("NumNodes", "", "missing", "NumNodes"),
        ("NumNodes", None, "missing", "NumNodes"),
        ("NodeList", None, "missing", None),
        ("NodeList", "", "empty", None),
        ("NodeList", "(null)", "null_token", "held_NodeList"),
        ("NodeList", "N/A", "assigned_or_other", "held_NodeList"),
        ("NodeList", "None assigned", "assigned_or_other", "held_NodeList"),
        ("NodeList", "allocated-host", "assigned_or_other", "held_NodeList"),
        ("BatchHost", "(null)", "null_token", None),
        ("BatchHost", None, "missing", None),
        ("BatchHost", "", "empty", "held_BatchHost"),
        ("BatchHost", "allocated-host", "assigned_or_other", "held_BatchHost"),
    ),
)
def test_scontrol_allocation_representations_are_categorized_without_loosening(
    field: str,
    value: str | None,
    category: str,
    mismatch: str | None,
    monkeypatch,
) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    record = exact_held_record(launcher, job_id, job_name)
    if value is None:
        record.pop(field, None)
    else:
        record[field] = value
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: (record, set())
    )

    def rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return [[job_id, job_name, "PENDING", "JobHeldUser"]]
        if "--allocations" in command:
            return [[job_id, job_name, "PENDING", "Unknown", "None assigned"]]
        return [[job_id, "PENDING"]]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    exact, mismatches, conflicts, details = launcher.held_snapshot(job_id, job_name)
    assert conflicts == ()
    assert details["scontrol_allocation_categories"][field] == category
    assert exact is (mismatch is None)
    if mismatch is not None:
        assert mismatch in mismatches


@pytest.mark.parametrize(
    ("num_nodes", "node_list", "expected_mismatches"),
    (
        ("1", "cpu-test-001", ()),
        ("1-1", "cpu-test-001", ("NumNodes",)),
        ("2", "cpu-test-001", ("NumNodes",)),
        ("1", None, ("activation_NodeList",)),
        ("1", "", ("activation_NodeList",)),
        ("1", "(null)", ("activation_NodeList",)),
        ("1", "N/A", ("activation_NodeList",)),
        ("1", "None", ("activation_NodeList",)),
        ("1", "Unknown", ("activation_NodeList",)),
        ("1", "None assigned", ("activation_NodeList",)),
        ("1", "/untrusted", ("activation_NodeList",)),
        ("1-1", "", ("NumNodes", "activation_NodeList")),
    ),
)
def test_activation_requires_exact_allocated_one_node_representation(
    num_nodes: str,
    node_list: str | None,
    expected_mismatches: tuple[str, ...],
    monkeypatch,
) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    record = exact_activation_record(launcher, job_id, job_name)
    record["NumNodes"] = num_nodes
    if node_list is None:
        record.pop("NodeList")
    else:
        record["NodeList"] = node_list
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: (record, set())
    )

    def rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return [[job_id, job_name, "RUNNING", "None"]]
        return [[job_id, job_name, "RUNNING"]]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    exact, state, mismatches, conflicts, details = launcher.post_release_snapshot(
        job_id, job_name
    )
    assert state == "RUNNING" and conflicts == ()
    assert exact is (not expected_mismatches)
    assert mismatches == expected_mismatches
    if not expected_mismatches:
        assert details["scontrol_allocation_categories"] == (
            exact_activation_allocation_categories()
        )


@pytest.mark.parametrize(
    ("mutation", "expected_mismatch"),
    (
        ("job_state", "held_JobState"),
        ("reason", "held_Reason"),
        ("priority", "held_Priority"),
        ("start_time", "held_StartTime"),
        ("batch_host", "held_BatchHost"),
        ("queue", "held_squeue"),
        ("accounting", "held_accounting"),
        ("steps", "held_steps"),
    ),
)
def test_live_held_representation_still_requires_every_other_proof(
    mutation: str, expected_mismatch: str, monkeypatch
) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    record = exact_held_record(launcher, job_id, job_name)
    if mutation == "job_state":
        record["JobState"] = "RUNNING"
    elif mutation == "reason":
        record["Reason"] = "Resources"
    elif mutation == "priority":
        record["Priority"] = "1"
    elif mutation == "start_time":
        record["StartTime"] = "2026-09-19T00:00:00"
    elif mutation == "batch_host":
        record["BatchHost"] = "cpu-test-001"
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: (record, set())
    )

    def rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            state = "RUNNING" if mutation == "queue" else "PENDING"
            reason = "None" if mutation == "queue" else "JobHeldUser"
            return [[job_id, job_name, state, reason]]
        if "--allocations" in command:
            state = "RUNNING" if mutation == "accounting" else "PENDING"
            return [[job_id, job_name, state, "Unknown", "None assigned"]]
        if mutation == "steps":
            return [[job_id, "PENDING"], [f"{job_id}.batch", "RUNNING"]]
        return [[job_id, "PENDING"]]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    exact, mismatches, conflicts, _details = launcher.held_snapshot(job_id, job_name)
    assert exact is False and conflicts == ()
    assert expected_mismatch in mismatches


def test_persistent_held_mismatch_fails_closed_with_sanitized_fields(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    monkeypatch.setattr(
        launcher,
        "held_snapshot",
        lambda *_args, **_kwargs: (
            False,
            ("held_StartTime",),
            (),
            held_details("shape"),
        ),
    )
    clock = [100.0]
    monkeypatch.setattr(launcher.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        launcher.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    telemetry = launcher.poll_held_convergence("123", "mirc-" + "1" * 24)
    assert telemetry["converged"] is False
    assert telemetry["identity_status"] == "unavailable_or_incomplete"
    assert telemetry["explicit_conflict_fields"] == []
    assert telemetry["polls"] > 12
    assert telemetry["polls"] < launcher.HELD_POLL_MAX_ITERATIONS
    assert telemetry["deadline_seconds"] == 982
    assert telemetry["elapsed_milliseconds"] >= 982_000
    assert telemetry["observed_mismatch_fields"] == ["held_StartTime"]
    assert telemetry["mismatch_field_occurrences"] == {
        "held_StartTime": telemetry["polls"]
    }
    assert telemetry["final_mismatch_fields"] == ["held_StartTime"]
    assert telemetry["held_accounting_status_counts"]["shape"] == telemetry["polls"]


def test_lost_hold_before_or_after_authorization_never_releases(monkeypatch) -> None:
    launcher = load_launcher()
    telemetry = held_telemetry(launcher)
    monkeypatch.setattr(
        launcher, "poll_held_convergence", lambda *_args: dict(telemetry)
    )
    calls: list[str] = []
    monkeypatch.setattr(
        launcher, "publish_authorization", lambda *_args: calls.append("published")
    )
    snapshots = iter(
        [
            (True, (), (), held_details()),
            (False, ("held_Reason",), (), held_details("shape")),
        ]
    )
    monkeypatch.setattr(
        launcher, "held_snapshot", lambda *_args, **_kwargs: next(snapshots)
    )
    with pytest.raises(
        launcher.LauncherError, match="held_state_lost_after_authorization"
    ):
        launcher.authorize_held_job(
            "123", "mirc-" + "1" * 24, Path("/tmp/auth"), b"auth", "1" * 64
        )
    assert calls == ["published"]


@pytest.mark.parametrize("control_outcome", ("unknown", "nonzero"))
def test_release_ambiguous_but_applied_is_accepted_once(
    control_outcome: str, monkeypatch
) -> None:
    launcher = load_launcher()
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or control_outcome,
    )
    monkeypatch.setattr(
        launcher,
        "poll_activation",
        lambda *_args: (
            {
                "converged": True,
                "identity_status": "converged",
                "explicit_conflict_fields": [],
                "polls": 2,
                "consecutive_exact": 2,
                "elapsed_milliseconds": 1,
                "observed_mismatch_fields": [],
                "mismatch_field_count": 0,
                "state_class": "active",
            },
            "RUNNING",
        ),
    )
    record = launcher.release_and_reconcile("123", "mirc-" + "1" * 24)
    assert record["command_outcome"] == control_outcome
    assert record["observed_state"] == "RUNNING"
    assert len(controls) == 1 and controls[0][-2:] == ("release", "123")


def test_release_not_applied_or_terminal_never_gets_permit(monkeypatch) -> None:
    launcher = load_launcher()
    monkeypatch.setattr(launcher, "invoke_control_once", lambda _command: "nonzero")
    monkeypatch.setattr(
        launcher,
        "poll_activation",
        lambda *_args: (
            {
                "converged": False,
                "identity_status": "unavailable_or_incomplete",
                "explicit_conflict_fields": [],
                "polls": 12,
                "consecutive_exact": 0,
                "elapsed_milliseconds": 1,
                "observed_mismatch_fields": ["activation_hold"],
                "mismatch_field_count": 1,
                "state_class": "unknown",
            },
            "PENDING",
        ),
    )
    with pytest.raises(launcher.LauncherError, match="activation_not_converged"):
        launcher.release_and_reconcile("123", "mirc-" + "1" * 24)
    monkeypatch.setattr(
        launcher,
        "poll_activation",
        lambda *_args: (
            {
                "converged": True,
                "identity_status": "converged",
                "explicit_conflict_fields": [],
                "polls": 2,
                "consecutive_exact": 2,
                "elapsed_milliseconds": 1,
                "observed_mismatch_fields": [],
                "mismatch_field_count": 0,
                "state_class": "terminal",
            },
            "CANCELLED",
        ),
    )
    with pytest.raises(
        launcher.LauncherError, match="activation_terminal_before_permit"
    ):
        launcher.release_and_reconcile("123", "mirc-" + "1" * 24)


def test_timeout_submission_is_recovered_without_second_sbatch(monkeypatch) -> None:
    launcher = load_launcher()
    candidate, outcome = launcher.parse_sbatch_response("timeout", 124, "")
    assert candidate is None and outcome == "timeout"
    lookups: list[str] = []
    monkeypatch.setattr(
        launcher,
        "lookup_submission",
        lambda *_args: lookups.append("lookup") or ("unique", "123"),
    )
    assert (
        launcher.resolve_submission(
            candidate, outcome, "mirc-" + "1" * 24, "2026-09-19"
        )
        == ("123", "name_lookup")
    )
    assert lookups == ["lookup"]


def test_terminal_proof_requires_every_step_terminal(monkeypatch) -> None:
    launcher = load_launcher()
    job_name = "mirc-" + "1" * 24
    active_step = True

    def rows(command, _width, _code, **_kwargs):
        nonlocal active_step
        if command[0] == "/usr/bin/squeue":
            return []
        if "--allocations" in command:
            return [["123", job_name, "CANCELLED"]]
        return [
            ["123", "CANCELLED"],
            ["123.batch", "RUNNING" if active_step else "CANCELLED"],
            ["123.extern", "COMPLETED"],
        ]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    monkeypatch.setattr(
        launcher,
        "_scheduler_record",
        lambda *_args, **_kwargs: (
            {"JobId": "123", "JobName": job_name, "UserId": launcher.EXPECTED_USER_ID},
            set(),
        ),
    )
    snapshot = launcher.terminal_snapshot("123", job_name)
    assert snapshot["snapshot_status"] == "active"
    assert snapshot["mismatch_fields"] == ("cancellation_steps",)
    active_step = False
    snapshot = launcher.terminal_snapshot("123", job_name)
    assert snapshot["snapshot_status"] == "terminal"
    assert snapshot["state"] == "CANCELLED"
    assert snapshot["mismatch_fields"] == ()
    assert len(snapshot["step_signature"]) == 3


def test_cancellation_requires_stable_terminal_allocation(monkeypatch) -> None:
    launcher = load_launcher()
    monkeypatch.setattr(
        launcher,
        "prove_candidate_identity",
        lambda *_args: {
            "identity_status": "converged",
            "identity_converged": True,
            "identity_poll_attempts": 1,
            "candidate_provenance": "sbatch_stdout",
            "observed_mismatch_fields": [],
            "explicit_conflict_fields": [],
            "identity_elapsed_milliseconds": 0,
        },
    )
    controls: list[str] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda _command: controls.append("cancel") or "completed",
    )
    snapshots = iter(
        [
            scheduler_snapshot("active", "RUNNING", ("cancellation_squeue",)),
            scheduler_snapshot("terminal", "FAILED", (), (("123", "FAILED"),)),
            scheduler_snapshot(
                "terminal", "CANCELLED", (), (("123", "CANCELLED"),)
            ),
            scheduler_snapshot(
                "terminal", "CANCELLED", (), (("123", "CANCELLED"),)
            ),
        ]
    )
    monkeypatch.setattr(launcher, "terminal_snapshot", lambda *_args, **_kwargs: next(snapshots))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    proof = launcher.cancel_and_prove(
        "123",
        "mirc-" + "1" * 24,
        "2026-09-19",
        candidate_provenance="sbatch_stdout",
    )
    assert proof["proof_polls"] == 3
    assert proof["consecutive_exact"] == 2
    assert proof["terminal_state"] == "CANCELLED"
    assert controls == ["cancel"]


def test_real_cancellation_retries_transient_identity_before_exact_id_cancel(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    job_name = "mirc-" + "1" * 24
    record = {
        "JobId": "123",
        "JobName": job_name,
        "UserId": "tianhaowu(656177)",
    }
    identities = iter(
        [
            (None, {"scontrol_unavailable"}),
            (None, {"scontrol_unavailable"}),
            (record, set()),
        ]
    )
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: next(identities)
    )
    snapshots = iter(
        [
            scheduler_snapshot("active", "RUNNING", ("cancellation_squeue",)),
            scheduler_snapshot(
                "terminal", "CANCELLED", (), (("123", "CANCELLED"),)
            ),
            scheduler_snapshot(
                "terminal", "CANCELLED", (), (("123", "CANCELLED"),)
            ),
        ]
    )
    monkeypatch.setattr(launcher, "terminal_snapshot", lambda *_args, **_kwargs: next(snapshots))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "completed",
    )
    proof = launcher.cancel_and_prove(
        "123",
        job_name,
        "2026-09-19",
        candidate_provenance="sbatch_stdout",
    )
    assert proof["identity_status"] == "converged"
    assert proof["identity_poll_attempts"] == 3
    assert proof["explicit_conflict_fields"] == []
    assert proof["candidate_provenance"] == "sbatch_stdout"
    assert proof["cancel_attempts"] == 1
    assert controls == [("/usr/bin/scancel", "-M", launcher.CLUSTER, "123")]


def test_persistent_identity_failure_still_exact_id_cancels_trusted_candidate_and_seals(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    monkeypatch.setattr(
        launcher,
        "_scheduler_record",
        lambda *_args, **_kwargs: (None, {"scontrol_unavailable"}),
    )
    monkeypatch.setattr(
        launcher,
        "terminal_snapshot",
        lambda *_args, **_kwargs: scheduler_snapshot(
            "unavailable_or_incomplete",
            "UNKNOWN",
            ("cancellation_accounting",),
        ),
    )
    clock = FakeClock()
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "unknown",
    )
    with pytest.raises(
        launcher.LifecycleFailure, match="^cancellation_unconfirmed$"
    ) as caught:
        launcher.cancel_and_prove(
            "123",
            "mirc-" + "1" * 24,
            "2026-09-19",
            candidate_provenance="sbatch_stdout",
        )
    assert controls == [("/usr/bin/scancel", "-M", launcher.CLUSTER, "123")]
    cancellation = caught.value.cancellation
    assert cancellation is not None
    assert cancellation["identity_converged"] is False
    assert cancellation["identity_poll_attempts"] > 12
    assert (
        cancellation["identity_poll_attempts"]
        < launcher.CANCEL_IDENTITY_POLL_MAX_ITERATIONS
    )
    assert cancellation["identity_elapsed_milliseconds"] >= 180_000
    assert cancellation["proof_polls"] > 12
    assert cancellation["proof_polls"] < launcher.CANCEL_TERMINAL_POLL_MAX_ITERATIONS
    assert cancellation["elapsed_milliseconds"] >= 300_000
    assert cancellation["cancel_attempts"] == 1
    assert cancellation["cancel_command_outcome"] == "unknown"
    launcher.publish_failure(
        {
            "state": "ambiguous",
            "code": "cancellation_unconfirmed",
            "cancellation": cancellation,
        }
    )
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    assert stat.S_IMODE(launcher.FAILURE_CERTIFICATE.stat().st_mode) == 0o400
    sealed = json.loads(launcher.FAILURE_CERTIFICATE.read_bytes())
    assert sealed["state"] == "ambiguous"
    assert sealed["code"] == "cancellation_unconfirmed"


def test_live_identity_conflict_never_calls_control_and_seals_ambiguous_failure(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    conflict = {
        "JobId": "123",
        "JobName": "conflicting-live-job",
        "UserId": "different-user(1)",
    }
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: (conflict, set())
    )
    monkeypatch.setattr(
        launcher,
        "terminal_snapshot",
        lambda *_args, **_kwargs: pytest.fail(
            "conflicting identity must not reach terminal query"
        ),
    )
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "completed",
    )
    with pytest.raises(
        launcher.LifecycleFailure, match="^cancellation_unconfirmed$"
    ) as caught:
        launcher.cancel_and_prove(
            "123",
            "mirc-" + "1" * 24,
            "2026-09-19",
            candidate_provenance="sbatch_stdout",
        )
    assert controls == []
    cancellation = caught.value.cancellation
    assert cancellation is not None
    assert cancellation["identity_status"] == "explicit_identity_conflict"
    assert cancellation["explicit_conflict_fields"] == ["JobName", "UserId"]
    assert cancellation["identity_poll_attempts"] == 1
    assert cancellation["cancel_attempts"] == 0
    launcher.publish_failure(
        {
            "state": "ambiguous",
            "code": "cancellation_unconfirmed",
            "cancellation": cancellation,
        }
    )
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    assert stat.S_IMODE(launcher.FAILURE_CERTIFICATE.stat().st_mode) == 0o400
    sealed = json.loads(launcher.FAILURE_CERTIFICATE.read_bytes())
    assert sealed["state"] == "ambiguous"
    assert sealed["code"] == "cancellation_unconfirmed"


def test_submit_stdout_candidate_conflict_seals_ambiguous_without_control(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    monkeypatch.setattr(launcher.secrets, "token_hex", lambda _size: "1" * 24)
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(
        launcher,
        "lookup_submission",
        lambda *_args: (_ for _ in ()).throw(
            launcher.LauncherError("scheduler_identity_unavailable")
        ),
    )
    conflict = {
        "JobId": "123",
        "JobName": "conflicting-live-job",
        "UserId": "different-user(1)",
    }
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: (conflict, set())
    )
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "completed",
    )
    with pytest.raises(launcher.LauncherError, match="^cancellation_unconfirmed$"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert controls == []
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    sealed = json.loads(launcher.FAILURE_CERTIFICATE.read_bytes())
    assert sealed["state"] == "ambiguous"
    assert sealed["code"] == "cancellation_unconfirmed"
    cancellation = sealed["lifecycle"]["cancellation"]
    assert cancellation["candidate_provenance"] == "sbatch_stdout"
    assert cancellation["identity_status"] == "explicit_identity_conflict"
    assert cancellation["cancel_attempts"] == 0


def test_missing_identity_fields_are_incomplete_not_conflicting(monkeypatch) -> None:
    launcher = load_launcher()
    incomplete = {"JobId": "123", "JobName": "", "UserId": ""}
    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: (incomplete, set())
    )
    clock = FakeClock()
    monkeypatch.setattr(launcher.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(launcher.time, "sleep", clock.sleep)
    proof = launcher.prove_candidate_identity(
        "123", "mirc-" + "1" * 24, "sbatch_stdout"
    )
    assert proof["identity_status"] == "unavailable_or_incomplete"
    assert proof["explicit_conflict_fields"] == []
    assert proof["identity_poll_attempts"] > 12
    assert proof["identity_poll_attempts"] < launcher.CANCEL_IDENTITY_POLL_MAX_ITERATIONS
    assert proof["identity_elapsed_milliseconds"] >= 180_000
    assert proof["observed_mismatch_fields"] == ["missing_JobName", "missing_UserId"]


def test_identity_conflict_is_monotonic_in_held_and_activation_polls(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    held_calls = 0

    def held(*_args, **_kwargs):
        nonlocal held_calls
        held_calls += 1
        if held_calls == 1:
            return False, ("JobName",), ("JobName",), held_details("shape")
        pytest.fail("a held identity conflict must stop convergence")

    monkeypatch.setattr(launcher, "held_snapshot", held)
    held_result = launcher.poll_held_convergence("123", "mirc-" + "1" * 24)
    assert held_calls == 1
    assert held_result["identity_status"] == "explicit_identity_conflict"
    assert held_result["explicit_conflict_fields"] == ["JobName"]

    activation_calls = 0

    def activation(*_args, **_kwargs):
        nonlocal activation_calls
        activation_calls += 1
        if activation_calls == 1:
            return (
                False,
                "RUNNING",
                ("UserId",),
                ("UserId",),
                activation_details(),
            )
        pytest.fail("an activation identity conflict must stop convergence")

    monkeypatch.setattr(launcher, "post_release_snapshot", activation)
    activation_result, state = launcher.poll_activation(
        "123", "mirc-" + "1" * 24
    )
    assert activation_calls == 1 and state == "RUNNING"
    assert activation_result["identity_status"] == "explicit_identity_conflict"
    assert activation_result["explicit_conflict_fields"] == ["UserId"]


def test_identity_requires_exact_user_id_across_all_scheduler_snapshots(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    record = {
        "JobId": job_id,
        "JobName": job_name,
        "UserId": launcher.EXPECTED_USER_ID + "-suffix",
    }
    missing, conflicts = launcher._identity_field_observation(
        record, job_id, job_name
    )
    assert missing == set() and conflicts == {"UserId"}

    monkeypatch.setattr(
        launcher, "_scheduler_record", lambda *_args, **_kwargs: (record, set())
    )
    monkeypatch.setattr(
        launcher,
        "_pipe_rows",
        lambda *_args, **_kwargs: [],
    )
    held = launcher.held_snapshot(job_id, job_name)
    assert held[2] == ("UserId",)
    activation = launcher.post_release_snapshot(job_id, job_name)
    assert activation[3] == ("UserId",)
    terminal = launcher.terminal_snapshot(job_id, job_name)
    assert terminal["snapshot_status"] == "explicit_identity_conflict"
    assert terminal["explicit_conflict_fields"] == ("UserId",)
    proof = launcher.prove_candidate_identity(job_id, job_name, "sbatch_stdout")
    assert proof["identity_status"] == "explicit_identity_conflict"
    assert proof["explicit_conflict_fields"] == ["UserId"]


def test_conflict_after_identity_proof_before_control_forbids_scancel(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    monkeypatch.setattr(
        launcher,
        "prove_candidate_identity",
        lambda *_args: {
            "identity_status": "converged",
            "identity_converged": True,
            "identity_poll_attempts": 1,
            "candidate_provenance": "sbatch_stdout",
            "observed_mismatch_fields": [],
            "explicit_conflict_fields": [],
            "identity_elapsed_milliseconds": 0,
        },
    )
    monkeypatch.setattr(
        launcher,
        "terminal_snapshot",
        lambda *_args, **_kwargs: scheduler_snapshot(
            "explicit_identity_conflict",
            "UNKNOWN",
            ("JobName",),
            explicit_conflict_fields=("JobName",),
        ),
    )
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "completed",
    )
    with pytest.raises(launcher.LifecycleFailure) as caught:
        launcher.cancel_and_prove(
            "123",
            "mirc-" + "1" * 24,
            "2026-09-19",
            candidate_provenance="sbatch_stdout",
        )
    assert controls == []
    assert caught.value.cancellation is not None
    assert caught.value.cancellation["identity_status"] == "explicit_identity_conflict"
    assert caught.value.cancellation["cancel_attempts"] == 0


def test_snapshot_conflict_survives_later_scheduler_query_failure(monkeypatch) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    exact_record = {
        "JobId": job_id,
        "JobName": job_name,
        "UserId": launcher.EXPECTED_USER_ID,
        "JobState": "RUNNING",
    }
    monkeypatch.setattr(
        launcher,
        "_scheduler_record",
        lambda *_args, **_kwargs: (exact_record, set()),
    )

    def activation_rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return [[job_id, "conflicting-name", "RUNNING", "None"]]
        raise launcher.LauncherError("activation_accounting_unavailable")

    monkeypatch.setattr(launcher, "_pipe_rows", activation_rows)
    activation = launcher.post_release_snapshot(job_id, job_name)
    assert activation[3] == ("JobName",)

    def terminal_rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return []
        if "--allocations" in command:
            return [[job_id, "conflicting-name", "RUNNING"]]
        raise launcher.LauncherError("cancellation_steps_unavailable")

    monkeypatch.setattr(launcher, "_pipe_rows", terminal_rows)
    terminal = launcher.terminal_snapshot(job_id, job_name)
    assert terminal["snapshot_status"] == "explicit_identity_conflict"
    assert terminal["explicit_conflict_fields"] == ("JobName",)


def test_pre_control_snapshot_classifies_empty_live_identity_as_incomplete(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    job_id = "123"
    job_name = "mirc-" + "1" * 24
    monkeypatch.setattr(
        launcher,
        "_scheduler_record",
        lambda *_args, **_kwargs: (
            {
                "JobId": job_id,
                "JobName": job_name,
                "UserId": launcher.EXPECTED_USER_ID,
            },
            set(),
        ),
    )

    def rows(command, _width, _code, **_kwargs):
        if command[0] == "/usr/bin/squeue":
            return [["", job_name]]
        if "--allocations" in command:
            return [[job_id, job_name, "RUNNING"]]
        return [[job_id, "RUNNING"]]

    monkeypatch.setattr(launcher, "_pipe_rows", rows)
    snapshot = launcher.terminal_snapshot(job_id, job_name)
    assert snapshot["snapshot_status"] == "unavailable_or_incomplete"
    assert snapshot["explicit_conflict_fields"] == ()
    assert "missing_JobId" in snapshot["mismatch_fields"]


def test_direct_sbatch_provenance_never_downgrades_on_cleanup_lookup(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    monkeypatch.setattr(launcher.secrets, "token_hex", lambda _size: "1" * 24)
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    lookup_calls: list[str] = []
    monkeypatch.setattr(
        launcher,
        "lookup_submission",
        lambda *_args: lookup_calls.append("lookup") or ("unique", "123"),
    )
    monkeypatch.setattr(
        launcher,
        "authorize_held_job",
        lambda *_args: (_ for _ in ()).throw(launcher.LauncherError("injected")),
    )
    provenances: list[str] = []
    monkeypatch.setattr(
        launcher,
        "cancel_and_prove",
        lambda *_args, **kwargs: (
            provenances.append(kwargs["candidate_provenance"])
            or {"terminal_state": "CANCELLED"}
        ),
    )
    with pytest.raises(launcher.LauncherError, match="^injected$"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert lookup_calls == ["lookup", "lookup"]
    assert provenances == ["sbatch_and_name"]


def test_held_identity_conflict_forbids_authorization_release_and_cleanup_control(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    monkeypatch.setattr(launcher.secrets, "token_hex", lambda _size: "1" * 24)
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(launcher, "lookup_submission", lambda *_args: ("unique", "123"))
    monkeypatch.setattr(
        launcher,
        "held_snapshot",
        lambda *_args, **_kwargs: (
            False,
            ("JobName",),
            ("JobName",),
            held_details("shape"),
        ),
    )
    published: list[str] = []
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "publish_authorization",
        lambda *_args: published.append("authorization"),
    )
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "completed",
    )
    with pytest.raises(launcher.LauncherError, match="^cancellation_unconfirmed$"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert published == []
    assert controls == []
    sealed = json.loads(launcher.FAILURE_CERTIFICATE.read_bytes())
    cancellation = sealed["lifecycle"]["cancellation"]
    assert cancellation["identity_status"] == "explicit_identity_conflict"
    assert cancellation["explicit_conflict_fields"] == ["JobName"]
    assert cancellation["cancel_attempts"] == 0


def test_activation_identity_conflict_forbids_cleanup_cancel(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    monkeypatch.setattr(launcher.secrets, "token_hex", lambda _size: "1" * 24)
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(launcher, "lookup_submission", lambda *_args: ("unique", "123"))
    monkeypatch.setattr(launcher, "authorize_held_job", lambda *_args: {"converged": True})
    monkeypatch.setattr(
        launcher,
        "poll_activation",
        lambda *_args: (
            {
                "converged": False,
                "identity_status": "explicit_identity_conflict",
                "explicit_conflict_fields": ["UserId"],
                "polls": 1,
                "consecutive_exact": 0,
                "elapsed_milliseconds": 1,
                "observed_mismatch_fields": ["UserId"],
                "mismatch_field_count": 1,
                "state_class": "unknown",
            },
            "RUNNING",
        ),
    )
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "completed",
    )
    with pytest.raises(launcher.LauncherError, match="^cancellation_unconfirmed$"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert len(controls) == 1
    assert controls[0][-2:] == ("release", "123")
    sealed = json.loads(launcher.FAILURE_CERTIFICATE.read_bytes())
    cancellation = sealed["lifecycle"]["cancellation"]
    assert cancellation["identity_status"] == "explicit_identity_conflict"
    assert cancellation["explicit_conflict_fields"] == ["UserId"]
    assert cancellation["cancel_attempts"] == 0


def test_name_only_candidate_is_never_canceled_without_identity_proof(monkeypatch) -> None:
    launcher = load_launcher()
    monkeypatch.setattr(
        launcher,
        "_scheduler_record",
        lambda *_args, **_kwargs: (None, {"scontrol_unavailable"}),
    )
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    controls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: controls.append(tuple(command)) or "completed",
    )
    with pytest.raises(launcher.LifecycleFailure, match="^cancellation_unconfirmed$"):
        launcher.cancel_and_prove(
            "123",
            "mirc-" + "1" * 24,
            "2026-09-19",
            candidate_provenance="name_lookup",
        )
    assert controls == []


def test_failure_between_receipt_and_permit_seals_failure(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    token = "1" * 24
    auth = reservation / f"job_authorization_{token}.json"
    permit = reservation / f"activation_permit_{token}.json"
    (reservation / "launch_intent.json").write_bytes(b"intent\n")
    (reservation / "slurm_environment.bin").write_bytes(b"PUBLIC=1\0")
    (reservation / "launch_intent.json").chmod(0o400)
    (reservation / "slurm_environment.bin").chmod(0o400)
    auth.write_bytes(b"auth\n")
    auth.chmod(0o400)
    real_write = launcher.V1.write_once

    def fail_permit(path, raw, mode):
        if path == permit:
            raise launcher.LauncherError("injected_permit_failure")
        return real_write(path, raw, mode)

    monkeypatch.setattr(launcher, "write_once", fail_permit)
    with pytest.raises(launcher.LauncherError, match="injected_permit_failure"):
        launcher.publish_success(
            {"state": "submitted"},
            authorization_path=auth,
            authorization_sha=hashlib.sha256(b"auth\n").hexdigest(),
            activation_permit_path=permit,
            activation_permit_raw=b"permit\n",
            activation_permit_sha=hashlib.sha256(b"permit\n").hexdigest(),
            commit_state={"committed": False},
        )
    assert not launcher.SUBMISSION_RECEIPT.exists() and not permit.exists()
    monkeypatch.setattr(launcher, "write_once", real_write)
    launcher.publish_failure({"state": "failed"})
    assert launcher.FAILURE_CERTIFICATE.exists()
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500


def test_post_commit_failure_never_reopens_or_publishes_failure(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    token = "1" * 24
    auth = reservation / f"job_authorization_{token}.json"
    permit = reservation / f"activation_permit_{token}.json"
    for path, body in (
        (launcher.INTENT, b"intent\n"),
        (launcher.ENVIRONMENT_FILE, b"PUBLIC=1\0"),
        (auth, b"auth\n"),
    ):
        path.write_bytes(body)
        path.chmod(0o400)
    real_sync = launcher.V1.sync_directory

    def fail_after_commit(path: Path) -> None:
        if path == reservation and stat.S_IMODE(path.stat().st_mode) == 0o500:
            raise OSError("injected durable-commit fsync failure")
        real_sync(path)

    monkeypatch.setattr(launcher, "sync_directory", fail_after_commit)
    commit_state = {"committed": False}
    with pytest.raises(OSError, match="durable-commit"):
        launcher.publish_success(
            {"state": "submitted"},
            authorization_path=auth,
            authorization_sha=hashlib.sha256(b"auth\n").hexdigest(),
            activation_permit_path=permit,
            activation_permit_raw=b"permit\n",
            activation_permit_sha=hashlib.sha256(b"permit\n").hexdigest(),
            commit_state=commit_state,
        )
    assert commit_state == {"committed": True}
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    assert launcher.SUBMISSION_RECEIPT.exists() and permit.exists()
    with pytest.raises(launcher.LauncherError, match="terminal_receipt_conflict"):
        launcher.publish_failure({"state": "failed"})
    assert not launcher.FAILURE_CERTIFICATE.exists()


@pytest.mark.parametrize(
    ("stage", "committed"),
    [
        ("receipt_write", False),
        ("receipt_verify", False),
        ("permit_write", False),
        ("permit_verify", False),
        ("children_scan", False),
        ("precommit_sync", False),
        ("chmod", False),
        ("postcommit_sync", True),
        ("parent_sync", True),
        ("unmask", True),
    ],
)
def test_success_publication_boundary_failures_are_fail_closed(
    stage: str, committed: bool, tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    token = "1" * 24
    auth = reservation / f"job_authorization_{token}.json"
    permit = reservation / f"activation_permit_{token}.json"
    for path, body in (
        (launcher.INTENT, b"intent\n"),
        (launcher.ENVIRONMENT_FILE, b"PUBLIC=1\0"),
        (auth, b"auth\n"),
    ):
        path.write_bytes(body)
        path.chmod(0o400)

    real_write = launcher.V1.write_once
    real_file_bytes = launcher.V1.file_bytes
    real_scandir = launcher.os.scandir
    real_sync = launcher.V1.sync_directory
    real_chmod = launcher.os.chmod
    scandir_calls = 0

    def injected_write(path, raw, mode):
        if (stage == "receipt_write" and path == launcher.SUBMISSION_RECEIPT) or (
            stage == "permit_write" and path == permit
        ):
            raise launcher.LauncherError(f"injected_{stage}")
        return real_write(path, raw, mode)

    def injected_file_bytes(path, **kwargs):
        if (stage == "receipt_verify" and path == launcher.SUBMISSION_RECEIPT) or (
            stage == "permit_verify" and path == permit
        ):
            raise launcher.LauncherError(f"injected_{stage}")
        return real_file_bytes(path, **kwargs)

    def injected_scandir(path):
        nonlocal scandir_calls
        scandir_calls += 1
        if stage == "children_scan" and scandir_calls == 2:
            raise OSError("injected children scan")
        return real_scandir(path)

    def injected_sync(path: Path) -> None:
        mode = stat.S_IMODE(reservation.stat().st_mode)
        if stage == "precommit_sync" and path == reservation and mode == 0o700:
            raise OSError("injected precommit sync")
        if stage == "postcommit_sync" and path == reservation and mode == 0o500:
            raise OSError("injected postcommit sync")
        if stage == "parent_sync" and path == reservation.parent and mode == 0o500:
            raise OSError("injected parent sync")
        real_sync(path)

    def injected_chmod(path, mode, **kwargs):
        if stage == "chmod" and path == reservation:
            raise OSError("injected chmod")
        return real_chmod(path, mode, **kwargs)

    sigmask_calls = 0

    def injected_sigmask(how, mask):
        nonlocal sigmask_calls
        sigmask_calls += 1
        if stage == "unmask" and sigmask_calls == 2:
            raise launcher.LaunchInterrupted(signal.SIGTERM)
        return set()

    monkeypatch.setattr(launcher, "write_once", injected_write)
    monkeypatch.setattr(launcher, "file_bytes", injected_file_bytes)
    monkeypatch.setattr(launcher.os, "scandir", injected_scandir)
    monkeypatch.setattr(launcher, "sync_directory", injected_sync)
    monkeypatch.setattr(launcher.os, "chmod", injected_chmod)
    monkeypatch.setattr(launcher.signal, "pthread_sigmask", injected_sigmask)
    commit_state = {"committed": False}
    expected_exception = {
        "receipt_write": launcher.LauncherError,
        "receipt_verify": launcher.LauncherError,
        "permit_write": launcher.LauncherError,
        "permit_verify": launcher.LauncherError,
        "children_scan": OSError,
        "precommit_sync": launcher.LifecycleFailure,
        "chmod": OSError,
        "postcommit_sync": OSError,
        "parent_sync": OSError,
        "unmask": launcher.LaunchInterrupted,
    }[stage]
    with pytest.raises(expected_exception):
        launcher.publish_success(
            {"state": "submitted"},
            authorization_path=auth,
            authorization_sha=hashlib.sha256(b"auth\n").hexdigest(),
            activation_permit_path=permit,
            activation_permit_raw=b"permit\n",
            activation_permit_sha=hashlib.sha256(b"permit\n").hexdigest(),
            commit_state=commit_state,
        )
    assert commit_state["committed"] is committed
    assert launcher.SUBMISSION_RECEIPT.exists() is committed
    assert permit.exists() is committed
    assert stat.S_IMODE(reservation.stat().st_mode) == (0o500 if committed else 0o700)


def test_publish_failure_refuses_partial_success_markers(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    for marker in ("submission_receipt.json", "activation_permit_" + "1" * 24 + ".json"):
        reservation = tmp_path / marker
        reservation.mkdir(mode=0o700)
        monkeypatch.setattr(launcher, "RESERVATION", reservation)
        monkeypatch.setattr(
            launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
        )
        monkeypatch.setattr(
            launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
        )
        (reservation / marker).write_bytes(b"sealed\n")
        with pytest.raises(launcher.LauncherError, match="terminal_receipt_conflict"):
            launcher.publish_failure({"state": "failed"})
        assert not launcher.FAILURE_CERTIFICATE.exists()


def test_lifecycle_failures_preserve_sanitized_held_and_release_telemetry(
    monkeypatch,
) -> None:
    launcher = load_launcher()
    held = failed_held_telemetry(launcher)
    monkeypatch.setattr(launcher, "poll_held_convergence", lambda *_args: dict(held))
    with pytest.raises(launcher.LifecycleFailure) as held_error:
        launcher.authorize_held_job(
            "123", "mirc-" + "1" * 24, Path("/tmp/auth"), b"auth", "1" * 64
        )
    assert str(held_error.value) == "held_identity_not_converged"
    assert held_error.value.held_validation == {
        **held,
        "final_pre_authorization_mismatch_fields": None,
        "post_authorization_mismatch_fields": None,
    }

    release = failed_activation_telemetry(launcher)
    for field in ("attempts", "command_outcome", "observed_state"):
        release.pop(field)
    monkeypatch.setattr(launcher, "invoke_control_once", lambda _command: "nonzero")
    monkeypatch.setattr(launcher, "poll_activation", lambda *_args: (dict(release), "PENDING"))
    with pytest.raises(launcher.LifecycleFailure) as release_error:
        launcher.release_and_reconcile("123", "mirc-" + "1" * 24)
    assert str(release_error.value) == "activation_not_converged"
    assert release_error.value.release == {
        "attempts": 1,
        "command_outcome": "nonzero",
        "observed_state": "PENDING",
        **release,
    }


def test_sbatch_signal_reaps_child_process_group(monkeypatch) -> None:
    launcher = load_launcher()
    killed: list[int] = []

    class FakeProcess:
        pid = 4242

        def __init__(self):
            self.calls = 0
            self.returncode = None

        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise launcher.LaunchInterrupted(signal.SIGTERM)
            self.returncode = -signal.SIGTERM
            return self.returncode

        def poll(self):
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(
        launcher.os,
        "killpg",
        lambda _pid, sig: killed.append(sig),
    )
    with pytest.raises(launcher.LaunchInterrupted):
        launcher.invoke_sbatch(["/usr/bin/sbatch"])
    assert killed == [signal.SIGTERM]
    assert process.returncode == -signal.SIGTERM


def test_wrapper_is_held_and_refuses_unsealed_or_mutated_gate() -> None:
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    assert '"--hold"' in inspect.getsource(load_launcher().sbatch_command)
    assert "'directory|500|tianhaowu'" in wrapper
    assert "submission_failure.json" in wrapper
    assert 'require_file "$RETRY_AUTHORIZATION_FILE" 400' in wrapper
    assert 'require_file "$RETRY_ACTIVATION_PERMIT_FILE" 400' in wrapper
    assert 'require_file "$LAUNCHER" 500 "$RETRY_LAUNCHER_SHA256"' in wrapper
    assert 'require_file "$GENERATOR" 500 "$RETRY_GENERATOR_SHA256"' in wrapper
    assert wrapper.index("gate_deadline=") < wrapper.index(
        'require_git_equal "$SOURCE_ROOT"'
    )
    assert wrapper.index("RETRY_ACTIVATION_PERMIT_FILE") < wrapper.index(
        'exec /bin/bash "$RUN_ORACLE"'
    )


def test_wrapper_envelope_gate_rejects_mutated_permit(tmp_path: Path) -> None:
    launcher = load_launcher()
    token = "1" * 24
    job_id = "123"
    job_name = f"mirc-{token}"
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    wrapper_hash = "a" * 64
    auth_path = reservation / f"job_authorization_{token}.json"
    permit_path = reservation / f"activation_permit_{token}.json"
    receipt_path = reservation / "submission_receipt.json"
    environment_path = reservation / "slurm_environment.bin"
    intent_path = reservation / "launch_intent.json"
    environment_path.write_bytes(b"PUBLIC=1\0")
    intent_path.write_bytes(b"intent\n")

    def sealed(body: dict, field: str) -> bytes:
        return launcher.envelope(body, field)

    packaging_provenance = canonical_packaging_provenance(launcher)
    auth_body = {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_job_authorization",
        "state": "held_identity_authorized",
        "cluster": launcher.CLUSTER,
        "job_name": job_name,
        "launch_token": token,
        "reservation": str(reservation),
        "authorization_path": str(auth_path),
        "launcher_sha256": "b" * 64,
        "job_wrapper_sha256": wrapper_hash,
        "source_revision": "r",
        "source_tree": "t",
        "verifiers_revision": launcher.VERIFIERS_REVISION,
        "vmvm_tb_v2_sha256": launcher.VMVM_SHA256,
        "x2p_environment_sha256": synthetic_x2p_sha256(),
        "module_import_closure": {
            "packaging": packaging_provenance,
        },
        "selection": {
            "task_file_sha256": "d" * 64,
            "role_file_sha256": "e" * 64,
            "receipt_file_sha256": "f" * 64,
            "receipt_sha256": "0" * 64,
            "selected": 19,
            "retry_candidates": 15,
            "controls": 4,
        },
        "held_identity_required_consecutive": 2,
    }
    auth_raw = sealed(auth_body, "authorization_sha256")
    auth_path.write_bytes(auth_raw)
    auth_hash = hashlib.sha256(auth_raw).hexdigest()
    permit_body = {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_activation_permit",
        "state": "activate",
        "cluster": launcher.CLUSTER,
        "job_name": job_name,
        "launch_token": token,
        "reservation": str(reservation),
        "authorization_sha256": auth_hash,
        "submission_receipt": str(receipt_path),
        "job_wrapper_sha256": wrapper_hash,
    }
    permit_raw = sealed(permit_body, "activation_permit_sha256")
    permit_path.write_bytes(permit_raw)
    permit_hash = hashlib.sha256(permit_raw).hexdigest()
    receipt_body = {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_submission",
        "state": "submitted",
        "code": None,
        "launcher_sha256": "b" * 64,
        "generator_sha256": launcher.GENERATOR_SHA256,
        "job_wrapper_sha256": wrapper_hash,
        "intent_sha256": hashlib.sha256(b"intent\n").hexdigest(),
        "environment_sha256": hashlib.sha256(b"PUBLIC=1\0").hexdigest(),
        "source_revision": "r",
        "source_tree": "t",
        "verifiers_revision": launcher.VERIFIERS_REVISION,
        "vmvm_tb_v2_sha256": launcher.VMVM_SHA256,
        "x2p_environment_sha256": synthetic_x2p_sha256(),
        "selection": {
            "task_file_sha256": "d" * 64,
            "role_file_sha256": "e" * 64,
            "receipt_file_sha256": "f" * 64,
            "receipt_sha256": "0" * 64,
            "selected": 19,
            "retry_candidates": 15,
            "controls": 4,
        },
        "attempt_policy": launcher.ATTEMPT_POLICY,
        "module_import_closure": {
            "packaging": packaging_provenance,
        },
        "scheduler": {
            "cluster": launcher.CLUSTER,
            "job_id": job_id,
            "job_name": job_name,
            "launch_token": token,
            "submission_attempts": 1,
            "submitted_held": True,
            "time_limit": "7-00:00:00",
        },
        "lifecycle": {
            "protocol": "held_two_phase_deadline_v2",
            "authorization": {
                "mode": "0400",
                "path": str(auth_path),
                "sha256": auth_hash,
            },
            "activation_permit": {
                "mode": "0400",
                "path": str(permit_path),
                "published_last": True,
                "sha256": permit_hash,
            },
            "cancellation": None,
            "held_validation": held_telemetry(launcher),
            "release": {
                **activation_telemetry(launcher),
                "observed_state": "RUNNING",
            },
        },
        "acceptance": {
            "minimum_valid": 10,
            "all_controls_valid": True,
            "minimum_retry_recoveries": 6,
            "projected_union_valid": 2500,
        },
        "automatic_union_or_promotion": False,
    }
    receipt_path.write_bytes(sealed(receipt_body, "submission_receipt_sha256"))
    wrapper = JOB_PATH.read_text(encoding="utf-8")
    assert wrapper.count("<<'PY'") == 2
    assert "/usr/bin/python3 -I -S -B - <<'PY'" in wrapper
    marker = "<<'PY' >/dev/null 2>/dev/null || fail\n"
    start = wrapper.index(marker) + len(marker)
    program = wrapper[start : wrapper.index("\nPY\n", start)]
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-",
        str(auth_path),
        auth_hash,
        str(permit_path),
        permit_hash,
        str(receipt_path),
        str(environment_path),
        job_id,
        job_name,
        token,
        str(reservation),
        wrapper_hash,
    ]
    target_match = re.search(
        r"\(\n(?P<targets>(?:    [a-z_]+,\n)+)\) = sys\.argv\[1:\]",
        program,
    )
    assert target_match is not None
    targets = tuple(
        re.findall(r"^    ([a-z_]+),$", target_match.group("targets"), re.MULTILINE)
    )
    assert targets == (
        "auth_path",
        "auth_hash",
        "permit_path",
        "permit_hash",
        "receipt_path",
        "environment_path",
        "job_id",
        "job_name",
        "token",
        "reservation",
        "wrapper_hash",
    )
    assert len(command[5:]) == len(targets) == len(set(targets)) == 11
    environment = {
        "TASK_FILE_SHA256": "d" * 64,
        "SELECTION_ROLE_FILE_SHA256": "e" * 64,
        "SELECTION_RECEIPT_FILE_SHA256": "f" * 64,
        "SELECTION_RECEIPT_SHA256": "0" * 64,
        "RETRY_LAUNCHER_SHA256": "b" * 64,
        "RETRY_GENERATOR_SHA256": launcher.GENERATOR_SHA256,
        "RETRY_SOURCE_REVISION": "r",
        "RETRY_SOURCE_TREE": "t",
        "RETRY_VERIFIERS_REVISION": launcher.VERIFIERS_REVISION,
        "RETRY_VMVM_SHA256": launcher.VMVM_SHA256,
        **{
            launcher.X2P_DIGEST_ENV_NAMES[name]: digest
            for name, digest in synthetic_x2p_sha256().items()
        },
    }
    passed = subprocess.run(
        command,
        check=False,
        input=program.encode(),
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert passed.returncode == 0 and not passed.stdout and not passed.stderr
    permit_path.write_bytes(permit_raw + b"mutation")
    rejected = subprocess.run(
        command,
        check=False,
        input=program.encode(),
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert rejected.returncode != 0

    permit_path.write_bytes(permit_raw)
    for field in (
        "launcher_sha256",
        "generator_sha256",
        "source_revision",
        "source_tree",
        "verifiers_revision",
        "vmvm_tb_v2_sha256",
        "x2p_environment_sha256",
        "attempt_policy",
        "acceptance",
        "selection",
    ):
        mutated_receipt = copy.deepcopy(receipt_body)
        if field == "selection":
            mutated_receipt[field]["receipt_sha256"] = "1" * 64
        elif field in {"attempt_policy", "acceptance"}:
            mutated_receipt[field] = {}
        else:
            mutated_receipt[field] = "9" * 64
        receipt_path.write_bytes(
            sealed(mutated_receipt, "submission_receipt_sha256")
        )
        rejected = subprocess.run(
            command,
            check=False,
            input=program.encode(),
            capture_output=True,
            env=environment,
            timeout=10,
        )
        assert rejected.returncode != 0, field

    for section, field, value in (
        ("held_validation", "polls", "2"),
        ("release", "observed_mismatch_fields", ["raw field with spaces"]),
    ):
        mutated_receipt = copy.deepcopy(receipt_body)
        mutated_receipt["lifecycle"][section][field] = value
        if field == "observed_mismatch_fields":
            mutated_receipt["lifecycle"][section]["mismatch_field_count"] = 1
        receipt_path.write_bytes(
            sealed(mutated_receipt, "submission_receipt_sha256")
        )
        rejected = subprocess.run(
            command,
            check=False,
            input=program.encode(),
            capture_output=True,
            env=environment,
            timeout=10,
        )
        assert rejected.returncode != 0, (section, field)

    mutated_permit = copy.deepcopy(permit_body)
    mutated_permit["unexpected"] = True
    mutated_permit_raw = sealed(mutated_permit, "activation_permit_sha256")
    mutated_permit_hash = hashlib.sha256(mutated_permit_raw).hexdigest()
    permit_path.write_bytes(mutated_permit_raw)
    mutated_receipt = copy.deepcopy(receipt_body)
    mutated_receipt["lifecycle"]["activation_permit"][
        "sha256"
    ] = mutated_permit_hash
    receipt_path.write_bytes(sealed(mutated_receipt, "submission_receipt_sha256"))
    mutated_command = list(command)
    mutated_command[8] = mutated_permit_hash
    rejected = subprocess.run(
        mutated_command,
        check=False,
        input=program.encode(),
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert rejected.returncode != 0

    mutated_auth = copy.deepcopy(auth_body)
    mutated_auth["unexpected"] = True
    mutated_auth_raw = sealed(mutated_auth, "authorization_sha256")
    mutated_auth_hash = hashlib.sha256(mutated_auth_raw).hexdigest()
    auth_path.write_bytes(mutated_auth_raw)
    rebound_permit = copy.deepcopy(permit_body)
    rebound_permit["authorization_sha256"] = mutated_auth_hash
    rebound_permit_raw = sealed(rebound_permit, "activation_permit_sha256")
    rebound_permit_hash = hashlib.sha256(rebound_permit_raw).hexdigest()
    permit_path.write_bytes(rebound_permit_raw)
    rebound_receipt = copy.deepcopy(receipt_body)
    rebound_receipt["lifecycle"]["authorization"]["sha256"] = mutated_auth_hash
    rebound_receipt["lifecycle"]["activation_permit"][
        "sha256"
    ] = rebound_permit_hash
    receipt_path.write_bytes(sealed(rebound_receipt, "submission_receipt_sha256"))
    rebound_command = list(command)
    rebound_command[6] = mutated_auth_hash
    rebound_command[8] = rebound_permit_hash
    rejected = subprocess.run(
        rebound_command,
        check=False,
        input=program.encode(),
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert rejected.returncode != 0


def test_name_ambiguity_still_cancels_known_sbatch_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kw: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(
        launcher,
        "lookup_submission",
        lambda *_args: (_ for _ in ()).throw(
            launcher.LauncherError("scheduler_submission_not_unique")
        ),
    )
    cancellations: list[bool] = []
    monkeypatch.setattr(
        launcher,
        "cancel_and_prove",
        lambda *_args, **kwargs: (
            cancellations.append(kwargs["candidate_provenance"])
            or {"terminal_state": "CANCELLED"}
        ),
    )
    sealed: list[dict] = []
    monkeypatch.setattr(
        launcher, "publish_failure", lambda body: sealed.append(body) or "f" * 64
    )
    with pytest.raises(launcher.LauncherError, match="cancellation_unconfirmed"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert cancellations == ["sbatch_stdout"]
    assert sealed and sealed[0]["state"] == "ambiguous"
    assert sealed[0]["lifecycle"]["cancellation"]["known_candidate_cancelled"] is True


def test_submit_failure_certificate_retains_held_poll_telemetry(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(launcher, "lookup_submission", lambda *_args: ("unique", "123"))
    telemetry = failed_held_telemetry(launcher)
    telemetry["final_pre_authorization_mismatch_fields"] = None
    telemetry["post_authorization_mismatch_fields"] = None
    monkeypatch.setattr(
        launcher,
        "authorize_held_job",
        lambda *_args: (_ for _ in ()).throw(
            launcher.LifecycleFailure(
                "held_identity_not_converged", held_validation=telemetry
            )
        ),
    )
    monkeypatch.setattr(
        launcher,
        "cancel_and_prove",
        lambda *_args, **_kwargs: {"terminal_state": "CANCELLED"},
    )
    sealed: list[dict] = []
    monkeypatch.setattr(
        launcher, "publish_failure", lambda body: sealed.append(body) or "f" * 64
    )
    with pytest.raises(launcher.LauncherError, match="held_identity_not_converged"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert sealed[0]["lifecycle"]["held_validation"] == telemetry


def test_submit_failure_certificate_retains_release_poll_telemetry(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(launcher, "lookup_submission", lambda *_args: ("unique", "123"))
    held = {"converged": True, "observed_mismatch_fields": []}
    monkeypatch.setattr(launcher, "authorize_held_job", lambda *_args: dict(held))
    release = {
        **failed_activation_telemetry(launcher),
        "command_outcome": "nonzero",
    }
    monkeypatch.setattr(
        launcher,
        "release_and_reconcile",
        lambda *_args: (_ for _ in ()).throw(
            launcher.LifecycleFailure("activation_not_converged", release=release)
        ),
    )
    monkeypatch.setattr(
        launcher,
        "cancel_and_prove",
        lambda *_args, **_kwargs: {"terminal_state": "CANCELLED"},
    )
    sealed: list[dict] = []
    monkeypatch.setattr(
        launcher, "publish_failure", lambda body: sealed.append(body) or "f" * 64
    )
    with pytest.raises(launcher.LauncherError, match="activation_not_converged"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert sealed[0]["lifecycle"]["held_validation"] == held
    assert sealed[0]["lifecycle"]["release"] == release


def test_submit_never_cancels_or_publishes_failure_after_admission_commit(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(launcher, "lookup_submission", lambda *_args: ("unique", "123"))
    monkeypatch.setattr(launcher, "authorize_held_job", lambda *_args: {})
    monkeypatch.setattr(launcher, "release_and_reconcile", lambda *_args: {})

    def committed_failure(*_args, **kwargs):
        kwargs["commit_state"]["committed"] = True
        raise launcher.LaunchInterrupted(signal.SIGTERM)

    monkeypatch.setattr(launcher, "publish_success", committed_failure)
    cleanup: list[str] = []
    monkeypatch.setattr(
        launcher,
        "cancel_and_prove",
        lambda *_args, **_kwargs: cleanup.append("cancel") or {},
    )
    monkeypatch.setattr(
        launcher,
        "publish_failure",
        lambda _body: cleanup.append("failure") or "f" * 64,
    )
    with pytest.raises(launcher.LaunchInterrupted):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert cleanup == []


def test_signal_after_unknown_submit_recovers_and_cancels(
    monkeypatch, tmp_path: Path
) -> None:
    launcher = load_launcher()
    reservation = tmp_path / "reservation"
    reservation.mkdir(mode=0o700)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(launcher, "LOG_ROOT", tmp_path / "log")
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kw: None
    )
    monkeypatch.setattr(
        launcher, "acquire_reservation", lambda *_args: ("1" * 64, "2" * 64)
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: (_ for _ in ()).throw(
            launcher.LaunchInterrupted(signal.SIGTERM)
        ),
    )
    monkeypatch.setattr(launcher, "lookup_submission", lambda *_args: ("unique", "123"))
    canceled: list[str] = []
    monkeypatch.setattr(
        launcher,
        "cancel_and_prove",
        lambda job_id, *_args, **_kwargs: (
            canceled.append(job_id) or {"terminal_state": "CANCELLED"}
        ),
    )
    monkeypatch.setattr(launcher, "publish_failure", lambda _body: "f" * 64)
    with pytest.raises(launcher.LauncherError, match="launch_interrupted"):
        launcher.submit_once(
            "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
            synthetic_tls_credentials(launcher),
            synthetic_x2p_values(),
        )
    assert canceled == ["123"]


def test_public_success_state_machine_publishes_permit_last_and_seals(
    tmp_path: Path, monkeypatch
) -> None:
    launcher = load_launcher()
    oracle = tmp_path / "oracle"
    logs = tmp_path / "logs"
    oracle.mkdir()
    logs.mkdir()
    output = oracle / "run"
    reservation = oracle / "reservation"
    log_root = logs / "run"
    monkeypatch.setattr(launcher, "OUTPUT_ROOT", output)
    monkeypatch.setattr(launcher, "RESERVATION", reservation)
    monkeypatch.setattr(launcher, "LOG_ROOT", log_root)
    monkeypatch.setattr(launcher, "INTENT", reservation / "launch_intent.json")
    monkeypatch.setattr(
        launcher, "ENVIRONMENT_FILE", reservation / "slurm_environment.bin"
    )
    monkeypatch.setattr(
        launcher, "SUBMISSION_RECEIPT", reservation / "submission_receipt.json"
    )
    monkeypatch.setattr(
        launcher, "FAILURE_CERTIFICATE", reservation / "submission_failure.json"
    )
    monkeypatch.setattr(launcher.secrets, "token_hex", lambda _size: "1" * 24)
    monkeypatch.setattr(launcher, "scheduler_matches", lambda *_args: set())
    monkeypatch.setattr(
        launcher, "immediate_pre_submit_revalidation", lambda **_kw: None
    )
    monkeypatch.setattr(
        launcher,
        "invoke_sbatch",
        lambda _command: ("completed", 0, "123;fair-cw-use2-3\n"),
    )
    monkeypatch.setattr(launcher, "lookup_submission", lambda *_args: ("unique", "123"))
    monkeypatch.setattr(
        launcher,
        "held_snapshot",
        lambda *_args, **_kwargs: (True, (), (), held_details()),
    )
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    releases: list[str] = []
    monkeypatch.setattr(
        launcher,
        "invoke_control_once",
        lambda command: releases.append(command[-2]) or "completed",
    )
    monkeypatch.setattr(
        launcher,
        "poll_activation",
        lambda *_args: (activation_telemetry(launcher), "PENDING"),
    )
    job_id, receipt_sha = launcher.submit_once(
        "a" * 64, object(), "b" * 64, "c" * 64, "d" * 64, "e" * 64,
        synthetic_tls_credentials(launcher),
        synthetic_x2p_values(),
    )
    assert job_id == "123" and len(receipt_sha) == 64
    assert releases == ["release"]
    assert stat.S_IMODE(reservation.stat().st_mode) == 0o500
    assert {path.name for path in reservation.iterdir()} == {
        "launch_intent.json",
        "slurm_environment.bin",
        "submission_receipt.json",
        "job_authorization_" + "1" * 24 + ".json",
        "activation_permit_" + "1" * 24 + ".json",
    }
    assert not launcher.FAILURE_CERTIFICATE.exists()
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o400 for path in reservation.iterdir()
    )
    receipt = json.loads(launcher.SUBMISSION_RECEIPT.read_bytes())
    observed = launcher.validate_submission_receipt(
        receipt,
        launcher_sha="a" * 64,
        task_sha="b" * 64,
        role_sha="c" * 64,
        receipt_file_sha="d" * 64,
        receipt_sha="e" * 64,
        x2p_sha256=synthetic_x2p_sha256(),
    )
    assert observed[0] == "123"
    assert observed[3] == receipt["submission_receipt_sha256"]
    assert (
        receipt_sha
        == hashlib.sha256(launcher.SUBMISSION_RECEIPT.read_bytes()).hexdigest()
    )
    assert not output.exists()
