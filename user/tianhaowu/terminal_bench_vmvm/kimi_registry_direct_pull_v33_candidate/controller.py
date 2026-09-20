#!/usr/bin/env python3
"""One-shot, task-free Kimi registry direct-pull gate.

The controller admits exactly one held Slurm allocation, proves its identity twice,
releases it once, and records only an aggregate terminal result.  It never starts a
container, model, endpoint, sandbox, task, or evaluator.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
BUNDLE = BASE / "watchers/k3_registry_direct_pull_gate_20260920t211000z_v33"
APPROVAL = BASE / "approvals/k3_registry_direct_pull_gate_20260920t211000z_v33.approval.json"
RUN_ROOT = BASE / "diagnostics/k3_registry_direct_pull_gate_20260920t211000z_v33"
LOG_ROOT = BASE / "logs/k3_registry_direct_pull_gate_20260920t211000z_v33"
LOCK = BASE / "locks/k3_registry_direct_pull_gate_20260920t211000z_v33.lock"
# V33 is bound to the reviewed cleanup-safe direct-pull successor.
SOURCE_BOUND = True
SOURCE_ROOT = BASE / "sources/ram-common-468a6e5"
SOURCE_BUNDLE = BASE / "sources/ram-common-468a6e5.bundle"
SOURCE_REVISION = "468a6e5b83ba51a8fe0389f1105f34dd18fa03f3"
SOURCE_TREE = "bd6d81b7748c5055876100b9dc115eed8a764fe0"
SOURCE_BUNDLE_SHA256 = "7aaeec5142d7d3e0fdaabebc441094e79300adb36aee370f8a397a3f356968a3"
SOURCE_BUNDLE_SIZE = 5_436_664
COMPUTE_PROBE_ROOT = BASE / "diagnostics/k3_compute_tool_manifest_diag_20260920t203000z_v7"
COMPUTE_PROBE_PRIVATE = COMPUTE_PROBE_ROOT / "private_manifest.tsv"
COMPUTE_PROBE_PRIVATE_SHA256 = "5ff855d974f26c242d27eb5bc8ab32e52e5c4a33f03ebcd670d520a2c64d8333"
COMPUTE_PROBE_PRIVATE_SIZE = 8_023
COMPUTE_PROBE_RESULT = COMPUTE_PROBE_ROOT / "result.json"
COMPUTE_PROBE_RESULT_SHA256 = "ae05540829e86b24dadf820f000734ebe48cc0cada0fe66027d6dd1e66e22344"
COMPUTE_PROBE_RESULT_SIZE = 747
COMPUTE_PROBE_JOB_RESULT = COMPUTE_PROBE_ROOT / "job_result.json"
COMPUTE_PROBE_JOB_RESULT_SHA256 = "d42b56f78a6d6da8c0ff3145322e4ee21eec7818909521b7e26eac85204bd14e"
COMPUTE_PROBE_JOB_RESULT_SIZE = 316
COMPUTE_PROBE_APPROVAL_SHA256 = "321bade8ec60c56cc4339f3e1e3e6318acec843c401acd5b03f13ef9a8305544"
COMPUTE_PROBE_BASELINE_SHA256 = "d9fc3a8df4f0b7dac46948183814da6d577e75b5246a1aad0b12ae09ce048630"
COMPUTE_PROJECTION_SHA256 = "22adaa08c33b4b7f4636fdc9af884c52928f7f9ae00987e7adff6b667e19f1d6"
COMPUTE_PROBE_NODE = "g3-128-185"
COMPUTE_PROBE_ENTRIES = 33
COMPUTE_PROBE_MISMATCH_BITMAP = "110111100011101111110111111111101"
COMPUTE_PROBE_PYTHON_BITMAP = "1001"
COMPUTE_PYTHON = "/usr/bin/python3.12"
COMPUTE_PYTHON_SHA256 = "50d2b4d722d4b3b275e16d1d3b23457e5649428af598cc56f83c8544914e4690"
WORKER = SOURCE_ROOT / "vllm_tools/serve_api_v2/src/serve_api_v2/worker/worker_vllm.sh"
AWS_CREDS = SOURCE_ROOT / "vllm_tools/serve_api_v2/src/serve_api_v2/worker/aws_creds.sh"
ARG_TEST = SOURCE_ROOT / "vllm_tools/serve_api_v2/tests/script_tests/smoke_container_args.sh"
MODEL_CARD = SOURCE_ROOT / "vllm_tools/serve_api_v2/config/models/kimi-k3/card.toml"
SOURCE_FILES = {
    WORKER: "a73b75e3d1dc6bdef78842a5346db49a7e2f9649e661ce9e48424c5e05f3f6c5",
    AWS_CREDS: "f5f6abc7a2c8663a86f630a54ad41ff50efe85bca736dd7413e5882e036b4358",
    ARG_TEST: "6cc6f76dc55136ec0e63afb3469635949113903ba8c7ccc13ff2ca5c62cef677",
    MODEL_CARD: "af24f4a86e7dc0a360f5e68bcca82adf88dfb4847abc8c4d26aaebb4355adf8e",
}
IMAGE = (
    "588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/vllm-openai:"
    "kimi-k3-kda-logprobs-fix-v2-20260916@"
    "sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20"
)
IMAGE_DIGEST = "sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20"
CLUSTER = "fair-cw-use2-3"
OWNER = "tianhaowu"
OWNER_UID = 656177
OWNER_RECORD = "tianhaowu(656177)"
JOB_NAME = "k3-reg-pull-211000-v33"
COMMENT_PREFIX = "k3-reg-pull-v33:"
PARTITION = "g3"
ACCOUNT = "ram"
QOS = "g3_lowest"
WALLTIME = "00:30:00"
SIGNAL_LEAD_SECONDS = 240
PODMAN_GUARD_SIGNAL_BOUND_SECONDS = 3
PROBE_CLEANUP_BOUND_SECONDS = 125
OUTER_KILL_GRACE_SECONDS = 150
PARENT_TERM_GRACE_SECONDS = 160
PARENT_KILL_REAP_SECONDS = 5
BATCH_CLEANUP_BOUND_SECONDS = 25
RESULT_PUBLICATION_BOUND_SECONDS = 20
SIGNAL_TEARDOWN_BOUND_SECONDS = (
    PARENT_TERM_GRACE_SECONDS
    + PARENT_KILL_REAP_SECONDS
    + BATCH_CLEANUP_BOUND_SECONDS
    + RESULT_PUBLICATION_BOUND_SECONDS
)
CPUS = 4
MEMORY = "16G"
EXCLUDED = ("g3-136-221", "g3-136-247", "g3-136-251", "g3-136-253")
PINNED_NODE = COMPUTE_PROBE_NODE
CANONICAL_TMUX_TARGET = "swebench_vmvm:Launcher.0"
EXPECTED_REQ_TRES = {
    "billing": "4",
    "cpu": "4",
    "gres/gpu": "1",
    "mem": "16G",
    "node": "1",
}
EXPECTED_QOS_PRIORITY = 1
EXPECTED_QOS_OUTBOUND = ("normal",)
EXPECTED_QOS_PREEMPTORS = (
    "g3_adapt_high",
    "g3_admin_high",
    "g3_comm_shared",
    "g3_core_shared",
    "g3_dino_high",
    "g3_esi_high",
    "g3_guacamole_high",
    "g3_mnm_high",
    "g3_umami_high",
)
TLS_NAMES = ("THRIFT_TLS_CL_CERT_PATH", "THRIFT_TLS_CL_KEY_PATH")
TLS_SIZE = 5580
HASH_ENV = {
    "launcher": "EXPECTED_LAUNCHER_SHA256",
    "controller": "EXPECTED_CONTROLLER_SHA256",
    "batch": "EXPECTED_BATCH_SHA256",
    "probe": "EXPECTED_PROBE_SHA256",
    "classifier": "EXPECTED_CLASSIFIER_SHA256",
    "podman_guard": "EXPECTED_PODMAN_GUARD_SHA256",
    "scrubber": "EXPECTED_SCRUBBER_SHA256",
    "tools_manifest": "EXPECTED_TOOLS_MANIFEST_SHA256",
    "readme": "EXPECTED_README_SHA256",
    "tests": "EXPECTED_TEST_SHA256",
    "pending": "EXPECTED_PENDING_SHA256",
}
BUNDLE_FILES = {
    "launcher": ("launch.sh", 0o500),
    "controller": ("controller.py", 0o500),
    "batch": ("run_registry_gate.sbatch", 0o500),
    "probe": ("probe_registry_gate.sh", 0o500),
    "classifier": ("classify_registry_error.sh", 0o500),
    "podman_guard": ("podman_guard.sh", 0o500),
    "scrubber": ("scrub_private_tree.py", 0o500),
    "tools_manifest": ("compute_tools.sha256", 0o400),
    "readme": ("README.md", 0o400),
    "tests": ("test_controller.py", 0o400),
    "pending": ("pending.json", 0o400),
}
TOOLS = {
    Path("/usr/bin/python3.12"): "1a301bb1763139d48ae638d97b11edf56de6cd185e1b054eae6dc28c271c0c5f",
    Path("/usr/bin/bash"): "af955ef55333c8fc9c5aa50df91ad1a629d9a79a9afa125cd5e9629585f78015",
    Path("/usr/bin/sbatch"): "3c1029c3a436107bf48b3b2d450e5fd1c9b204e6674906005cbbbb3c7df7feda",
    Path("/usr/bin/scontrol"): "395549996ab93fbbb806b8d68d355a97d9dbdf28dad2f421872b8d1fbdabe4ad",
    Path("/usr/bin/squeue"): "45fa838a4882d58d7bd2604f52b79aae98fafe1d165008d56f7220a4e7faf341",
    Path("/usr/bin/sacct"): "5149de553e71a44118c6f30e0f7bba5cb55f540308a7943f084f24709b588c57",
    Path("/usr/bin/scancel"): "6b8c2c876e8e47b42995901d7c51244fca8c0f180ba9b6a4c3ed7373fdeebac9",
    Path("/usr/bin/sacctmgr"): "2dcd07aebda7cc95ebbf8daecadde9d8d7788b89a9c3ec85a0f4693bf5f85c2f",
    Path("/usr/bin/tmux"): "e38ba2aef1810640f05fd8afaa62daf47ccce6bc0e18d73f73b8b6cc94deade2",
    Path("/usr/bin/git"): "aa6540695d076182256dd6e96c8b302e4d56381e3000bbfd5c71bbdfe94a4942",
}
SAFE_ENV = {
    "HOME": "/nonexistent",
    "USER": OWNER,
    "LOGNAME": OWNER,
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "SLURM_CLUSTER_NAME": CLUSTER,
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}
SHA_RE = re.compile(r"[0-9a-f]{64}")
JOB_RE = re.compile(r"[1-9][0-9]{0,19}")
TOKEN_RE = re.compile(r"[0-9a-f]{24}")
COMPUTE_MANIFEST_CATEGORY_RE = re.compile(r"source_compute_manifest_c([0-9]{2})_b([01]{33})")
NULLISH = frozenset({None, "", "None", "(null)", "Unknown"})
LIVE_WRITER_CATEGORY = "live_writer_cleanup_unproven"
TERMINAL = frozenset(
    {
        "BOOT_FAIL",
        "CANCELLED",
        "COMPLETED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "TIMEOUT",
    }
)
ALLOWED_PUBLIC_CATEGORIES = frozenset(
    {
        "success",
        "allocation_identity",
        "source_spool_identity",
        "source_spool_hash",
        "source_bundle_identity",
        "source_bundle_hash",
        "probe_source_identity",
        "private_environment",
        "podman_info_command",
        "podman_info_shape",
        "podman_store_graphroot",
        "podman_store_runroot",
        "podman_store_driver",
        "podman_info_image_present",
        "podman_info_image_check",
        "registry_pull",
        "pull_mint_broker",
        "pull_mint_timeout",
        "pull_mint_empty",
        "pull_token_shape",
        "pull_authfile_create",
        "pull_authfile_lookup",
        "pull_guard_precondition",
        "pull_guard_child",
        "pull_guard_postcondition",
        "pull_http_400",
        "pull_http_401",
        "pull_http_403",
        "pull_http_404",
        "pull_http_other4xx",
        "pull_http_5xx",
        "pull_expired",
        "pull_not_authorized",
        "pull_denied",
        "pull_auth_challenge",
        "pull_config",
        "pull_writeback",
        "pull_tls",
        "pull_proxy",
        "pull_transport",
        "pull_timeout",
        "pull_image_missing",
        "pull_platform",
        "pull_storage",
        "pull_empty_125",
        "pull_empty_other",
        "pull_unknown",
        "image_identity",
        "image_remove",
        "private_cleanup",
        "private_cleanup_retained",
        "private_cleanup_sensitive",
        LIVE_WRITER_CATEGORY,
        "interrupted",
        "internal",
    }
)
INTERRUPTED = False
SUBMISSION_ATTEMPTED = False
SUBMITTED_JOB_ID: str | None = None
OWNED_JOB_IDS: set[str] = set()
TERMINAL_ACCOUNTING_OBSERVED = False


class GateError(RuntimeError):
    pass


class SchedulerUnavailable(GateError):
    pass


class IdentityTransient(GateError):
    pass


class AccountingTransient(GateError):
    pass


class TerminalBeforeActive(GateError):
    pass


class GateInterrupted(BaseException):
    pass


@dataclass(frozen=True)
class Capture:
    raw: bytes
    sha256: str
    signature: tuple[int, ...]


@dataclass
class LockState:
    fd: int
    parent_fd: int
    inode: tuple[int, int]
    parent_identity: tuple[int, int, int, int]


def fail(code: str) -> None:
    raise GateError(code)


def require_source_bound() -> None:
    if not SOURCE_BOUND:
        fail("source_unbound")


def error_code(error: BaseException) -> str:
    if isinstance(error, GateInterrupted):
        return "signal"
    if isinstance(error, GateError) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(error)):
        return str(error)
    return "internal_error"


def valid_compute_manifest_category(category: object) -> bool:
    if not isinstance(category, str):
        return False
    match = COMPUTE_MANIFEST_CATEGORY_RE.fullmatch(category)
    if match is None:
        return False
    mismatch_count = int(match.group(1))
    mismatch_bitmap = match.group(2)
    return 1 <= mismatch_count <= 33 and mismatch_bitmap.count("1") == mismatch_count


def signal_handler(_signum: int, _frame: object) -> None:
    global INTERRUPTED
    INTERRUPTED = True


def check_interrupted() -> None:
    if INTERRUPTED:
        raise GateInterrupted()


@contextlib.contextmanager
def commit_signal_mask() -> object:
    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        check_interrupted()
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def stable_file(
    path: Path,
    *,
    mode: int,
    expected: str | None = None,
    maximum: int = 64 << 20,
    uid: int = OWNER_UID,
) -> Capture:
    try:
        before = path.lstat()
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != mode
                or opened.st_uid != uid
                or opened.st_nlink != 1
                or opened.st_size > maximum
            ):
                fail("file_identity")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                block = os.read(fd, min(1 << 20, remaining))
                if not block:
                    break
                chunks.append(block)
                remaining -= len(block)
            raw = b"".join(chunks)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        named = path.lstat()
    except OSError as error:
        raise GateError("file_identity") from error
    if (
        signature(before) != signature(opened)
        or signature(opened) != signature(after)
        or signature(after) != signature(named)
    ):
        fail("file_race")
    observed = digest(raw)
    if expected is not None and observed != expected:
        fail("file_hash")
    return Capture(raw, observed, signature(opened))


def run(
    argv: Sequence[str], *, timeout: int = 30, env: Mapping[str, str] | None = None, code: str = "command"
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=dict(env or SAFE_ENV),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SchedulerUnavailable(f"{code}_unavailable") from error
    if len(result.stdout) + len(result.stderr) > (1 << 20):
        fail(f"{code}_oversize")
    if result.returncode != 0:
        raise SchedulerUnavailable(f"{code}_failed")
    return result


def bundle_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    if BUNDLE.resolve(strict=True) != BUNDLE or BUNDLE.is_symlink():
        fail("bundle_identity")
    info = BUNDLE.stat(follow_symlinks=False)
    if stat.S_IMODE(info.st_mode) != 0o500 or info.st_uid != OWNER_UID:
        fail("bundle_identity")
    for key, (name, mode) in BUNDLE_FILES.items():
        expected = os.environ.get(HASH_ENV[key], "")
        if SHA_RE.fullmatch(expected) is None:
            fail("bundle_hash_environment")
        captured = stable_file(BUNDLE / name, mode=mode, expected=expected)
        hashes[key] = captured.sha256
    if sorted(path.name for path in BUNDLE.iterdir()) != sorted(name for name, _mode in BUNDLE_FILES.values()):
        fail("bundle_extra_file")
    return hashes


def validate_tools() -> None:
    for path, expected in TOOLS.items():
        stable_file(path, mode=0o755, expected=expected, maximum=16 << 20, uid=0)


def git_output(*args: str) -> str:
    result = run(("/usr/bin/git", "-C", str(SOURCE_ROOT), *args), env=SAFE_ENV, code="source_git")
    try:
        return result.stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as error:
        raise GateError("source_git_encoding") from error


def validate_compute_probe(tools_manifest: Path) -> tuple[tuple[int, ...], ...]:
    private = stable_file(
        COMPUTE_PROBE_PRIVATE,
        mode=0o400,
        expected=COMPUTE_PROBE_PRIVATE_SHA256,
        maximum=16 << 10,
    )
    if len(private.raw) != COMPUTE_PROBE_PRIVATE_SIZE:
        fail("compute_probe_private_size")
    result = stable_file(
        COMPUTE_PROBE_RESULT,
        mode=0o400,
        expected=COMPUTE_PROBE_RESULT_SHA256,
        maximum=4096,
    )
    if len(result.raw) != COMPUTE_PROBE_RESULT_SIZE:
        fail("compute_probe_result_size")
    job_result = stable_file(
        COMPUTE_PROBE_JOB_RESULT,
        mode=0o400,
        expected=COMPUTE_PROBE_JOB_RESULT_SHA256,
        maximum=4096,
    )
    if len(job_result.raw) != COMPUTE_PROBE_JOB_RESULT_SIZE:
        fail("compute_probe_job_result_size")
    try:
        result_payload = json.loads(result.raw)
        job_payload = json.loads(job_result.raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError("compute_probe_result_json") from error
    result_keys = {
        "approval_sha256",
        "baseline_manifest_sha256",
        "category",
        "elapsed",
        "exit_code",
        "job_id",
        "kind",
        "mismatch_bitmap",
        "mismatch_count",
        "private_manifest_sha256",
        "public_log_sha256",
        "python_candidate_count",
        "python_preferred_index",
        "python_usable_bitmap",
        "python_usable_count",
        "schema_version",
        "slurm_state",
        "state",
    }
    expected_job = {
        "category": "comparison_complete",
        "checked_count": COMPUTE_PROBE_ENTRIES,
        "kind": "k3-compute-tool-manifest-diag-v7",
        "mismatch_bitmap": COMPUTE_PROBE_MISMATCH_BITMAP,
        "mismatch_count": 26,
        "python_candidate_count": 4,
        "python_preferred_index": 3,
        "python_usable_bitmap": COMPUTE_PROBE_PYTHON_BITMAP,
        "python_usable_count": 2,
        "schema_version": 1,
        "state": "complete",
    }
    aggregate_keys = (
        "category",
        "mismatch_bitmap",
        "mismatch_count",
        "python_candidate_count",
        "python_preferred_index",
        "python_usable_bitmap",
        "python_usable_count",
        "schema_version",
        "state",
    )
    if (
        result.raw != canonical(result_payload)
        or job_result.raw != canonical(job_payload)
        or set(result_payload) != result_keys
        or job_payload != expected_job
        or result_payload.get("kind") != "k3-compute-tool-manifest-diag-v7-result"
        or result_payload.get("state") != "complete"
        or result_payload.get("category") != "comparison_complete"
        or result_payload.get("slurm_state") != "COMPLETED"
        or result_payload.get("exit_code") != "0:0"
        or result_payload.get("elapsed") != "00:00:15"
        or JOB_RE.fullmatch(str(result_payload.get("job_id", ""))) is None
        or result_payload.get("approval_sha256") != COMPUTE_PROBE_APPROVAL_SHA256
        or result_payload.get("baseline_manifest_sha256") != COMPUTE_PROBE_BASELINE_SHA256
        or result_payload.get("mismatch_bitmap") != COMPUTE_PROBE_MISMATCH_BITMAP
        or result_payload.get("mismatch_count") != 26
        or result_payload.get("python_candidate_count") != 4
        or result_payload.get("python_preferred_index") != 3
        or result_payload.get("python_usable_bitmap") != COMPUTE_PROBE_PYTHON_BITMAP
        or result_payload.get("python_usable_count") != 2
        or result_payload.get("private_manifest_sha256") != COMPUTE_PROBE_PRIVATE_SHA256
        or result_payload.get("public_log_sha256") != COMPUTE_PROBE_JOB_RESULT_SHA256
        or any(result_payload.get(key) != job_payload.get(key) for key in aggregate_keys)
    ):
        fail("compute_probe_result_contract")
    try:
        text = private.raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise GateError("compute_probe_private_encoding") from error
    if not text.endswith("\n") or "\r" in text or "\0" in text:
        fail("compute_probe_private_shape")
    lines = text.splitlines()
    expected_header = [
        "schema_version\t1",
        "kind\tk3-compute-tool-manifest-diag-v7-private",
        "state\tcomplete",
        f"job_id\t{result_payload['job_id']}",
        f"node\t{COMPUTE_PROBE_NODE}",
        f"baseline_sha256\t{COMPUTE_PROBE_BASELINE_SHA256}",
        f"records\t{COMPUTE_PROBE_ENTRIES}",
        "python_candidates\t4",
    ]
    if lines[: len(expected_header)] != expected_header or len(lines) != len(expected_header) + 37:
        fail("compute_probe_private_shape")
    records = [line.split("\t") for line in lines[8:41]]
    python_rows = [line.split("\t") for line in lines[41:]]
    if len(records) != COMPUTE_PROBE_ENTRIES or len(python_rows) != 4:
        fail("compute_probe_private_shape")
    derived_bitmap = ""
    seen: set[str] = set()
    projection: list[str] = []
    observed_by_path: dict[str, str] = {}
    for index, row in enumerate(records):
        if len(row) != 8:
            fail("compute_probe_record")
        raw_index, source, status, path_metadata, target_metadata, expected, observed, path = row
        expected_status = "match" if observed == expected else "hash_mismatch"
        if (
            raw_index != str(index)
            or source != "fresh_compute_node"
            or status != expected_status
            or path_metadata != "regular_file:755:0:1"
            or target_metadata != "regular_file:755:0:1"
            or SHA_RE.fullmatch(expected) is None
            or SHA_RE.fullmatch(observed) is None
            or re.fullmatch(r"/usr/bin/[A-Za-z0-9._+-]+", path) is None
            or path in seen
        ):
            fail("compute_probe_record")
        seen.add(path)
        observed_by_path[path] = observed
        derived_bitmap += "0" if status == "match" else "1"
        projection.append(f"{observed}  {path}")
    if (
        derived_bitmap != COMPUTE_PROBE_MISMATCH_BITMAP
        or observed_by_path.get(COMPUTE_PYTHON) != COMPUTE_PYTHON_SHA256
    ):
        fail("compute_probe_projection")
    projection_raw = ("\n".join(projection) + "\n").encode()
    manifest = stable_file(
        tools_manifest,
        mode=0o400,
        expected=COMPUTE_PROJECTION_SHA256,
        maximum=4096,
    )
    if manifest.raw != projection_raw:
        fail("compute_probe_projection")
    candidates = ("/usr/bin/python3", "/usr/bin/python3.10", "/usr/bin/python3.11", COMPUTE_PYTHON)
    python_bitmap = ""
    for index, row in enumerate(python_rows):
        if len(row) != 12:
            fail("compute_probe_python_shape")
        (
            label,
            raw_index,
            usable,
            kind,
            path_metadata,
            target_metadata,
            observed,
            major,
            minor,
            path,
            link_target,
            resolved_target,
        ) = row
        if (
            label != "python"
            or raw_index != str(index)
            or usable not in {"0", "1"}
            or kind not in {"absent", "regular", "symlink", "other"}
            or path != candidates[index]
            or (observed != "-" and SHA_RE.fullmatch(observed) is None)
            or (major == "-") != (minor == "-")
            or (major != "-" and (not major.isdigit() or not minor.isdigit()))
        ):
            fail("compute_probe_python_shape")
        regular_identity = (
            kind == "regular"
            and path_metadata == "regular_file:755:0:1"
            and target_metadata == path_metadata
            and link_target == "-"
            and resolved_target == path
        )
        symlink_identity = (
            kind == "symlink"
            and path_metadata == "symbolic_link:777:0:1"
            and target_metadata == "regular_file:755:0:1"
            and link_target not in {"", "-"}
            and resolved_target.startswith("/usr/bin/")
            and os.path.normpath(resolved_target) == resolved_target
        )
        derived_usable = (
            (regular_identity or symlink_identity)
            and observed != "-"
            and major == "3"
            and int(minor) >= 9
        )
        if (usable == "1") != derived_usable:
            fail("compute_probe_python_identity")
        python_bitmap += usable
    if python_bitmap != COMPUTE_PROBE_PYTHON_BITMAP:
        fail("compute_probe_python_identity")
    if python_rows[3] != [
        "python",
        "3",
        "1",
        "regular",
        "regular_file:755:0:1",
        "regular_file:755:0:1",
        COMPUTE_PYTHON_SHA256,
        "3",
        "12",
        COMPUTE_PYTHON,
        "-",
        COMPUTE_PYTHON,
    ]:
        fail("compute_probe_selected_identity")
    return private.signature, result.signature, job_result.signature, manifest.signature


def validate_source(tools_manifest: Path) -> None:
    require_source_bound()
    stable_file(SOURCE_BUNDLE, mode=0o400, expected=SOURCE_BUNDLE_SHA256, maximum=8 << 20)
    if SOURCE_BUNDLE.stat().st_size != SOURCE_BUNDLE_SIZE:
        fail("source_bundle_size")
    if SOURCE_ROOT.resolve(strict=True) != SOURCE_ROOT or SOURCE_ROOT.is_symlink():
        fail("source_root")
    source_root_info = SOURCE_ROOT.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(source_root_info.st_mode)
        or stat.S_IMODE(source_root_info.st_mode) != 0o500
        or source_root_info.st_uid != OWNER_UID
    ):
        fail("source_root")
    if (
        git_output("rev-parse", "HEAD^{commit}") != SOURCE_REVISION
        or git_output("rev-parse", "HEAD^{tree}") != SOURCE_TREE
    ):
        fail("source_revision")
    if git_output("status", "--porcelain=v1", "--untracked-files=all"):
        fail("source_dirty")
    for path, expected in SOURCE_FILES.items():
        mode = 0o500 if path != MODEL_CARD else 0o400
        stable_file(path, mode=mode, expected=expected, maximum=2 << 20)
    validate_compute_probe(tools_manifest)


def qos_contract() -> None:
    result = run(("/usr/bin/sacctmgr", "-n", "-P", "show", "qos", "format=Name,Priority,Preempt"), code="qos")
    rows: dict[str, tuple[int, tuple[str, ...]]] = {}
    try:
        for line in result.stdout.decode("utf-8", "strict").splitlines():
            fields = line.split("|")
            if len(fields) != 3 or not fields[0] or not fields[1].isdigit() or fields[0] in rows:
                fail("qos_shape")
            rows[fields[0]] = (int(fields[1]), tuple(item for item in fields[2].split(",") if item))
    except UnicodeDecodeError as error:
        raise GateError("qos_encoding") from error
    if rows.get(QOS) != (EXPECTED_QOS_PRIORITY, EXPECTED_QOS_OUTBOUND):
        fail("qos_semantics")
    inbound = tuple(sorted(name for name, (_priority, targets) in rows.items() if QOS in targets))
    if inbound != EXPECTED_QOS_PREEMPTORS:
        fail("qos_preemptors")
    config = run(("/usr/bin/scontrol", "-M", CLUSTER, "show", "config"), code="cluster_config").stdout.decode(
        "utf-8", "strict"
    )
    if not re.search(r"^PreemptType\s*= preempt/qos$", config, re.MULTILINE) or not re.search(
        r"^PreemptMode\s*= REQUEUE$", config, re.MULTILINE
    ):
        fail("preemption_config")


def approval_contract(hashes: Mapping[str, str], tls: Mapping[str, object] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "k3-registry-direct-pull-gate-v33-approval",
        "state": "approved_once" if SOURCE_BOUND else "blocked_source_unbound",
        "diagnostic_only": True,
        "production_authorized": False,
        "bundle": str(BUNDLE),
        "bundle_hashes": dict(hashes),
        "source_bound": SOURCE_BOUND,
        "source_root": str(SOURCE_ROOT),
        "source_revision": SOURCE_REVISION,
        "source_tree": SOURCE_TREE,
        "source_bundle_sha256": SOURCE_BUNDLE_SHA256,
        "source_files": {str(path.relative_to(SOURCE_ROOT)): value for path, value in SOURCE_FILES.items()},
        "compute_tool_provenance": {
            "node": PINNED_NODE,
            "probe_kind": "k3-compute-tool-manifest-diag-v7",
            "fresh_entries": COMPUTE_PROBE_ENTRIES,
            "fresh_source": "fresh_compute_node",
            "identity_semantics": "nofollow-path-and-followed-target-both-regular-0755-root-single-link",
            "projection_sha256": COMPUTE_PROJECTION_SHA256,
            "private_manifest_path": str(COMPUTE_PROBE_PRIVATE),
            "private_manifest_sha256": COMPUTE_PROBE_PRIVATE_SHA256,
            "private_manifest_size": COMPUTE_PROBE_PRIVATE_SIZE,
            "result_path": str(COMPUTE_PROBE_RESULT),
            "result_sha256": COMPUTE_PROBE_RESULT_SHA256,
            "result_size": COMPUTE_PROBE_RESULT_SIZE,
            "job_result_path": str(COMPUTE_PROBE_JOB_RESULT),
            "job_result_sha256": COMPUTE_PROBE_JOB_RESULT_SHA256,
            "job_result_size": COMPUTE_PROBE_JOB_RESULT_SIZE,
            "probe_approval_sha256": COMPUTE_PROBE_APPROVAL_SHA256,
            "baseline_sha256": COMPUTE_PROBE_BASELINE_SHA256,
            "baseline_mismatch_bitmap": COMPUTE_PROBE_MISMATCH_BITMAP,
            "python_preferred_index": 3,
            "python_usable_bitmap": COMPUTE_PROBE_PYTHON_BITMAP,
            "python_version": "3.12",
            "python_identity": "regular_file:755:0:1",
            "all_33_fresh_and_exact": True,
        },
        "image": IMAGE,
        "image_digest": IMAGE_DIGEST,
        "scheduler": {
            "cluster": CLUSTER,
            "partition": PARTITION,
            "account": ACCOUNT,
            "qos": QOS,
            "nodes": 1,
            "tasks": 1,
            "gpus_per_node": 1,
            "cpus_per_task": CPUS,
            "memory": MEMORY,
            "time": WALLTIME,
            "no_requeue": True,
            "signal": f"TERM@{SIGNAL_LEAD_SECONDS}",
            "exclude": list(EXCLUDED),
            "nodelist": PINNED_NODE,
            "held_submit": True,
            "release_once": True,
            "nested_srun": True,
        },
        "job_name": JOB_NAME,
        "canonical_tmux_target": CANONICAL_TMUX_TARGET,
        "launch_command": "exec 9<launch.sh; LAUNCHER_FD=9 /proc/self/fd/9 execute",
        "tls_private_binding": dict(tls) if tls is not None else "resolved_at_approval",
        "protocol": {
            "one_sbatch": True,
            "one_srun": True,
            "one_ucloud_mint": True,
            "ucloud_outform_text": True,
            "one_offline_podman_authfile_lookup": True,
            "network_login_forbidden": True,
            "one_guarded_digest_pinned_pull": True,
            "registry_pull_retries": 0,
            "pull_explicit_authfile": True,
            "pull_explicit_platform": "linux/arm64",
            "pull_tls_verify": True,
            "exact_digest_inspection": True,
            "exact_repository_digest": True,
            "image_removed_after_inspection": True,
            "token_shape_coarse_only": True,
            "guard_stage_markers": ["precondition", "child", "postcondition"],
            "task_free": True,
            "model_free": True,
            "container_run_forbidden": True,
            "podman_run_forbidden": True,
            "private_raw_output": True,
            "public_single_json": True,
            "approval_consumed_by_owner_intent": True,
            "sealed_memfd_batch_stdin": True,
            "sbatch_stdin_without_script_operand": True,
            "spooled_batch_self_hash": True,
            "source_failure_phase_split": True,
            "compute_manifest_mismatch_encoding": "count-plus-33-bit-index-bitmap",
            "compute_manifest_observed_hashes_public": False,
            "compute_manifest_fresh_probe_bound": True,
            "compute_manifest_symlinks_rejected": True,
            "terminal_accounting_stable_reads": 2,
            "rapid_terminal_handoff": True,
            "terminal_observation_suppresses_cancel": True,
            "terminal_queue_absence_before_result": True,
            "fd_bound_runtime_sources": True,
            "dirfd_anchored_cleanup": True,
            "retained_scrubbed_roots": True,
            "retained_raw_stream_fds": True,
            "podman_directory_inode_binding": True,
            "per_attempt_podman_directory_binding": True,
            "descriptor_open_stderr_restored": True,
            "rootless_storage_path_equals_graphroot": True,
            "rootless_runroot": "XDG_RUNTIME_DIR/containers",
            "cleanup_roots_pairwise_disjoint": True,
            "podman_info_categories": [
                "podman_info_command",
                "podman_info_shape",
                "podman_store_graphroot",
                "podman_store_runroot",
                "podman_store_driver",
                "podman_info_image_present",
                "podman_info_image_check",
            ],
            "positive_probe_cleanup_proof": "gate_cleanup=retained_empty",
            "cleanup_failure_precedes_operational_category": True,
            "unsafe_entry_preflight": True,
            "mountpoint_rejection": True,
            "global_cleanup_preflight": True,
            "cleanup_single_writer_required": True,
            "podman_writer_quiescence_handshake": True,
            "bounded_signal_cleanup_seconds": SIGNAL_TEARDOWN_BOUND_SECONDS,
            "podman_guard_signal_bound_seconds": PODMAN_GUARD_SIGNAL_BOUND_SECONDS,
            "signal_deferred_cleanup": True,
            "signal_deadline_armed_on_receipt": True,
            "live_writer_cleanup_unproven_terminal": True,
            "live_writer_scheduler_absence_before_final_result": True,
            "cleanup_retry_budget": 3,
            "probe_cleanup_deadline_seconds": PROBE_CLEANUP_BOUND_SECONDS,
            "fd_relative_no_follow_scrub": True,
            "sensitive_fd_scrub": True,
            "sensitive_files_nlink_zero_after_writer_quiescence": True,
            "retained_empty_directories": True,
            "private_scrub_forbidden_without_writer_quiescence": True,
            "live_writer_private_cleanup_claim": False,
            "single_non_reentrant_publication": True,
            "signal_deferred_publication": True,
            "named_object_fsync_only": True,
            "durable_result_precedes_public_stream": True,
            "maximum_public_json_lines": 1,
            "maximum_durable_results": 1,
            "malformed_submit_output_reconciled": True,
            "discovered_id_bound_before_identity_wait": True,
            "unknown_id_cleanup_reconciled": True,
            "terminal_lock_single_use": True,
        },
    }


def pending_contract(hashes: Mapping[str, str] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "k3-registry-direct-pull-gate-v33-plan",
        "state": "pending_independent_approval" if SOURCE_BOUND else "pending_corrected_source_binding",
        "launch_eligible": False,
        "source_bound": SOURCE_BOUND,
        "approval_path": str(APPROVAL),
        "bundle": str(BUNDLE),
        "bundle_hashes": dict(hashes or {}),
        "approval_template": approval_contract(hashes or {}, None),
    }


def tls_binding() -> tuple[dict[str, str], dict[str, object]]:
    paths: dict[str, str] = {}
    facts: list[tuple[int, int, int, int, int, str]] = []
    for name in TLS_NAMES:
        raw = os.environ.get(name, "")
        if not raw or not Path(raw).is_absolute():
            fail("tls_path")
        try:
            canonical_path = Path(os.path.realpath(raw))
            if canonical_path.resolve(strict=True) != canonical_path:
                fail("tls_path")
            captured = stable_file(canonical_path, mode=0o500, maximum=8192)
        except OSError as error:
            raise GateError("tls_path") from error
        if len(captured.raw) != TLS_SIZE:
            fail("tls_identity")
        facts.append(
            (
                captured.signature[0],
                captured.signature[1],
                captured.signature[3],
                captured.signature[5],
                len(captured.raw),
                captured.sha256,
            )
        )
        paths[name] = str(canonical_path)
    if facts[0] != facts[1]:
        fail("tls_alias_mismatch")
    fact = facts[0]
    private = {"sha256": fact[5], "size": fact[4], "mode": 0o500, "owner_uid": OWNER_UID, "same_inode": True}
    return paths, private


def validate_approval(hashes: Mapping[str, str], private_tls: Mapping[str, object]) -> tuple[str, dict[str, object]]:
    require_source_bound()
    expected = os.environ.get("EXPECTED_APPROVAL_SHA256", "")
    if SHA_RE.fullmatch(expected) is None:
        fail("approval_hash_environment")
    captured = stable_file(APPROVAL, mode=0o400, expected=expected, maximum=1 << 20)
    try:
        payload = json.loads(captured.raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError("approval_json") from error
    if captured.raw != canonical(payload) or payload != approval_contract(hashes, private_tls):
        fail("approval_contract")
    return captured.sha256, payload


def parse_record(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as error:
        raise SchedulerUnavailable("scheduler_encoding") from error
    record: dict[str, str] = {}
    for token in text.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key and key not in record:
            record[key] = value
    if not record:
        raise SchedulerUnavailable("scheduler_empty")
    return record


def show_job(job_id: str) -> dict[str, str]:
    if JOB_RE.fullmatch(job_id) is None:
        fail("job_id")
    return parse_record(run(("/usr/bin/scontrol", "-M", CLUSTER, "show", "job", "-o", job_id), code="show_job").stdout)


def parse_tres(raw: str | None, *, allow_null: bool) -> dict[str, str] | None:
    if raw in NULLISH:
        if allow_null:
            return None
        fail("request_tres")
    assert raw is not None
    parsed: dict[str, str] = {}
    for item in raw.split(","):
        if item.count("=") != 1:
            fail("request_tres")
        key, value = item.split("=", 1)
        if not key or not value or key in parsed or any(character.isspace() for character in item):
            fail("request_tres")
        parsed[key] = value
    if parsed != EXPECTED_REQ_TRES:
        fail("request_tres")
    return parsed


def singleton(raw: str | None, expected: int) -> bool:
    return raw in {str(expected), f"{expected}-{expected}"}


def identity_projection(record: Mapping[str, str]) -> tuple[str | None, ...]:
    return tuple(
        record.get(field)
        for field in (
            "JobId",
            "JobName",
            "UserId",
            "Comment",
            "Command",
            "WorkDir",
            "Account",
            "QOS",
            "Partition",
            "NumNodes",
            "NumCPUs",
            "ReqTRES",
            "AllocTRES",
            "TimeLimit",
            "StdOut",
            "StdErr",
            "Requeue",
            "Restarts",
            "JobState",
            "Reason",
            "Priority",
            "EligibleTime",
        )
    )


def static_identity(record: Mapping[str, str], job_id: str, token: str) -> None:
    expected = {
        "JobId": job_id,
        "JobName": JOB_NAME,
        "UserId": OWNER_RECORD,
        "Comment": f"{COMMENT_PREFIX}{token}",
        "Command": "(null)",
        "WorkDir": str(BUNDLE),
        "Account": ACCOUNT,
        "QOS": QOS,
        "Partition": PARTITION,
        "TimeLimit": WALLTIME,
        "StdOut": str(LOG_ROOT / f"slurm-{job_id}.log"),
        "StdErr": str(LOG_ROOT / f"slurm-{job_id}.log"),
        "Requeue": "0",
    }
    for field, value in expected.items():
        if record.get(field) != value:
            fail(f"identity_{field.lower()}")
    if record.get("Restarts") not in {None, "0"}:
        fail("identity_restarts")
    if not singleton(record.get("NumCPUs"), CPUS):
        fail("identity_cpus")


def held_identity(record: Mapping[str, str], job_id: str, token: str) -> tuple[str | None, ...]:
    static_identity(record, job_id, token)
    if (
        record.get("JobState", "").split("+")[0] != "PENDING"
        or record.get("Priority") != "0"
        or record.get("EligibleTime") != "Unknown"
    ):
        fail("held_envelope")
    if record.get("AllocTRES") not in {"", "None", "(null)"}:
        if record.get("AllocTRES") in {None, "Unknown"}:
            raise IdentityTransient("held_alloc_tres")
        fail("held_alloc_tres")
    if parse_tres(record.get("ReqTRES"), allow_null=True) is None:
        raise IdentityTransient("held_req_tres")
    nodes = record.get("NumNodes")
    if not singleton(nodes, 1):
        if nodes in set(NULLISH) | {"0", "0-1"}:
            raise IdentityTransient("held_nodes")
        fail("identity_nodes")
    if record.get("Reason") != "JobHeldUser":
        if record.get("Reason") in NULLISH:
            raise IdentityTransient("held_reason")
        fail("held_reason")
    return identity_projection(record)


def released_identity(record: Mapping[str, str], job_id: str, token: str) -> tuple[str | None, ...]:
    static_identity(record, job_id, token)
    if parse_tres(record.get("ReqTRES"), allow_null=False) is None or not singleton(record.get("NumNodes"), 1):
        fail("released_resources")
    state = record.get("JobState", "").split("+")[0]
    if state in TERMINAL:
        raise TerminalBeforeActive("terminal_before_active")
    if state not in {"PENDING", "CONFIGURING", "RUNNING", "COMPLETING"}:
        if state in NULLISH:
            raise IdentityTransient("released_state")
        fail("released_state")
    if state == "PENDING":
        if record.get("AllocTRES") not in {"", "None", "(null)"}:
            fail("released_alloc_tres")
        priority = record.get("Priority")
        eligible = record.get("EligibleTime")
        reason = record.get("Reason")
        if reason == "JobHeldUser" or reason in NULLISH or priority in NULLISH or eligible in NULLISH:
            raise IdentityTransient("release_propagation")
        if not priority or not priority.isdigit() or int(priority) <= 0:
            fail("released_priority")
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", eligible or "") is None:
            fail("released_eligible")
    else:
        parsed = parse_tres(record.get("AllocTRES"), allow_null=True)
        if parsed is None:
            raise IdentityTransient("released_alloc_tres")
    return identity_projection(record)


def queue_name_ids() -> set[str]:
    identifiers: set[str] = set()
    queue = run(("/usr/bin/squeue", "-M", CLUSTER, "-h", "-u", OWNER, "-n", JOB_NAME, "-o", "%i|%j|%u"), code="squeue")
    try:
        lines = queue.stdout.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as error:
        raise SchedulerUnavailable("squeue_encoding") from error
    for line in lines:
        fields = line.strip().split("|")
        if len(fields) != 3 or fields[1:] != [JOB_NAME, OWNER] or JOB_RE.fullmatch(fields[0]) is None:
            fail("name_query_shape")
        identifiers.add(fields[0])
    return identifiers


def exact_job_in_owner_queue(job_id: str) -> bool:
    queue = run(("/usr/bin/squeue", "-M", CLUSTER, "-h", "-u", OWNER, "-o", "%i|%j|%u"), code="squeue")
    present = False
    try:
        lines = queue.stdout.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as error:
        raise SchedulerUnavailable("squeue_encoding") from error
    for line in lines:
        fields = line.strip().split("|")
        if len(fields) != 3 or not fields[0] or fields[2] != OWNER:
            fail("queue_census_shape")
        if fields[0] != job_id:
            continue
        if fields[1] != JOB_NAME:
            fail("queue_identity_conflict")
        present = True
    return present


def prove_queue_absent(job_id: str, *, timeout: float = 90, interruptible: bool = True) -> None:
    deadline = time.monotonic() + timeout
    absent_reads = 0
    while time.monotonic() < deadline:
        if interruptible:
            check_interrupted()
        try:
            present = exact_job_in_owner_queue(job_id)
            names = queue_name_ids()
        except SchedulerUnavailable:
            absent_reads = 0
        else:
            if names - {job_id}:
                fail("queue_identity_conflict")
            absent_reads = absent_reads + 1 if not present and job_id not in names else 0
            if absent_reads >= 2:
                return
        time.sleep(1)
    fail("queue_absence_unproven")


def name_ids() -> set[str]:
    identifiers = queue_name_ids()
    accounting = run(
        (
            "/usr/bin/sacct",
            "-M",
            CLUSTER,
            "-X",
            "-n",
            "-P",
            "-S",
            "2026-09-20",
            "--name",
            JOB_NAME,
            "-o",
            "JobIDRaw,JobName,User",
        ),
        code="sacct",
    )
    for line in accounting.stdout.decode("utf-8", "strict").splitlines():
        fields = line.strip().split("|")
        if fields and fields[-1] == "":
            fields.pop()
        if len(fields) != 3:
            fail("name_query_shape")
        if fields[1] == JOB_NAME:
            if fields[2] != OWNER or JOB_RE.fullmatch(fields[0]) is None:
                fail("name_query_shape")
            identifiers.add(fields[0])
    return identifiers


def prove_fresh() -> None:
    for path in (RUN_ROOT, LOG_ROOT, LOCK):
        if path.exists() or path.is_symlink():
            fail("namespace_not_fresh")
    if name_ids():
        fail("job_name_not_fresh")


def process_parent(pid: int, proc_root: Path = Path("/proc")) -> int:
    if pid <= 1:
        fail("tmux_ancestry")
    path = proc_root / str(pid) / "stat"
    try:
        if path.stat(follow_symlinks=False).st_uid != OWNER_UID:
            fail("tmux_ancestry")
        raw = path.read_bytes()
    except OSError as error:
        raise GateError("tmux_ancestry") from error
    if len(raw) > 4096 or raw.count(b"\n") > 1 or (b"\n" in raw and not raw.endswith(b"\n")):
        fail("tmux_ancestry")
    raw = raw.removesuffix(b"\n")
    close = raw.rfind(b")")
    if close < 3:
        fail("tmux_ancestry")
    fields = raw[close + 2 :].split()
    if len(fields) < 2 or not fields[1].isdigit():
        fail("tmux_ancestry")
    return int(fields[1])


def pid_ancestry_contains(start: int, target: int, proc_root: Path = Path("/proc")) -> bool:
    current = start
    seen: set[int] = set()
    for _index in range(64):
        if current == target:
            return True
        if current in seen or current <= 1:
            return False
        seen.add(current)
        current = process_parent(current, proc_root)
    return False


def validate_tmux() -> None:
    if os.environ.get("TMUX_PANE") != "%0":
        fail("tmux_pane")
    result = run(
        (
            "/usr/bin/tmux",
            "display-message",
            "-p",
            "-t",
            "%0",
            "#{session_name}:#{window_name}.#{pane_index}|#{pane_pid}",
        ),
        env={**SAFE_ENV, "TMUX": os.environ.get("TMUX", ""), "TMUX_PANE": "%0"},
        code="tmux",
    )
    fields = result.stdout.decode("utf-8", "strict").strip().split("|")
    if len(fields) != 2 or fields[0] != CANONICAL_TMUX_TARGET or not fields[1].isdigit():
        fail("tmux_identity")
    pane_pid = int(fields[1])
    if pane_pid <= 1 or not pid_ancestry_contains(os.getpid(), pane_pid):
        fail("tmux_identity")


def acquire_lock() -> LockState:
    LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_before = LOCK.parent.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or stat.S_IMODE(parent_before.st_mode) != 0o700
        or parent_before.st_uid != OWNER_UID
    ):
        fail("lock_parent_identity")
    parent_fd = os.open(LOCK.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        fd = os.open(
            LOCK.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd
        )
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        opened = os.fstat(fd)
        named = os.stat(LOCK.name, dir_fd=parent_fd, follow_symlinks=False)
    except BaseException:
        os.close(parent_fd)
        raise
    if (
        (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        or opened.st_uid != OWNER_UID
        or stat.S_IMODE(opened.st_mode) != 0o600
    ):
        os.close(fd)
        os.close(parent_fd)
        fail("lock_identity")
    parent_identity = (parent_before.st_dev, parent_before.st_ino, parent_before.st_mode, parent_before.st_uid)
    return LockState(fd, parent_fd, (opened.st_dev, opened.st_ino), parent_identity)


def write_fd(fd: int, raw: bytes) -> None:
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    view = memoryview(raw)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            fail("write_failed")
        view = view[count:]
    os.fsync(fd)


def finalize_lock(lock: LockState, category: str) -> None:
    payload = canonical({"category": category, "kind": "k3-registry-direct-pull-gate-v33-lock", "state": "terminal"})
    write_fd(lock.fd, payload)
    opened = os.fstat(lock.fd)
    named = os.stat(LOCK.name, dir_fd=lock.parent_fd, follow_symlinks=False)
    parent = os.fstat(lock.parent_fd)
    if (
        (opened.st_dev, opened.st_ino) != lock.inode
        or (named.st_dev, named.st_ino) != lock.inode
        or (parent.st_dev, parent.st_ino, parent.st_mode, parent.st_uid) != lock.parent_identity
    ):
        fail("lock_drift")
    os.lseek(lock.fd, 0, os.SEEK_SET)
    if os.read(lock.fd, len(payload) + 1) != payload:
        fail("lock_terminal_verify")
    fcntl.flock(lock.fd, fcntl.LOCK_UN)
    os.close(lock.fd)
    os.close(lock.parent_fd)
    lock.fd = -1
    lock.parent_fd = -1


def publish_exclusive(directory: Path, name: str, payload: object) -> str:
    raw = canonical(payload)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False) if not directory.exists() else None
    parent_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    temp_name = f".{name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    source_inode: tuple[int, int] | None = None
    try:
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
            dir_fd=parent_fd,
        )
        try:
            opened = os.fstat(fd)
            source_inode = (opened.st_dev, opened.st_ino)
            view = memoryview(raw)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    fail("publish_write")
                view = view[count:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(temp_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        final = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        source = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
        if (final.st_dev, final.st_ino) != (source.st_dev, source.st_ino) or final.st_nlink != 2:
            fail("publish_identity")
        os.unlink(temp_name, dir_fd=parent_fd)
        final = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (final.st_dev, final.st_ino) != source_inode or final.st_nlink != 1:
            fail("publish_identity")
        os.fsync(parent_fd)
    finally:
        if source_inode is not None:
            try:
                leftover = os.stat(temp_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (leftover.st_dev, leftover.st_ino) == source_inode:
                    with contextlib.suppress(OSError):
                        os.unlink(temp_name, dir_fd=parent_fd)
                        os.fsync(parent_fd)
        os.close(parent_fd)
    return digest(raw)


def write_environment(path: Path, values: Mapping[str, str]) -> str:
    if any(not key or "=" in key or "\0" in key or "\0" in value for key, value in values.items()):
        fail("environment_invalid")
    raw = b"".join(f"{key}={values[key]}".encode() + b"\0" for key in sorted(values))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
    try:
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                fail("environment_write")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest(raw)


def sbatch_command(environment_path: Path, token: str) -> list[str]:
    return [
        "/usr/bin/sbatch",
        "-M",
        CLUSTER,
        "--parsable",
        "--hold",
        f"--job-name={JOB_NAME}",
        f"--comment={COMMENT_PREFIX}{token}",
        f"--chdir={BUNDLE}",
        f"--partition={PARTITION}",
        f"--account={ACCOUNT}",
        f"--qos={QOS}",
        "--nodes=1",
        "--ntasks=1",
        "--gpus-per-node=1",
        f"--cpus-per-task={CPUS}",
        f"--mem={MEMORY}",
        f"--time={WALLTIME}",
        "--no-requeue",
        f"--signal=B:TERM@{SIGNAL_LEAD_SECONDS}",
        f"--exclude={','.join(EXCLUDED)}",
        f"--nodelist={PINNED_NODE}",
        f"--output={LOG_ROOT}/slurm-%j.log",
        f"--error={LOG_ROOT}/slurm-%j.log",
        "--open-mode=truncate",
        f"--export-file={environment_path}",
    ]


def stable_reads(job_id: str, token: str, *, held: bool, rounds: int = 32) -> dict[str, str]:
    global TERMINAL_ACCOUNTING_OBSERVED
    last: tuple[str | None, ...] | None = None
    count = 0
    deadline = time.monotonic() + 45
    last_transient: BaseException | None = None
    for _index in range(rounds):
        check_interrupted()
        try:
            record = show_job(job_id)
            projection = held_identity(record, job_id, token) if held else released_identity(record, job_id, token)
        except TerminalBeforeActive:
            TERMINAL_ACCOUNTING_OBSERVED = True
            raise
        except (SchedulerUnavailable, IdentityTransient) as error:
            last_transient = error
            count = 0
            last = None
            if not held:
                try:
                    terminal_record = accounting(job_id)
                    terminal_state = (
                        normalized_accounting_state(terminal_record) if terminal_record is not None else None
                    )
                    if terminal_record is not None and terminal_state in TERMINAL:
                        terminal_accounting_projection(terminal_record, job_id, token)
                        TERMINAL_ACCOUNTING_OBSERVED = True
                        raise TerminalBeforeActive("terminal_before_active")
                except (SchedulerUnavailable, AccountingTransient):
                    pass
        else:
            count = count + 1 if projection == last else 1
            last = projection
            last_transient = None
            if count >= 2:
                return record
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(1.5, remaining))
    if last_transient is not None:
        raise GateError(error_code(last_transient)) from last_transient
    fail("identity_unstable")


def submit_once(environment_path: Path, token: str, batch_raw: bytes) -> str:
    global SUBMISSION_ATTEMPTED, SUBMITTED_JOB_ID
    check_interrupted()
    command = sbatch_command(environment_path, token)
    batch_fd = -1
    submission_failure: str | None = None
    try:
        batch_fd = os.memfd_create("k3-registry-direct-pull-gate-v33-batch", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
        view = memoryview(batch_raw)
        while view:
            count = os.write(batch_fd, view)
            if count <= 0:
                fail("batch_input_write")
            view = view[count:]
        os.fchmod(batch_fd, 0o400)
        seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        fcntl.fcntl(batch_fd, fcntl.F_ADD_SEALS, seals)
        os.lseek(batch_fd, 0, os.SEEK_SET)
        SUBMISSION_ATTEMPTED = True
        result = subprocess.run(
            command,
            stdin=batch_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=SAFE_ENV,
            timeout=30,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
        submission_failure = "submission_unavailable"
    finally:
        if batch_fd >= 0:
            os.close(batch_fd)
    direct: str | None = None
    if result is not None and result.returncode != 0:
        submission_failure = "submission_cli_failed"
    if result is not None and result.returncode == 0 and len(result.stdout) < 4096:
        try:
            candidate = result.stdout.decode("utf-8", "strict").strip().split(";", 1)[0]
        except UnicodeDecodeError:
            candidate = ""
        if JOB_RE.fullmatch(candidate):
            direct = candidate
            SUBMITTED_JOB_ID = direct
            OWNED_JOB_IDS.add(direct)
    deadline = time.monotonic() + 60
    last_query_error: SchedulerUnavailable | None = None
    while True:
        try:
            candidates = queue_name_ids()
        except SchedulerUnavailable as error:
            last_query_error = error
            candidates = set()
        if direct is not None:
            candidates.add(direct)
        if len(candidates) > 1:
            fail("submission_conflict")
        if len(candidates) == 1 and last_query_error is None:
            job_id = next(iter(candidates))
            SUBMITTED_JOB_ID = job_id
            OWNED_JOB_IDS.add(job_id)
            stable_reads(job_id, token, held=True)
            if queue_name_ids() - {job_id}:
                fail("submission_conflict")
            return job_id
        if time.monotonic() >= deadline:
            if last_query_error is not None:
                raise GateError(error_code(last_query_error)) from last_query_error
            if submission_failure is not None:
                fail(submission_failure)
            fail("submission_missing")
        time.sleep(2)
        last_query_error = None


def release_once(job_id: str, token: str) -> None:
    stable_reads(job_id, token, held=True)
    run(("/usr/bin/scontrol", "-M", CLUSTER, "release", job_id), code="release")
    try:
        stable_reads(job_id, token, held=False, rounds=48)
    except TerminalBeforeActive:
        # A very short diagnostic may publish and terminate between release
        # and the first two active projections.  Static identity and exact
        # resources were already checked by released_identity; hand off to
        # stable terminal accounting rather than treating this as cleanup.
        return


def accounting(job_id: str) -> dict[str, str] | None:
    result = run(
        (
            "/usr/bin/sacct",
            "-M",
            CLUSTER,
            "-X",
            "-n",
            "-P",
            "-j",
            job_id,
            "-o",
            "JobIDRaw,JobName,User,Account,QOS,Partition,State,ExitCode,Elapsed,ReqTRES,AllocTRES,NNodes,ReqCPUS,Timelimit,Comment",
        ),
        code="accounting",
    )
    names = (
        "JobIDRaw",
        "JobName",
        "User",
        "Account",
        "QOS",
        "Partition",
        "State",
        "ExitCode",
        "Elapsed",
        "ReqTRES",
        "AllocTRES",
        "NNodes",
        "ReqCPUS",
        "TimeLimit",
        "Comment",
    )
    try:
        lines = [line for line in result.stdout.decode("utf-8", "strict").splitlines() if line.strip()]
    except UnicodeDecodeError as error:
        raise AccountingTransient("accounting_shape") from error
    records: list[dict[str, str]] = []
    for line in lines:
        fields = line.split("|")
        if fields and fields[-1] == "":
            fields.pop()
        if len(fields) != len(names):
            raise AccountingTransient("accounting_shape")
        record = dict(zip(names, fields, strict=True))
        row_id = record["JobIDRaw"]
        if row_id in NULLISH:
            raise AccountingTransient("accounting_shape")
        parsed_id = re.fullmatch(r"([1-9][0-9]{0,19})(?:\.(?:batch|extern|[0-9]+))?", row_id)
        if row_id == job_id:
            records.append(record)
        elif parsed_id is not None and parsed_id.group(1) == job_id:
            continue
        elif parsed_id is None:
            raise AccountingTransient("accounting_shape")
        else:
            fail("accounting_unexpected_job")
    if not records:
        return None
    projections = {tuple(record[name] for name in names) for record in records}
    if len(projections) != 1:
        raise AccountingTransient("accounting_shape")
    return records[0]


def normalized_accounting_state(record: Mapping[str, str]) -> str:
    raw = record.get("State")
    if raw in NULLISH:
        raise AccountingTransient("accounting_propagation")
    parts = (raw or "").split()
    if not parts:
        raise AccountingTransient("accounting_propagation")
    normalized = parts[0].split("+", 1)[0]
    if re.fullmatch(r"[A-Z][A-Z_]*", normalized) is None:
        raise AccountingTransient("accounting_propagation")
    return normalized


def terminal_accounting_projection(record: Mapping[str, str], job_id: str, token: str) -> tuple[str, ...]:
    expected = {
        "JobIDRaw": job_id,
        "JobName": JOB_NAME,
        "User": OWNER,
        "Account": ACCOUNT,
        "QOS": QOS,
        "Partition": PARTITION,
        "TimeLimit": WALLTIME,
        "Comment": f"{COMMENT_PREFIX}{token}",
    }
    for key, value in expected.items():
        observed = record.get(key)
        if observed in NULLISH:
            raise AccountingTransient("accounting_propagation")
        if observed != value:
            fail("accounting_identity")
    state = normalized_accounting_state(record)
    if state not in TERMINAL:
        fail("accounting_not_terminal")
    for field in ("ExitCode", "Elapsed", "ReqTRES", "AllocTRES", "NNodes", "ReqCPUS"):
        if record.get(field) in NULLISH:
            raise AccountingTransient("accounting_propagation")
    if re.fullmatch(r"[0-9]+:[0-9]+", record.get("ExitCode", "")) is None or re.fullmatch(
        r"(?:[0-9]+-)?[0-9]{2}:[0-5][0-9]:[0-5][0-9]", record.get("Elapsed", "")
    ) is None:
        raise AccountingTransient("accounting_propagation")
    if (
        parse_tres(record.get("ReqTRES"), allow_null=False) is None
        or parse_tres(record.get("AllocTRES"), allow_null=False) is None
        or not singleton(record.get("NNodes"), 1)
        or not singleton(record.get("ReqCPUS"), CPUS)
    ):
        fail("accounting_identity")
    fields = (
        "JobIDRaw",
        "JobName",
        "User",
        "Account",
        "QOS",
        "Partition",
        "State",
        "ExitCode",
        "Elapsed",
        "ReqTRES",
        "AllocTRES",
        "NNodes",
        "ReqCPUS",
        "TimeLimit",
        "Comment",
    )
    return tuple(record.get(field, "") for field in fields)


def live_writer_result_projection(job_id: str) -> tuple[tuple[int, ...], tuple[int, ...], str] | None:
    durable_path = RUN_ROOT / "job_result.json"
    public_path = LOG_ROOT / f"slurm-{job_id}.log"
    if not os.path.lexists(durable_path) or not os.path.lexists(public_path):
        return None
    try:
        durable = stable_file(durable_path, mode=0o400, maximum=4096)
        public = stable_file(public_path, mode=0o600, maximum=4096)
        _durable_sha, durable_category = validate_result_payload(durable, False)
        _public_sha, public_category = validate_result_payload(public, False)
    except GateError:
        return None
    if (
        durable.raw != public.raw
        or durable_category != LIVE_WRITER_CATEGORY
        or public_category != LIVE_WRITER_CATEGORY
    ):
        return None
    return durable.signature, public.signature, durable.sha256


def wait_terminal(job_id: str, token: str) -> dict[str, str]:
    global TERMINAL_ACCOUNTING_OBSERVED
    deadline = time.monotonic() + 2_100
    previous_live_writer: tuple[tuple[int, ...], tuple[int, ...], str] | None = None
    scheduler_cleanup_proven = False
    previous_terminal: tuple[str, ...] | None = None
    terminal_reads = 0
    while time.monotonic() < deadline:
        check_interrupted()
        try:
            record = accounting(job_id)
            accounting_state = normalized_accounting_state(record) if record is not None else None
        except (SchedulerUnavailable, AccountingTransient):
            record = None
            accounting_state = None
            previous_terminal = None
            terminal_reads = 0
        if record is not None and accounting_state in TERMINAL:
            try:
                projection = terminal_accounting_projection(record, job_id, token)
            except AccountingTransient:
                previous_terminal = None
                terminal_reads = 0
            else:
                TERMINAL_ACCOUNTING_OBSERVED = True
                terminal_reads = terminal_reads + 1 if projection == previous_terminal else 1
                previous_terminal = projection
                if terminal_reads >= 2:
                    return record
        else:
            previous_terminal = None
            terminal_reads = 0
        if not scheduler_cleanup_proven and not TERMINAL_ACCOUNTING_OBSERVED:
            current_live_writer = live_writer_result_projection(job_id)
            if current_live_writer is not None and current_live_writer == previous_live_writer:
                cancel_exact(job_id, token)
                scheduler_cleanup_proven = True
            previous_live_writer = current_live_writer
        time.sleep(5)
    fail("terminal_timeout")


def stable_result_file(path: Path, mode: int) -> Capture:
    previous: tuple[int, ...] | None = None
    deadline = time.monotonic() + 45
    last_error: GateError | None = None
    while time.monotonic() < deadline:
        try:
            captured = stable_file(path, mode=mode, maximum=4096)
        except GateError as error:
            last_error = error
            previous = None
        else:
            if captured.signature == previous:
                return captured
            previous = captured.signature
            last_error = None
        time.sleep(1)
    if last_error is not None:
        raise last_error
    fail("result_unstable")


def validate_result_payload(captured: Capture, succeeded: bool) -> tuple[str, str]:
    try:
        payload = json.loads(captured.raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError("public_log_json") from error
    category = payload.get("category")
    classified_compute_manifest_failure = valid_compute_manifest_category(category)
    if (
        captured.raw != canonical(payload)
        or set(payload) != {"category", "image_digest", "kind", "platform", "state"}
        or payload.get("kind") != "k3-registry-direct-pull-gate-v33"
        or payload.get("image_digest") != IMAGE_DIGEST
        or payload.get("platform") != "linux/arm64"
        or (
            category not in ALLOWED_PUBLIC_CATEGORIES
            and not classified_compute_manifest_failure
        )
    ):
        fail("public_log_contract")
    if succeeded and payload != {
        "category": "success",
        "image_digest": IMAGE_DIGEST,
        "kind": "k3-registry-direct-pull-gate-v33",
        "platform": "linux/arm64",
        "state": "complete",
    }:
        fail("public_log_success")
    if not succeeded and (
        category == "success" or payload.get("state") != "blocked"
    ):
        fail("public_log_failure")
    return captured.sha256, str(category)


def validate_public_results(job_id: str, succeeded: bool) -> tuple[str, str, str]:
    durable = stable_result_file(RUN_ROOT / "job_result.json", 0o400)
    public = stable_result_file(LOG_ROOT / f"slurm-{job_id}.log", 0o600)
    durable_sha, durable_category = validate_result_payload(durable, succeeded)
    public_sha, public_category = validate_result_payload(public, succeeded)
    if durable.raw != public.raw or durable_category != public_category:
        fail("result_mismatch")
    return public_sha, durable_sha, public_category


def cancellation_envelope(record: Mapping[str, str], job_id: str, token: str) -> bool:
    critical = {
        "JobId": job_id,
        "JobName": JOB_NAME,
        "UserId": OWNER_RECORD,
        "Comment": f"{COMMENT_PREFIX}{token}",
    }
    complete = True
    for field, expected in critical.items():
        actual = record.get(field)
        if actual in NULLISH:
            complete = False
        elif actual != expected:
            fail("cleanup_identity_conflict")
    optional = {
        "Command": "(null)",
        "WorkDir": str(BUNDLE),
        "Account": ACCOUNT,
        "QOS": QOS,
        "Partition": PARTITION,
        "TimeLimit": WALLTIME,
        "StdOut": str(LOG_ROOT / f"slurm-{job_id}.log"),
        "StdErr": str(LOG_ROOT / f"slurm-{job_id}.log"),
        "Requeue": "0",
    }
    for field, expected in optional.items():
        actual = record.get(field)
        if actual not in NULLISH and actual != expected:
            fail("cleanup_identity_conflict")
    raw_tres = record.get("ReqTRES")
    if raw_tres not in NULLISH:
        try:
            parse_tres(raw_tres, allow_null=False)
        except GateError as error:
            raise GateError("cleanup_identity_conflict") from error
    cpus = record.get("NumCPUs")
    if cpus not in NULLISH and not singleton(cpus, CPUS):
        fail("cleanup_identity_conflict")
    nodes = record.get("NumNodes")
    if nodes not in set(NULLISH) | {"0", "0-1"} and not singleton(nodes, 1):
        fail("cleanup_identity_conflict")
    return complete


def cancel_exact(job_id: str | None, token: str) -> None:
    global SUBMITTED_JOB_ID
    if TERMINAL_ACCOUNTING_OBSERVED:
        fail("cancel_after_terminal")
    if job_id is None:
        if not SUBMISSION_ATTEMPTED:
            return
        deadline = time.monotonic() + 60
        absent_reads = 0
        while time.monotonic() < deadline:
            try:
                candidates = queue_name_ids()
            except SchedulerUnavailable:
                absent_reads = 0
            else:
                if len(candidates) > 1:
                    fail("cleanup_identity_conflict")
                if len(candidates) == 1:
                    job_id = next(iter(candidates))
                    SUBMITTED_JOB_ID = job_id
                    OWNED_JOB_IDS.add(job_id)
                    break
                absent_reads += 1
            time.sleep(1)
        if job_id is None:
            if absent_reads >= 2:
                return
            fail("cleanup_identity_unproven")
    if job_id not in OWNED_JOB_IDS:
        fail("cleanup_identity_unproven")
    identity_proven = False
    terminal = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            record = show_job(job_id)
        except SchedulerUnavailable:
            time.sleep(1)
            continue
        envelope_complete = cancellation_envelope(record, job_id, token)
        state = record.get("JobState", "").split("+")[0]
        terminal = state in TERMINAL
        if envelope_complete:
            identity_proven = True
            break
        time.sleep(1)
    if not identity_proven:
        absent_reads = 0
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                ids = queue_name_ids()
            except SchedulerUnavailable:
                absent_reads = 0
            else:
                absent_reads = absent_reads + 1 if not ids else 0
                if absent_reads >= 2:
                    return
            time.sleep(1)
        fail("cleanup_identity_unproven")
    cancel_error: SchedulerUnavailable | None = None
    if not terminal:
        try:
            run(("/usr/bin/scancel", "-M", CLUSTER, job_id), code="cancel")
        except SchedulerUnavailable as error:
            cancel_error = error
    absent_reads = 0
    queue_deadline = time.monotonic() + 90
    while time.monotonic() < queue_deadline:
        try:
            ids = queue_name_ids()
        except SchedulerUnavailable:
            absent_reads = 0
            time.sleep(1)
            continue
        absent_reads = absent_reads + 1 if not ids else 0
        if absent_reads >= 2:
            return
        time.sleep(1)
    if cancel_error is not None:
        raise GateError(error_code(cancel_error)) from cancel_error
    fail("cancel_timeout")


def reconcile_live_writer_terminal(category: str, job_id: str, token: str) -> bool:
    if category != LIVE_WRITER_CATEGORY:
        return False
    # The batch deliberately retained its private tree because a writer was
    # still observable after its bounded kill ladder.  Terminal accounting is
    # already established by the caller; now additionally prove the exact
    # scheduler namespace absent before any aggregate result is committed.
    del token
    prove_queue_absent(job_id)
    return True


def execute(hashes: Mapping[str, str]) -> None:
    global TERMINAL_ACCOUNTING_OBSERVED
    require_source_bound()
    TERMINAL_ACCOUNTING_OBSERVED = False
    check_interrupted()
    compute_probe_binding = validate_compute_probe(BUNDLE / "compute_tools.sha256")
    validate_tmux()
    paths, private_tls = tls_binding()
    approval_sha, approval = validate_approval(hashes, private_tls)
    prove_fresh()
    check_interrupted()
    lock = acquire_lock()
    job_id: str | None = None
    token = os.urandom(12).hex()
    final_category = "internal_error"
    scheduler_cleanup_proven = False
    try:
        prove_fresh_after_lock = [path for path in (RUN_ROOT, LOG_ROOT) if path.exists() or path.is_symlink()]
        if prove_fresh_after_lock or name_ids():
            fail("namespace_not_fresh")
        RUN_ROOT.mkdir(mode=0o700)
        LOG_ROOT.mkdir(mode=0o700)
        environment_path = RUN_ROOT / "slurm_environment.bin"
        environment = {
            "HOME": "/storage/home/tianhaowu",
            "USER": OWNER,
            "LOGNAME": OWNER,
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "SLURM_EXPORT_ENV": "NONE",
            "GATE_BUNDLE": str(BUNDLE),
            "GATE_SOURCE_ROOT": str(SOURCE_ROOT),
            "GATE_SOURCE_REVISION": SOURCE_REVISION,
            "GATE_SOURCE_TREE": SOURCE_TREE,
            "GATE_WORKER_SHA256": SOURCE_FILES[WORKER],
            "GATE_AWS_CREDS_SHA256": SOURCE_FILES[AWS_CREDS],
            "GATE_IMAGE": IMAGE,
            "GATE_IMAGE_DIGEST": IMAGE_DIGEST,
            "GATE_BATCH_SHA256": hashes["batch"],
            "GATE_PROBE_SHA256": hashes["probe"],
            "GATE_CLASSIFIER_SHA256": hashes["classifier"],
            "GATE_PODMAN_GUARD_SHA256": hashes["podman_guard"],
            "GATE_SCRUBBER_SHA256": hashes["scrubber"],
            "GATE_TOOL_MANIFEST_SHA256": hashes["tools_manifest"],
            "GATE_JOB_RESULT": str(RUN_ROOT / "job_result.json"),
            "GATE_JOB_NAME": JOB_NAME,
            "GATE_EXPECTED_UID": str(OWNER_UID),
            "GATE_TLS_SHA256": str(private_tls["sha256"]),
            "GATE_TLS_SIZE": str(private_tls["size"]),
            **paths,
        }
        environment_sha = write_environment(environment_path, environment)
        check_interrupted()
        current_compute_probe_binding = validate_compute_probe(BUNDLE / "compute_tools.sha256")
        current_paths, current_private_tls = tls_binding()
        current_approval_sha, current_approval = validate_approval(hashes, current_private_tls)
        if (
            current_compute_probe_binding != compute_probe_binding
            or current_paths != paths
            or current_private_tls != private_tls
            or current_approval_sha != approval_sha
            or current_approval != approval
        ):
            fail("approval_revalidation")
        intent = {
            "schema_version": 1,
            "kind": "k3-registry-direct-pull-gate-v33-owner-intent",
            "state": "armed",
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "approval_sha256": approval_sha,
            "approval_payload": approval,
            "bundle_hashes": dict(hashes),
            "environment_sha256": environment_sha,
            "job_name": JOB_NAME,
            "job_comment": f"{COMMENT_PREFIX}{token}",
        }
        publish_exclusive(RUN_ROOT, "owner_intent.json", intent)
        batch_capture = stable_file(
            BUNDLE / "run_registry_gate.sbatch",
            mode=0o500,
            expected=hashes["batch"],
            maximum=1 << 20,
        )
        job_id = submit_once(environment_path, token, batch_capture.raw)
        publish_exclusive(
            RUN_ROOT,
            "submission.json",
            {"job_id": job_id, "kind": "k3-registry-direct-pull-gate-v33-submission", "state": "held_identity_proven"},
        )
        release_once(job_id, token)
        terminal = wait_terminal(job_id, token)
        prove_queue_absent(job_id)
        scheduler_cleanup_proven = True
        check_interrupted()
        success = terminal["State"].split()[0].split("+")[0] == "COMPLETED" and terminal["ExitCode"] == "0:0"
        log_sha, durable_sha, category = validate_public_results(job_id, success)
        check_interrupted()
        reconcile_live_writer_terminal(category, job_id, token)
        final_category = category if not success else "success"
        result = {
            "schema_version": 1,
            "kind": "k3-registry-direct-pull-gate-v33-result",
            "state": "passed" if success else "failed",
            "category": final_category,
            "job_id": job_id,
            "slurm_state": terminal["State"],
            "exit_code": terminal["ExitCode"],
            "elapsed": terminal["Elapsed"],
            "public_log_sha256": log_sha,
            "durable_job_result_sha256": durable_sha,
            "source_revision": SOURCE_REVISION,
            "image_digest": IMAGE_DIGEST,
            "approval_sha256": approval_sha,
            "environment_sha256": environment_sha,
        }
        with commit_signal_mask():
            finalize_lock(lock, final_category)
            publish_exclusive(RUN_ROOT, "result.json", result)
        if not success:
            fail("gate_failed")
    except BaseException as error:
        cleanup_failure: BaseException | None = None
        if not scheduler_cleanup_proven and TERMINAL_ACCOUNTING_OBSERVED and job_id is not None:
            try:
                prove_queue_absent(job_id, interruptible=False)
                scheduler_cleanup_proven = True
            except BaseException as cleanup_error:
                cleanup_failure = cleanup_error
        if not scheduler_cleanup_proven and cleanup_failure is None:
            try:
                cancel_exact(job_id or SUBMITTED_JOB_ID, token)
            except BaseException as cleanup_error:
                cleanup_failure = cleanup_error
        if lock.fd >= 0:
            try:
                finalize_lock(lock, error_code(error))
            except BaseException as lock_error:
                cleanup_failure = lock_error
        if cleanup_failure is not None:
            raise GateError("cleanup_failed") from cleanup_failure
        raise


def audit(hashes: Mapping[str, str]) -> dict[str, object]:
    require_source_bound()
    validate_tools()
    validate_source(BUNDLE / "compute_tools.sha256")
    qos_contract()
    prove_fresh()
    expected_pending = canonical(pending_contract({key: value for key, value in hashes.items() if key != "pending"}))
    if stable_file(BUNDLE / "pending.json", mode=0o400).raw != expected_pending:
        fail("pending_contract")
    return {
        "jobs_submitted": 0,
        "kind": "k3-registry-direct-pull-gate-v33-audit",
        "source_revision": SOURCE_REVISION,
        "state": "passed",
    }


def main() -> int:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)
    if len(sys.argv) != 2 or sys.argv[1] not in {"audit", "execute", "render-pending"}:
        print(canonical({"category": "arguments", "state": "blocked"}).decode(), end="", file=sys.stderr)
        return 2
    if sys.argv[1] == "render-pending":
        print(canonical(pending_contract()).decode(), end="")
        return 0
    try:
        require_source_bound()
        hashes = bundle_hashes()
        result = audit(hashes)
        if sys.argv[1] == "execute":
            execute(hashes)
            result = {"jobs_submitted": 1, "kind": "k3-registry-direct-pull-gate-v33-execute", "state": "complete"}
    except BaseException as error:
        print(canonical({"category": error_code(error), "state": "blocked"}).decode(), end="", file=sys.stderr)
        return 2
    print(canonical(result).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
