#!/usr/bin/python3.12
"""One-shot, fail-closed launcher for a fresh two-endpoint Kimi deployment.

The module is inert unless invoked as ``controller.py execute`` through the
reviewed launcher with an exact approval hash.  Tests import it but never call
the scheduler or deployment entry point.
"""

from __future__ import annotations

import contextlib
import ctypes
import errno
import fcntl
import hashlib
import importlib
import io
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

OWNER = "tianhaowu"
OWNER_UID = 656177
OWNER_RECORD = "tianhaowu(656177)"
CLUSTER = "fair-cw-use2-3"

BUNDLE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_tb4_eval_deploy_20260920t045200z_v13")
LAUNCHER = BUNDLE / "launch.sh"
CONTROLLER = BUNDLE / "controller.py"
PLAN = BUNDLE / "pending.json"
README = BUNDLE / "README.md"
TESTS = BUNDLE / "test_controller.py"
BUILDER = BUNDLE / "build_runtime_zip.py"
RUNTIME_ZIP = BUNDLE / "runtime.zip"
PYTHON_RUNTIME_TAR = BUNDLE / "python-runtime.tar"
APPROVAL = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/approvals/k3_tb4_eval_deploy_20260920t045200z_v13.approval.json"
)
RUN_PARENT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/gates")
RUN_ROOT = RUN_PARENT / "k3_tb4_eval_launch_20260920t045200z_v13"
ROUTE_ROOT = RUN_PARENT / "k3_tb4_eval_route_20260920t045200z_v13"
ROUTE_POLICY = ROUTE_ROOT / "route_policy.json"
INITIAL_OBSERVATION = RUN_ROOT / "initial_spec_observation.json"
RESOLVED_BINDING = ROUTE_ROOT / "resolved_spec_binding.json"
LAUNCH_RECEIPT = RUN_ROOT / "deployment_receipt.json"
READINESS = ROUTE_ROOT / "readiness.json"
ROUTE_BINDING = ROUTE_ROOT / "live_route_binding.json"
COMMIT_MARKER = ROUTE_ROOT / "ready_commit.json"
CLEANUP_RECEIPT = RUN_ROOT / "cleanup_receipt.json"
OUTPUT_ROOT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/runs/k3_tb4_eval_20260920t045200z_v13")
GLOBAL_LOCK = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/watchers/k3_tb4_eval_deploy_20260920t045200z_v13.global.lock"
)

DEPLOYMENT_ID = "tianhaowu-k3-kda-tb4-eval-20260920t045200z"
STALE_DEPLOYMENT_IDS = frozenset(
    {
        "tianhaowu-k3-kda-tb4-eval-20260919t215851z",
        "tianhaowu-k3-kda-tb4-eval-20260919t231622z",
        "tianhaowu-k3-kda-tb4-eval-20260919t232542z",
        "tianhaowu-k3-kda-tb4-eval-20260919t234429z",
        "tianhaowu-k3-kda-tb4-eval-20260920t002545z",
        "tianhaowu-k3-kda-tb4-eval-20260920t010300z",
        "tianhaowu-k3-kda-tb4-eval-20260920t013200z",
        "tianhaowu-k3-kda-tb4-eval-20260920t020900z",
        "tianhaowu-k3-kda-tb4-eval-20260920t030300z",
        "tianhaowu-k3-kda-tb4-eval-20260920t034500z",
    }
)
DEPLOYMENTS_ROOT = Path("/checkpoint/ram/shared/vllm_deployments_v2")
DEPLOYMENT_ROOT = DEPLOYMENTS_ROOT / DEPLOYMENT_ID
REMOVED_ROOT = DEPLOYMENTS_ROOT / ".removed"
HISTORY_START = "2026-09-20T04:52:00"

SOURCE_REPO = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-0322cd439")
SERVE_ROOT = SOURCE_REPO / "vllm_tools/serve_api_v2"
SERVE_PACKAGE = SERVE_ROOT / "src/serve_api_v2"
CONFIG_ROOT = SERVE_ROOT / "config"
SOURCE_REVISION = "0322cd43963cbad632128b8e00946a55f16a8085"
SOURCE_TREE = "eac4040827d2ef1a82b067220616cfe8d3459a32"
SOURCE_BUNDLE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-0322cd439.bundle")
SOURCE_BUNDLE_SHA256 = "897b84846c9974d376d76fb9928b58a08dabc8182e750fd04aadcaaa87182127"
SOURCE_MANIFEST = {
    "directories": 57,
    "files": 223,
    "bytes": 4_108_938,
    "sha256": "3410c83d8f0b1288e72f6bf69897d542e7b6da297521542119b6e25ccc483c5c",
}
SNAPSHOT_MANIFEST = {
    "directories": 7,
    "files": 66,
    "bytes": 945_983,
    "sha256": "fa8798096687d427a9ad7d970f9fe063f959f747782767cf1e063d45ff7bdb57",
}
EVALUATOR_ROOT = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/prime-rl-a09a9a189")
EVALUATOR_REVISION = "a09a9a189697034e23b776fdbfccb369522c469d"
EVALUATOR_TREE = "58bec828df10962ec5411762837aa6e3f71461da"
EVAL_CONFIGS = {
    EVALUATOR_ROOT
    / "user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_fresh_smoke12h.toml": "ff6edee61c10e8c1d08c26b94fd186af96f3e06ad3d85a9d78728c3bc1ede7d3",
    EVALUATOR_ROOT
    / "user/tianhaowu/terminal_bench_vmvm/configs/eval/tb4_kimi_k3_max_miniswe.toml": "c7efe001a81799b16bdad67207cae8ead9768e42103257f447a0622bdfa6bad9",
    EVALUATOR_ROOT
    / "user/tianhaowu/terminal_bench_vmvm/configs/eval/mobius_kimi_k3_max_2500.toml": "b9108ce49908a768b0a5479601df5fee3ce9f7bf6d63eafb744ea63764fe31af",
}
EVALUATOR_CONTEXT_CAP = 262_144
SERVE_SH_SHA256 = "9ec94dc320762a65298084287b818959765ebeabd5b673778f6884c244fb38de"
MODEL_CARD_SHA256 = "af24f4a86e7dc0a360f5e68bcca82adf88dfb4847abc8c4d26aaebb4355adf8e"
CLUSTER_CONFIG_SHA256 = "fb77d8c681fe7577ccc86867f84ee719339e444976c51b3ea343dcc4a11e2f03"
HARDWARE_CONFIG_SHA256 = "69a1bd564e8bed91ccbf3c2e2fcb862ba3bce2cc0e4754e3dbd1179d7b29cf13"
CHECKPOINT_CONFIG_SHA256 = "66abfefd546592fc3ca7fb2015c64e47c9ff2ffbe491206cdb080fc7a5722bdb"
DEFAULTS_CONFIG_SHA256 = "d82601c8c1cf833330d05e7fcd0393565dfe6d59d3011b75bc54a7f0b923d9bc"

PYTHON_RUNTIME_ROOT = Path(os.environ.get("K3_V13_PYTHON_RUNTIME_ROOT", "/nonexistent"))
PYTHON = PYTHON_RUNTIME_ROOT / "bin/python3.12"
PYTHON_SHA256 = "1a301bb1763139d48ae638d97b11edf56de6cd185e1b054eae6dc28c271c0c5f"
BASH = Path("/usr/bin/bash")
BASH_SHA256 = "af955ef55333c8fc9c5aa50df91ad1a629d9a79a9afa125cd5e9629585f78015"
GIT = Path("/usr/bin/git")
GIT_SHA256 = "aa6540695d076182256dd6e96c8b302e4d56381e3000bbfd5c71bbdfe94a4942"
SCHEDULER_BINARIES = {
    Path("/usr/bin/sbatch"): "3c1029c3a436107bf48b3b2d450e5fd1c9b204e6674906005cbbbb3c7df7feda",
    Path("/usr/bin/scontrol"): "395549996ab93fbbb806b8d68d355a97d9dbdf28dad2f421872b8d1fbdabe4ad",
    Path("/usr/bin/squeue"): "45fa838a4882d58d7bd2604f52b79aae98fafe1d165008d56f7220a4e7faf341",
    Path("/usr/bin/sacct"): "5149de553e71a44118c6f30e0f7bba5cb55f540308a7943f084f24709b588c57",
    Path("/usr/bin/scancel"): "6b8c2c876e8e47b42995901d7c51244fca8c0f180ba9b6a4c3ed7373fdeebac9",
    Path("/usr/bin/sacctmgr"): "2dcd07aebda7cc95ebbf8daecadde9d8d7788b89a9c3ec85a0f4693bf5f85c2f",
    Path("/usr/bin/tmux"): "e38ba2aef1810640f05fd8afaa62daf47ccce6bc0e18d73f73b8b6cc94deade2",
}
PYTHON_STDLIB = PYTHON_RUNTIME_ROOT / "lib/python3.12"
PYTHON_RUNTIME_MANIFEST = {
    "directories": 51,
    "files": 627,
    "bytes": 32_476_972,
    "sha256": "dedc3de09ac619c013db021b58bb5a357e010a1f790711efca0caeb8dd1c84d9",
}
PYTHON_RUNTIME_TAR_SHA256 = "02e92c608d152ac8e76893e674fcb98e12d092f965b066d497c38f002bced3be"
RUNTIME_ZIP_SHA256 = "cb2b8d5c1623ec9f613b50083a7e3ba71d324e92fb1d64568fd38e5f39733dbc"

PIXI_ENVS_ROOT = Path("/checkpoint/ram/shared/pixi_envs")
PIXI_BIN_ROOT = Path("/checkpoint/ram/shared/pixi-multiarch")
COORDINATOR_ENV = "control-plane-x86/5937b7ff8961"
PROXY_ENV = "proxy-litellm-x86/acef315f40ed"
WORKER_ENV = "control-plane-aarch64/95f64bce4ba7"
SERVING_RUNTIME_MANIFESTS = {
    "coordinator": {
        "entries": 11_401,
        "files": 9_304,
        "symlinks": 1_298,
        "bytes": 320_649_824,
        "sha256": "4de492b4bddb9734ac0d66a107238bb7b5a258ef3e8d23f496301ee683da5cda",
    },
    "proxy": {
        "entries": 32_034,
        "files": 26_381,
        "symlinks": 1_171,
        "bytes": 876_706_414,
        "sha256": "09b1cdc9f393e52826f00ece54ca9df4128cc5f40a4010182f830697a7eca7cd",
    },
    "worker": {
        "entries": 11_398,
        "files": 9_307,
        "symlinks": 1_296,
        "bytes": 331_877_045,
        "sha256": "04fde6b833c8622a4afac2960c070925d3be8067fa9f2aa9d8b1bd78b96522ae",
    },
    "pixi_bin": {
        "entries": 3,
        "files": 2,
        "symlinks": 0,
        "bytes": 143_550_904,
        "sha256": "37b5da204008b2755e683cab24e82c4bc92f72f5897cf67ea5b6690f26e47702",
    },
}

MODEL = "Kimi-K3"
MODEL_SELECTOR = "kimi-k3"
MODEL_ROOT = Path("/checkpoint/ram/shared/models/moonshotai/Kimi-K3")
MODEL_REVISION = "9f62e4e9fffbd0a83ddd60e1c209d828994b3569"
MODEL_INDEX_SHA256 = "a1c5210650ce71d2d3ae9ec5a101ac4afd3cf4b10091be589853437eb967febd"
MODEL_PROVENANCE_SHA256 = "70ab6155394302da7f47d478646753cd924cfb451151f289ee2869e0f7f74a05"
MODEL_RECORDS = 114
MODEL_SHARDS = 96
MODEL_TOTAL_WEIGHT_BYTES = 1_560_936_091_448
MODEL_INDEX_TOTAL_SIZE = 1_560_860_324_864
MODEL_OWNER_UID = 156734
MODEL_OWNER_GID = 1003647
IMAGE = (
    "588845226011.dkr.ecr.us-east-2.amazonaws.com/msl_infra/"
    "vllm-openai:kimi-k3-kda-logprobs-fix-v2-20260916@"
    "sha256:642f60668388b6c8e2d98f93577c9cd6a8aafaca7344dc4ab6a9e040774dec20"
)
PIECEWISE = '{"cudagraph_mode":"PIECEWISE"}'
INITIAL_SPEC_NORMALIZED_SHA256 = "5806417d9f273dfc1e4e266b418fa170284e0344fda8847f4dcf50ce5ec8b321"
FINAL_SPEC_NORMALIZED_SHA256 = "db6adc2c94d534c76ce5f314934dcfcc9ded19de7f98c118c4a1ec0fc9d4cdf9"
EXPLAIN_NORMALIZED_SHA256 = "d6aa92805687264167ab24efd4e27958de17ed1f355db5db10310a0bc943da97"

JOB_NAME = f"{DEPLOYMENT_ID}-coord"
JOB_COMMENT_PREFIX = "k3-tb4-v13-"
JOB_TIME_LIMIT = "7-00:00:00"
WORKER_QOS = "g3_lowest"
EXPECTED_WORKER_QOS_PRIORITY = 1
EXPECTED_WORKER_QOS_OUTBOUND = ("normal",)
EXPECTED_WORKER_QOS_PREEMPTORS = (
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
WORKER_QOS_PREEMPTIBLE = True
WORKER_EXCLUDE_NODES = (
    "g3-136-221",
    "g3-136-247",
    "g3-136-251",
    "g3-136-253",
)
PREEMPTION_GRACE_SECONDS = 180
PREEMPTION_WAVE_BUDGET = 1
PREEMPTION_WINDOW_SECONDS = 7 * 24 * 60 * 60
WAIT_SECONDS = 10_800
SUBMIT_TIMEOUT = 90
COMMAND_TIMEOUT = 30
OUTPUT_LIMIT = 2 << 20
ZERO_ROUNDS = 6
ZERO_INTERVAL = 5
COORDINATOR_IDENTITY_ROUNDS = 31
COORDINATOR_IDENTITY_INTERVAL = 1.0
TMUX_SOCKET = "/tmp/tmux-656177/default"
TMUX_PANE = "%0"
TMUX_IDENTITY = "swebench_vmvm:Launcher.0"
TMUX_SESSION_ID = "$0"
TMUX_SESSION_CREATED = "1789806215"
TMUX_WINDOW_ID = "@0"
TMUX_PANE_PID = "933680"

DEPLOY_ARGS = (
    DEPLOYMENT_ID,
    "--model",
    MODEL_SELECTOR,
    "--cluster",
    CLUSTER,
    "--hardware",
    "gb300",
    "--checkpoint-source",
    "cluster-shared",
    "--endpoints",
    "2",
    "--worker-kind",
    "vllm",
    "--image",
    IMAGE,
    "--partition",
    "g3",
    "--account",
    "ram",
    "--qos",
    WORKER_QOS,
    "--worker-exclude-node",
    WORKER_EXCLUDE_NODES[0],
    "--worker-exclude-node",
    WORKER_EXCLUDE_NODES[1],
    "--worker-exclude-node",
    WORKER_EXCLUDE_NODES[2],
    "--worker-exclude-node",
    WORKER_EXCLUDE_NODES[3],
    "--time",
    JOB_TIME_LIMIT,
    "--time-min",
    "3-00:00:00",
    "--gpus-per-endpoint",
    "16",
    "--cpus-per-task",
    "96",
    "--mem",
    "900G",
    "--proxy-kind",
    "litellm",
    "--proxy-partition",
    "cpu_x86",
    "--proxy-account",
    "everyone",
    "--proxy-qos",
    "cpu_x86_lowest",
    "--proxy-time",
    JOB_TIME_LIMIT,
    "--proxy-cpus-per-task",
    "8",
    "--proxy-mem",
    "32G",
    "--sticky",
    "--sticky-ttl",
    "14400",
    "--transport",
    "http",
    "--coord-partition",
    "cpu_x86",
    "--coord-account",
    "everyone",
    "--coord-qos",
    "cpu_x86_lowest",
    "--coord-time",
    JOB_TIME_LIMIT,
    "--coord-cpus-per-task",
    "4",
    "--coord-mem",
    "16G",
    "--startup-grace",
    "7200",
    "--walltime-presubmit",
    "1200",
    "--worker-usr1-warn",
    "120",
    "--proxy-usr1-warn",
    "600",
    "--set",
    "proxy.config.request_timeout=43200",
    "--set",
    "proxy.config.num_retries=0",
    "--lifetime",
    "7d",
)

SAFE_ENV = {
    "HOME": "/nonexistent",
    "USER": OWNER,
    "LOGNAME": OWNER,
    "PATH": "/usr/bin:/bin",
    "SHELL": "/usr/bin/bash",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "SLURM_CLUSTER_NAME": CLUSTER,
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "V2_DEPLOYMENTS_ROOT": str(DEPLOYMENTS_ROOT),
    "CONFIG_DIR": str(CONFIG_ROOT),
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}
REGISTRY_TLS_ENV_NAMES = (
    "THRIFT_TLS_CL_CERT_PATH",
    "THRIFT_TLS_CL_KEY_PATH",
)
JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
SLURM_NULLISH = frozenset({None, "", "None", "(null)", "Unknown"})
TERMINAL_STATES = frozenset(
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
STOP_EVENT = threading.Event()
SUBMITTED_JOB_ID: str | None = None
SUBMITTED_DIRECT = False
SUBMIT_ERROR_CODE: str | None = None
COORDINATOR_RELEASED = False
REGISTRY_BINDING: dict[str, str] = {}


class DeploymentError(RuntimeError):
    pass


class SchedulerUnavailable(DeploymentError):
    pass


class CoordinatorIdentityTransient(DeploymentError):
    pass


class LaunchCancelled(BaseException):
    pass


@dataclass(frozen=True)
class Captured:
    raw: bytes
    sha256: str
    signature: tuple[int, ...]


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class GlobalLock:
    descriptor: int
    directory_descriptor: int
    identity: tuple[int, int]
    directory_identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class TerminalLockProof:
    sha256: str
    device: int
    inode: int


def fail(code: str) -> None:
    raise DeploymentError(code)


def sanitized_error_code(error: BaseException) -> str:
    if isinstance(error, LaunchCancelled):
        return "signal"
    if isinstance(error, DeploymentError):
        code = str(error)
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is not None:
            return code
    return "internal_error"


def registry_tls_binding() -> dict[str, str]:
    bound: dict[str, str] = {}
    for name in REGISTRY_TLS_ENV_NAMES:
        raw = os.environ.get(name, "")
        if not raw or not Path(raw).is_absolute():
            fail("registry_tls_binding")
        path = Path(raw)
        try:
            before = path.lstat()
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            try:
                opened = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            after = path.lstat()
        except OSError as error:
            raise DeploymentError("registry_tls_binding") from error
        if not (
            signature(before) == signature(opened) == signature(after)
            and stat.S_ISREG(opened.st_mode)
            and opened.st_uid == OWNER_UID
            and opened.st_nlink == 1
            and stat.S_IMODE(opened.st_mode) & stat.S_IRUSR
            and stat.S_IMODE(opened.st_mode) & 0o077 == 0
        ):
            fail("registry_tls_binding")
        bound[name] = raw
    return bound


def canonical_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def stable_file(
    path: Path,
    *,
    expected_sha256: str | None = None,
    mode: int | None = None,
    uid: int = OWNER_UID,
    maximum: int = 64 << 20,
    allow_empty: bool = False,
) -> Captured:
    descriptor = -1
    try:
        before_name = path.lstat()
        if (
            not stat.S_ISREG(before_name.st_mode)
            or before_name.st_uid != uid
            or before_name.st_nlink != 1
            or (mode is not None and stat.S_IMODE(before_name.st_mode) != mode)
            or before_name.st_size > maximum
            or (not allow_empty and before_name.st_size == 0)
        ):
            fail("file_identity")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(descriptor)
        if signature(opened) != signature(before_name):
            fail("file_race")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            block = os.read(descriptor, min(1 << 20, remaining))
            if not block:
                fail("file_short_read")
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(descriptor)
        after_name = path.lstat()
    except DeploymentError:
        raise
    except OSError as error:
        raise DeploymentError("file_unavailable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        signature(before_name) != signature(opened)
        or signature(opened) != signature(after)
        or signature(after) != signature(after_name)
    ):
        fail("file_race")
    raw = b"".join(chunks)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        fail("file_hash")
    return Captured(raw, digest, signature(after))


def content_tree_manifest(root: Path) -> dict[str, Any]:
    try:
        resolved = root.resolve(strict=True)
        root_before = root.lstat()
    except OSError as error:
        raise DeploymentError("manifest_root") from error
    if root != resolved or not stat.S_ISDIR(root_before.st_mode):
        fail("manifest_root")
    records: list[list[Any]] = []
    directory_identities: list[tuple[Path, tuple[int, ...]]] = []
    directories = files = total = 0
    for directory, names, filenames in os.walk(root, followlinks=False):
        if STOP_EVENT.is_set():
            raise LaunchCancelled()
        names.sort()
        filenames.sort()
        current = Path(directory)
        current_status = current.stat(follow_symlinks=False)
        if not stat.S_ISDIR(current_status.st_mode) or current_status.st_uid != OWNER_UID:
            fail("manifest_entry")
        relative_dir = current.relative_to(root).as_posix()
        records.append(
            [
                "d",
                "." if relative_dir == "." else relative_dir,
                stat.S_IMODE(current_status.st_mode),
                current_status.st_uid,
            ]
        )
        directory_identities.append((current, signature(current_status)))
        directories += 1
        for name in names:
            child = current / name
            child_status = child.lstat()
            if child.is_symlink() or not stat.S_ISDIR(child_status.st_mode):
                fail("manifest_entry")
        for name in filenames:
            path = current / name
            if path.is_symlink() or path.suffix.lower() in {".pyc", ".pyo"}:
                fail("manifest_entry")
            captured = stable_file(path, uid=OWNER_UID, maximum=128 << 20, allow_empty=True)
            relative = path.relative_to(root).as_posix()
            records.append(
                [
                    "f",
                    relative,
                    len(captured.raw),
                    captured.sha256,
                    stat.S_IMODE(captured.signature[2]),
                ]
            )
            files += 1
            total += len(captured.raw)
    if any(signature(path.lstat()) != expected for path, expected in directory_identities):
        fail("manifest_race")
    digest = hashlib.sha256(
        json.dumps(
            {"schema_version": 1, "records": records},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "directories": directories,
        "files": files,
        "bytes": total,
        "sha256": digest,
    }


def identity_tree_manifest(root: Path) -> dict[str, Any]:
    """Reproduce the previously reviewed root-runtime manifest algorithm."""
    try:
        root_before = root.lstat()
    except OSError as error:
        raise DeploymentError("runtime_manifest_root") from error
    if not stat.S_ISDIR(root_before.st_mode) or root_before.st_uid != 0:
        fail("runtime_manifest_root")
    records: list[dict[str, Any]] = []
    total = 0
    paths = [root, *root.rglob("*")]
    paths.sort(key=lambda item: "" if item == root else item.relative_to(root).as_posix())
    for path in paths:
        if STOP_EVENT.is_set():
            raise LaunchCancelled()
        metadata = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        record: dict[str, Any] = {
            "path": relative,
            "mode": stat.S_IMODE(metadata.st_mode),
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
            "nlink": metadata.st_nlink,
            "size": metadata.st_size,
        }
        if stat.S_ISDIR(metadata.st_mode):
            if metadata.st_uid != 0:
                fail("runtime_manifest_identity")
            record["kind"] = "dir"
        elif stat.S_ISREG(metadata.st_mode):
            captured = stable_file(path, uid=0, maximum=128 << 20, allow_empty=True)
            record["kind"] = "file"
            record["sha256"] = captured.sha256
            total += len(captured.raw)
        elif stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(path)
            after = path.lstat()
            if (
                signature(after) != signature(metadata)
                or os.readlink(path) != target
                or metadata.st_uid != 0
                or not target
            ):
                fail("runtime_manifest_race")
            record["kind"] = "symlink"
            record["target"] = target
        else:
            fail("runtime_manifest_entry")
        records.append(record)
    if signature(root.lstat()) != signature(root_before):
        fail("runtime_manifest_race")
    return {
        "entries": len(records),
        "bytes": total,
        "sha256": hashlib.sha256(canonical_bytes(records)[:-1]).hexdigest(),
    }


def external_tree_manifest(root: Path) -> dict[str, Any]:
    """Hash a shared runtime tree while retaining its identity metadata."""
    try:
        root_before = root.lstat()
        if root.resolve(strict=True) != root or not stat.S_ISDIR(root_before.st_mode):
            fail("external_runtime_root")
    except OSError as error:
        raise DeploymentError("external_runtime_root") from error
    records: list[list[Any]] = []
    identities: list[tuple[Path, tuple[int, ...], str | None]] = []
    total = files = symlinks = 0
    paths = [root, *root.rglob("*")]
    paths.sort(key=lambda item: "" if item == root else item.relative_to(root).as_posix())
    for path in paths:
        if STOP_EVENT.is_set():
            raise LaunchCancelled()
        try:
            before = path.lstat()
        except OSError as error:
            raise DeploymentError("external_runtime_entry") from error
        relative = "." if path == root else path.relative_to(root).as_posix()
        identity = [
            relative,
            stat.S_IMODE(before.st_mode),
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
        ]
        if stat.S_ISDIR(before.st_mode):
            records.append(["d", *identity])
            identities.append((path, signature(before), None))
            continue
        if stat.S_ISLNK(before.st_mode):
            target = os.readlink(path)
            if not target or Path(target).is_absolute():
                fail("external_runtime_symlink")
            try:
                path.resolve(strict=True).relative_to(root)
            except (OSError, ValueError) as error:
                raise DeploymentError("external_runtime_symlink") from error
            records.append(["l", *identity, target])
            identities.append((path, signature(before), target))
            symlinks += 1
            continue
        if not stat.S_ISREG(before.st_mode) or before.st_size > 256 << 20:
            fail("external_runtime_entry")
        descriptor = -1
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            opened = os.fstat(descriptor)
            if signature(opened) != signature(before):
                fail("external_runtime_race")
            digest = hashlib.sha256()
            remaining = opened.st_size
            while remaining:
                block = os.read(descriptor, min(1 << 20, remaining))
                if not block:
                    fail("external_runtime_short_read")
                digest.update(block)
                remaining -= len(block)
            after = os.fstat(descriptor)
        except DeploymentError:
            raise
        except OSError as error:
            raise DeploymentError("external_runtime_entry") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if signature(before) != signature(after):
            fail("external_runtime_race")
        records.append(["f", *identity, digest.hexdigest()])
        identities.append((path, signature(after), None))
        files += 1
        total += opened.st_size
    for path, expected, target in identities:
        try:
            observed = path.lstat()
            observed_target = os.readlink(path) if target is not None else None
        except OSError as error:
            raise DeploymentError("external_runtime_race") from error
        if signature(observed) != expected or observed_target != target:
            fail("external_runtime_race")
    if signature(root.lstat()) != signature(root_before):
        fail("external_runtime_race")
    return {
        "entries": len(records),
        "files": files,
        "symlinks": symlinks,
        "bytes": total,
        "sha256": hashlib.sha256(canonical_bytes(records)[:-1]).hexdigest(),
    }


def validate_serving_runtime() -> dict[str, dict[str, Any]]:
    observed = {
        "coordinator": external_tree_manifest(PIXI_ENVS_ROOT / COORDINATOR_ENV),
        "proxy": external_tree_manifest(PIXI_ENVS_ROOT / PROXY_ENV),
        "worker": external_tree_manifest(PIXI_ENVS_ROOT / WORKER_ENV),
        "pixi_bin": external_tree_manifest(PIXI_BIN_ROOT),
    }
    if observed != SERVING_RUNTIME_MANIFESTS:
        fail("serving_runtime_manifest")
    return observed


def run_command(
    argv: Sequence[str],
    *,
    timeout: float = COMMAND_TIMEOUT,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> Result:
    try:
        process = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=dict(env or SAFE_ENV),
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired as error:
        raise SchedulerUnavailable("command_timeout") from error
    except OSError as error:
        raise SchedulerUnavailable("command_unavailable") from error
    if len(process.stdout) + len(process.stderr) > OUTPUT_LIMIT:
        fail("command_output_oversize")
    if check and process.returncode != 0:
        raise SchedulerUnavailable("command_failed")
    return Result(process.returncode, process.stdout, process.stderr)


def git_value(*args: str) -> bytes:
    return run_command((str(GIT), "-C", str(SOURCE_REPO), *args), env=SAFE_ENV).stdout.strip()


def validate_source() -> None:
    stable_file(
        SOURCE_BUNDLE,
        expected_sha256=SOURCE_BUNDLE_SHA256,
        mode=0o400,
        maximum=16 << 20,
    )
    for path, digest in (
        (SERVE_ROOT / "serve.sh", SERVE_SH_SHA256),
        (CONFIG_ROOT / "models/kimi-k3/card.toml", MODEL_CARD_SHA256),
        (CONFIG_ROOT / "clusters/fair-cw-use2-3.toml", CLUSTER_CONFIG_SHA256),
        (CONFIG_ROOT / "hardware.toml", HARDWARE_CONFIG_SHA256),
        (CONFIG_ROOT / "checkpoint_sources.toml", CHECKPOINT_CONFIG_SHA256),
        (CONFIG_ROOT / "_defaults.toml", DEFAULTS_CONFIG_SHA256),
    ):
        stable_file(path, expected_sha256=digest, maximum=4 << 20)
    if git_value("rev-parse", "--verify", "HEAD").decode() != SOURCE_REVISION:
        fail("source_revision")
    if git_value("rev-parse", "--verify", "HEAD^{tree}").decode() != SOURCE_TREE:
        fail("source_tree")
    symbolic = run_command(
        (str(GIT), "-C", str(SOURCE_REPO), "symbolic-ref", "-q", "HEAD"),
        env=SAFE_ENV,
        check=False,
    )
    if symbolic.returncode == 0 or symbolic.stdout or symbolic.stderr:
        fail("source_not_detached")
    if git_value("status", "--porcelain=v1", "--untracked-files=all"):
        fail("source_dirty")
    ignored = git_value("status", "--ignored", "--porcelain=v1", "--untracked-files=all")
    if ignored:
        fail("source_ignored_files")
    if content_tree_manifest(SERVE_ROOT) != SOURCE_MANIFEST:
        fail("source_manifest")


def validate_evaluator() -> None:
    for revision_arg, expected in (
        ("HEAD", EVALUATOR_REVISION),
        ("HEAD^{tree}", EVALUATOR_TREE),
    ):
        observed = run_command(
            (
                str(GIT),
                "-C",
                str(EVALUATOR_ROOT),
                "rev-parse",
                "--verify",
                revision_arg,
            ),
            env=SAFE_ENV,
        ).stdout.strip()
        if observed.decode("utf-8", "strict") != expected:
            fail("evaluator_revision")
    status = run_command(
        (
            str(GIT),
            "-C",
            str(EVALUATOR_ROOT),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ),
        env=SAFE_ENV,
    )
    if status.stdout:
        fail("evaluator_dirty")
    import tomllib

    for path, digest in EVAL_CONFIGS.items():
        captured = stable_file(path, expected_sha256=digest, maximum=1 << 20)
        try:
            config = tomllib.loads(captured.raw.decode("utf-8", "strict"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise DeploymentError("evaluator_config") from error
        if (
            config.get("model") != MODEL
            or config.get("max_input_tokens") != EVALUATOR_CONTEXT_CAP
            or config.get("max_output_tokens") != EVALUATOR_CONTEXT_CAP
            or config.get("max_total_tokens") != EVALUATOR_CONTEXT_CAP
        ):
            fail("evaluator_context_policy")


def validate_runtime_zip(raw: bytes | None = None) -> bytes:
    captured = stable_file(
        RUNTIME_ZIP,
        expected_sha256=RUNTIME_ZIP_SHA256,
        mode=0o400,
        maximum=16 << 20,
    )
    if raw is not None and raw != captured.raw:
        fail("runtime_zip_changed")
    try:
        with zipfile.ZipFile(io.BytesIO(captured.raw)) as archive:
            names = archive.namelist()
            if (
                archive.testzip() is not None
                or len(names) != len(set(names))
                or "REDEPLOY_RUNTIME_MANIFEST.json" not in names
                or any(
                    name.startswith("/") or ".." in Path(name).parts or name.endswith((".pyc", ".pyo", ".pth", ".so"))
                    for name in names
                )
            ):
                fail("runtime_zip_invalid")
            manifest = json.loads(archive.read("REDEPLOY_RUNTIME_MANIFEST.json"))
            records = []
            for name in sorted(n for n in names if n != "REDEPLOY_RUNTIME_MANIFEST.json"):
                value = archive.read(name)
                records.append([name, len(value), hashlib.sha256(value).hexdigest()])
            if manifest != {
                "schema_version": 1,
                "kind": "k3-redeploy-pure-python-runtime",
                "files": records,
            }:
                fail("runtime_zip_manifest")
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        KeyError,
        json.JSONDecodeError,
    ) as error:
        raise DeploymentError("runtime_zip_invalid") from error
    return captured.raw


def model_provenance() -> dict[str, Any]:
    for path, mode in (
        (DEPLOYMENTS_ROOT.parent / "models", 0o2775),
        (MODEL_ROOT.parent, 0o2755),
        (MODEL_ROOT, 0o2755),
        (MODEL_ROOT / ".cache/huggingface/download", 0o2755),
    ):
        metadata = path.stat(follow_symlinks=False)
        if (
            path.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_uid != MODEL_OWNER_UID
            or metadata.st_gid != MODEL_OWNER_GID
            or (path != DEPLOYMENTS_ROOT.parent / "models" and metadata.st_mode & 0o022)
        ):
            fail("model_directory_identity")
    metadata_root = MODEL_ROOT / ".cache/huggingface/download"
    try:
        index_raw = stable_file(
            MODEL_ROOT / "model.safetensors.index.json",
            expected_sha256=MODEL_INDEX_SHA256,
            mode=0o644,
            uid=MODEL_OWNER_UID,
            maximum=64 << 20,
        ).raw
        index = json.loads(index_raw)
    except (ValueError, json.JSONDecodeError) as error:
        raise DeploymentError("model_index") from error
    weight_map = index.get("weight_map")
    metadata_block = index.get("metadata")
    if (
        not isinstance(weight_map, dict)
        or not isinstance(metadata_block, dict)
        or metadata_block.get("total_size") != MODEL_INDEX_TOTAL_SIZE
    ):
        fail("model_index")
    shards = sorted(set(weight_map.values()))
    if len(shards) != MODEL_SHARDS or any(not isinstance(name, str) for name in shards):
        fail("model_shards")
    records: list[list[Any]] = []
    root_files = sorted(
        (
            path
            for path in MODEL_ROOT.rglob("*")
            if path.is_file() and ".cache" not in path.parts and ".eval_results" not in path.parts
        ),
        key=lambda path: path.relative_to(MODEL_ROOT).as_posix(),
    )
    for path in root_files:
        if STOP_EVENT.is_set():
            raise LaunchCancelled()
        relative = path.relative_to(MODEL_ROOT).as_posix()
        before = path.stat(follow_symlinks=False)
        if (
            path.is_symlink()
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o644
            or before.st_uid != MODEL_OWNER_UID
            or before.st_gid != MODEL_OWNER_GID
            or before.st_nlink != 1
        ):
            fail("model_file_identity")
        if path.suffix == ".safetensors":
            meta_path = metadata_root / f"{relative}.metadata"
            metadata = stable_file(
                meta_path,
                mode=0o644,
                uid=MODEL_OWNER_UID,
                maximum=4096,
            )
            try:
                lines = metadata.raw.decode("utf-8", "strict").splitlines()
            except UnicodeDecodeError as error:
                raise DeploymentError("model_metadata") from error
            if len(lines) != 3 or lines[0] != MODEL_REVISION or SHA_RE.fullmatch(lines[1]) is None:
                fail("model_metadata")
            after = path.stat(follow_symlinks=False)
            if signature(before) != signature(after):
                fail("model_file_race")
            records.append(
                [
                    "weight",
                    relative,
                    before.st_size,
                    stat.S_IMODE(before.st_mode),
                    before.st_uid,
                    before.st_gid,
                    before.st_nlink,
                    metadata.sha256,
                    lines[1],
                ]
            )
        else:
            captured = stable_file(
                path,
                mode=0o644,
                uid=MODEL_OWNER_UID,
                maximum=64 << 20,
                allow_empty=True,
            )
            records.append(
                [
                    "file",
                    relative,
                    len(captured.raw),
                    stat.S_IMODE(before.st_mode),
                    before.st_uid,
                    before.st_gid,
                    before.st_nlink,
                    captured.sha256,
                ]
            )
    if shards != sorted(record[1] for record in records if record[0] == "weight"):
        fail("model_shards")
    payload = {
        "schema_version": 1,
        "revision": MODEL_REVISION,
        "index_total_size": MODEL_INDEX_TOTAL_SIZE,
        "records": records,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = {
        "revision": MODEL_REVISION,
        "records": len(records),
        "shards": len(shards),
        "weight_bytes": sum(record[2] for record in records if record[0] == "weight"),
        "index_total_size": MODEL_INDEX_TOTAL_SIZE,
        "manifest_sha256": digest,
        "weight_binding": "immutable-owner-hf-revision-etag-size",
    }
    if result != {
        "revision": MODEL_REVISION,
        "records": MODEL_RECORDS,
        "shards": MODEL_SHARDS,
        "weight_bytes": MODEL_TOTAL_WEIGHT_BYTES,
        "index_total_size": MODEL_INDEX_TOTAL_SIZE,
        "manifest_sha256": MODEL_PROVENANCE_SHA256,
        "weight_binding": "immutable-owner-hf-revision-etag-size",
    }:
        fail("model_manifest")
    return result


def validate_root_runtime() -> None:
    try:
        runtime_root = PYTHON_RUNTIME_ROOT.resolve(strict=True)
    except OSError as error:
        raise DeploymentError("python_runtime_root") from error
    if (
        runtime_root != PYTHON_RUNTIME_ROOT
        or Path(sys.executable) != PYTHON
        or Path(sys.prefix) != runtime_root
        or Path(sys.base_prefix) != runtime_root
        or os.environ.get("K3_V13_RUNTIME_TAR_SHA256") != PYTHON_RUNTIME_TAR_SHA256
    ):
        fail("python_runtime_identity")
    stable_file(
        PYTHON,
        expected_sha256=PYTHON_SHA256,
        mode=0o555,
        uid=OWNER_UID,
        maximum=16 << 20,
    )
    stable_file(
        PYTHON_RUNTIME_TAR,
        expected_sha256=PYTHON_RUNTIME_TAR_SHA256,
        mode=0o400,
        maximum=64 << 20,
    )
    stable_file(BASH, expected_sha256=BASH_SHA256, mode=0o755, uid=0, maximum=4 << 20)
    stable_file(GIT, expected_sha256=GIT_SHA256, mode=0o755, uid=0, maximum=8 << 20)
    for path, digest in SCHEDULER_BINARIES.items():
        stable_file(path, expected_sha256=digest, mode=0o755, uid=0, maximum=2 << 20)
    if content_tree_manifest(PYTHON_RUNTIME_ROOT) != PYTHON_RUNTIME_MANIFEST:
        fail("python_runtime_manifest")
    if any(
        path.is_symlink() or path.name.endswith((".pth", ".pyc", ".pyo")) or path.name == "__pycache__"
        for path in PYTHON_RUNTIME_ROOT.rglob("*")
    ):
        fail("python_runtime_unbound_entry")


def expected_hashes() -> dict[str, str]:
    keys = {
        "launcher": "EXPECTED_LAUNCHER_SHA256",
        "controller": "EXPECTED_CONTROLLER_SHA256",
        "plan": "EXPECTED_PLAN_SHA256",
        "readme": "EXPECTED_README_SHA256",
        "tests": "EXPECTED_TEST_SHA256",
        "builder": "EXPECTED_BUILDER_SHA256",
        "runtime_zip": "EXPECTED_RUNTIME_ZIP_SHA256",
        "python_runtime": "EXPECTED_PYTHON_RUNTIME_TAR_SHA256",
    }
    result = {name: os.environ.get(variable, "") for name, variable in keys.items()}
    if any(SHA_RE.fullmatch(value) is None for value in result.values()):
        fail("bundle_hash_environment")
    return result


def batch_plan() -> dict[str, Any]:
    return {
        "deployment_id": DEPLOYMENT_ID,
        "excluded_stale_deployment_ids": sorted(STALE_DEPLOYMENT_IDS),
        "model": MODEL,
        "model_selector": MODEL_SELECTOR,
        "model_revision": MODEL_REVISION,
        "model_provenance_sha256": MODEL_PROVENANCE_SHA256,
        "image": IMAGE,
        "source_revision": SOURCE_REVISION,
        "source_tree": SOURCE_TREE,
        "source_bundle_sha256": SOURCE_BUNDLE_SHA256,
        "source_manifest": SOURCE_MANIFEST,
        "snapshot_manifest": SNAPSHOT_MANIFEST,
        "output_root": str(OUTPUT_ROOT),
        "evaluator_revision": EVALUATOR_REVISION,
        "evaluator_tree": EVALUATOR_TREE,
        "evaluator_config_sha256": {path.name: digest for path, digest in EVAL_CONFIGS.items()},
        "evaluator_context_cap": EVALUATOR_CONTEXT_CAP,
        "runtime_zip_sha256": RUNTIME_ZIP_SHA256,
        "python_runtime_tar_sha256": PYTHON_RUNTIME_TAR_SHA256,
        "python_runtime_manifest": PYTHON_RUNTIME_MANIFEST,
        "serving_runtime_manifests": SERVING_RUNTIME_MANIFESTS,
        "endpoints": 2,
        "gpus_per_endpoint": 16,
        "worker_partition": "g3",
        "worker_account": "ram",
        "worker_qos": WORKER_QOS,
        "worker_qos_priority": EXPECTED_WORKER_QOS_PRIORITY,
        "worker_qos_outbound_preempt_targets": list(EXPECTED_WORKER_QOS_OUTBOUND),
        "worker_qos_preemptible": WORKER_QOS_PREEMPTIBLE,
        "worker_qos_preemptors": list(EXPECTED_WORKER_QOS_PREEMPTORS),
        "worker_exclude_nodes": list(WORKER_EXCLUDE_NODES),
        "full_fleet_preemption_grace_seconds": PREEMPTION_GRACE_SECONDS,
        "full_fleet_preemption_wave_budget": PREEMPTION_WAVE_BUDGET,
        "full_fleet_preemption_window_seconds": PREEMPTION_WINDOW_SECONDS,
        "worker_time": JOB_TIME_LIMIT,
        "worker_time_min": "3-00:00:00",
        "proxy_request_timeout": 43_200,
        "proxy_num_retries": 0,
        "sticky": True,
        "sticky_ttl": 14_400,
        "compilation_config": PIECEWISE,
        "initial_spec_normalized_sha256": INITIAL_SPEC_NORMALIZED_SHA256,
        "final_spec_normalized_sha256": FINAL_SPEC_NORMALIZED_SHA256,
        "held_coordinator": True,
        "coordinator_nodes": 1,
        "coordinator_cpus": 4,
        "coordinator_memory": "16G",
        "coordinator_nodes_explicit": True,
        "coordinator_req_tres": {"billing": "4", "cpu": "4", "mem": "16G", "node": "1"},
        "coordinator_cold_standby": "exactly_one_afternotok",
        "service_generation_stable_at_receipt": True,
        "resume": False,
    }


def pending_contract() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "k3-two-endpoint-replacement-deployment-plan",
        "state": "pending_independent_approval",
        "launch_eligible": False,
        "approval_path": str(APPROVAL),
        "run_root": str(RUN_ROOT),
        "global_lock": str(GLOBAL_LOCK),
        "plan": batch_plan(),
        "lifecycle": {
            "pre_submit_name_absence": True,
            "approval_revalidated_before_owner_intent": True,
            "approval_payload_bound_in_owner_intent": True,
            "post_consumption_approval_path_independent": True,
            "pre_lock_namespace_freshness": True,
            "post_lock_namespace_freshness": True,
            "global_lock_exclusive_creation": True,
            "global_lock_identity_after_acquire": True,
            "global_lock_never_unlinked": True,
            "global_lock_replacement_retained": True,
            "global_lock_terminal_tombstone": True,
            "global_lock_descriptor_closed_before_success": True,
            "held_submission": True,
            "ambiguous_submission_reconciliation_rounds": ZERO_ROUNDS,
            "coordinator_identity_retry_rounds": COORDINATOR_IDENTITY_ROUNDS,
            "coordinator_identity_retry_interval_seconds": COORDINATOR_IDENTITY_INTERVAL,
            "coordinator_identity_monotonic_deadline_seconds": 30,
            "coordinator_identity_fields_never_weakened": True,
            "coordinator_req_tres_exact": True,
            "coordinator_singleton_ranges_semantic": True,
            "coordinator_held_node_incomplete_spellings": [
                None,
                "",
                "None",
                "(null)",
                "Unknown",
                "0",
                "0-1",
            ],
            "coordinator_cpu_cardinality_strict": True,
            "coordinator_held_stable_reads": 2,
            "coordinator_release_stable_reads": 2,
            "coordinator_incomplete_allocation_retry_only": True,
            "coordinator_standby_stable_reads": 2,
            "coordinator_standby_propagation_bounded": True,
            "coordinator_standby_monotonic_deadline": True,
            "nested_submit_error_code_preserved": True,
            "post_submit_identity": True,
            "initial_spec_stable_reads": 2,
            "release_after_initial_spec_receipt": True,
            "rollback_on_failure": True,
            "terminal_cleanup_rounds": ZERO_ROUNDS,
            "cleanup_exact_deployment_stop": True,
            "cleanup_coordinator_identity_bound_before_stop": True,
            "cleanup_exact_stop_not_vetoed_by_identity_warning": True,
            "cleanup_post_stop_terminal_proof_uses_bound_ids": True,
            "cleanup_stop_success_credits_prebound_ids_without_accounting": True,
            "cleanup_unbound_ids_require_two_name_queue_absence_reads": True,
            "cleanup_successor_lifecycle_binding_stable_reads": 2,
            "cleanup_exact_job_name_sweep": True,
            "failure_leaves_staged_artifacts_non_promoting": True,
            "failure_requires_commit_marker_absence": True,
            "atomic_no_replace_publication": True,
            "readiness_producer_consumer_cross_binding": True,
            "readiness_signal_checked_before_and_after_publish": True,
            "python_runtime_verified_before_imports": True,
            "success_commit_signal_linearized": True,
            "success_commit_marker_last": True,
            "commit_marker_binds_source_and_terminal_lock": True,
            "commit_link_error_never_authorizes_rollback": True,
        },
        "resource_risks": {
            "gb300_gpus": 32,
            "gb300_nodes": 8,
            "g3_lowest_qos_capacity_not_guaranteed": True,
            "g3_lowest_qos_is_preemptible": WORKER_QOS_PREEMPTIBLE,
            "worker_bad_nodes_excluded": list(WORKER_EXCLUDE_NODES),
            "seven_day_allocations": 2,
            "shared_runtime_trees_group_writable": True,
            "shared_runtime_content_revalidated_before_release": True,
        },
    }


def validate_bundle(self_raw: bytes) -> dict[str, str]:
    hashes = expected_hashes()
    expected = {
        "launch.sh": ("launcher", 0o500),
        "controller.py": ("controller", 0o500),
        "pending.json": ("plan", 0o400),
        "README.md": ("readme", 0o444),
        "test_controller.py": ("tests", 0o444),
        "build_runtime_zip.py": ("builder", 0o444),
        "runtime.zip": ("runtime_zip", 0o400),
        "python-runtime.tar": ("python_runtime", 0o400),
    }
    metadata = BUNDLE.stat(follow_symlinks=False)
    if (
        BUNDLE.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o500
        or metadata.st_uid != OWNER_UID
        or {entry.name for entry in BUNDLE.iterdir()} != set(expected)
    ):
        fail("bundle_identity")
    for name, (key, mode) in expected.items():
        stable_file(
            BUNDLE / name,
            expected_sha256=hashes[key],
            mode=mode,
            maximum=64 << 20 if name == "python-runtime.tar" else 16 << 20,
        )
    if hashlib.sha256(self_raw).hexdigest() != hashes["controller"]:
        fail("controller_capture")
    try:
        plan = json.loads(stable_file(PLAN, mode=0o400, maximum=1 << 20).raw)
    except (ValueError, json.JSONDecodeError) as error:
        raise DeploymentError("plan_json") from error
    if plan != pending_contract():
        fail("plan_contract")
    validate_runtime_zip()
    return hashes


def approval_contract(hashes: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "k3-two-endpoint-replacement-deployment-approval",
        "state": "approved",
        "decision": "APPROVE",
        "owner": OWNER,
        "owner_uid": OWNER_UID,
        "bundle_path": str(BUNDLE),
        "bundle_hashes": dict(hashes),
        "plan_sha256": hashlib.sha256(canonical_bytes(batch_plan())).hexdigest(),
        "deployment_id": DEPLOYMENT_ID,
        "source_revision": SOURCE_REVISION,
        "source_tree": SOURCE_TREE,
        "model_revision": MODEL_REVISION,
        "no_existing_namespace_confirmed": True,
        "no_existing_scheduler_history_confirmed": True,
        "resource_risk_accepted": True,
    }


def validate_approval(hashes: Mapping[str, str]) -> tuple[str, dict[str, Any]]:
    expected = os.environ.get("EXPECTED_APPROVAL_SHA256", "")
    if SHA_RE.fullmatch(expected) is None:
        fail("approval_hash_environment")
    captured = stable_file(APPROVAL, expected_sha256=expected, mode=0o400, maximum=1 << 20)
    try:
        payload = json.loads(captured.raw)
    except (ValueError, json.JSONDecodeError) as error:
        raise DeploymentError("approval_json") from error
    if captured.raw != canonical_bytes(payload) or payload != approval_contract(hashes):
        fail("approval_contract")
    return captured.sha256, payload


def validate_consumed_owner_intent(
    *,
    intent_sha: str,
    route_policy_sha: str,
    expected_hashes: Mapping[str, str] | None = None,
    expected_approval_sha: str | None = None,
    expected_approval: Mapping[str, Any] | None = None,
    expected_model: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    intent, observed_sha = load_json_artifact(RUN_ROOT / "owner_intent.json")
    approval = intent.get("approval_payload")
    bundle_hashes = intent.get("bundle_hashes")
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "created_at",
        "approval_sha256",
        "approval_payload",
        "bundle_hashes",
        "plan",
        "route_policy_sha256",
        "explain_normalized_sha256",
        "model_provenance",
        "serving_runtime_manifests",
        "job_name",
        "job_comment",
    }
    bundle_keys = {
        "launcher",
        "controller",
        "plan",
        "readme",
        "tests",
        "builder",
        "runtime_zip",
        "python_runtime",
    }
    if (
        observed_sha != intent_sha
        or set(intent) != expected_keys
        or intent.get("schema_version") != 2
        or intent.get("kind") != "k3-tb4-v13-deployment-intent"
        or intent.get("state") != "armed"
        or not isinstance(intent.get("created_at"), str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", intent["created_at"]) is None
        or not isinstance(approval, dict)
        or not isinstance(bundle_hashes, dict)
        or set(bundle_hashes) != bundle_keys
        or any(not isinstance(value, str) or SHA_RE.fullmatch(value) is None for value in bundle_hashes.values())
        or not isinstance(intent.get("approval_sha256"), str)
        or SHA_RE.fullmatch(intent["approval_sha256"]) is None
        or hashlib.sha256(canonical_bytes(approval)).hexdigest() != intent["approval_sha256"]
        or approval != approval_contract(bundle_hashes)
        or intent.get("plan") != batch_plan()
        or intent.get("route_policy_sha256") != route_policy_sha
        or intent.get("explain_normalized_sha256") != EXPLAIN_NORMALIZED_SHA256
        or (expected_model is not None and intent.get("model_provenance") != dict(expected_model))
        or intent.get("serving_runtime_manifests") != SERVING_RUNTIME_MANIFESTS
        or intent.get("job_name") != JOB_NAME
        or not isinstance(intent.get("job_comment"), str)
        or re.fullmatch(re.escape(JOB_COMMENT_PREFIX) + r"[0-9a-f]{20}", intent["job_comment"]) is None
        or (expected_hashes is not None and bundle_hashes != dict(expected_hashes))
        or (expected_approval_sha is not None and intent["approval_sha256"] != expected_approval_sha)
        or (expected_approval is not None and approval != dict(expected_approval))
    ):
        fail("owner_intent_binding")
    return intent


def sealed_memfd(name: str, raw: bytes, mode: int = 0o400) -> int:
    descriptor = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                fail("memfd_write")
            view = view[count:]
        os.fchmod(descriptor, mode)
        seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            fail("memfd_seals")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@dataclass
class ServeAPI:
    deploy: ModuleType
    stop: ModuleType
    common: ModuleType
    coord_client: ModuleType
    yaml: ModuleType
    runtime_fd: int
    runtime_path: str
    baseline_modules: frozenset[str]


def load_serve_api(runtime_raw: bytes) -> ServeAPI:
    descriptor = sealed_memfd("k3-redeploy-runtime", runtime_raw)
    flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
    fcntl.fcntl(descriptor, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)
    runtime_path = f"/proc/self/fd/{descriptor}"
    initial_path = tuple(sys.path)
    allowed = {
        str(PYTHON_RUNTIME_ROOT / "lib/python312.zip"),
        str(PYTHON_STDLIB),
        str(PYTHON_STDLIB / "lib-dynload"),
    }
    if set(initial_path) != allowed or len(initial_path) != 3:
        os.close(descriptor)
        fail("stdlib_path")
    baseline = frozenset(sys.modules)
    sys.path.insert(0, runtime_path)
    try:
        deploy = importlib.import_module("serve_api_v2.cli.deploy")
        stop = importlib.import_module("serve_api_v2.cli.stop")
        common = importlib.import_module("serve_api_v2.cli._common")
        coord_client = importlib.import_module("serve_api_v2.coord_client")
        yaml = importlib.import_module("yaml")
    except BaseException:
        sys.path[:] = list(initial_path)
        os.close(descriptor)
        raise
    common.V2_DIR = SERVE_PACKAGE
    deploy.V2_DIR = SERVE_PACKAGE
    return ServeAPI(deploy, stop, common, coord_client, yaml, descriptor, runtime_path, baseline)


def validate_import_origins(api: ServeAPI) -> None:
    for name in set(sys.modules) - set(api.baseline_modules):
        module = sys.modules.get(name)
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if origin in {None, "built-in", "frozen"}:
            continue
        if not isinstance(origin, str):
            fail("module_origin")
        if origin.startswith(api.runtime_path + "/"):
            continue
        try:
            Path(origin).resolve(strict=True).relative_to(PYTHON_STDLIB)
        except (OSError, ValueError) as error:
            raise DeploymentError("module_origin") from error


def close_serve_api(api: ServeAPI) -> None:
    sys.path[:] = [path for path in sys.path if path != api.runtime_path]
    for name in set(sys.modules) - set(api.baseline_modules):
        module = sys.modules.get(name)
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if isinstance(origin, str) and origin.startswith(api.runtime_path + "/"):
            sys.modules.pop(name, None)
    os.close(api.runtime_fd)


def normalized_spec(spec_raw: bytes, yaml_module: ModuleType) -> tuple[str, dict[str, Any]]:
    try:
        payload = yaml_module.safe_load(spec_raw)
    except Exception as error:
        raise DeploymentError("spec_parse") from error
    if not isinstance(payload, dict) or set(payload) != {"metadata", "spec"}:
        fail("spec_schema")
    metadata = payload.get("metadata")
    spec = payload.get("spec")
    if not isinstance(metadata, dict) or not isinstance(spec, dict):
        fail("spec_schema")
    applied_at = metadata.pop("applied_at", None)
    if (
        not isinstance(applied_at, str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", applied_at) is None
    ):
        fail("spec_timestamp")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return digest, payload


def validate_spec(api: ServeAPI, *, final: bool) -> tuple[str, str]:
    captured = stable_file(DEPLOYMENT_ROOT / "spec.yaml", mode=0o644, maximum=1 << 20)
    normalized, payload = normalized_spec(captured.raw, api.yaml)
    expected = FINAL_SPEC_NORMALIZED_SHA256 if final else INITIAL_SPEC_NORMALIZED_SHA256
    if normalized != expected:
        fail("spec_normalized")
    spec = payload["spec"]
    worker = spec.get("worker", {})
    engine = worker.get("engine", {})
    vllm = engine.get("vllm", {})
    extra = vllm.get("extra_args", {})
    proxy = spec.get("proxy", {})
    proxy_config = proxy.get("config", {})
    if (
        payload["metadata"] != {"applied_by": OWNER, "git_sha": SOURCE_REVISION}
        or spec.get("model") != MODEL_SELECTOR
        or spec.get("served_model_name") != MODEL
        or spec.get("cluster") != CLUSTER
        or spec.get("pixi_envs_dir") != str(PIXI_ENVS_ROOT)
        or spec.get("pixi_bin_dir") != str(PIXI_BIN_ROOT)
        or spec.get("fabric") != "ib"
        or spec.get("topology_segment") is not True
        or spec.get("num_endpoints") != 2
        or spec.get("lifetime_seconds") != 604_800
        or worker.get("kind") != "vllm"
        or worker.get("sbatch_params")
        != {
            "partition": "g3",
            "account": "ram",
            "qos": WORKER_QOS,
            "time_limit": JOB_TIME_LIMIT,
            "gpus_per_endpoint": 16,
            "cpus_per_task": 96,
            "mem": "900G",
            "gpus_per_node": 4,
            "time_min": "3-00:00:00",
            "exclude_nodes": list(WORKER_EXCLUDE_NODES),
        }
        or engine.get("model", {}).get("image") != IMAGE
        or vllm.get("max_model_len") != 1_048_576
        or extra.get("compilation-config") != PIECEWISE
        or spec.get("coordinator", {}).get("pixi_env") != COORDINATOR_ENV
        or proxy.get("kind") != "litellm"
        or proxy_config.get("pixi_env") != PROXY_ENV
        or proxy_config.get("request_timeout") != 43_200
        or proxy_config.get("num_retries") != 0
        or proxy_config.get("sticky") is not True
        or proxy_config.get("sticky_ttl") != 14_400
    ):
        fail("spec_contract")
    candidates = spec.get("checkpoint_candidates")
    model_path = engine.get("model", {}).get("path")
    if engine.get("model", {}).get("env") != WORKER_ENV:
        fail("spec_worker_runtime")
    if final:
        if candidates != [] or model_path != str(MODEL_ROOT):
            fail("spec_checkpoint")
    else:
        if not isinstance(candidates, list) or len(candidates) != 1 or model_path is not None:
            fail("spec_checkpoint")
        candidate = candidates[0]
        if (
            candidate.get("source_id") != "cluster-shared"
            or candidate.get("backend") != "cluster_filesystem"
            or candidate.get("location") != str(MODEL_ROOT)
            or candidate.get("load_format") != "runai_streamer"
        ):
            fail("spec_checkpoint")
    return captured.sha256, normalized


def observe_stable_spec(api: ServeAPI, *, final: bool, rounds: int = 2, interval: float = 1.0) -> tuple[str, str]:
    if rounds < 2:
        fail("spec_stability_rounds")
    prior: tuple[str, str] | None = None
    for index in range(rounds):
        current = validate_spec(api, final=final)
        if prior is not None and current != prior:
            fail("spec_changed_during_observation")
        prior = current
        if index + 1 < rounds and STOP_EVENT.wait(interval):
            raise LaunchCancelled()
    if prior is None:
        fail("spec_observation_missing")
    return prior


def normalize_explain(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise DeploymentError("explain_encoding") from error
    text = re.sub(r"\x1b\[[0-9;]*[mK]", "", text)
    lines = [line for line in text.splitlines() if not re.match(r"^\[INFO  [0-9:]*\]  CONFIG_DIR=", line)]
    return ("\n".join(lines) + "\n").encode()


def run_explain(api: ServeAPI) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = api.deploy.main([*DEPLOY_ARGS, "--explain"])
    raw = stdout.getvalue().encode()
    if result != 0 or len(raw) + len(stderr.getvalue().encode()) > OUTPUT_LIMIT:
        fail("explain_failed")
    normalized = normalize_explain(raw)
    digest = hashlib.sha256(normalized).hexdigest()
    required = (
        b"# fit-check: ok",
        b"proxy.config.request_timeout = 43200",
        b"proxy.config.num_retries = 0",
        b'vllm.extra_args.compilation-config = \'{"cudagraph_mode":"PIECEWISE"}\'',
        b"--qos=g3_lowest",
        b"--time-min=3-00:00:00",
        b"--gpus-per-endpoint=16",
        b"--endpoints=2",
        b"--worker-exclude-node=g3-136-221",
        b"--worker-exclude-node=g3-136-247",
        b"--worker-exclude-node=g3-136-251",
        b"--worker-exclude-node=g3-136-253",
    )
    if digest != EXPLAIN_NORMALIZED_SHA256 or any(item not in normalized for item in required):
        fail("explain_contract")
    return digest


def scheduler_env() -> dict[str, str]:
    return {
        "HOME": "/nonexistent",
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "SLURM_CLUSTER_NAME": CLUSTER,
    }


def derive_worker_qos_preemptors() -> tuple[str, ...]:
    qos = run_command(
        (
            "/usr/bin/sacctmgr",
            "-n",
            "-P",
            "show",
            "qos",
            "format=Name,Priority,Preempt",
        ),
        env=scheduler_env(),
    )
    try:
        rows: dict[str, tuple[int, tuple[str, ...]]] = {}
        for line in qos.stdout.decode("utf-8", "strict").splitlines():
            if not line:
                continue
            fields = line.split("|")
            if len(fields) != 3 or not fields[0] or fields[0] in rows or re.fullmatch(r"[0-9]+", fields[1]) is None:
                fail("qos_preempt_shape")
            rows[fields[0]] = (
                int(fields[1]),
                tuple(item for item in fields[2].split(",") if item),
            )
    except UnicodeDecodeError as error:
        raise DeploymentError("qos_preempt_encoding") from error
    if WORKER_QOS not in rows:
        fail("worker_qos_missing")
    priority, outbound = rows[WORKER_QOS]
    if priority != EXPECTED_WORKER_QOS_PRIORITY or outbound != EXPECTED_WORKER_QOS_OUTBOUND:
        fail("worker_qos_semantics_changed")
    inbound = tuple(sorted(name for name, (_priority, targets) in rows.items() if WORKER_QOS in targets))
    if inbound != EXPECTED_WORKER_QOS_PREEMPTORS or not inbound:
        fail("worker_qos_preemption_changed")
    config = run_command(
        ("/usr/bin/scontrol", "-M", CLUSTER, "show", "config"),
        env=scheduler_env(),
    )
    text = config.stdout.decode("utf-8", "strict")
    if (
        re.search(r"^PreemptType\s*= preempt/qos$", text, re.MULTILINE) is None
        or re.search(r"^PreemptMode\s*= REQUEUE$", text, re.MULTILINE) is None
    ):
        fail("cluster_preemption_changed")
    return inbound


def parse_scontrol(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as error:
        raise SchedulerUnavailable("scontrol_encoding") from error
    if not text or "\n" in text or "\r" in text or "\x00" in text:
        raise SchedulerUnavailable("scontrol_shape")
    matches = list(re.finditer(r"(?:^| )([A-Za-z][A-Za-z0-9_/:]*)=", text))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if key in result:
            raise SchedulerUnavailable("scontrol_duplicate")
        result[key] = text[start:end].rstrip()
    return result


def slurm_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", value)
    if match is None:
        fail("slurm_duration")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if hours > 23 or minutes > 59 or seconds > 59:
        fail("slurm_duration")
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


def show_job(job_id: str) -> dict[str, str]:
    if JOB_ID_RE.fullmatch(job_id) is None:
        fail("job_id")
    result = run_command(("/usr/bin/scontrol", "show", "job", "-o", job_id), env=scheduler_env())
    record = parse_scontrol(result.stdout)
    if record.get("JobId") != job_id:
        fail("job_identity")
    return record


def name_job_ids(name: str = JOB_NAME) -> set[str]:
    identifiers: set[str] = set()
    queue = run_command(
        ("/usr/bin/squeue", "-M", CLUSTER, "-h", "--name", name, "-o", "%A|%j"),
        env=scheduler_env(),
    )
    try:
        queue_lines = queue.stdout.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as error:
        raise SchedulerUnavailable("scheduler_query_encoding") from error
    for line in queue_lines:
        fields = line.strip().split("|")
        if len(fields) != 2:
            fail("scheduler_query_shape")
        if fields[1] == name:
            if JOB_ID_RE.fullmatch(fields[0]) is None:
                fail("scheduler_query_shape")
            identifiers.add(fields[0])
    accounting = run_command(
        (
            "/usr/bin/sacct",
            "-M",
            CLUSTER,
            "-n",
            "-X",
            "-S",
            HISTORY_START,
            "--name",
            name,
            "--format=JobIDRaw,JobName",
            "-P",
        ),
        env=scheduler_env(),
    )
    try:
        accounting_lines = accounting.stdout.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as error:
        raise SchedulerUnavailable("scheduler_query_encoding") from error
    for line in accounting_lines:
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split("|")
        if len(fields) not in {2, 3} or (len(fields) == 3 and fields[2]):
            fail("scheduler_query_shape")
        if fields[1] == name:
            if JOB_ID_RE.fullmatch(fields[0]) is None:
                fail("scheduler_query_shape")
            identifiers.add(fields[0])
    return identifiers


def prove_name_absent(rounds: int = 2, delay: float = 1.0) -> None:
    for index in range(rounds):
        if name_job_ids():
            fail("job_name_not_fresh")
        if index + 1 < rounds and STOP_EVENT.wait(delay):
            raise LaunchCancelled()


def coordinator_record(job_id: str) -> dict[str, str]:
    try:
        return show_job(job_id)
    except SchedulerUnavailable as error:
        code = sanitized_error_code(error)
        raise SchedulerUnavailable(f"coordinator_{code}") from error
    except DeploymentError as error:
        if sanitized_error_code(error) in {"job_id", "job_identity"}:
            raise DeploymentError("coordinator_job_id") from error
        raise


def validate_coordinator_static_fields(
    record: Mapping[str, str],
    job_id: str,
    token: str,
    *,
    allow_incomplete: bool = False,
) -> str | None:
    expected_command = str(DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch")
    coordinator_log = str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.coord.log")
    checks = (
        ("coordinator_job_name", "JobName", JOB_NAME),
        ("coordinator_user", "UserId", OWNER_RECORD),
        ("coordinator_comment", "Comment", token),
        ("coordinator_command", "Command", expected_command),
        ("coordinator_workdir", "WorkDir", str(SERVE_ROOT)),
        ("coordinator_account", "Account", "everyone"),
        ("coordinator_qos", "QOS", "cpu_x86_lowest"),
        ("coordinator_partition", "Partition", "cpu_x86"),
        ("coordinator_time_limit", "TimeLimit", JOB_TIME_LIMIT),
        ("coordinator_stdout", "StdOut", coordinator_log),
        ("coordinator_stderr", "StdErr", coordinator_log),
        ("coordinator_requeue", "Requeue", "0"),
    )
    incomplete: str | None = None
    for code, field, expected in checks:
        actual = record.get(field)
        if actual == expected:
            continue
        if allow_incomplete and actual in SLURM_NULLISH:
            if incomplete is None:
                incomplete = code
        else:
            fail(code)
    if record.get("Restarts") not in {None, "0"}:
        fail("coordinator_restarts")
    return incomplete


def parse_coordinator_req_tres(record: Mapping[str, str], *, allow_incomplete: bool) -> str | None:
    raw = record.get("ReqTRES")
    if raw in SLURM_NULLISH:
        if allow_incomplete:
            return "coordinator_req_tres"
        fail("coordinator_req_tres")
    assert raw is not None
    parsed: dict[str, str] = {}
    for item in raw.split(","):
        if item.count("=") != 1:
            fail("coordinator_req_tres")
        key, value = item.split("=", 1)
        if (
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_/:.-]*", key) is None
            or not value
            or key in parsed
            or any(character.isspace() for character in value)
        ):
            fail("coordinator_req_tres")
        parsed[key] = value
    expected_tres = {"billing": "4", "cpu": "4", "mem": "16G", "node": "1"}
    if any(key not in expected_tres for key in parsed):
        fail("coordinator_req_tres")
    if parsed != expected_tres:
        fail("coordinator_req_tres")
    return None


def validate_started_coordinator_alloc_tres(record: Mapping[str, str], *, allow_incomplete: bool) -> str | None:
    raw = record.get("AllocTRES")
    if raw in SLURM_NULLISH:
        if allow_incomplete:
            return "coordinator_alloc_tres"
        fail("coordinator_alloc_tres")
    assert raw is not None
    parsed: dict[str, str] = {}
    for item in raw.split(","):
        if item.count("=") != 1:
            fail("coordinator_alloc_tres")
        key, value = item.split("=", 1)
        if (
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_/:.-]*", key) is None
            or not value
            or key in parsed
            or any(character.isspace() for character in value)
        ):
            fail("coordinator_alloc_tres")
        parsed[key] = value
    if parsed != {"billing": "4", "cpu": "4", "mem": "16G", "node": "1"}:
        fail("coordinator_alloc_tres")
    return None


def semantic_singleton(value: str | None, expected: int) -> bool:
    target = str(expected)
    return value in {target, f"{target}-{target}"}


def validate_coordinator_allocation(
    record: Mapping[str, str], *, allow_incomplete: bool, allow_zero_to_one: bool = False
) -> str | None:
    nodes = record.get("NumNodes")
    if not semantic_singleton(nodes, 1):
        incomplete_nodes = set(SLURM_NULLISH) | {"0"}
        if allow_zero_to_one:
            incomplete_nodes.add("0-1")
        if allow_incomplete and nodes in incomplete_nodes:
            node_incomplete = "coordinator_nodes"
        else:
            fail("coordinator_nodes")
    else:
        node_incomplete = None
    if not semantic_singleton(record.get("NumCPUs"), 4):
        fail("coordinator_cpus")
    return node_incomplete


def validate_held_envelope(record: Mapping[str, str]) -> str | None:
    checks = (
        ("coordinator_held_state", record.get("JobState", "").split("+")[0], "PENDING"),
        ("coordinator_held_priority", record.get("Priority"), "0"),
        ("coordinator_held_eligible", record.get("EligibleTime"), "Unknown"),
    )
    for code, actual, expected in checks:
        if actual != expected:
            fail(code)
    allocated = record.get("AllocTRES")
    if allocated in {"", "None", "(null)"}:
        return None
    if allocated in {None, "Unknown"}:
        return "coordinator_alloc_tres"
    else:
        fail("coordinator_alloc_tres")


def validate_released_state(record: Mapping[str, str], *, allow_incomplete: bool) -> str | None:
    state = record.get("JobState", "").split("+")[0]
    if state in TERMINAL_STATES:
        fail("coordinator_terminal_after_release")
    if state not in {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING"}:
        if allow_incomplete and state in SLURM_NULLISH:
            return "coordinator_release_state"
        fail("coordinator_release_state")
    if state != "PENDING":
        return validate_started_coordinator_alloc_tres(record, allow_incomplete=allow_incomplete)
    reason = record.get("Reason")
    priority = record.get("Priority")
    eligible = record.get("EligibleTime")
    incomplete: str | None = None
    allocated = record.get("AllocTRES")
    if allocated not in {"", "None", "(null)"}:
        if allow_incomplete and allocated in {None, "Unknown"}:
            incomplete = "coordinator_alloc_tres"
        else:
            fail("coordinator_alloc_tres")
    if reason == "JobHeldUser" or reason in SLURM_NULLISH:
        if allow_incomplete:
            incomplete = "coordinator_still_held"
        else:
            fail("coordinator_still_held")
    if priority is None or re.fullmatch(r"[0-9]+", priority) is None:
        if allow_incomplete and priority in SLURM_NULLISH:
            incomplete = incomplete or "coordinator_release_priority"
        else:
            fail("coordinator_release_priority")
    elif int(priority) <= 0:
        if allow_incomplete:
            incomplete = incomplete or "coordinator_release_priority"
        else:
            fail("coordinator_release_priority")
    if eligible in SLURM_NULLISH:
        if allow_incomplete:
            incomplete = incomplete or "coordinator_release_eligible"
        else:
            fail("coordinator_release_eligible")
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", eligible or "") is None:
        fail("coordinator_release_eligible")
    return incomplete


def coordinator_identity(job_id: str, token: str, *, held: bool | None) -> dict[str, str]:
    record = coordinator_record(job_id)
    allow_incomplete = held is not False
    static_incomplete = validate_coordinator_static_fields(record, job_id, token, allow_incomplete=False)
    request_incomplete = parse_coordinator_req_tres(record, allow_incomplete=allow_incomplete)
    allocation_incomplete = validate_coordinator_allocation(
        record,
        allow_incomplete=allow_incomplete,
        allow_zero_to_one=held is True,
    )
    if held:
        envelope_incomplete = validate_held_envelope(record)
        reason_incomplete: str | None = None
        if record.get("Reason") != "JobHeldUser":
            if record.get("Reason") in SLURM_NULLISH:
                reason_incomplete = "coordinator_held_reason"
            else:
                fail("coordinator_held_reason")
        incomplete = next(
            (
                code
                for code in (
                    envelope_incomplete,
                    request_incomplete,
                    static_incomplete,
                    allocation_incomplete,
                    reason_incomplete,
                )
                if code is not None
            ),
            None,
        )
        if incomplete is not None:
            raise CoordinatorIdentityTransient(incomplete)
    else:
        released_incomplete = validate_released_state(record, allow_incomplete=held is None)
        incomplete = next(
            (
                code
                for code in (
                    released_incomplete,
                    request_incomplete,
                    static_incomplete,
                    allocation_incomplete,
                )
                if code is not None
            ),
            None,
        )
        if incomplete is not None:
            raise CoordinatorIdentityTransient(incomplete)
    return record


def coordinator_identity_projection(record: Mapping[str, str]) -> tuple[str | None, ...]:
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


def coordinator_static_identity(job_id: str, token: str) -> dict[str, str]:
    record = coordinator_record(job_id)
    validate_coordinator_static_fields(record, job_id, token)
    parse_coordinator_req_tres(record, allow_incomplete=False)
    validate_coordinator_allocation(record, allow_incomplete=False)
    return record


def stop_process_group(process: subprocess.Popen[bytes]) -> bool:
    group = process.pid
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, signum)
        except ProcessLookupError:
            break
        except OSError:
            return False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=0.2)
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return process.poll() is not None
    except OSError:
        return False
    return False


def bounded_submit(argv: Sequence[str], env: Mapping[str, str]) -> tuple[str, int, bytes, bool]:
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    try:
        process = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            cwd=str(SERVE_ROOT),
            start_new_session=True,
        )
    except OSError:
        return "exec_error", 127, b"", True
    if process.stdout is None or process.stderr is None:
        return "capture_error", 127, b"", stop_process_group(process)
    selector = selectors.DefaultSelector()
    streams = {
        process.stdout.fileno(): process.stdout,
        process.stderr.fileno(): process.stderr,
    }
    buffers = {descriptor: bytearray() for descriptor in streams}
    deadline = time.monotonic() + SUBMIT_TIMEOUT
    outcome = "completed"
    try:
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            if STOP_EVENT.is_set():
                outcome = "signal"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = "timeout"
                break
            for key, _mask in selector.select(min(remaining, 0.2)):
                descriptor = int(key.fd)
                try:
                    block = os.read(descriptor, 65536)
                except BlockingIOError:
                    continue
                if not block:
                    selector.unregister(descriptor)
                else:
                    buffers[descriptor].extend(block)
                    if sum(map(len, buffers.values())) > OUTPUT_LIMIT:
                        outcome = "oversize"
                        break
            if outcome == "oversize":
                break
        if outcome == "completed":
            returncode = process.wait(timeout=1)
            terminal = process.poll() is not None
        else:
            terminal = stop_process_group(process)
            returncode = process.returncode if process.returncode is not None else 127
    except BaseException:
        stop_process_group(process)
        raise
    finally:
        selector.close()
    captured = b"".join(bytes(buffers[key]) for key in sorted(buffers))
    return outcome, returncode, captured, terminal


def submit_held(argv: Sequence[str], export_env: Mapping[str, str], token: str) -> str:
    global SUBMITTED_DIRECT, SUBMITTED_JOB_ID
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    if SUBMITTED_JOB_ID is not None:
        fail("duplicate_submit_call")
    if CURRENT_API is None:
        fail("serve_api_not_loaded")
    expected_script = str(DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch")
    if not argv or argv[0] != "sbatch" or argv[-1] != expected_script:
        fail("coordinator_argv")
    expected_argv = (
        "sbatch",
        f"--job-name={JOB_NAME}",
        "--no-requeue",
        "--signal=B:USR1@600",
        "--partition=cpu_x86",
        "--account=everyone",
        "--qos=cpu_x86_lowest",
        f"--time={JOB_TIME_LIMIT}",
        "--cpus-per-task=4",
        "--gpus-per-task=0",
        "--mem=16G",
        f"--output={DEPLOYMENT_ROOT}/slurm_logs/%j.coord.log",
        f"--error={DEPLOYMENT_ROOT}/slurm_logs/%j.coord.log",
        "--export=ALL",
        expected_script,
    )
    if tuple(argv) != expected_argv:
        fail("coordinator_argv")
    expected_exports = {
        "DEPLOYMENT_DIR": str(DEPLOYMENT_ROOT),
        "DEPLOYMENT_ID": DEPLOYMENT_ID,
        "SERVE_API_V2_SRC_DIR": str(DEPLOYMENT_ROOT / "src/serve_api_v2"),
        "PIXI_ENVS_DIR": str(PIXI_ENVS_ROOT),
        "PIXI_BIN_DIR": str(PIXI_BIN_ROOT),
        "COORD_PIXI_ENV": COORDINATOR_ENV,
    }
    if dict(export_env) != expected_exports:
        fail("coordinator_environment")
    validate_source()
    model_provenance()
    validate_spec(CURRENT_API, final=False)
    if content_tree_manifest(DEPLOYMENT_ROOT / "src/serve_api_v2") != SNAPSHOT_MANIFEST:
        fail("deployment_snapshot")
    prove_name_absent(rounds=1, delay=0)
    command = [
        "/usr/bin/sbatch",
        "--parsable",
        "--hold",
        f"--comment={token}",
        "--nodes=1",
        *argv[1:],
    ]
    clean_env = {**SAFE_ENV, **REGISTRY_BINDING, **dict(export_env)}
    outcome, returncode, output, process_terminal = bounded_submit(command, clean_env)
    direct: str | None = None
    if outcome == "completed" and returncode == 0:
        text = output.decode("utf-8", "strict").strip()
        candidate = text.split(";", 1)[0]
        if JOB_ID_RE.fullmatch(candidate):
            direct = candidate
    candidates: set[str] = set()
    query_error = False
    identity_error: DeploymentError | None = None
    stable_identity_reads = 0
    last_identity: tuple[str | None, ...] | None = None
    identity_deadline = time.monotonic() + ((COORDINATOR_IDENTITY_ROUNDS - 1) * COORDINATOR_IDENTITY_INTERVAL)
    for index in range(COORDINATOR_IDENTITY_ROUNDS):
        try:
            candidates = name_job_ids()
        except SchedulerUnavailable:
            query_error = True
            candidates = set()
        if direct is not None:
            candidates.add(direct)
        if len(candidates) > 1:
            fail("submission_conflict")
        if len(candidates) == 1:
            job_id = next(iter(candidates))
            SUBMITTED_JOB_ID = job_id
            SUBMITTED_DIRECT = direct == job_id
            try:
                record = coordinator_identity(job_id, token, held=True)
            except (SchedulerUnavailable, CoordinatorIdentityTransient) as error:
                # The job returned by sbatch can precede its complete scontrol
                # record. Retry only query availability or the narrow
                # request/allocation/held-reason propagation window. Static
                # drift, runnable/terminal state, nonzero priority, and
                # eligible jobs fail immediately.
                identity_error = error
                stable_identity_reads = 0
                last_identity = None
            else:
                observed = coordinator_identity_projection(record)
                stable_identity_reads = stable_identity_reads + 1 if observed == last_identity else 1
                last_identity = observed
                identity_error = None
                if stable_identity_reads >= 2:
                    if outcome != "completed" or returncode != 0 or direct != job_id or not process_terminal:
                        fail("submission_ambiguous_reconciled")
                    return job_id
        remaining = identity_deadline - time.monotonic()
        if index + 1 >= COORDINATOR_IDENTITY_ROUNDS or remaining <= 0:
            break
        if STOP_EVENT.wait(min(COORDINATOR_IDENTITY_INTERVAL, remaining)):
            raise LaunchCancelled()
    if identity_error is not None:
        raise DeploymentError(sanitized_error_code(identity_error)) from identity_error
    if stable_identity_reads:
        fail("coordinator_identity_unstable")
    if query_error:
        raise SchedulerUnavailable("submission_query_unavailable")
    fail("submission_missing")


CURRENT_API: ServeAPI | None = None


def validate_cli_environment() -> None:
    allowed = set(SAFE_ENV) | {
        "EXPECTED_LAUNCHER_SHA256",
        "EXPECTED_CONTROLLER_SHA256",
        "EXPECTED_PLAN_SHA256",
        "EXPECTED_README_SHA256",
        "EXPECTED_TEST_SHA256",
        "EXPECTED_BUILDER_SHA256",
        "EXPECTED_RUNTIME_ZIP_SHA256",
        "EXPECTED_PYTHON_RUNTIME_TAR_SHA256",
        "EXPECTED_APPROVAL_SHA256",
        "K3_V13_PYTHON_RUNTIME_ROOT",
        "K3_V13_RUNTIME_TAR_SHA256",
        *REGISTRY_TLS_ENV_NAMES,
        "LAUNCHER_FD",
        "TMUX",
        "TMUX_PANE",
        "PWD",
        "SHLVL",
        "_",
    }
    if any(key not in allowed for key in os.environ) or any(
        os.environ.get(key) != value for key, value in SAFE_ENV.items()
    ):
        fail("environment")
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.no_user_site
        and sys.flags.safe_path
        and sys.dont_write_bytecode
    ):
        fail("python_flags")


def validate_tmux_ancestry() -> None:
    tmux = os.environ.get("TMUX", "").split(",", 1)[0]
    if tmux != TMUX_SOCKET or os.environ.get("TMUX_PANE") != TMUX_PANE:
        fail("tmux_environment")
    socket = Path(TMUX_SOCKET)
    metadata = socket.stat(follow_symlinks=False)
    if (
        socket.is_symlink()
        or not stat.S_ISSOCK(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != OWNER_UID
    ):
        fail("tmux_socket")
    result = run_command(
        (
            "/usr/bin/tmux",
            "-S",
            TMUX_SOCKET,
            "display-message",
            "-p",
            "-t",
            TMUX_PANE,
            "#{session_name}:#{window_name}.#{pane_index}|#{session_id}|#{session_created}|#{window_id}|#{pane_id}|#{pane_pid}",
        ),
        env={
            "HOME": "/nonexistent",
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "TMUX": os.environ["TMUX"],
            "TMUX_PANE": TMUX_PANE,
        },
        timeout=10,
    )
    expected = "|".join(
        (
            TMUX_IDENTITY,
            TMUX_SESSION_ID,
            TMUX_SESSION_CREATED,
            TMUX_WINDOW_ID,
            TMUX_PANE,
            TMUX_PANE_PID,
        )
    ).encode()
    if result.stdout.strip() != expected:
        fail("tmux_identity")
    current = os.getpid()
    for _ in range(128):
        if str(current) == TMUX_PANE_PID:
            return
        if current <= 1:
            break
        try:
            status = Path(f"/proc/{current}/status").read_text()
        except OSError as error:
            raise DeploymentError("tmux_ancestry") from error
        match = re.search(r"^PPid:\s+([0-9]+)$", status, re.MULTILINE)
        if match is None:
            fail("tmux_ancestry")
        current = int(match.group(1))
    fail("tmux_ancestry")


def inode_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def lock_directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


def lock_metadata_valid(value: os.stat_result) -> bool:
    return (
        stat.S_ISREG(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_uid == OWNER_UID
        and value.st_nlink == 1
        and value.st_size == 0
    )


def assert_paths_fresh(*, held_global_lock: GlobalLock | None = None) -> None:
    if DEPLOYMENT_ID in STALE_DEPLOYMENT_IDS or any(
        DEPLOYMENT_ID.startswith(stale + "-") or stale.startswith(DEPLOYMENT_ID + "-") for stale in STALE_DEPLOYMENT_IDS
    ):
        fail("stale_namespace_collision")
    for path in (RUN_ROOT, ROUTE_ROOT, OUTPUT_ROOT, DEPLOYMENT_ROOT):
        if path.exists() or path.is_symlink():
            fail("namespace_exists")
    if held_global_lock is None:
        if GLOBAL_LOCK.exists() or GLOBAL_LOCK.is_symlink():
            fail("namespace_exists")
    else:
        # The post-lock pass permits exactly the lock opened by this process;
        # its pathname and descriptor must still name the same private inode.
        validate_global_lock(held_global_lock)
    if REMOVED_ROOT.is_dir() and any(entry.name.startswith(f"{DEPLOYMENT_ID}-") for entry in REMOVED_ROOT.iterdir()):
        fail("archived_namespace_exists")
    prove_name_absent()


def validate_global_lock(lock: GlobalLock) -> None:
    try:
        directory = os.fstat(lock.directory_descriptor)
        named_directory = GLOBAL_LOCK.parent.lstat()
        opened = os.fstat(lock.descriptor)
        named = os.stat(GLOBAL_LOCK.name, dir_fd=lock.directory_descriptor, follow_symlinks=False)
    except OSError as error:
        raise DeploymentError("global_lock_identity") from error
    if (
        lock_directory_identity(directory) != lock.directory_identity
        or lock_directory_identity(named_directory) != lock.directory_identity
        or inode_identity(opened) != lock.identity
        or inode_identity(named) != lock.identity
        or not lock_metadata_valid(opened)
        or signature(opened) != signature(named)
    ):
        fail("global_lock_identity")


def terminal_lock_payload(outcome: str, error_code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "k3-tb4-v13-terminal-lock",
        "state": f"terminal_{outcome}",
        "deployment_id": DEPLOYMENT_ID,
        "error_code": error_code,
    }


def finalize_global_lock(lock: GlobalLock, *, outcome: str, error_code: str) -> TerminalLockProof:
    """Finalize the owned lock as a permanent tombstone; never unlink a pathname."""
    if (
        outcome not in {"commit_pending", "failure", "signal"}
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error_code) is None
    ):
        fail("global_lock_terminal_state")
    raw = canonical_bytes(terminal_lock_payload(outcome, error_code))
    failure: BaseException | None = None
    descriptor_closed = False
    try:
        validate_global_lock(lock)
        os.lseek(lock.descriptor, 0, os.SEEK_SET)
        os.ftruncate(lock.descriptor, 0)
        view = memoryview(raw)
        while view:
            count = os.write(lock.descriptor, view)
            if count <= 0:
                fail("global_lock_write")
            view = view[count:]
        os.fsync(lock.descriptor)
        opened = os.fstat(lock.descriptor)
        named = os.stat(GLOBAL_LOCK.name, dir_fd=lock.directory_descriptor, follow_symlinks=False)
        directory = os.fstat(lock.directory_descriptor)
        named_directory = GLOBAL_LOCK.parent.lstat()
        if (
            inode_identity(opened) != lock.identity
            or inode_identity(named) != lock.identity
            or not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != OWNER_UID
            or opened.st_nlink != 1
            or opened.st_size != len(raw)
            or signature(opened) != signature(named)
            or lock_directory_identity(directory) != lock.directory_identity
            or lock_directory_identity(named_directory) != lock.directory_identity
            or os.pread(lock.descriptor, len(raw) + 1, 0) != raw
        ):
            fail("global_lock_identity")
        os.close(lock.descriptor)
        descriptor_closed = True
        captured = stable_file(GLOBAL_LOCK, mode=0o600, maximum=4096)
        if captured.raw != raw or captured.signature[:2] != lock.identity:
            fail("global_lock_terminal_verify")
        if (
            lock_directory_identity(os.fstat(lock.directory_descriptor)) != lock.directory_identity
            or lock_directory_identity(GLOBAL_LOCK.parent.lstat()) != lock.directory_identity
        ):
            fail("global_lock_directory")
    except BaseException as error:
        failure = error
    finally:
        close_failure: OSError | None = None
        if not descriptor_closed:
            try:
                os.close(lock.descriptor)
            except OSError as error:
                close_failure = error
        try:
            os.close(lock.directory_descriptor)
        except OSError as error:
            close_failure = error
        if failure is None and close_failure is not None:
            failure = close_failure
    if failure is not None:
        if isinstance(failure, DeploymentError):
            raise failure
        raise DeploymentError("global_lock_finalize") from failure
    return TerminalLockProof(
        sha256=hashlib.sha256(raw).hexdigest(),
        device=lock.identity[0],
        inode=lock.identity[1],
    )


def acquire_global_lock() -> GlobalLock:
    directory_descriptor = -1
    descriptor = -1
    lock: GlobalLock | None = None
    try:
        before = GLOBAL_LOCK.parent.lstat()
        if (
            GLOBAL_LOCK.parent.is_symlink()
            or not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != OWNER_UID
        ):
            fail("global_lock_directory")
        directory_descriptor = os.open(
            GLOBAL_LOCK.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        directory = os.fstat(directory_descriptor)
        directory_identity = lock_directory_identity(directory)
        if directory_identity != lock_directory_identity(before):
            fail("global_lock_directory")
        try:
            descriptor = os.open(
                GLOBAL_LOCK.name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_descriptor,
            )
        except OSError as error:
            if error.errno == errno.EEXIST:
                raise DeploymentError("global_lock_exists") from error
            raise DeploymentError("global_lock_create") from error
        opened = os.fstat(descriptor)
        lock = GlobalLock(
            descriptor=descriptor,
            directory_descriptor=directory_descriptor,
            identity=inode_identity(opened),
            directory_identity=directory_identity,
        )
        validate_global_lock(lock)
        os.fsync(directory_descriptor)
        directory_event = signature(os.fstat(directory_descriptor))
        if signature(GLOBAL_LOCK.parent.lstat()) != directory_event:
            fail("global_lock_directory_event")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise DeploymentError("global_lock_busy") from error
        validate_global_lock(lock)
        return lock
    except BaseException as primary:
        if lock is not None:
            try:
                finalize_global_lock(
                    lock,
                    outcome="signal" if isinstance(primary, LaunchCancelled) else "failure",
                    error_code=sanitized_error_code(primary),
                )
            except BaseException as release_error:
                release_error.add_note("global lock acquisition cleanup failed")
                raise release_error from primary
        else:
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            if directory_descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(directory_descriptor)
        raise


def publish_exclusive(directory: Path, name: str, payload: Mapping[str, Any], mode: int = 0o400) -> str:
    raw = canonical_bytes(dict(payload))
    if not name or name != Path(name).name:
        fail("publish_name")
    directory_fd = -1
    try:
        before = directory.lstat()
        if (
            directory.is_symlink()
            or not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != OWNER_UID
        ):
            fail("publish_directory")
        directory_fd = os.open(
            directory,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        opened = os.fstat(directory_fd)
        if signature(before) != signature(opened):
            fail("publish_directory_race")
    except DeploymentError:
        if directory_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(directory_fd)
        raise
    except OSError as error:
        if directory_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(directory_fd)
        raise DeploymentError("publish_directory") from error
    temporary = f".{name}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                fail("publish_write")
            view = view[count:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        written = os.fstat(descriptor)
        os.close(descriptor)
        descriptor = -1
        named_temporary = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
        if signature(named_temporary) != signature(written):
            fail("publish_temporary_race")
        os.link(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        linked_source = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
        linked_target = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if inode_identity(linked_source) != inode_identity(written) or signature(linked_source) != signature(
            linked_target
        ):
            fail("publish_link_race")
        os.unlink(temporary, dir_fd=directory_fd)
        try:
            os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            fail("publish_temporary_cleanup")
        target_fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=directory_fd)
        try:
            target = os.fstat(target_fd)
            observed = os.pread(target_fd, len(raw) + 1, 0)
            named_target = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        finally:
            os.close(target_fd)
        if (
            not stat.S_ISREG(target.st_mode)
            or stat.S_IMODE(target.st_mode) != mode
            or target.st_uid != OWNER_UID
            or target.st_nlink != 1
            or inode_identity(target) != inode_identity(written)
            or signature(named_target) != signature(target)
            or observed != raw
        ):
            fail("publish_verify")
        os.fsync(directory_fd)
        if (
            signature(os.fstat(directory_fd))[:6] != signature(opened)[:6]
            or signature(directory.lstat())[:6] != signature(opened)[:6]
            or signature(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) != signature(target)
        ):
            fail("publish_directory_race")
    except BaseException:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        # Failure retains any temporary/final artifact. The fresh namespace is
        # then poisoned instead of deleting a pathname that another process
        # could have replaced.
        raise
    finally:
        with contextlib.suppress(OSError):
            os.close(directory_fd)
    return hashlib.sha256(raw).hexdigest()


def commit_marker_absent() -> bool:
    """A failed attempt is non-promoting exactly when no final marker exists."""
    try:
        COMMIT_MARKER.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def validate_status(payload: Any, coordinator_job: str) -> tuple[list[str], str]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 4:
        fail("status_schema")
    summary = payload.get("endpoints_summary")
    coord = payload.get("coord")
    proxy = payload.get("proxy")
    spec = payload.get("spec")
    endpoints = payload.get("endpoints")
    if (
        payload.get("deployment_id") != DEPLOYMENT_ID
        or payload.get("phase") != "serving"
        or summary != {"desired": 2, "ready": 2, "pending": 0, "running_not_ready": 0}
        or not isinstance(coord, dict)
        or coord.get("jobid") != coordinator_job
        or not isinstance(coord.get("ticks_completed"), int)
        or isinstance(coord.get("ticks_completed"), bool)
        or coord["ticks_completed"] < 1
        or not isinstance(spec, dict)
        or spec.get("model") != MODEL_SELECTOR
        or spec.get("served_model_name") != MODEL
        or spec.get("num_endpoints_desired") != 2
        or spec.get("gpu_partition") != "g3"
        or spec.get("account") != "ram"
        or spec.get("qos") != WORKER_QOS
        or spec.get("gpus_per_endpoint") != 16
        or not isinstance(endpoints, list)
        or len(endpoints) != 2
        or not isinstance(proxy, dict)
    ):
        fail("status_contract")
    workers: list[str] = []
    routes: set[tuple[str, int]] = set()
    for endpoint in endpoints:
        host = endpoint.get("host") if isinstance(endpoint, dict) else None
        port = endpoint.get("port") if isinstance(endpoint, dict) else None
        if (
            not isinstance(endpoint, dict)
            or JOB_ID_RE.fullmatch(str(endpoint.get("jobid", ""))) is None
            or endpoint.get("slurm_state") != "RUNNING"
            or endpoint.get("sub_state") != "ready"
            or not isinstance(host, str)
            or not host
            or not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65_535
        ):
            fail("status_endpoint")
        workers.append(str(endpoint["jobid"]))
        routes.add((host, port))
    proxy_job = str(proxy.get("jobid", ""))
    extras = proxy.get("extras")
    if (
        JOB_ID_RE.fullmatch(proxy_job) is None
        or proxy.get("slurm_state") != "RUNNING"
        or not isinstance(proxy.get("url"), str)
        or not proxy["url"].startswith("http://")
        or not isinstance(extras, dict)
        or set(extras) != {"proxy_type", "prometheus_port", "sticky", "sticky_ttl", "redis_port"}
        or extras.get("proxy_type") != "litellm"
        or extras.get("sticky") is not True
        or extras.get("sticky_ttl") != 14_400
        or any(
            not isinstance(extras.get(key), int) or isinstance(extras.get(key), bool) or not 1 <= extras[key] <= 65_535
            for key in ("prometheus_port", "redis_port")
        )
    ):
        fail("status_proxy")
    if len(set(workers)) != 2 or len(routes) != 2 or proxy_job in workers:
        fail("status_job_ids")
    return sorted(workers, key=int), proxy_job


def service_job_identity(job_id: str, role: str) -> dict[str, str]:
    record = show_job(job_id)
    state = record.get("JobState", "").split("+")[0]
    if role == "worker":
        expected = {
            "JobName": f"{DEPLOYMENT_ID}-ep",
            "Account": "ram",
            "QOS": WORKER_QOS,
            "Partition": "g3",
            "ExcNodeList": ",".join(WORKER_EXCLUDE_NODES),
            "TimeMin": "3-00:00:00",
            "Command": str(DEPLOYMENT_ROOT / "src/serve_api_v2/worker/worker.sbatch"),
            "StdOut": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.worker.log"),
            "StdErr": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.worker.log"),
        }
    elif role == "proxy":
        expected = {
            "JobName": f"{DEPLOYMENT_ID}-proxy",
            "Account": "everyone",
            "QOS": "cpu_x86_lowest",
            "Partition": "cpu_x86",
            "TimeLimit": JOB_TIME_LIMIT,
            "Command": str(DEPLOYMENT_ROOT / "src/serve_api_v2/proxy/proxy.sbatch"),
            "StdOut": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.proxy.log"),
            "StdErr": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.proxy.log"),
        }
    else:
        fail("service_role")
    if (
        record.get("UserId") != OWNER_RECORD
        or state != "RUNNING"
        or record.get("WorkDir") != str(SERVE_ROOT)
        or record.get("Requeue") != "0"
        or record.get("Restarts") not in {None, "0"}
        or any(record.get(key) != value for key, value in expected.items())
        or (role == "worker" and not semantic_singleton(record.get("NumNodes"), 4))
        or (role == "worker" and not semantic_singleton(record.get("NumCPUs"), 384))
        or (role == "proxy" and not semantic_singleton(record.get("NumNodes"), 1))
        or (role == "proxy" and not semantic_singleton(record.get("NumCPUs"), 8))
        or (role == "worker" and not 43_200 <= slurm_duration_seconds(record.get("TimeLimit", "")) <= 604_800)
    ):
        fail("service_job_identity")
    return record


def validate_standby_job(standby: str, primary_job: str) -> dict[str, str]:
    record = show_job(standby)
    dependency = record.get("Dependency", "")
    coordinator_log = str(DEPLOYMENT_ROOT / f"slurm_logs/{standby}.coord.log")
    try:
        request_incomplete = parse_coordinator_req_tres(record, allow_incomplete=True)
    except DeploymentError as error:
        raise DeploymentError("coordinator_standby_req_tres") from error
    try:
        allocation_incomplete = validate_coordinator_allocation(record, allow_incomplete=True, allow_zero_to_one=True)
    except DeploymentError as error:
        code = sanitized_error_code(error)
        mapped = {
            "coordinator_nodes": "coordinator_standby_nodes",
            "coordinator_cpus": "coordinator_standby_cpus",
        }.get(code, "coordinator_standby_identity")
        raise DeploymentError(mapped) from error
    allocated = record.get("AllocTRES")
    allocated_incomplete = allocated in {None, "Unknown"}
    reason = record.get("Reason")
    reason_incomplete = reason in SLURM_NULLISH
    dependency_incomplete = dependency in SLURM_NULLISH
    if (
        record.get("JobName") != JOB_NAME
        or record.get("UserId") != OWNER_RECORD
        or record.get("Command") != str(DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch")
        or record.get("WorkDir") != str(SERVE_ROOT)
        or record.get("Account") != "everyone"
        or record.get("QOS") != "cpu_x86_lowest"
        or record.get("Partition") != "cpu_x86"
        or (not allocated_incomplete and allocated not in {"", "None", "(null)"})
        or record.get("TimeLimit") != JOB_TIME_LIMIT
        or record.get("StdOut") != coordinator_log
        or record.get("StdErr") != coordinator_log
        or record.get("Requeue") != "0"
        or record.get("Restarts") not in {None, "0"}
        or record.get("JobState", "").split("+")[0] != "PENDING"
        or (not reason_incomplete and reason != "Dependency")
        or (
            not dependency_incomplete
            and re.fullmatch(rf"afternotok:{re.escape(primary_job)}(?:\(unfulfilled\))?", dependency) is None
        )
    ):
        fail("coordinator_standby_identity")
    incomplete = next(
        (
            code
            for code in (
                "coordinator_standby_req_tres" if request_incomplete else None,
                (
                    "coordinator_standby_nodes"
                    if allocation_incomplete == "coordinator_nodes"
                    else "coordinator_standby_cpus"
                    if allocation_incomplete == "coordinator_cpus"
                    else None
                ),
                "coordinator_standby_alloc_tres" if allocated_incomplete else None,
                "coordinator_standby_reason" if reason_incomplete else None,
                "coordinator_standby_dependency" if dependency_incomplete else None,
            )
            if code is not None
        ),
        None,
    )
    if incomplete is not None:
        raise CoordinatorIdentityTransient(incomplete)
    return record


def standby_identity(primary_job: str, wait_seconds: float = 300, *, cancel_on_signal: bool = True) -> str:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    stable_reads = 0
    last_projection: tuple[str | None, ...] | None = None
    last_standby: str | None = None
    identity_error: DeploymentError | None = None
    rounds = max(1, int(max(0.0, wait_seconds)) + 1)
    for index in range(rounds):
        if index and time.monotonic() > deadline:
            break
        try:
            identifiers = name_job_ids(JOB_NAME)
        except SchedulerUnavailable as error:
            identity_error = error
            stable_reads = 0
            last_projection = None
            last_standby = None
        else:
            if primary_job not in identifiers or len(identifiers) > 2:
                fail("coordinator_standby_cardinality")
            if len(identifiers) == 1:
                identity_error = None
                stable_reads = 0
                last_projection = None
                last_standby = None
            else:
                standby = next(iter(identifiers - {primary_job}))
                try:
                    record = validate_standby_job(standby, primary_job)
                except (SchedulerUnavailable, CoordinatorIdentityTransient) as error:
                    identity_error = error
                    stable_reads = 0
                    last_projection = None
                    last_standby = None
                else:
                    projection = (*coordinator_identity_projection(record), record.get("Dependency"))
                    stable_reads = stable_reads + 1 if standby == last_standby and projection == last_projection else 1
                    last_standby = standby
                    last_projection = projection
                    identity_error = None
                    if stable_reads >= 2:
                        return standby
        remaining = deadline - time.monotonic()
        if index + 1 >= rounds or remaining <= 0:
            break
        delay = min(1.0, remaining)
        if cancel_on_signal:
            if STOP_EVENT.wait(delay):
                raise LaunchCancelled()
        else:
            time.sleep(delay)
    if identity_error is not None:
        raise DeploymentError(sanitized_error_code(identity_error)) from identity_error
    if stable_reads:
        fail("coordinator_standby_identity_unstable")
    fail("coordinator_standby_missing")


def cleanup_successor_identity(job_id: str, primary_job: str) -> dict[str, str]:
    record = coordinator_record(job_id)
    coordinator_log = str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.coord.log")
    expected = {
        "JobName": JOB_NAME,
        "UserId": OWNER_RECORD,
        "Command": str(DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch"),
        "WorkDir": str(SERVE_ROOT),
        "Account": "everyone",
        "QOS": "cpu_x86_lowest",
        "Partition": "cpu_x86",
        "TimeLimit": JOB_TIME_LIMIT,
        "StdOut": coordinator_log,
        "StdErr": coordinator_log,
        "Requeue": "0",
    }
    if any(record.get(key) != value for key, value in expected.items()) or record.get("Restarts") not in {None, "0"}:
        fail("coordinator_cleanup_identity")
    request_incomplete = parse_coordinator_req_tres(record, allow_incomplete=True)
    state = record.get("JobState", "").split("+")[0]
    allocation_incomplete: str | None = None
    allocated_incomplete: str | None = None
    reason_incomplete: str | None = None
    dependency_incomplete: str | None = None
    if state == "PENDING" and record.get("Reason") in SLURM_NULLISH:
        reason_incomplete = "coordinator_cleanup_reason"
        dependency = record.get("Dependency", "")
        if dependency in SLURM_NULLISH:
            dependency_incomplete = "coordinator_standby_dependency"
        elif re.fullmatch(rf"afternotok:{re.escape(primary_job)}(?:\(unfulfilled\))?", dependency) is None:
            fail("coordinator_cleanup_dependency")
        allocation_incomplete = validate_coordinator_allocation(record, allow_incomplete=True, allow_zero_to_one=True)
        if record.get("AllocTRES") not in {"", "None", "(null)"}:
            if record.get("AllocTRES") in {None, "Unknown"}:
                allocated_incomplete = "coordinator_standby_alloc_tres"
            else:
                fail("coordinator_alloc_tres")
    elif state == "PENDING" and record.get("Reason") == "Dependency":
        dependency = record.get("Dependency", "")
        if re.fullmatch(rf"afternotok:{re.escape(primary_job)}(?:\(unfulfilled\))?", dependency) is None:
            if dependency in SLURM_NULLISH:
                dependency_incomplete = "coordinator_standby_dependency"
            else:
                fail("coordinator_cleanup_dependency")
        allocation_incomplete = validate_coordinator_allocation(record, allow_incomplete=True, allow_zero_to_one=True)
        if record.get("AllocTRES") not in {"", "None", "(null)"}:
            if record.get("AllocTRES") in {None, "Unknown"}:
                allocated_incomplete = "coordinator_standby_alloc_tres"
            else:
                fail("coordinator_alloc_tres")
    elif state == "PENDING":
        allocation_incomplete = validate_coordinator_allocation(record, allow_incomplete=True, allow_zero_to_one=True)
        released_incomplete = validate_released_state(record, allow_incomplete=True)
        if released_incomplete is not None:
            allocated_incomplete = released_incomplete
    elif state in {"RUNNING", "CONFIGURING", "COMPLETING"}:
        allocation_incomplete = validate_coordinator_allocation(record, allow_incomplete=True)
        allocated_incomplete = validate_started_coordinator_alloc_tres(record, allow_incomplete=True)
    elif state in TERMINAL_STATES:
        validate_coordinator_allocation(record, allow_incomplete=True)
        allocated = record.get("AllocTRES")
        if allocated not in {"", "None", "(null)", None, "Unknown"}:
            validate_started_coordinator_alloc_tres(record, allow_incomplete=False)
    else:
        fail("coordinator_cleanup_state")
    incomplete = next(
        (
            code
            for code in (
                request_incomplete,
                allocation_incomplete,
                allocated_incomplete,
                reason_incomplete,
                dependency_incomplete,
            )
            if code is not None
        ),
        None,
    )
    if incomplete is not None:
        raise CoordinatorIdentityTransient(incomplete)
    return record


def bind_cleanup_successor(job_id: str, primary_job: str, *, wait_seconds: float = 30) -> dict[str, str]:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    rounds = max(1, int(max(0.0, wait_seconds)) + 1)
    stable_reads = 0
    last_projection: tuple[str | None, ...] | None = None
    last_record: dict[str, str] | None = None
    identity_error: DeploymentError | None = None
    for index in range(rounds):
        if index and time.monotonic() > deadline:
            break
        try:
            record = cleanup_successor_identity(job_id, primary_job)
        except (SchedulerUnavailable, CoordinatorIdentityTransient) as error:
            identity_error = error
            stable_reads = 0
            last_projection = None
            last_record = None
        else:
            projection = (*coordinator_identity_projection(record), record.get("Dependency"))
            stable_reads = stable_reads + 1 if projection == last_projection else 1
            last_projection = projection
            last_record = record
            identity_error = None
            if stable_reads >= 2:
                return record
        remaining = deadline - time.monotonic()
        if index + 1 >= rounds or remaining <= 0:
            break
        time.sleep(min(1.0, remaining))
    if identity_error is not None:
        code = sanitized_error_code(identity_error)
        if isinstance(identity_error, SchedulerUnavailable):
            raise SchedulerUnavailable(code) from identity_error
        raise CoordinatorIdentityTransient(code) from identity_error
    if last_record is not None:
        raise CoordinatorIdentityTransient("coordinator_cleanup_identity_unstable")
    raise CoordinatorIdentityTransient("coordinator_cleanup_identity_unavailable")


def wait_for_serving(api: ServeAPI, coordinator_job: str) -> tuple[list[str], str, int]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if STOP_EVENT.wait(5):
            raise LaunchCancelled()
        payload = api.coord_client.fetch_status(DEPLOYMENT_ID, timeout=3.0)
        if payload is None:
            state = show_job(coordinator_job).get("JobState", "").split("+")[0]
            if state in TERMINAL_STATES:
                fail("coordinator_terminal_before_serving")
            continue
        if payload.get("phase") in {"failed", "expired"}:
            fail("deployment_terminal_before_serving")
        if payload.get("phase") != "serving":
            continue
        workers, proxy_job, ticks = (
            *validate_status(payload, coordinator_job),
            payload["coord"]["ticks_completed"],
        )
        return workers, proxy_job, ticks
    fail("deployment_readiness_timeout")


def begin_commit() -> set[signal.Signals]:
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    if STOP_EVENT.is_set():
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        raise LaunchCancelled()
    return previous


def end_commit(previous: set[signal.Signals]) -> None:
    signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def release_job(job_id: str, token: str) -> None:
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    coordinator_identity(job_id, token, held=True)
    result = run_command(("/usr/bin/scontrol", "release", job_id), env=scheduler_env(), check=False)
    if result.returncode != 0:
        fail("release_failed")
    deadline = time.monotonic() + 60
    stable_reads = 0
    last_projection: tuple[str | None, ...] | None = None
    while time.monotonic() < deadline:
        try:
            record = coordinator_identity(job_id, token, held=None)
        except (SchedulerUnavailable, CoordinatorIdentityTransient):
            stable_reads = 0
            last_projection = None
        else:
            observed = coordinator_identity_projection(record)
            stable_reads = stable_reads + 1 if observed == last_projection else 1
            last_projection = observed
            if stable_reads >= 2:
                return
        if STOP_EVENT.wait(1):
            raise LaunchCancelled()
    fail("release_unconfirmed")


def cancel_exact(job_id: str, token: str | None, direct: bool = False) -> bool:
    try:
        record = show_job(job_id)
    except SchedulerUnavailable:
        if direct:
            try:
                result = run_command(("/usr/bin/scancel", job_id), env=scheduler_env(), check=False)
                return result.returncode == 0 and prove_terminal(job_id)
            except DeploymentError:
                return False
        return False
    except DeploymentError:
        return False
    name = record.get("JobName", "")
    user = record.get("UserId", "")
    comment = record.get("Comment")
    expected_by_name = {
        JOB_NAME: {
            "Command": str(DEPLOYMENT_ROOT / "src/serve_api_v2/coordinator/coordinator.sbatch"),
            "Account": "everyone",
            "QOS": "cpu_x86_lowest",
            "Partition": "cpu_x86",
            "TimeLimit": JOB_TIME_LIMIT,
            "Requeue": "0",
            "StdOut": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.coord.log"),
            "StdErr": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.coord.log"),
        },
        f"{DEPLOYMENT_ID}-ep": {
            "Command": str(DEPLOYMENT_ROOT / "src/serve_api_v2/worker/worker.sbatch"),
            "Account": "ram",
            "QOS": WORKER_QOS,
            "Partition": "g3",
            "ExcNodeList": ",".join(WORKER_EXCLUDE_NODES),
            "TimeMin": "3-00:00:00",
            "Requeue": "0",
            "StdOut": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.worker.log"),
            "StdErr": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.worker.log"),
        },
        f"{DEPLOYMENT_ID}-proxy": {
            "Command": str(DEPLOYMENT_ROOT / "src/serve_api_v2/proxy/proxy.sbatch"),
            "Account": "everyone",
            "QOS": "cpu_x86_lowest",
            "Partition": "cpu_x86",
            "TimeLimit": JOB_TIME_LIMIT,
            "Requeue": "0",
            "StdOut": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.proxy.log"),
            "StdErr": str(DEPLOYMENT_ROOT / f"slurm_logs/{job_id}.proxy.log"),
        },
    }
    expected = expected_by_name.get(name)
    worker_time_ok = True
    coordinator_resources_ok = True
    if name == JOB_NAME:
        try:
            parse_coordinator_req_tres(record, allow_incomplete=False)
        except DeploymentError:
            coordinator_resources_ok = False
        coordinator_state = record.get("JobState", "").split("+")[0]
        coordinator_resources_ok = (
            coordinator_resources_ok
            and (
                semantic_singleton(record.get("NumNodes"), 1)
                or record.get("NumNodes") in SLURM_NULLISH
                or record.get("NumNodes") == "0"
                or (coordinator_state == "PENDING" and record.get("NumNodes") == "0-1")
            )
            and semantic_singleton(record.get("NumCPUs"), 4)
        )
    service_resources_ok = (
        name != f"{DEPLOYMENT_ID}-ep"
        or (semantic_singleton(record.get("NumNodes"), 4) and semantic_singleton(record.get("NumCPUs"), 384))
    ) and (
        name != f"{DEPLOYMENT_ID}-proxy"
        or (semantic_singleton(record.get("NumNodes"), 1) and semantic_singleton(record.get("NumCPUs"), 8))
    )
    if name == f"{DEPLOYMENT_ID}-ep":
        try:
            worker_seconds = slurm_duration_seconds(record.get("TimeLimit", ""))
        except DeploymentError:
            return False
        worker_time_ok = 43_200 <= worker_seconds <= 604_800
    if (
        user != OWNER_RECORD
        or expected is None
        or record.get("WorkDir") != str(SERVE_ROOT)
        or record.get("Restarts") not in {None, "0"}
        or any(record.get(key) != value for key, value in expected.items())
        or not coordinator_resources_ok
        or not service_resources_ok
        or not worker_time_ok
        or (name == JOB_NAME and token is not None and comment != token)
    ):
        return False
    try:
        result = run_command(("/usr/bin/scancel", job_id), env=scheduler_env(), check=False)
        if result.returncode != 0:
            return False
        return prove_terminal(job_id)
    except DeploymentError:
        return False


def prove_terminal(job_id: str) -> bool:
    stable = 0
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and stable < ZERO_ROUNDS:
        queue = run_command(
            ("/usr/bin/squeue", "-M", CLUSTER, "-h", "-j", job_id, "-o", "%A"),
            env=scheduler_env(),
            check=False,
        )
        accounting = run_command(
            (
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "-n",
                "-P",
                "-j",
                job_id,
                "--format=JobIDRaw,State",
            ),
            env=scheduler_env(),
            check=False,
        )
        if queue.returncode != 0 or accounting.returncode != 0:
            stable = 0
        else:
            try:
                queue_ids = {
                    line.strip() for line in queue.stdout.decode("utf-8", "strict").splitlines() if line.strip()
                }
                rows = [
                    line.strip().split("|")
                    for line in accounting.stdout.decode("utf-8", "strict").splitlines()
                    if line.strip()
                ]
            except UnicodeDecodeError:
                return False
            relevant = [parts for parts in rows if parts[0].split(".", 1)[0] == job_id]
            parent_seen = any(parts[0] == job_id for parts in relevant)
            if (
                not relevant
                or not parent_seen
                or job_id in queue_ids
                or any(len(parts) < 2 or parts[1].split("+")[0] not in TERMINAL_STATES for parts in relevant)
            ):
                stable = 0
            else:
                stable += 1
        if stable < ZERO_ROUNDS:
            time.sleep(ZERO_INTERVAL)
    return stable == ZERO_ROUNDS


def prove_queue_absent(job_id: str, rounds: int = 2) -> bool:
    if JOB_ID_RE.fullmatch(job_id) is None or rounds < 2:
        return False
    exact_names = (JOB_NAME, f"{DEPLOYMENT_ID}-ep", f"{DEPLOYMENT_ID}-proxy")
    for index in range(rounds):
        observed: set[str] = set()
        for name in exact_names:
            try:
                queue = run_command(
                    (
                        "/usr/bin/squeue",
                        "-M",
                        CLUSTER,
                        "-h",
                        "--user",
                        OWNER,
                        "--name",
                        name,
                        "-o",
                        "%A|%j|%u",
                    ),
                    env=scheduler_env(),
                    check=False,
                )
                lines = queue.stdout.decode("utf-8", "strict").splitlines()
            except (DeploymentError, UnicodeDecodeError):
                return False
            if queue.returncode != 0:
                return False
            for line in lines:
                fields = line.strip().split("|")
                if (
                    len(fields) != 3
                    or JOB_ID_RE.fullmatch(fields[0]) is None
                    or fields[1] != name
                    or fields[2] != OWNER
                ):
                    return False
                observed.add(fields[0])
        if job_id in observed:
            return False
        if index + 1 < rounds:
            time.sleep(1)
    return True


def archive_failed_namespace() -> bool:
    try:
        source = DEPLOYMENT_ROOT.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISDIR(source.st_mode) or source.st_uid != OWNER_UID or DEPLOYMENT_ROOT.is_symlink():
        return False
    descriptors: list[int] = []
    try:
        for path in (DEPLOYMENTS_ROOT, REMOVED_ROOT):
            before = path.lstat()
            if (
                path.is_symlink()
                or not stat.S_ISDIR(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o2775
                or before.st_uid != MODEL_OWNER_UID
                or before.st_gid != MODEL_OWNER_GID
            ):
                return False
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
            if signature(os.fstat(descriptor)) != signature(before):
                os.close(descriptor)
                return False
            descriptors.append(descriptor)
        source_fd, removed_fd = descriptors
        suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = f"{DEPLOYMENT_ID}-{suffix}-{os.getpid()}-failed-closed"
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if (
            renameat2(
                source_fd,
                DEPLOYMENT_ID.encode(),
                removed_fd,
                target.encode(),
                1,
            )
            != 0
        ):
            return False
        os.fsync(source_fd)
        os.fsync(removed_fd)
        try:
            os.stat(DEPLOYMENT_ID, dir_fd=source_fd, follow_symlinks=False)
            return False
        except FileNotFoundError:
            pass
        moved = os.stat(target, dir_fd=removed_fd, follow_symlinks=False)
        return signature(moved)[:6] == signature(source)[:6]
    except (AttributeError, OSError, TypeError):
        return False
    finally:
        for descriptor in descriptors:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def exact_deployment_stop(api: ServeAPI | None) -> dict[str, Any]:
    """Run the pinned stop implementation for this exact v13 namespace only."""
    try:
        status = DEPLOYMENT_ROOT.lstat()
    except FileNotFoundError:
        return {"attempted": False, "reason": "namespace_absent"}
    except OSError:
        return {"attempted": False, "reason": "namespace_unreadable"}
    stop_paths = None if api is None else getattr(api.stop, "paths", None)
    original_prune = None if stop_paths is None else getattr(stop_paths, "prune_removed_dir", None)
    if (
        api is None
        or not callable(original_prune)
        or DEPLOYMENT_ROOT.is_symlink()
        or not stat.S_ISDIR(status.st_mode)
        or status.st_uid != OWNER_UID
        or DEPLOYMENT_ROOT.resolve().parent != DEPLOYMENTS_ROOT.resolve()
        or getattr(api.stop, "COORD_DRAIN_TIMEOUT_S", None) != 60
        or getattr(api.stop, "CHILD_DRAIN_TIMEOUT_S", None) != 120
    ):
        return {"attempted": False, "reason": "stop_contract_unavailable"}
    clean = {
        **scheduler_env(),
        "USER": OWNER,
        "LOGNAME": OWNER,
        "V2_DEPLOYMENTS_ROOT": str(DEPLOYMENTS_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    previous = dict(os.environ)
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        stop_paths.prune_removed_dir = lambda _root: 0
        os.environ.clear()
        os.environ.update(clean)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = api.stop.main([DEPLOYMENT_ID])
    except BaseException as error:
        return {
            "attempted": True,
            "completed": False,
            "category": type(error).__name__,
        }
    finally:
        stop_paths.prune_removed_dir = original_prune
        os.environ.clear()
        os.environ.update(previous)
    out = stdout.getvalue().encode()
    err = stderr.getvalue().encode()
    if len(out) + len(err) > OUTPUT_LIMIT:
        return {"attempted": True, "completed": False, "category": "output_oversize"}
    if type(result) is not int:
        return {
            "attempted": True,
            "completed": False,
            "category": "stop_result_invalid",
            "stdout_sha256": hashlib.sha256(out).hexdigest(),
            "stderr_sha256": hashlib.sha256(err).hexdigest(),
        }
    if result != 0:
        return {
            "attempted": True,
            "completed": False,
            "category": "stop_nonzero",
            "returncode": result,
            "stdout_sha256": hashlib.sha256(out).hexdigest(),
            "stderr_sha256": hashlib.sha256(err).hexdigest(),
        }
    return {
        "attempted": True,
        "completed": True,
        "returncode": result,
        "stdout_sha256": hashlib.sha256(out).hexdigest(),
        "stderr_sha256": hashlib.sha256(err).hexdigest(),
    }


def cleanup(token: str, known: Sequence[str]) -> dict[str, Any]:
    candidates = set(known)
    bound_candidates = set(known)
    if SUBMITTED_JOB_ID is not None:
        candidates.add(SUBMITTED_JOB_ID)
        bound_candidates.add(SUBMITTED_JOB_ID)
    discovered: dict[str, set[str]] = {}
    query_unavailable = False
    identity_unavailable = False
    for name in (JOB_NAME, f"{DEPLOYMENT_ID}-ep", f"{DEPLOYMENT_ID}-proxy"):
        with contextlib.suppress(DeploymentError, SchedulerUnavailable):
            discovered[name] = name_job_ids(name)
        if name not in discovered:
            query_unavailable = True
    coordinators = discovered.get(JOB_NAME, set())
    coordinator_conflict = len(coordinators) > 2
    primary = SUBMITTED_JOB_ID
    successors = coordinators - ({primary} if primary is not None else set())
    if len(successors) > 1 or (successors and (not COORDINATOR_RELEASED or primary is None)):
        coordinator_conflict = True
    elif successors:
        standby = next(iter(successors))
        try:
            if primary in coordinators:
                try:
                    if standby_identity(primary, wait_seconds=30, cancel_on_signal=False) != standby:
                        fail("coordinator_standby_identity")
                except (DeploymentError, SchedulerUnavailable):
                    bind_cleanup_successor(standby, primary)
            else:
                bind_cleanup_successor(standby, primary)
        except (SchedulerUnavailable, CoordinatorIdentityTransient):
            identity_unavailable = True
        except DeploymentError:
            coordinator_conflict = True
        else:
            bound_candidates.add(standby)
    conflict = (
        coordinator_conflict
        or len(discovered.get(f"{DEPLOYMENT_ID}-ep", set())) > 2
        or len(discovered.get(f"{DEPLOYMENT_ID}-proxy", set())) > 1
        or sum(len(values) for values in discovered.values()) != len(set().union(*discovered.values()))
    )
    stop_result = exact_deployment_stop(CURRENT_API)
    for values in discovered.values():
        candidates.update(values)
    discovered_services = discovered.get(f"{DEPLOYMENT_ID}-ep", set()) | discovered.get(f"{DEPLOYMENT_ID}-proxy", set())
    if conflict and stop_result.get("completed") is not True:
        return {
            "deployment_stop": stop_result,
            "jobs_seen": sum(len(value) for value in discovered.values()),
            "jobs_terminal": 0,
            "all_terminal": False,
            "namespace_archived": False,
            "identity_conflict": True,
            "identity_unavailable": identity_unavailable,
            "query_unavailable": query_unavailable,
        }
    outcomes = {
        job: (
            True
            if stop_result.get("completed") is True and job in bound_candidates
            else prove_queue_absent(job)
            if stop_result.get("completed") is True
            else cancel_exact(
                job,
                token if job == SUBMITTED_JOB_ID else None,
                job == SUBMITTED_JOB_ID and SUBMITTED_DIRECT,
            )
            if job in bound_candidates or job in discovered_services
            else False
        )
        for job in sorted(candidates, key=int)
    }
    stable_sweeps = 0
    sweep_rounds = 0
    exact_names = (JOB_NAME, f"{DEPLOYMENT_ID}-ep", f"{DEPLOYMENT_ID}-proxy")
    while sweep_rounds < ZERO_ROUNDS and stable_sweeps < 2:
        sweep_rounds += 1
        observed: set[str] = set()
        observed_names: dict[str, str] = {}
        for name in exact_names:
            try:
                named = name_job_ids(name)
                observed.update(named)
                observed_names.update({job: name for job in named})
            except (DeploymentError, SchedulerUnavailable):
                query_unavailable = True
        late = observed - candidates
        if late:
            stable_sweeps = 0
            for job in sorted(late, key=int):
                if stop_result.get("completed") is True:
                    outcomes[job] = prove_queue_absent(job)
                elif observed_names.get(job) == JOB_NAME:
                    if SUBMITTED_JOB_ID is None or not COORDINATOR_RELEASED:
                        conflict = True
                        outcomes[job] = False
                    else:
                        try:
                            bind_cleanup_successor(job, SUBMITTED_JOB_ID)
                        except (SchedulerUnavailable, CoordinatorIdentityTransient):
                            identity_unavailable = True
                            outcomes[job] = False
                        except DeploymentError:
                            conflict = True
                            outcomes[job] = False
                        else:
                            bound_candidates.add(job)
                            outcomes[job] = cancel_exact(job, None, False)
                else:
                    outcomes[job] = cancel_exact(job, None, False)
            candidates.update(late)
        else:
            stable_sweeps += 1
        if stable_sweeps < 2:
            time.sleep(ZERO_INTERVAL)
    discovery_complete = not query_unavailable and stable_sweeps == 2
    all_terminal = discovery_complete and (bool(outcomes) and all(outcomes.values()) if candidates else True)
    archived = archive_failed_namespace() if all_terminal else False
    return {
        "deployment_stop": stop_result,
        "jobs_seen": len(candidates),
        "jobs_terminal": sum(outcomes.values()),
        "all_terminal": all_terminal,
        "namespace_archived": archived,
        "identity_conflict": conflict,
        "identity_unavailable": identity_unavailable,
        "query_unavailable": query_unavailable,
        "exact_name_sweep_rounds": sweep_rounds,
        "exact_name_sweep_stable_rounds": stable_sweeps,
    }


def signal_handler(_signum: int, _frame: Any) -> None:
    STOP_EVENT.set()


def run_deploy(api: ServeAPI, token: str) -> tuple[int, bytes, bytes]:
    global SUBMIT_ERROR_CODE
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    SUBMIT_ERROR_CODE = None
    original = api.deploy._sbatch_coordinator

    def held(s: Any, dep_dir: Path, deployment_id: str) -> str:
        global SUBMIT_ERROR_CODE
        argv, export_env = api.deploy.coordinator_sbatch_argv(s=s, dep_dir=dep_dir, deployment_id=deployment_id)
        try:
            return submit_held(argv, export_env, token)
        except DeploymentError as error:
            # deploy.main intentionally converts RuntimeError subclasses to a
            # generic return code. Retain only our allowlisted code out of band
            # so execute can report the exact fail-closed reason without raw
            # scheduler output.
            SUBMIT_ERROR_CODE = sanitized_error_code(error)
            raise

    api.deploy._sbatch_coordinator = held
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous = Path.cwd()
    try:
        os.chdir(SERVE_ROOT)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = api.deploy.main([*DEPLOY_ARGS, "--no-watch"])
    finally:
        os.chdir(previous)
        api.deploy._sbatch_coordinator = original
    if SUBMIT_ERROR_CODE is not None:
        raise DeploymentError(SUBMIT_ERROR_CODE)
    out = stdout.getvalue().encode()
    err = stderr.getvalue().encode()
    if len(out) + len(err) > OUTPUT_LIMIT:
        fail("deploy_output_oversize")
    return result, out, err


def route_policy_payload(preemptors: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "k3-tb4-v13-route-policy",
        "state": "armed",
        "deployment_id": DEPLOYMENT_ID,
        "model": MODEL,
        "desired_workers": 2,
        "source_revision": SOURCE_REVISION,
        "source_tree": SOURCE_TREE,
        "source_snapshot_manifest": SNAPSHOT_MANIFEST,
        "evaluator_revision": EVALUATOR_REVISION,
        "evaluator_tree": EVALUATOR_TREE,
        "evaluator_config_sha256": {path.name: digest for path, digest in EVAL_CONFIGS.items()},
        "evaluator_context_cap": EVALUATOR_CONTEXT_CAP,
        "worker_qos": WORKER_QOS,
        "worker_qos_priority": EXPECTED_WORKER_QOS_PRIORITY,
        "worker_qos_outbound_preempt_targets": list(EXPECTED_WORKER_QOS_OUTBOUND),
        "worker_qos_preemptible": WORKER_QOS_PREEMPTIBLE,
        "worker_qos_preemptors": list(preemptors),
        "worker_exclude_nodes": list(WORKER_EXCLUDE_NODES),
        "full_fleet_preemption_grace_seconds": PREEMPTION_GRACE_SECONDS,
        "full_fleet_preemption_wave_budget": PREEMPTION_WAVE_BUDGET,
        "full_fleet_preemption_window_seconds": PREEMPTION_WINDOW_SECONDS,
        "required_initial_observation": str(INITIAL_OBSERVATION),
        "required_resolved_binding": str(RESOLVED_BINDING),
        "required_launch_receipt": str(LAUNCH_RECEIPT),
        "required_readiness": str(READINESS),
        "required_route_binding": str(ROUTE_BINDING),
        "required_commit_marker": str(COMMIT_MARKER),
        "reserved_output_root": str(OUTPUT_ROOT),
        "smoke_requires_commit_marker": True,
    }


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("artifact_duplicate_key")
        result[key] = value
    return result


def load_json_artifact(path: Path) -> tuple[dict[str, Any], str]:
    captured = stable_file(path, mode=0o400, maximum=2 << 20)
    try:
        payload = json.loads(
            captured.raw,
            object_pairs_hook=reject_duplicate_json_keys,
            parse_constant=lambda _value: fail("artifact_json_constant"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeploymentError("artifact_json") from error
    if not isinstance(payload, dict):
        fail("artifact_json_root")
    return payload, captured.sha256


def validate_generation_artifact_graph(
    *,
    intent_sha: str,
    initial_sha: str,
    resolved_sha: str,
    launch_sha: str,
    route_policy_sha: str,
    coordinator: str,
    standby: str,
    workers: Sequence[str],
    proxy_job: str,
) -> tuple[str, str]:
    policy, observed_policy_sha = load_json_artifact(ROUTE_POLICY)
    initial, observed_initial_sha = load_json_artifact(INITIAL_OBSERVATION)
    resolved, observed_resolved_sha = load_json_artifact(RESOLVED_BINDING)
    launch, observed_launch_sha = load_json_artifact(LAUNCH_RECEIPT)
    if (
        observed_policy_sha != route_policy_sha
        or observed_initial_sha != initial_sha
        or observed_resolved_sha != resolved_sha
        or observed_launch_sha != launch_sha
        or policy != route_policy_payload(EXPECTED_WORKER_QOS_PREEMPTORS)
        or initial.get("state") != "stable_initial_spec_observed"
        or initial.get("deployment_id") != DEPLOYMENT_ID
        or initial.get("intent_sha256") != intent_sha
        or initial.get("route_policy_sha256") != route_policy_sha
        or initial.get("coordinator_job") != coordinator
        or initial.get("spec_normalized_sha256") != INITIAL_SPEC_NORMALIZED_SHA256
        or initial.get("stable_reads") != 2
        or resolved.get("state") != "resolved_spec_bound"
        or resolved.get("deployment_id") != DEPLOYMENT_ID
        or resolved.get("intent_sha256") != intent_sha
        or resolved.get("route_policy_sha256") != route_policy_sha
        or resolved.get("initial_observation_sha256") != initial_sha
        or resolved.get("coordinator_job") != coordinator
        or resolved.get("spec_normalized_sha256") != FINAL_SPEC_NORMALIZED_SHA256
        or resolved.get("source_revision") != SOURCE_REVISION
        or resolved.get("source_tree") != SOURCE_TREE
        or resolved.get("source_snapshot_manifest") != SNAPSHOT_MANIFEST
        or resolved.get("worker_qos") != WORKER_QOS
        or resolved.get("worker_qos_priority") != EXPECTED_WORKER_QOS_PRIORITY
        or resolved.get("worker_qos_outbound_preempt_targets") != list(EXPECTED_WORKER_QOS_OUTBOUND)
        or resolved.get("worker_qos_preemptible") is not True
        or resolved.get("worker_qos_preemptors") != list(EXPECTED_WORKER_QOS_PREEMPTORS)
        or resolved.get("worker_exclude_nodes") != list(WORKER_EXCLUDE_NODES)
        or launch.get("state") != "live_final_spec_bound"
        or launch.get("deployment_id") != DEPLOYMENT_ID
        or launch.get("intent_sha256") != intent_sha
        or launch.get("route_policy_sha256") != route_policy_sha
        or launch.get("initial_observation_sha256") != initial_sha
        or launch.get("resolved_binding_sha256") != resolved_sha
        or launch.get("coordinator_job") != coordinator
        or launch.get("coordinator_standby_job") != standby
        or launch.get("worker_jobs") != list(workers)
        or launch.get("proxy_job") != proxy_job
        or launch.get("spec_sha256") != resolved.get("spec_sha256")
        or launch.get("spec_normalized_sha256") != resolved.get("spec_normalized_sha256")
    ):
        fail("artifact_graph")
    return str(resolved["spec_sha256"]), str(resolved["spec_normalized_sha256"])


def validate_live_generation(
    api: ServeAPI,
    *,
    token: str,
    coordinator: str,
    standby: str,
    workers: Sequence[str],
    proxy_job: str,
    expected_spec_sha: str,
    expected_spec_normalized: str,
) -> int:
    spec_sha, spec_normalized = observe_stable_spec(api, final=True)
    if spec_sha != expected_spec_sha or spec_normalized != expected_spec_normalized:
        fail("live_spec_changed")
    status = api.coord_client.fetch_status(DEPLOYMENT_ID, timeout=3.0)
    observed_workers, observed_proxy = validate_status(status, coordinator)
    if observed_workers != list(workers) or observed_proxy != proxy_job:
        fail("live_generation_changed")
    coordinator_identity(coordinator, token, held=False)
    if standby_identity(coordinator, wait_seconds=1) != standby:
        fail("live_standby_changed")
    for job in workers:
        service_job_identity(job, "worker")
    service_job_identity(proxy_job, "proxy")
    return int(status["coord"]["ticks_completed"])


def produce_readiness(
    api: ServeAPI,
    *,
    token: str,
    intent_sha: str,
    initial_sha: str,
    resolved_sha: str,
    launch_sha: str,
    route_policy_sha: str,
    coordinator: str,
    standby: str,
    workers: Sequence[str],
    proxy_job: str,
) -> str:
    spec_sha, normalized = validate_generation_artifact_graph(
        intent_sha=intent_sha,
        initial_sha=initial_sha,
        resolved_sha=resolved_sha,
        launch_sha=launch_sha,
        route_policy_sha=route_policy_sha,
        coordinator=coordinator,
        standby=standby,
        workers=workers,
        proxy_job=proxy_job,
    )
    ticks = validate_live_generation(
        api,
        token=token,
        coordinator=coordinator,
        standby=standby,
        workers=workers,
        proxy_job=proxy_job,
        expected_spec_sha=spec_sha,
        expected_spec_normalized=normalized,
    )
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    readiness_sha = publish_exclusive(
        ROUTE_ROOT,
        READINESS.name,
        {
            "schema_version": 2,
            "kind": "k3-tb4-v13-readiness",
            "state": "staged_passed",
            "promotion_eligible": False,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "deployment_id": DEPLOYMENT_ID,
            "intent_sha256": intent_sha,
            "route_policy_sha256": route_policy_sha,
            "initial_observation_sha256": initial_sha,
            "resolved_binding_sha256": resolved_sha,
            "launch_receipt_sha256": launch_sha,
            "spec_sha256": spec_sha,
            "spec_normalized_sha256": normalized,
            "coordinator_job": coordinator,
            "coordinator_standby_job": standby,
            "worker_jobs": list(workers),
            "proxy_job": proxy_job,
            "coordinator_ticks_completed": ticks,
            "model_requests_sent": 0,
            "smoke_jobs_submitted": 0,
        },
    )
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    return readiness_sha


def consume_readiness(
    api: ServeAPI,
    *,
    token: str,
    readiness_sha: str,
    intent_sha: str,
    initial_sha: str,
    resolved_sha: str,
    launch_sha: str,
    route_policy_sha: str,
    coordinator: str,
    standby: str,
    workers: Sequence[str],
    proxy_job: str,
) -> str:
    readiness, observed_readiness_sha = load_json_artifact(READINESS)
    spec_sha, normalized = validate_generation_artifact_graph(
        intent_sha=intent_sha,
        initial_sha=initial_sha,
        resolved_sha=resolved_sha,
        launch_sha=launch_sha,
        route_policy_sha=route_policy_sha,
        coordinator=coordinator,
        standby=standby,
        workers=workers,
        proxy_job=proxy_job,
    )
    if (
        observed_readiness_sha != readiness_sha
        or readiness.get("state") != "staged_passed"
        or readiness.get("promotion_eligible") is not False
        or readiness.get("deployment_id") != DEPLOYMENT_ID
        or readiness.get("intent_sha256") != intent_sha
        or readiness.get("route_policy_sha256") != route_policy_sha
        or readiness.get("initial_observation_sha256") != initial_sha
        or readiness.get("resolved_binding_sha256") != resolved_sha
        or readiness.get("launch_receipt_sha256") != launch_sha
        or readiness.get("spec_sha256") != spec_sha
        or readiness.get("spec_normalized_sha256") != normalized
        or readiness.get("coordinator_job") != coordinator
        or readiness.get("coordinator_standby_job") != standby
        or readiness.get("worker_jobs") != list(workers)
        or readiness.get("proxy_job") != proxy_job
        or readiness.get("model_requests_sent") != 0
        or readiness.get("smoke_jobs_submitted") != 0
    ):
        fail("readiness_graph")
    ticks = validate_live_generation(
        api,
        token=token,
        coordinator=coordinator,
        standby=standby,
        workers=workers,
        proxy_job=proxy_job,
        expected_spec_sha=spec_sha,
        expected_spec_normalized=normalized,
    )
    if ticks < int(readiness["coordinator_ticks_completed"]):
        fail("readiness_generation_regressed")
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    route_binding_sha = publish_exclusive(
        ROUTE_ROOT,
        ROUTE_BINDING.name,
        {
            "schema_version": 2,
            "kind": "k3-tb4-v13-live-route-binding",
            "state": "staged_ready_for_commit",
            "promotion_eligible": False,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "deployment_id": DEPLOYMENT_ID,
            "route_policy_sha256": route_policy_sha,
            "initial_observation_sha256": initial_sha,
            "resolved_binding_sha256": resolved_sha,
            "launch_receipt_sha256": launch_sha,
            "readiness_sha256": readiness_sha,
            "spec_sha256": spec_sha,
            "spec_normalized_sha256": normalized,
            "coordinator_job": coordinator,
            "coordinator_standby_job": standby,
            "worker_jobs": list(workers),
            "proxy_job": proxy_job,
            "worker_qos": WORKER_QOS,
            "worker_qos_preemptible": WORKER_QOS_PREEMPTIBLE,
            "smoke_jobs_submitted": 0,
        },
    )
    if STOP_EVENT.is_set():
        raise LaunchCancelled()
    return route_binding_sha


def ready_commit_payload(
    *,
    source_name: str,
    source_device: int,
    source_inode: int,
    intent_sha: str,
    initial_sha: str,
    resolved_sha: str,
    route_policy_sha: str,
    launch_sha: str,
    readiness_sha: str,
    route_binding_sha: str,
    lock_proof: TerminalLockProof,
    coordinator: str,
    standby: str,
    workers: Sequence[str],
    proxy_job: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "k3-tb4-v13-ready-commit",
        "state": "ready_for_smoke",
        "promotion_eligible": True,
        "deployment_id": DEPLOYMENT_ID,
        "commit_source_name": source_name,
        "commit_source_device": source_device,
        "commit_source_inode": source_inode,
        "owner_intent_sha256": intent_sha,
        "initial_observation_sha256": initial_sha,
        "resolved_binding_sha256": resolved_sha,
        "route_policy_sha256": route_policy_sha,
        "launch_receipt_sha256": launch_sha,
        "readiness_sha256": readiness_sha,
        "route_binding_sha256": route_binding_sha,
        "lock_tombstone_sha256": lock_proof.sha256,
        "lock_tombstone_device": lock_proof.device,
        "lock_tombstone_inode": lock_proof.inode,
        "coordinator_job": coordinator,
        "coordinator_standby_job": standby,
        "worker_jobs": list(workers),
        "proxy_job": proxy_job,
        "model_requests_sent": 0,
        "smoke_jobs_submitted": 0,
    }


def prepare_ready_commit(
    *,
    intent_sha: str,
    initial_sha: str,
    resolved_sha: str,
    route_policy_sha: str,
    launch_sha: str,
    readiness_sha: str,
    route_binding_sha: str,
    lock_proof: TerminalLockProof,
    coordinator: str,
    standby: str,
    workers: Sequence[str],
    proxy_job: str,
) -> tuple[Path, str, dict[str, Any]]:
    source_name = f".ready_commit.{os.urandom(16).hex()}.source.json"
    source_path = ROUTE_ROOT / source_name
    directory_descriptor = descriptor = -1
    try:
        before = ROUTE_ROOT.lstat()
        if (
            ROUTE_ROOT.is_symlink()
            or not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != OWNER_UID
        ):
            fail("commit_directory")
        directory_descriptor = os.open(
            ROUTE_ROOT,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        if signature(os.fstat(directory_descriptor)) != signature(before):
            fail("commit_directory")
        descriptor = os.open(
            source_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_descriptor,
        )
        created = os.fstat(descriptor)
        source_identity = inode_identity(created)
        payload = ready_commit_payload(
            source_name=source_name,
            source_device=source_identity[0],
            source_inode=source_identity[1],
            intent_sha=intent_sha,
            initial_sha=initial_sha,
            resolved_sha=resolved_sha,
            route_policy_sha=route_policy_sha,
            launch_sha=launch_sha,
            readiness_sha=readiness_sha,
            route_binding_sha=route_binding_sha,
            lock_proof=lock_proof,
            coordinator=coordinator,
            standby=standby,
            workers=workers,
            proxy_job=proxy_job,
        )
        raw = canonical_bytes(payload)
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                fail("commit_source_write")
            view = view[count:]
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        written = os.fstat(descriptor)
        if inode_identity(written) != source_identity or written.st_size != len(raw):
            fail("commit_source")
        os.close(descriptor)
        descriptor = -1
        captured = stable_file(source_path, mode=0o400, maximum=1 << 20)
        if captured.raw != raw or captured.signature[:2] != source_identity:
            fail("commit_source")
        os.fsync(directory_descriptor)
        return source_path, captured.sha256, payload
    except BaseException:
        # A failed source is non-authoritative and retained; no path is deleted.
        raise
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if directory_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(directory_descriptor)


def arm_ready_commit(
    *,
    source_path: Path,
    source_sha: str,
    payload: Mapping[str, Any],
    lock_proof: TerminalLockProof,
    intent_sha: str,
    initial_sha: str,
    resolved_sha: str,
    launch_sha: str,
    route_policy_sha: str,
    readiness_sha: str,
    route_binding_sha: str,
    coordinator: str,
    standby: str,
    workers: Sequence[str],
    proxy_job: str,
) -> tuple[int, int]:
    if (
        source_path.parent != ROUTE_ROOT
        or re.fullmatch(r"\.ready_commit\.[0-9a-f]{32}\.source\.json", source_path.name) is None
    ):
        fail("commit_contract")
    readiness, observed_readiness_sha = load_json_artifact(READINESS)
    route_binding, observed_route_binding_sha = load_json_artifact(ROUTE_BINDING)
    validate_generation_artifact_graph(
        intent_sha=intent_sha,
        initial_sha=initial_sha,
        resolved_sha=resolved_sha,
        launch_sha=launch_sha,
        route_policy_sha=route_policy_sha,
        coordinator=coordinator,
        standby=standby,
        workers=workers,
        proxy_job=proxy_job,
    )
    if (
        observed_readiness_sha != readiness_sha
        or readiness.get("state") != "staged_passed"
        or readiness.get("promotion_eligible") is not False
        or observed_route_binding_sha != route_binding_sha
        or route_binding.get("state") != "staged_ready_for_commit"
        or route_binding.get("promotion_eligible") is not False
        or route_binding.get("readiness_sha256") != readiness_sha
        or route_binding.get("deployment_id") != DEPLOYMENT_ID
    ):
        fail("commit_graph")
    source = stable_file(source_path, expected_sha256=source_sha, mode=0o400, maximum=1 << 20)
    expected_payload = ready_commit_payload(
        source_name=source_path.name,
        source_device=source.signature[0],
        source_inode=source.signature[1],
        intent_sha=intent_sha,
        initial_sha=initial_sha,
        resolved_sha=resolved_sha,
        route_policy_sha=route_policy_sha,
        launch_sha=launch_sha,
        readiness_sha=readiness_sha,
        route_binding_sha=route_binding_sha,
        lock_proof=lock_proof,
        coordinator=coordinator,
        standby=standby,
        workers=workers,
        proxy_job=proxy_job,
    )
    if dict(payload) != expected_payload or source.raw != canonical_bytes(expected_payload):
        fail("commit_source")
    if COMMIT_MARKER.exists() or COMMIT_MARKER.is_symlink():
        fail("commit_exists")
    directory_descriptor = -1
    source_descriptor = -1
    try:
        before = ROUTE_ROOT.lstat()
        if (
            ROUTE_ROOT.is_symlink()
            or not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != OWNER_UID
        ):
            fail("commit_directory")
        directory_descriptor = os.open(
            ROUTE_ROOT,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        if signature(os.fstat(directory_descriptor)) != signature(before):
            fail("commit_directory")
        source_descriptor = os.open(
            source_path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
        if signature(os.fstat(source_descriptor)) != source.signature:
            fail("commit_source")
        terminal = stable_file(GLOBAL_LOCK, expected_sha256=lock_proof.sha256, mode=0o600, maximum=4096)
        if terminal.signature[:2] != (lock_proof.device, lock_proof.inode) or terminal.raw != canonical_bytes(
            terminal_lock_payload("commit_pending", "none")
        ):
            fail("commit_lock_binding")
        try:
            os.stat(COMMIT_MARKER.name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            fail("commit_exists")
        return directory_descriptor, source_descriptor
    except BaseException:
        if source_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(source_descriptor)
        if directory_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(directory_descriptor)
        raise


def validate_ready_commit() -> dict[str, Any]:
    directory_fd = marker_fd = source_fd = -1
    try:
        before = ROUTE_ROOT.lstat()
        if (
            ROUTE_ROOT.is_symlink()
            or not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != OWNER_UID
        ):
            fail("commit_directory")
        directory_fd = os.open(
            ROUTE_ROOT,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        if signature(os.fstat(directory_fd)) != signature(before):
            fail("commit_directory")
        marker_fd = os.open(
            COMMIT_MARKER.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        marker_status = os.fstat(marker_fd)
        if (
            not stat.S_ISREG(marker_status.st_mode)
            or stat.S_IMODE(marker_status.st_mode) != 0o400
            or marker_status.st_uid != OWNER_UID
            or marker_status.st_nlink != 2
            or marker_status.st_size == 0
            or marker_status.st_size > 1 << 20
        ):
            fail("commit_marker")
        raw = os.pread(marker_fd, marker_status.st_size + 1, 0)
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
            parse_constant=lambda _value: fail("commit_marker"),
        )
        if not isinstance(payload, dict) or raw != canonical_bytes(payload):
            fail("commit_marker")
        source_name = payload.get("commit_source_name") if isinstance(payload, dict) else None
        if (
            not isinstance(source_name, str)
            or re.fullmatch(r"\.ready_commit\.[0-9a-f]{32}\.source\.json", source_name) is None
        ):
            fail("commit_marker")
        source_fd = os.open(
            source_name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        source_status = os.fstat(source_fd)
        named_marker = os.stat(COMMIT_MARKER.name, dir_fd=directory_fd, follow_symlinks=False)
        named_source = os.stat(source_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            signature(marker_status) != signature(source_status)
            or signature(marker_status) != signature(named_marker)
            or signature(marker_status) != signature(named_source)
            or os.pread(source_fd, source_status.st_size + 1, 0) != raw
            or payload.get("kind") != "k3-tb4-v13-ready-commit"
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != 1
            or payload.get("state") != "ready_for_smoke"
            or payload.get("promotion_eligible") is not True
            or payload.get("deployment_id") != DEPLOYMENT_ID
            or type(payload.get("commit_source_device")) is not int
            or payload.get("commit_source_device") != source_status.st_dev
            or type(payload.get("commit_source_inode")) is not int
            or payload.get("commit_source_inode") != source_status.st_ino
            or type(payload.get("model_requests_sent")) is not int
            or payload.get("model_requests_sent") != 0
            or type(payload.get("smoke_jobs_submitted")) is not int
            or payload.get("smoke_jobs_submitted") != 0
        ):
            fail("commit_marker")
        hash_fields = (
            "owner_intent_sha256",
            "initial_observation_sha256",
            "resolved_binding_sha256",
            "route_policy_sha256",
            "launch_receipt_sha256",
            "readiness_sha256",
            "route_binding_sha256",
            "lock_tombstone_sha256",
        )
        workers = payload.get("worker_jobs")
        if (
            any(
                not isinstance(payload.get(field), str) or SHA_RE.fullmatch(payload[field]) is None
                for field in hash_fields
            )
            or type(payload.get("lock_tombstone_device")) is not int
            or type(payload.get("lock_tombstone_inode")) is not int
            or payload["lock_tombstone_device"] < 0
            or payload["lock_tombstone_inode"] <= 0
            or not isinstance(payload.get("coordinator_job"), str)
            or JOB_ID_RE.fullmatch(payload["coordinator_job"]) is None
            or not isinstance(payload.get("coordinator_standby_job"), str)
            or JOB_ID_RE.fullmatch(payload["coordinator_standby_job"]) is None
            or not isinstance(workers, list)
            or len(workers) != 2
            or any(not isinstance(job, str) or JOB_ID_RE.fullmatch(job) is None for job in workers)
            or len(set(workers)) != 2
            or not isinstance(payload.get("proxy_job"), str)
            or JOB_ID_RE.fullmatch(payload["proxy_job"]) is None
        ):
            fail("commit_marker")
        lock_proof = TerminalLockProof(
            sha256=payload["lock_tombstone_sha256"],
            device=payload["lock_tombstone_device"],
            inode=payload["lock_tombstone_inode"],
        )
        expected_payload = ready_commit_payload(
            source_name=source_name,
            source_device=source_status.st_dev,
            source_inode=source_status.st_ino,
            intent_sha=payload["owner_intent_sha256"],
            initial_sha=payload["initial_observation_sha256"],
            resolved_sha=payload["resolved_binding_sha256"],
            route_policy_sha=payload["route_policy_sha256"],
            launch_sha=payload["launch_receipt_sha256"],
            readiness_sha=payload["readiness_sha256"],
            route_binding_sha=payload["route_binding_sha256"],
            lock_proof=lock_proof,
            coordinator=payload["coordinator_job"],
            standby=payload["coordinator_standby_job"],
            workers=workers,
            proxy_job=payload["proxy_job"],
        )
        if payload != expected_payload:
            fail("commit_marker")
        terminal = stable_file(
            GLOBAL_LOCK,
            expected_sha256=lock_proof.sha256,
            mode=0o600,
            maximum=4096,
        )
        if terminal.signature[:2] != (lock_proof.device, lock_proof.inode) or terminal.raw != canonical_bytes(
            terminal_lock_payload("commit_pending", "none")
        ):
            fail("commit_lock_binding")
        validate_consumed_owner_intent(
            intent_sha=payload["owner_intent_sha256"],
            route_policy_sha=payload["route_policy_sha256"],
            expected_model=model_provenance(),
        )
        spec_sha, normalized = validate_generation_artifact_graph(
            intent_sha=payload["owner_intent_sha256"],
            initial_sha=payload["initial_observation_sha256"],
            resolved_sha=payload["resolved_binding_sha256"],
            launch_sha=payload["launch_receipt_sha256"],
            route_policy_sha=payload["route_policy_sha256"],
            coordinator=payload["coordinator_job"],
            standby=payload["coordinator_standby_job"],
            workers=workers,
            proxy_job=payload["proxy_job"],
        )
        readiness, readiness_sha = load_json_artifact(READINESS)
        route_binding, route_binding_sha = load_json_artifact(ROUTE_BINDING)
        if (
            readiness_sha != payload["readiness_sha256"]
            or readiness.get("schema_version") != 2
            or readiness.get("kind") != "k3-tb4-v13-readiness"
            or readiness.get("state") != "staged_passed"
            or readiness.get("promotion_eligible") is not False
            or readiness.get("deployment_id") != DEPLOYMENT_ID
            or readiness.get("intent_sha256") != payload["owner_intent_sha256"]
            or readiness.get("route_policy_sha256") != payload["route_policy_sha256"]
            or readiness.get("initial_observation_sha256") != payload["initial_observation_sha256"]
            or readiness.get("resolved_binding_sha256") != payload["resolved_binding_sha256"]
            or readiness.get("launch_receipt_sha256") != payload["launch_receipt_sha256"]
            or readiness.get("spec_sha256") != spec_sha
            or readiness.get("spec_normalized_sha256") != normalized
            or readiness.get("coordinator_job") != payload["coordinator_job"]
            or readiness.get("coordinator_standby_job") != payload["coordinator_standby_job"]
            or readiness.get("worker_jobs") != workers
            or readiness.get("proxy_job") != payload["proxy_job"]
            or type(readiness.get("coordinator_ticks_completed")) is not int
            or readiness["coordinator_ticks_completed"] < 0
            or readiness.get("model_requests_sent") != 0
            or readiness.get("smoke_jobs_submitted") != 0
            or route_binding_sha != payload["route_binding_sha256"]
            or route_binding.get("schema_version") != 2
            or route_binding.get("kind") != "k3-tb4-v13-live-route-binding"
            or route_binding.get("state") != "staged_ready_for_commit"
            or route_binding.get("promotion_eligible") is not False
            or route_binding.get("deployment_id") != DEPLOYMENT_ID
            or route_binding.get("route_policy_sha256") != payload["route_policy_sha256"]
            or route_binding.get("initial_observation_sha256") != payload["initial_observation_sha256"]
            or route_binding.get("resolved_binding_sha256") != payload["resolved_binding_sha256"]
            or route_binding.get("launch_receipt_sha256") != payload["launch_receipt_sha256"]
            or route_binding.get("readiness_sha256") != payload["readiness_sha256"]
            or route_binding.get("spec_sha256") != spec_sha
            or route_binding.get("spec_normalized_sha256") != normalized
            or route_binding.get("coordinator_job") != payload["coordinator_job"]
            or route_binding.get("coordinator_standby_job") != payload["coordinator_standby_job"]
            or route_binding.get("worker_jobs") != workers
            or route_binding.get("proxy_job") != payload["proxy_job"]
            or route_binding.get("worker_qos") != WORKER_QOS
            or route_binding.get("worker_qos_preemptible") is not True
            or route_binding.get("smoke_jobs_submitted") != 0
        ):
            fail("commit_graph")
        terminal_after = stable_file(
            GLOBAL_LOCK,
            expected_sha256=lock_proof.sha256,
            mode=0o600,
            maximum=4096,
        )
        if terminal_after.signature != terminal.signature or terminal_after.raw != terminal.raw:
            fail("commit_lock_binding")
        if (
            signature(os.fstat(marker_fd)) != signature(marker_status)
            or signature(os.fstat(source_fd)) != signature(source_status)
            or signature(os.stat(COMMIT_MARKER.name, dir_fd=directory_fd, follow_symlinks=False))
            != signature(marker_status)
            or signature(os.stat(source_name, dir_fd=directory_fd, follow_symlinks=False)) != signature(source_status)
            or signature(os.fstat(directory_fd)) != signature(before)
            or signature(ROUTE_ROOT.lstat()) != signature(before)
        ):
            fail("commit_marker_race")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise DeploymentError("commit_marker") from error
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if marker_fd >= 0:
            os.close(marker_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
    return payload


def audit(self_raw: bytes) -> int:
    validate_cli_environment()
    hashes = validate_bundle(self_raw)
    validate_root_runtime()
    validate_source()
    validate_evaluator()
    runtime_raw = validate_runtime_zip()
    serving_runtime = validate_serving_runtime()
    model_provenance()
    preemptors = derive_worker_qos_preemptors()
    assert_paths_fresh()
    api = load_serve_api(runtime_raw)
    try:
        explain_sha = run_explain(api)
        validate_import_origins(api)
        if route_policy_payload(preemptors) != route_policy_payload(EXPECTED_WORKER_QOS_PREEMPTORS):
            fail("route_policy_preemption")
    finally:
        close_serve_api(api)
    print(
        json.dumps(
            {
                "state": "audit_passed",
                "jobs_submitted": 0,
                "deployment_id": DEPLOYMENT_ID,
                "explain_normalized_sha256": explain_sha,
                "bundle_hashes": hashes,
                "serving_runtime_manifests": serving_runtime,
                "worker_qos_preemptible": bool(preemptors),
                "worker_qos_preemptors": list(preemptors),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def execute(self_raw: bytes) -> int:
    global COORDINATOR_RELEASED, CURRENT_API, REGISTRY_BINDING
    validate_cli_environment()
    hashes = validate_bundle(self_raw)
    approval_sha, approval_payload = validate_approval(hashes)
    validate_root_runtime()
    validate_tmux_ancestry()
    validate_source()
    validate_evaluator()
    runtime_raw = validate_runtime_zip()
    serving_runtime = validate_serving_runtime()
    model = model_provenance()
    preemptors = derive_worker_qos_preemptors()
    REGISTRY_BINDING = registry_tls_binding()
    assert_paths_fresh()
    lock: GlobalLock | None = acquire_global_lock()
    api: ServeAPI | None = None
    run_created = False
    committed = False
    success_payload: dict[str, Any] | None = None
    terminal_error_code = "internal_error"
    token = JOB_COMMENT_PREFIX + hashlib.sha256((approval_sha + hashes["controller"]).encode()).hexdigest()[:20]
    known_jobs: list[str] = []
    try:
        assert_paths_fresh(held_global_lock=lock)
        validate_tmux_ancestry()
        os.mkdir(RUN_ROOT, 0o700)
        run_created = True
        os.mkdir(ROUTE_ROOT, 0o700)
        api = load_serve_api(runtime_raw)
        CURRENT_API = api
        explain_sha = run_explain(api)
        validate_import_origins(api)
        validate_source()
        validate_evaluator()
        model_provenance()
        prove_name_absent(rounds=2)
        route_policy_sha = publish_exclusive(ROUTE_ROOT, ROUTE_POLICY.name, route_policy_payload(preemptors))
        consumed_approval_sha, consumed_approval = validate_approval(hashes)
        if consumed_approval_sha != approval_sha or consumed_approval != approval_payload:
            fail("approval_changed_before_consumption")
        intent = {
            "schema_version": 2,
            "kind": "k3-tb4-v13-deployment-intent",
            "state": "armed",
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "approval_sha256": approval_sha,
            "approval_payload": approval_payload,
            "bundle_hashes": hashes,
            "plan": batch_plan(),
            "route_policy_sha256": route_policy_sha,
            "explain_normalized_sha256": explain_sha,
            "model_provenance": model,
            "serving_runtime_manifests": serving_runtime,
            "job_name": JOB_NAME,
            "job_comment": token,
        }
        intent_sha = publish_exclusive(RUN_ROOT, "owner_intent.json", intent)
        validate_source()
        validate_evaluator()
        model_provenance()
        prove_name_absent(rounds=1, delay=0)
        validate_global_lock(lock)
        validate_tmux_ancestry()
        result, out, err = run_deploy(api, token)
        if SUBMITTED_JOB_ID is not None:
            known_jobs.append(SUBMITTED_JOB_ID)
        if result != 0 or SUBMITTED_JOB_ID is None:
            fail("deploy_cli_failed")
        coordinator = SUBMITTED_JOB_ID
        coordinator_identity(coordinator, token, held=True)
        spec_sha, spec_normalized = observe_stable_spec(api, final=False)
        if content_tree_manifest(DEPLOYMENT_ROOT / "src/serve_api_v2") != SNAPSHOT_MANIFEST:
            fail("deployment_snapshot")
        initial_sha = publish_exclusive(
            RUN_ROOT,
            INITIAL_OBSERVATION.name,
            {
                "schema_version": 2,
                "kind": "k3-tb4-v13-initial-spec-observation",
                "state": "stable_initial_spec_observed",
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "deployment_id": DEPLOYMENT_ID,
                "intent_sha256": intent_sha,
                "route_policy_sha256": route_policy_sha,
                "coordinator_job": coordinator,
                "coordinator_held": True,
                "stable_reads": 2,
                "spec_sha256": spec_sha,
                "spec_normalized_sha256": spec_normalized,
            },
        )
        validate_source()
        validate_runtime_zip(runtime_raw)
        validate_serving_runtime()
        model_provenance()
        submission = {
            "schema_version": 2,
            "kind": "k3-tb4-v13-held-coordinator-submission",
            "state": "held_initial_spec_receipted",
            "intent_sha256": intent_sha,
            "route_policy_sha256": route_policy_sha,
            "initial_observation_sha256": initial_sha,
            "coordinator_job": coordinator,
            "job_name": JOB_NAME,
            "job_comment": token,
            "spec_sha256": spec_sha,
            "spec_normalized_sha256": spec_normalized,
            "cli_stdout_sha256": hashlib.sha256(out).hexdigest(),
            "cli_stderr_sha256": hashlib.sha256(err).hexdigest(),
            "raw_output_retained": False,
        }
        submission_sha = publish_exclusive(RUN_ROOT, "submission.json", submission)
        coordinator_identity(coordinator, token, held=True)
        COORDINATOR_RELEASED = True
        release_job(coordinator, token)
        workers, proxy_job, ticks = wait_for_serving(api, coordinator)
        standby_job = standby_identity(coordinator)
        known_jobs.extend([standby_job, *workers, proxy_job])
        spec_sha, spec_normalized = observe_stable_spec(api, final=True)
        if content_tree_manifest(DEPLOYMENT_ROOT / "src/serve_api_v2") != SNAPSHOT_MANIFEST:
            fail("deployment_snapshot")
        validate_source()
        validate_evaluator()
        validate_runtime_zip(runtime_raw)
        serving_runtime = validate_serving_runtime()
        model = model_provenance()
        validate_import_origins(api)
        coordinator_identity(coordinator, token, held=False)
        for worker_job in workers:
            service_job_identity(worker_job, "worker")
        service_job_identity(proxy_job, "proxy")
        previous_mask = begin_commit()
        try:
            validate_bundle(self_raw)
            validate_global_lock(lock)
            validate_consumed_owner_intent(
                intent_sha=intent_sha,
                route_policy_sha=route_policy_sha,
                expected_hashes=hashes,
                expected_approval_sha=approval_sha,
                expected_approval=approval_payload,
                expected_model=model,
            )
            stable_file(
                RUN_ROOT / "submission.json",
                expected_sha256=submission_sha,
                mode=0o400,
                maximum=1 << 20,
            )
            stable_file(
                INITIAL_OBSERVATION,
                expected_sha256=initial_sha,
                mode=0o400,
                maximum=1 << 20,
            )
            stable_file(
                ROUTE_POLICY,
                expected_sha256=route_policy_sha,
                mode=0o400,
                maximum=1 << 20,
            )
            final_spec_sha, final_normalized = validate_spec(api, final=True)
            if spec_sha != final_spec_sha or spec_normalized != final_normalized:
                fail("spec_changed_before_binding")
            if STOP_EVENT.is_set():
                raise LaunchCancelled()
            resolved_sha = publish_exclusive(
                ROUTE_ROOT,
                RESOLVED_BINDING.name,
                {
                    "schema_version": 2,
                    "kind": "k3-tb4-v13-resolved-spec-binding",
                    "state": "resolved_spec_bound",
                    "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "deployment_id": DEPLOYMENT_ID,
                    "intent_sha256": intent_sha,
                    "route_policy_sha256": route_policy_sha,
                    "initial_observation_sha256": initial_sha,
                    "submission_sha256": submission_sha,
                    "coordinator_job": coordinator,
                    "spec_sha256": spec_sha,
                    "spec_normalized_sha256": spec_normalized,
                    "source_revision": SOURCE_REVISION,
                    "source_tree": SOURCE_TREE,
                    "source_snapshot_manifest": SNAPSHOT_MANIFEST,
                    "worker_qos": WORKER_QOS,
                    "worker_qos_priority": EXPECTED_WORKER_QOS_PRIORITY,
                    "worker_qos_outbound_preempt_targets": list(EXPECTED_WORKER_QOS_OUTBOUND),
                    "worker_qos_preemptible": WORKER_QOS_PREEMPTIBLE,
                    "worker_qos_preemptors": list(preemptors),
                    "worker_exclude_nodes": list(WORKER_EXCLUDE_NODES),
                },
            )
            if STOP_EVENT.is_set():
                raise LaunchCancelled()
            launch_sha = publish_exclusive(
                RUN_ROOT,
                LAUNCH_RECEIPT.name,
                {
                    "schema_version": 2,
                    "kind": "k3-tb4-v13-deployment-receipt",
                    "state": "live_final_spec_bound",
                    "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "promotion_eligible": False,
                    "intent_sha256": intent_sha,
                    "submission_sha256": submission_sha,
                    "route_policy_sha256": route_policy_sha,
                    "initial_observation_sha256": initial_sha,
                    "resolved_binding_sha256": resolved_sha,
                    "deployment_id": DEPLOYMENT_ID,
                    "coordinator_job": coordinator,
                    "coordinator_standby_job": standby_job,
                    "worker_jobs": workers,
                    "proxy_job": proxy_job,
                    "ready_endpoints": 2,
                    "coordinator_ticks_completed": ticks,
                    "spec_sha256": spec_sha,
                    "spec_normalized_sha256": spec_normalized,
                    "source_revision": SOURCE_REVISION,
                    "source_tree": SOURCE_TREE,
                    "model_provenance": model,
                    "serving_runtime_manifests": serving_runtime,
                    "next_gate": "cross_bound_readiness",
                    "contains_endpoint_or_secret": False,
                },
            )
            if STOP_EVENT.is_set():
                raise LaunchCancelled()
        finally:
            end_commit(previous_mask)
        readiness_sha = produce_readiness(
            api,
            token=token,
            intent_sha=intent_sha,
            initial_sha=initial_sha,
            resolved_sha=resolved_sha,
            launch_sha=launch_sha,
            route_policy_sha=route_policy_sha,
            coordinator=coordinator,
            standby=standby_job,
            workers=workers,
            proxy_job=proxy_job,
        )
        route_binding_sha = consume_readiness(
            api,
            token=token,
            readiness_sha=readiness_sha,
            intent_sha=intent_sha,
            initial_sha=initial_sha,
            resolved_sha=resolved_sha,
            launch_sha=launch_sha,
            route_policy_sha=route_policy_sha,
            coordinator=coordinator,
            standby=standby_job,
            workers=workers,
            proxy_job=proxy_job,
        )
        previous_mask = begin_commit()
        commit_directory_descriptor = -1
        commit_source_descriptor = -1
        try:
            if STOP_EVENT.is_set():
                raise LaunchCancelled()
            if lock is None:
                fail("global_lock_identity")
            try:
                lock_proof = finalize_global_lock(lock, outcome="commit_pending", error_code="none")
            finally:
                lock = None
            if STOP_EVENT.is_set():
                raise LaunchCancelled()
            commit_source, commit_sha, commit_payload = prepare_ready_commit(
                intent_sha=intent_sha,
                initial_sha=initial_sha,
                resolved_sha=resolved_sha,
                route_policy_sha=route_policy_sha,
                launch_sha=launch_sha,
                readiness_sha=readiness_sha,
                route_binding_sha=route_binding_sha,
                lock_proof=lock_proof,
                coordinator=coordinator,
                standby=standby_job,
                workers=workers,
                proxy_job=proxy_job,
            )
            commit_directory_descriptor, commit_source_descriptor = arm_ready_commit(
                source_path=commit_source,
                source_sha=commit_sha,
                payload=commit_payload,
                lock_proof=lock_proof,
                intent_sha=intent_sha,
                initial_sha=initial_sha,
                resolved_sha=resolved_sha,
                launch_sha=launch_sha,
                route_policy_sha=route_policy_sha,
                readiness_sha=readiness_sha,
                route_binding_sha=route_binding_sha,
                coordinator=coordinator,
                standby=standby_job,
                workers=workers,
                proxy_job=proxy_job,
            )
            if STOP_EVENT.is_set():
                raise LaunchCancelled()
            try:
                os.link(
                    commit_source.name,
                    COMMIT_MARKER.name,
                    src_dir_fd=commit_directory_descriptor,
                    dst_dir_fd=commit_directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                # NFS may report an error after the server has committed the
                # hard link. Once the syscall was attempted, rollback is no
                # longer safe even if an immediate lookup reports ENOENT.
                committed = True
                try:
                    marker = os.stat(
                        COMMIT_MARKER.name,
                        dir_fd=commit_directory_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    raise DeploymentError("commit_link_ambiguous_absent") from error
                except OSError as proof_error:
                    raise DeploymentError("commit_link_ambiguous") from proof_error
                try:
                    source = os.fstat(commit_source_descriptor)
                except OSError as proof_error:
                    raise DeploymentError("commit_link_ambiguous") from proof_error
                if signature(marker) == signature(source) and source.st_nlink == 2:
                    pass
                else:
                    fail("commit_link_conflict")
            else:
                committed = True
        finally:
            if commit_source_descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(commit_source_descriptor)
            if commit_directory_descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(commit_directory_descriptor)
            end_commit(previous_mask)
        success_payload = {
            "state": "ready_for_smoke",
            "ready_endpoints": 2,
            "readiness_sha256": readiness_sha,
            "route_binding_sha256": route_binding_sha,
            "commit_sha256": commit_sha,
            "smoke_jobs_submitted": 0,
        }
    except BaseException as primary:
        terminal_error_code = sanitized_error_code(primary)
        if committed:
            raise
        cleanup_result = cleanup(token, known_jobs)
        cleanup_result["commit_marker_absent"] = commit_marker_absent()
        cleanup_confirmed = (
            cleanup_result["all_terminal"]
            and cleanup_result["namespace_archived"]
            and cleanup_result["commit_marker_absent"]
        )
        if run_created:
            with contextlib.suppress(BaseException):
                cleanup_sha = publish_exclusive(
                    RUN_ROOT,
                    CLEANUP_RECEIPT.name,
                    {
                        "schema_version": 2,
                        "kind": "k3-tb4-v13-cleanup-receipt",
                        "state": "cleanup_complete" if cleanup_confirmed else "cleanup_unconfirmed",
                        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "deployment_id": DEPLOYMENT_ID,
                        "category": type(primary).__name__,
                        "error_code": terminal_error_code,
                        "exact_job_names": [
                            JOB_NAME,
                            f"{DEPLOYMENT_ID}-ep",
                            f"{DEPLOYMENT_ID}-proxy",
                        ],
                        "bounded_terminal_rounds": ZERO_ROUNDS,
                        "bounded_terminal_interval_seconds": ZERO_INTERVAL,
                        "cleanup": cleanup_result,
                        "mutates_stale_generations": False,
                    },
                )
                publish_exclusive(
                    RUN_ROOT,
                    "failure.json",
                    {
                        "schema_version": 2,
                        "kind": "k3-tb4-v13-deployment-failure",
                        "state": "failed_closed",
                        "category": type(primary).__name__,
                        "error_code": terminal_error_code,
                        "cleanup_receipt_sha256": cleanup_sha,
                        "cleanup": cleanup_result,
                        "promotion_eligible": False,
                    },
                )
        if not cleanup_confirmed:
            primary.add_note("cleanup_unconfirmed")
        raise
    finally:
        REGISTRY_BINDING = {}
        if api is not None:
            with contextlib.suppress(BaseException):
                close_serve_api(api)
        if lock is not None:
            finalize_global_lock(
                lock,
                outcome="signal" if terminal_error_code == "signal" else "failure",
                error_code=terminal_error_code,
            )
    if success_payload is None:
        fail("success_payload_missing")
    print(json.dumps(success_payload, sort_keys=True, separators=(",", ":")))
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"audit", "execute"}:
        print('{"state":"inert","launch_eligible":false}')
        return 2
    raw = (
        Path(__file__).read_bytes()
        if not str(__file__).startswith("/proc/self/fd/")
        else os.pread(int(str(__file__).rsplit("/", 1)[1]), 4 << 20, 0)
    )
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    for signum in previous:
        signal.signal(signum, signal_handler)
    try:
        return audit(raw) if sys.argv[1] == "audit" else execute(raw)
    except LaunchCancelled:
        print('{"state":"failed_closed","category":"signal","error_code":"signal"}', file=sys.stderr)
        return 130
    except BaseException as error:
        print(
            json.dumps(
                {
                    "state": "failed_closed",
                    "category": type(error).__name__,
                    "error_code": sanitized_error_code(error),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
