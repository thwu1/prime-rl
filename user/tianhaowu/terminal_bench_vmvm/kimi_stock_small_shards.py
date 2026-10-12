#!/usr/bin/env python3
"""Plan and certify resumable Kimi 2,499-task stock/small shards.

Task membership is intentionally confined to mode-0600 artifacts.  Commands
print only counts, digests, shard indexes, and stable status codes.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tomllib
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Sequence

import audit_traces
import finalize_kimi_tb4_sandoq_small_full as tb4_full
import finalize_kimi_tb4_sandoq_small_v4_recovery as tb4_recovery
import finalize_kimi_tb4_sandoq_small_v6_supersession as tb4_transport
import finalize_kimi_tb4_sandoq_small_v8_supersession as tb4_v8
import finalize_kimi_tb4_sandoq_small_v12 as tb4_v12
import finalize_kimi_tb4_sandoq_small_v13 as tb4_v13
import finalize_kimi_tb4_sandoq_small_v14 as tb4_v14
import finalize_kimi_tb4_sandoq_small_v15 as tb4_v15
import kimi_sandoq_production as legacy
import kimi_stock_small_task_image_soak as task_image_soak
import kimi_tb4_provider_split as split
import prepare_kimi_tb4_miniswe246_union as union
import prepare_kimi_tb4_sandoq_small_full as tb4_small
from kimi_stock_endpoint_binding import (
    StockEndpointBinding,
    StockEndpointBindingError,
    load_capacity_binding,
)
from terminal_bench_vmvm.taskset import SHARED_VERIFIER_TERMINAL_TRANSPORT_DISPOSITION

SCHEMA_VERSION = 1
DYNAMIC_SCHEMA_VERSION = 2
PLAN_KIND = "kimi-k3-stock-small-sharded-production-plan"
COMPLETION_KIND = "kimi-k3-stock-small-shard-completion"
FINAL_KIND = "kimi-k3-stock-small-sharded-production-completion"
LAUNCH_KIND = "kimi-k3-stock-small-shard-launch"
DEPLOYMENT_NAMESPACE = "kimi-stock-small-20260927"
MODEL = "Kimi-K3"
TOTAL_TASKS = 2_499
SHARD_COUNT = 40
CONCURRENCY = 64
MAX_SHARD_TASKS = 63
MAX_SEQUENCE_TOKENS = 262_144
SAMPLE_TOKENS = 32_768
REQUEST_TIMEOUT_SECONDS = 144_000
ROLLOUT_TIMEOUT_SECONDS = 129_600
SESSION_TIMEOUT_SECONDS = 144_000
SHELL_ACTION_TIMEOUT_SECONDS = 3_600
MINIMUM_TB4_PASSES = 7
CPU_CAP = 1
MEMORY_MB_CAP = 2_048
STORAGE_MB_CAP = 10_240
PROVISIONING_RETRIES = 8
CAPACITY_PROFILE = "sandoq-stock-single-c64-v1"
ENDPOINT_IDENTIFIER = "tianhaowu-kimi-k3-stock-eval-20260927"
ENDPOINT_BUNDLE_SHA256 = "7ee38ee5d10c9cc7b04c2ddf9ff5b7813df148b2f7d425c1a4ff192f8fc4d581"
SOURCE_SPEC_SHA256 = "3b9d7b9e72767b9f65894ea024a08713ed10330c7d55c70cd99b2717056a9b39"
SOURCE_PROXY_SHA256 = "7894cd7205d0197620fa77edc747377e15c4e311769a0060be760659f5b29595"
STOCK_CAPACITY_SHA256 = "244dc901a555b4b73649c6185692c8a9d497319e0f8bcdcdb7373f6604c6f946"
STOCK_CAPACITY = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-stock-capacity-probes-20260927-v1/c64-fcedd7c6b.json"
)
SANDOQ_CAPACITY_SHA256 = "400d2c6cc39db2ab83c9dcec38a0e2870b76ced29e3bfb48bcd2478e8ba3b762"
SANDOQ_CAPACITY = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/diagnostics/"
    "sandoq-firecracker-small-c64-soak-20260927/run-1596293/receipt.json"
)
PROVIDER_PROFILE_SHA256 = "247d04de8dd4d5efcb00ebb4d507c20d90420369459aa9ba1e1e37758e2d5084"
PROVIDER_TOKEN_PATH_SHA256 = "19f886485a27dd272af667283ebeb57293a08723782af6c4bc83a05dca6dedc0"
IMAGE_MANIFEST_SHA256 = "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"
BASE_CONFIG_SHA256 = "9d84617bf05fa19355e7c80f40a1f845841e35b800b90fe3998d679f2fc6cd4b"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESULTS_ROW_BYTES = 128 * 1024 * 1024
TB4_SHARED_PRIME_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py",
    "user/tianhaowu/terminal_bench_vmvm/audit_traces.py",
    "user/tianhaowu/terminal_bench_vmvm/run_eval_with_zero_model_resume.sh",
    "user/tianhaowu/terminal_bench_vmvm/assess_zero_model_resume.py",
    "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/sandoq_provider_context.py",
    "user/tianhaowu/terminal_bench_vmvm/direct_kimi_router.py",
)
TB4_LANE_PRIME_FILES = (
    "user/tianhaowu/terminal_bench_vmvm/eval_run_identity.py",
    "user/tianhaowu/terminal_bench_vmvm/direct_kimi_workers.py",
    "user/tianhaowu/terminal_bench_vmvm/prepare_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_full.py",
    "user/tianhaowu/terminal_bench_vmvm/run_direct_kimi_sandoq_stage.sh",
    "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/"
    "run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch",
    "user/tianhaowu/terminal_bench_vmvm/run_kimi_tb4_miniswe246_sandoq_stock_single_full.sbatch",
    "user/tianhaowu/terminal_bench_vmvm/run_kimi_tb4_miniswe246_sandoq_small_full.sbatch",
    "user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/"
    "tb4_kimi_k3_miniswe246_sandoq_firecracker_small_full.base.toml",
    "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v7.py",
    "user/tianhaowu/terminal_bench_vmvm/kimi_tb4_provider_split.py",
)
TB4_PRODUCTION_SHARED_VARIANT_FILES = frozenset(
    {
        "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py",
    }
)
TB4_PRODUCTION_LANE_VARIANT_FILES = frozenset(
    {
        "user/tianhaowu/terminal_bench_vmvm/eval_run_identity.py",
        "user/tianhaowu/terminal_bench_vmvm/direct_kimi_workers.py",
        "user/tianhaowu/terminal_bench_vmvm/run_direct_kimi_sandoq_stage.sh",
    }
)
TB4_PRODUCTION_VARIANT_FILES = TB4_PRODUCTION_SHARED_VARIANT_FILES | TB4_PRODUCTION_LANE_VARIANT_FILES
TB4_SANDOQ_EXTENSION_PREFIX = "extensions/sandoq/sandoq_provider"
TB4_VERIFIERS_EXECUTION_FILES = (
    "verifiers/v1/env.py",
    "verifiers/v1/runtimes/sandoq.py",
    "verifiers/v1/harnesses/mini_swe_agent/harness.py",
    "verifiers/v1/harnesses/mini_swe_agent/program.py",
)
# Exact old/new content pairs for the immutable v8 execution and the reviewed
# production-only variants.  Any later edit to one of these files closes the gate.
TB4_PRODUCTION_VARIANT_PAIR_SHA256 = "1dceb059f96eaaeaa638bcf8dea22d432e83109fc4cea0a21dafd023d3530a21"
TB4_V12_PRODUCTION_SHARED_VARIANT_FILES = frozenset(
    {
        "user/tianhaowu/terminal_bench_vmvm/terminal_bench_vmvm/taskset.py",
    }
)
TB4_V12_PRODUCTION_LANE_VARIANT_FILES = frozenset(
    {
        "user/tianhaowu/terminal_bench_vmvm/eval_run_identity.py",
    }
)
TB4_V12_PRODUCTION_SANDOQ_VARIANT_FILES = frozenset(
    {
        "extensions/sandoq/sandoq_provider/oci_client.py",
        "extensions/sandoq/sandoq_provider/tests/test_oci_client_security.py",
    }
)
# The pending v12 certifier is source-bound to aa3; this is deliberately
# distinct from the post-certifier production revision audited by the pair hash.
TB4_V12_SUPERSESSION_SOURCE_REVISION = "aa3ebebec140261a437f538ffcb8b9b913974057"
TB4_V12_PRODUCTION_VARIANT_PAIR_SHA256 = "065b880a58c3be9d6fbbcf6cf7caa4be4a1e6ad9f9b5fb8b127d960bcc682866"
# The v13 certifier is an immutable additive commit atop the exact 3a39
# execution revision.  No execution-semantic files differ between those two
# revisions, so the reviewed variant set is deliberately empty and its digest
# is the canonical empty-map digest.  The production gate itself is a later
# commit; the supersession source stays pinned to the certifier commit.
TB4_V13_SUPERSESSION_SOURCE_REVISION = "eecb29f549e94984722806bc72bc02ea9d06db63"
TB4_V13_PRODUCTION_SHARED_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V13_PRODUCTION_LANE_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V13_PRODUCTION_SANDOQ_VARIANT_FILES: frozenset[str] = frozenset()
TB4_EMPTY_VARIANT_PAIR_SHA256 = "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"
TB4_V13_PRODUCTION_VARIANT_PAIR_SHA256 = TB4_EMPTY_VARIANT_PAIR_SHA256
# V14 extends the shared finalizer engine only behind an execution-contract
# opt-in.  Preserve acceptance of the exact v12/v13 source files by binding
# that one reviewed old/new source pair instead of relabeling either source.
TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_FILES = frozenset(
    {
        "user/tianhaowu/terminal_bench_vmvm/finalize_kimi_tb4_sandoq_small_v8_supersession.py",
    }
)
TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256 = "012b532ce1988da914f32b0ab18948e7151dbc4c367cb0e982449228f069ee0e"
TB4_V14_SUPERSESSION_SOURCE_REVISION = "5d78c4ee12f8350637956b3d683e557db465fd49"
TB4_V14_PRODUCTION_SHARED_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V14_PRODUCTION_LANE_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V14_PRODUCTION_SANDOQ_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V14_PRODUCTION_VARIANT_PAIR_SHA256 = TB4_EMPTY_VARIANT_PAIR_SHA256
# V15 binds the reviewed v14 lifecycle policy to the fresh v5 execution.
# The certifier is additive, so none of the execution-semantic files differ.
TB4_V15_SUPERSESSION_SOURCE_REVISION = "c0076df06780647a62e4b19f4b946aeb17a09eb4"
TB4_V15_PRODUCTION_SHARED_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V15_PRODUCTION_LANE_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V15_PRODUCTION_SANDOQ_VARIANT_FILES: frozenset[str] = frozenset()
TB4_V15_PRODUCTION_VARIANT_PAIR_SHA256 = TB4_EMPTY_VARIANT_PAIR_SHA256

PROXY_SUMMARY_MARKER = b"sandoq: buffered model proxy summary "
PROXY_SUMMARY_PREFIX_RE = re.compile(rb"[0-9]{2}:[0-9]{2}:[0-9]{2} +INFO \Z")
PROXY_SUMMARY_INTEGER_FIELDS = (
    "requests",
    "upstream_attempts",
    "logical_requests",
    "logical_upstream_attempts",
    "anonymous_upstream_attempts",
    "coalesced_requests",
    "replayed_requests",
    "expired_logical_retries",
    "downstream_disconnects",
    "conflicting_requests",
    "inflight",
    "streamed_requests",
    "response_bytes",
    "error_count",
    "unknown_path_requests",
)
PROXY_SUMMARY_MAPPING_FIELDS = ("statuses", "protocols", "path_counts")
ALLOWED_ERROR_TYPES = frozenset(
    {
        "HarnessError",
        "InterceptionError",
        "ProviderError",
        "SandboxError",
        "TasksetError",
        "ToolsetError",
        "TunnelError",
        "UserError",
    }
)


class StockSmallError(ValueError):
    """A stock/small production artifact failed closed."""


def _workflow_dir() -> Path:
    return Path(__file__).resolve(strict=True).parent


def _base_config_path() -> Path:
    return _workflow_dir() / "configs/eval/servers/cpu-132-021_8103/mobius_kimi_k3_stock_small_shard.base.toml"


def _provider_profile_path() -> Path:
    return _workflow_dir() / "configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json"


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _plain_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {"path": str(path), "bytes": len(body), "sha256": _sha256(body)}


def _read(
    path: Path,
    *,
    code: str,
    private: bool = False,
    held: split._HeldArtifactSet | None = None,
    maximum_bytes: int = 64 * 1024 * 1024,
) -> bytes:
    try:
        return split.read_regular(
            path,
            code=code,
            private=private,
            held=held,
            maximum_bytes=maximum_bytes,
        )
    except (OSError, ValueError) as error:
        raise StockSmallError(code) from error


def _json(body: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StockSmallError(code) from error
    if not isinstance(value, dict) or body != _canonical(value):
        raise StockSmallError(code)
    return value


def _counter_mapping(value: object) -> bool:
    return (
        isinstance(value, dict)
        and all(isinstance(key, str) and key for key in value)
        and all(_plain_nonnegative_integer(count) for count in value.values())
    )


def _buffered_proxy_audit(body: bytes) -> dict[str, Any]:
    """Reduce legacy proxy-log summaries with the shared v7 validator."""

    try:
        return tb4_transport._buffered_proxy_audit(
            body,
            expected_schema="logical-exact-once-v1",
        )
    except (RuntimeError, ValueError) as error:
        code = str(error)
        if code not in {
            "buffered_proxy_audit_invalid",
            "buffered_proxy_exact_once_invalid",
            "buffered_proxy_terminal_outcome_invalid",
        }:
            code = "buffered_proxy_audit_invalid"
        raise StockSmallError(code) from error


def _bind_proxy_audit_to_trace(
    audit: Mapping[str, Any],
    *,
    source_model_io_turns: int,
    clean_model_io_turns: int,
    validated_error_model_io_turns: int,
    maximum_terminal_gap: int,
    expected_summary_records: int,
) -> dict[str, Any]:
    if not _plain_nonnegative_integer(expected_summary_records):
        raise StockSmallError("buffered_proxy_trace_mismatch")
    trace = {
        "source_model_io_turns": source_model_io_turns,
        "clean_model_io_turns": clean_model_io_turns,
        "validated_error_model_io_turns": validated_error_model_io_turns,
        "execution_error_zeroes": maximum_terminal_gap,
        "error_model_io_audit_required": True,
    }
    try:
        return tb4_transport._exact_proxy_trace_binding(
            audit,
            trace,
            expected_summary_records=expected_summary_records,
        )
    except (RuntimeError, ValueError) as error:
        raise StockSmallError("buffered_proxy_trace_mismatch") from error


def _bind_router_to_transport(
    router_body: bytes,
    transport: Mapping[str, Any],
    *,
    provider_error_rows: int,
) -> dict[str, Any]:
    try:
        return tb4_transport._exact_router_proxy_binding(
            router_body,
            transport,
            {"provider_error_zeroes": provider_error_rows},
        )
    except (RuntimeError, ValueError) as error:
        raise StockSmallError("router_transport_binding_invalid") from error


def _validate_stock_small_cleanup(
    path: Path,
    run_dir: Path,
    identity: Mapping[str, Any],
    identity_sha256: str,
    invocation_identity_sha256: str,
    slurm_job_id: str,
    expected_count: int,
    held: split._HeldArtifactSet,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Validate a partial final wave against its fixed c64 pool envelope."""

    count_keys = {
        "recorded_outer_sessions",
        "verified_http_404",
        "already_absent",
        "deleted_and_verified",
        "assignments_acquired",
        "assignment_release_rows",
        "assignment_cancellation_rows",
        "cleanup_gateway_retry_count",
        "assignments_cleanup_verified",
        "assignment_event_order_high_water",
        "assignment_measured_high_water",
        "outer_sessions_created",
        "outer_sessions_deleted",
        "outer_session_high_water",
        "pool_drain_deleted",
        "gateway_close_warnings",
        "recovered_poisoned_assignments",
        "failures",
    }
    digest_keys = {
        "raw_audit_sha256",
        "pool_event_log_sha256",
        "pool_wal_sha256",
        "pool_drain_sha256",
    }
    body = _read(path, code="sandoq_cleanup_invalid", private=True, held=held)
    value = _json(body, code="sandoq_cleanup_invalid")
    if (
        not 1 <= expected_count <= MAX_SHARD_TASKS
        or set(value) != {"schema_version", "kind", "state", *count_keys, *digest_keys}
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-pool-cleanup"
        or value.get("state") != "passed"
        or any(not _plain_nonnegative_integer(value.get(key)) for key in count_keys)
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in digest_keys)
        or value.get("failures") != 0
        or value["recorded_outer_sessions"] < 1
        or value["recorded_outer_sessions"] != value["verified_http_404"]
        or value["recorded_outer_sessions"] != value["outer_sessions_created"]
        or value["recorded_outer_sessions"] != value["outer_sessions_deleted"]
        or value["assignment_measured_high_water"] != expected_count
        or not value["assignment_measured_high_water"] <= value["outer_session_high_water"] <= CONCURRENCY
        or value["assignments_acquired"] < expected_count
        or value["assignments_cleanup_verified"] != value["assignments_acquired"]
        or value["assignment_release_rows"] + value["assignment_cancellation_rows"] != value["assignments_acquired"]
    ):
        raise StockSmallError("sandoq_cleanup_invalid")
    execution = identity.get("execution")
    environment = execution.get("sandoq_environment") if isinstance(execution, dict) else None
    raw_path = run_dir / "pool_cleanup_audit.json"
    event_path = run_dir / "pool_events.jsonl"
    wal_path = run_dir / "control/sandoq-pool.wal.jsonl"
    if (
        not isinstance(environment, dict)
        or split._absolute_path(Path(str(environment.get("pool_event_log", "")))) != split._absolute_path(event_path)
        or split._absolute_path(Path(str(environment.get("pool_wal", "")))) != split._absolute_path(wal_path)
        or split._absolute_path(path) != split._absolute_path(run_dir / "sandoq_cleanup_audit.json")
    ):
        raise StockSmallError("sandoq_cleanup_run_mismatch")
    raw_body = _read(
        raw_path,
        code="sandoq_cleanup_invalid",
        private=True,
        held=held,
        maximum_bytes=32 * 1024 * 1024,
    )
    event_body = _read(
        event_path,
        code="sandoq_cleanup_invalid",
        private=True,
        held=held,
        maximum_bytes=128 * 1024 * 1024,
    )
    wal_body = _read(
        wal_path,
        code="sandoq_cleanup_invalid",
        private=True,
        held=held,
        maximum_bytes=128 * 1024 * 1024,
    )
    try:
        split._json_object(raw_body, code="sandoq_cleanup_invalid")
        split._validate_job_bound_jsonl(event_body, slurm_job_id, wal=False)
        split._validate_job_bound_jsonl(wal_body, slurm_job_id, wal=True)
    except (RuntimeError, ValueError) as error:
        raise StockSmallError("sandoq_cleanup_invalid") from error
    artifacts = {
        "cleanup_receipt": _artifact(path, body),
        "cleanup_raw_audit": _artifact(raw_path, raw_body),
        "cleanup_event_log": _artifact(event_path, event_body),
        "cleanup_wal": _artifact(wal_path, wal_body),
    }
    if (
        value["raw_audit_sha256"] != artifacts["cleanup_raw_audit"]["sha256"]
        or value["pool_event_log_sha256"] != artifacts["cleanup_event_log"]["sha256"]
        or value["pool_wal_sha256"] != artifacts["cleanup_wal"]["sha256"]
    ):
        raise StockSmallError("sandoq_cleanup_run_mismatch")
    return (
        {
            "kind": "sandoq-pool-cleanup",
            "state": "passed",
            "eval_run_identity_sha256": identity_sha256,
            "invocation_identity_sha256": invocation_identity_sha256,
            "recorded_outer_sessions": value["recorded_outer_sessions"],
            "verified_http_404": value["verified_http_404"],
            "assignment_measured_high_water": value["assignment_measured_high_water"],
            "failures": 0,
        },
        artifacts,
    )


def _tb4_audited_model_io_turns(rows: Mapping[str, Mapping[str, Any]]) -> int:
    turns = 0
    for row in rows.values():
        nodes = row.get("nodes")
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict) or node.get("sampled") is not True:
                continue
            model_io = node.get("model_io")
            response = model_io.get("response") if isinstance(model_io, dict) else None
            if isinstance(response, dict) and response.get("kind") == "exact_provider_json":
                turns += 1
    return turns


def _json_line(body: bytes, *, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise StockSmallError(code) from error
    if not isinstance(value, dict):
        raise StockSmallError(code)
    return value


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise StockSmallError("source_identity_invalid") from error
    if completed.stderr:
        raise StockSmallError("source_identity_invalid")
    return completed.stdout.strip()


def _validate_source(project_root: Path, expected_revision: str) -> Path:
    if REVISION_RE.fullmatch(expected_revision) is None:
        raise StockSmallError("source_identity_invalid")
    try:
        root = project_root.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("source_identity_invalid") from error
    if root != project_root or not root.is_dir():
        raise StockSmallError("source_identity_invalid")
    repositories = (root, root / "deps/verifiers", root / "deps/renderers")
    if _git(root, "rev-parse", "HEAD") != expected_revision or any(
        _git(repository, "status", "--porcelain=v1", "--untracked-files=all") for repository in repositories
    ):
        raise StockSmallError("source_identity_invalid")
    return root


def _load_base(held: split._HeldArtifactSet | None = None) -> tuple[dict[str, Any], bytes, Path]:
    path = _base_config_path().resolve(strict=True)
    body = _read(path, code="base_config_invalid", held=held)
    if _sha256(body) != BASE_CONFIG_SHA256:
        raise StockSmallError("base_config_invalid")
    try:
        value = tomllib.loads(body.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise StockSmallError("base_config_invalid") from error
    client = value.get("client")
    sampling = value.get("sampling")
    taskset = value.get("taskset")
    harness = value.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, dict) else None
    if (
        value.get("model") != MODEL
        or value.get("num_tasks") != 1
        or value.get("num_rollouts") != 1
        or value.get("max_concurrent") != CONCURRENCY
        or value.get("multiplex") != CONCURRENCY
        or value.get("max_turns") != 200
        or any(
            value.get(key) != MAX_SEQUENCE_TOKENS
            for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens")
        )
        or value.get("retain_traces") is not False
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or client.get("timeout") != REQUEST_TIMEOUT_SECONDS
        or client.get("max_connections") != CONCURRENCY
        or client.get("max_keepalive_connections") != CONCURRENCY
        or client.get("max_retries") != 0
        or not isinstance(sampling, dict)
        or sampling.get("max_tokens") != SAMPLE_TOKENS
        or sampling.get("reasoning_effort") != "max"
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, dict)
        or taskset.get("dataset_revision") != legacy.CANONICAL_DATASET_REVISION
        or taskset.get("enable_compose") is not False
        or taskset.get("resource_multiplier") != 1.0
        or taskset.get("resource_cpu_cap") != CPU_CAP
        or taskset.get("resource_memory_mb_cap") != MEMORY_MB_CAP
        or taskset.get("resource_storage_mb_cap") != STORAGE_MB_CAP
        or taskset.get("verifier_runtime_retries") != 0
        or taskset.get("retry_shared_verifier_scoring") is not False
        or not isinstance(harness, dict)
        or harness.get("id") != "mini-swe-agent"
        or harness.get("version") != "2.4.6"
        or harness.get("env") != {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}
        or harness.get("config_overrides")
        != [
            "agent.step_limit=200",
            "environment.environment_class=local",
            f"environment.timeout={SHELL_ACTION_TIMEOUT_SECONDS}",
            "model.model_kwargs.drop_params=true",
            "model.model_kwargs.timeout=144000",
            "model.model_kwargs.temperature=1.0",
            "model.model_kwargs.top_p=1.0",
            "model.model_kwargs.parallel_tool_calls=false",
        ]
        or runtime
        != {
            "type": "sandoq",
            "mode": "oci-runner",
            "session_timeout": SESSION_TIMEOUT_SECONDS,
            "network_access": True,
            "host_tunnel": "sandoq",
            "buffered_chat_completions": True,
            "guest_tunnel_url": "http://127.0.0.1:8485",
            "tunnel_pool_size": 4,
            "tunnel_ready_timeout": 30,
            "provisioning_retries": PROVISIONING_RETRIES,
            "expected_environment": "oci-runner-firecracker-small",
            "ecr_token_file": "/storage/home/tianhaowu/.config/oci-runner/ecr-token",
        }
        or value.get("timeout")
        != {"setup": 3_600, "rollout": ROLLOUT_TIMEOUT_SECONDS, "finalize": 3_600, "scoring": 21_600}
        or value.get("retries", {}).get("rollout", {}).get("max_retries") != 0
    ):
        raise StockSmallError("base_config_contract_invalid")
    return value, body, path


def _validate_provider_profile(held: split._HeldArtifactSet | None = None) -> tuple[Path, bytes]:
    path = _provider_profile_path().resolve(strict=True)
    body = _read(path, code="provider_profile_invalid", held=held)
    if _sha256(body) != PROVIDER_PROFILE_SHA256:
        raise StockSmallError("provider_profile_invalid")
    value = _json(body, code="provider_profile_invalid")
    if (
        value.get("environment") != "oci-runner-firecracker-small"
        or value.get("task_network") != "host"
        or value.get("effective_task_network") != "public"
        or value.get("transport_mode") != "auto"
    ):
        raise StockSmallError("provider_profile_invalid")
    return path, body


def _validate_stock_capacity(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[Path, bytes, StockEndpointBinding]:
    try:
        binding, body = load_capacity_binding(
            path,
            expected_sha256,
        )
    except (OSError, RuntimeError, ValueError, StockEndpointBindingError) as error:
        raise StockSmallError("stock_capacity_receipt_invalid") from error
    return binding.capacity_receipt_path, body, binding


def _validate_sandoq_capacity(
    path: Path,
    expected_sha256: str,
    held: split._HeldArtifactSet | None = None,
) -> tuple[Path, bytes]:
    try:
        canonical = path.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("sandoq_capacity_receipt_invalid") from error
    body = _read(canonical, code="sandoq_capacity_receipt_invalid", private=True, held=held)
    if expected_sha256 != SANDOQ_CAPACITY_SHA256 or _sha256(body) != expected_sha256:
        raise StockSmallError("sandoq_capacity_receipt_invalid")
    value = _json(body, code="sandoq_capacity_receipt_invalid")
    count = CONCURRENCY
    failures = value.get("create_failure_counts")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "sandoq-firecracker-small-c64-soak"
        or value.get("state") != "passed"
        or value.get("environment") != "oci-runner-firecracker-small"
        or value.get("profile_sha256") != PROVIDER_PROFILE_SHA256
        or any(
            value.get(key) != count
            for key in (
                "requested_concurrency",
                "create_attempts",
                "sessions_returned",
                "simultaneous_ready_verified",
                "delete_attempts",
                "typed_404_verified",
            )
        )
        or value.get("cleanup_failures") != 0
        or value.get("client_close_verified") is not True
        or value.get("mtls_available") is not True
        or value.get("transport_mode") != "proxy"
        or not isinstance(failures, dict)
        or any(item != 0 for item in failures.values())
    ):
        raise StockSmallError("sandoq_capacity_receipt_invalid")
    return canonical, body


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise StockSmallError("tb4_execution_semantics_invalid") from error
    if completed.stderr:
        raise StockSmallError("tb4_execution_semantics_invalid")
    return completed.stdout


def _git_file_hashes(repository: Path, revision: str, paths: Sequence[str]) -> dict[str, str]:
    if REVISION_RE.fullmatch(revision) is None or not paths or len(paths) != len(set(paths)):
        raise StockSmallError("tb4_execution_semantics_invalid")
    values: dict[str, str] = {}
    for relative in sorted(paths):
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise StockSmallError("tb4_execution_semantics_invalid")
        values[relative] = _sha256(_git_bytes(repository, "show", f"{revision}:{relative}"))
    return values


def _validated_hash_map(value: object, expected_paths: Sequence[str]) -> dict[str, str]:
    expected = set(expected_paths)
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or any(
            not isinstance(path, str) or not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None
            for path, digest in value.items()
        )
    ):
        raise StockSmallError("tb4_execution_semantics_invalid")
    return dict(value)


def _validate_tb4_execution_semantics(
    value: object,
    *,
    tb4_root: Path,
    production_root: Path,
    certificate_revision: str,
    verifiers_revision: str,
    production_shared_variant_files: frozenset[str] = TB4_PRODUCTION_SHARED_VARIANT_FILES,
    production_lane_variant_files: frozenset[str] = TB4_PRODUCTION_LANE_VARIANT_FILES,
    production_sandoq_variant_files: frozenset[str] = frozenset(),
    production_variant_pair_sha256: str = TB4_PRODUCTION_VARIANT_PAIR_SHA256,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "hash_kind",
        "source_revision",
        "prime_rl_shared_files",
        "prime_rl_shared_file_set_sha256",
        "tb4_lane_files",
        "tb4_lane_file_set_sha256",
        "sandoq_extension",
        "verifiers",
    }:
        raise StockSmallError("tb4_execution_semantics_invalid")
    extension = value.get("sandoq_extension")
    verifiers = value.get("verifiers")
    if (
        value.get("schema_version") != 1
        or value.get("hash_kind") != "raw-file-sha256"
        or value.get("source_revision") != certificate_revision
        or not isinstance(extension, dict)
        or set(extension) != {"path", "files", "file_set_sha256"}
        or extension.get("path") != TB4_SANDOQ_EXTENSION_PREFIX
        or not isinstance(verifiers, dict)
        or set(verifiers) != {"commit", "files", "file_set_sha256"}
        or verifiers.get("commit") != verifiers_revision
    ):
        raise StockSmallError("tb4_execution_semantics_invalid")

    shared_files = _validated_hash_map(
        value.get("prime_rl_shared_files"),
        TB4_SHARED_PRIME_FILES,
    )
    lane_files = _validated_hash_map(value.get("tb4_lane_files"), TB4_LANE_PRIME_FILES)
    extension_paths = tuple(
        line.decode("utf-8")
        for line in _git_bytes(
            tb4_root,
            "ls-tree",
            "-r",
            "--name-only",
            certificate_revision,
            "--",
            TB4_SANDOQ_EXTENSION_PREFIX,
        ).splitlines()
        if line
    )
    if not extension_paths or any(not path.startswith(TB4_SANDOQ_EXTENSION_PREFIX + "/") for path in extension_paths):
        raise StockSmallError("tb4_execution_semantics_invalid")
    if (
        not production_shared_variant_files <= set(TB4_SHARED_PRIME_FILES)
        or not production_lane_variant_files <= set(TB4_LANE_PRIME_FILES)
        or not production_sandoq_variant_files <= set(extension_paths)
        or SHA256_RE.fullmatch(production_variant_pair_sha256) is None
    ):
        raise StockSmallError("tb4_execution_semantics_invalid")
    extension_files = _validated_hash_map(extension.get("files"), extension_paths)
    verifier_files = _validated_hash_map(verifiers.get("files"), TB4_VERIFIERS_EXECUTION_FILES)
    observed_tb4_shared = _git_file_hashes(
        tb4_root,
        certificate_revision,
        TB4_SHARED_PRIME_FILES,
    )
    observed_tb4_lane = _git_file_hashes(
        tb4_root,
        certificate_revision,
        TB4_LANE_PRIME_FILES,
    )
    observed_tb4_extension = _git_file_hashes(tb4_root, certificate_revision, extension_paths)
    observed_tb4_verifiers = _git_file_hashes(
        tb4_root / "deps/verifiers",
        verifiers_revision,
        TB4_VERIFIERS_EXECUTION_FILES,
    )
    if (
        shared_files != observed_tb4_shared
        or value.get("prime_rl_shared_file_set_sha256") != _sha256(_canonical(shared_files))
        or lane_files != observed_tb4_lane
        or value.get("tb4_lane_file_set_sha256") != _sha256(_canonical(lane_files))
        or extension_files != observed_tb4_extension
        or extension.get("file_set_sha256") != _sha256(_canonical(extension_files))
        or verifier_files != observed_tb4_verifiers
        or verifiers.get("file_set_sha256") != _sha256(_canonical(verifier_files))
    ):
        raise StockSmallError("tb4_execution_semantics_invalid")

    production_revision = _git(production_root, "rev-parse", "HEAD")
    production_shared = _git_file_hashes(
        production_root,
        production_revision,
        TB4_SHARED_PRIME_FILES,
    )
    if any(
        production_shared[path] != shared_files[path]
        for path in set(TB4_SHARED_PRIME_FILES) - production_shared_variant_files
    ):
        raise StockSmallError("tb4_shared_execution_semantics_changed")
    production_lane = _git_file_hashes(
        production_root,
        production_revision,
        TB4_LANE_PRIME_FILES,
    )
    if any(
        production_lane[path] != lane_files[path] for path in set(TB4_LANE_PRIME_FILES) - production_lane_variant_files
    ):
        raise StockSmallError("tb4_lane_execution_semantics_changed")
    variant_pairs = {
        **{
            path: {"production": production_shared[path], "tb4": shared_files[path]}
            for path in sorted(production_shared_variant_files)
        },
        **{
            path: {"production": production_lane[path], "tb4": lane_files[path]}
            for path in sorted(production_lane_variant_files)
        },
    }

    production_extension_paths = tuple(
        line.decode("utf-8")
        for line in _git_bytes(
            production_root,
            "ls-tree",
            "-r",
            "--name-only",
            production_revision,
            "--",
            TB4_SANDOQ_EXTENSION_PREFIX,
        ).splitlines()
        if line
    )
    production_extension = _git_file_hashes(
        production_root,
        production_revision,
        production_extension_paths,
    )
    if production_extension_paths == extension_paths:
        variant_pairs.update(
            {
                path: {"production": production_extension[path], "tb4": extension_files[path]}
                for path in sorted(production_sandoq_variant_files)
            }
        )
    if _sha256(_canonical(variant_pairs)) != production_variant_pair_sha256:
        raise StockSmallError("tb4_lane_specific_semantics_changed")
    production_verifiers_revision = _git(production_root / "deps/verifiers", "rev-parse", "HEAD")
    production_verifiers = _git_file_hashes(
        production_root / "deps/verifiers",
        production_verifiers_revision,
        TB4_VERIFIERS_EXECUTION_FILES,
    )
    if (
        production_extension_paths != extension_paths
        or any(
            production_extension[path] != extension_files[path]
            for path in set(extension_paths) - production_sandoq_variant_files
        )
        or production_verifiers_revision != verifiers_revision
        or production_verifiers != verifier_files
    ):
        raise StockSmallError("tb4_shared_execution_semantics_changed")
    return {
        "schema_version": 1,
        "tb4_source_revision": certificate_revision,
        "production_source_revision": production_revision,
        "shared_prime_file_set_sha256": value["prime_rl_shared_file_set_sha256"],
        "tb4_lane_file_set_sha256": value["tb4_lane_file_set_sha256"],
        "production_variant_pair_sha256": production_variant_pair_sha256,
        "sandoq_extension_file_set_sha256": extension["file_set_sha256"],
        "verifiers_commit": verifiers_revision,
        "verifiers_file_set_sha256": verifiers["file_set_sha256"],
    }


def _validate_tb4_supersession_source(
    value: object,
    *,
    tb4_root: Path,
    production_root: Path,
    certificate_revision: str,
    source_paths: Sequence[str] = tb4_transport.SUPERSESSION_SOURCE_FILES,
    distinct_source_revision: bool = False,
    expected_source_revision: str | None = None,
    production_variant_files: frozenset[str] = frozenset(),
    production_variant_pair_sha256: str = TB4_EMPTY_VARIANT_PAIR_SHA256,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "project_root",
        "revision",
        "hash_kind",
        "files",
        "file_set_sha256",
    }:
        raise StockSmallError("tb4_supersession_source_invalid")
    source_revision = value.get("revision")
    source_root_value = value.get("project_root")
    source_root = Path(source_root_value) if isinstance(source_root_value, str) else Path()
    if (
        not isinstance(source_revision, str)
        or REVISION_RE.fullmatch(source_revision) is None
        or not isinstance(source_root_value, str)
        or not source_root_value
        or not source_root.is_absolute()
        or value.get("hash_kind") != "raw-file-sha256"
        or (expected_source_revision is not None and source_revision != expected_source_revision)
        or (not distinct_source_revision and source_revision != certificate_revision)
        or (not distinct_source_revision and source_root != tb4_root)
    ):
        raise StockSmallError("tb4_supersession_source_invalid")
    files = _validated_hash_map(value.get("files"), source_paths)
    production_revision = _git(production_root, "rev-parse", "HEAD")
    if distinct_source_revision:
        source_files = _git_file_hashes(production_root, source_revision, source_paths)
    else:
        source_files = _git_file_hashes(tb4_root, certificate_revision, source_paths)
    production_files = _git_file_hashes(production_root, production_revision, source_paths)
    file_set_sha256 = _sha256(_canonical(files))
    if (
        not isinstance(production_variant_files, frozenset)
        or not production_variant_files <= set(source_paths)
        or (production_variant_files and not distinct_source_revision)
        or not isinstance(production_variant_pair_sha256, str)
        or SHA256_RE.fullmatch(production_variant_pair_sha256) is None
        or files != source_files
        or any(files[path] != production_files[path] for path in set(source_paths) - production_variant_files)
        or _sha256(
            _canonical(
                {
                    path: {"production": production_files[path], "tb4": files[path]}
                    for path in sorted(production_variant_files)
                }
            )
        )
        != production_variant_pair_sha256
        or value.get("file_set_sha256") != file_set_sha256
    ):
        raise StockSmallError("tb4_supersession_source_invalid")
    result = {
        "source_revision": source_revision,
        "file_set_sha256": file_set_sha256,
    }
    if production_variant_files:
        result["production_variant_pair_sha256"] = production_variant_pair_sha256
    return result


def _validate_tb4_provider_context(
    value: object,
    *,
    executed_results: Mapping[str, Any],
    held: split._HeldArtifactSet | None,
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"artifact", "contract_sha256"}
        or SHA256_RE.fullmatch(str(value.get("contract_sha256", ""))) is None
    ):
        raise StockSmallError("tb4_gate_provider_context_invalid")
    provider_path, provider_body = _record_body(
        value.get("artifact"),
        code="tb4_gate_provider_context_invalid",
        private=True,
        held=held,
    )
    provider_snapshot = _json(provider_body, code="tb4_gate_provider_context_invalid")
    expected_provider_keys = {
        "schema_version",
        "kind",
        "state",
        "provider_environment",
        "effective_task_network",
        "task_network",
        "network_access",
        "allow_dockerhub_fallback",
        "provider_profile_sha256",
        "provider_token_file_path_sha256",
        "runtime_smoke_receipt_sha256",
        "provider_context_contract_sha256",
    }
    if (
        provider_path != Path(str(executed_results.get("path", ""))).parent / "sandoq-provider-context.json"
        or set(provider_snapshot) != expected_provider_keys
        or provider_snapshot.get("schema_version") != 1
        or provider_snapshot.get("kind") != "sandoq-provider-context-snapshot"
        or provider_snapshot.get("state") != "validated"
        or provider_snapshot.get("provider_environment") != "oci-runner-firecracker-small"
        or provider_snapshot.get("effective_task_network") != "public"
        or provider_snapshot.get("task_network") != "host"
        or provider_snapshot.get("network_access") is not True
        or provider_snapshot.get("allow_dockerhub_fallback") is not False
        or provider_snapshot.get("provider_profile_sha256") != PROVIDER_PROFILE_SHA256
        or provider_snapshot.get("provider_token_file_path_sha256") != PROVIDER_TOKEN_PATH_SHA256
        or provider_snapshot.get("runtime_smoke_receipt_sha256") is not None
        or provider_snapshot.get("provider_context_contract_sha256") != value.get("contract_sha256")
    ):
        raise StockSmallError("tb4_gate_provider_context_invalid")
    return provider_snapshot


def _tb4_gate_variant(value: Mapping[str, Any]) -> dict[str, Any]:
    supersession = value.get("supersession")
    reason = supersession.get("reason") if isinstance(supersession, Mapping) else None
    if value.get("schema_version") == 1 and reason == "fixed-denominator-exact-transport-v7":
        return {
            "schema_version": 1,
            "reason": reason,
            "extra_certificate_keys": frozenset(),
            "extra_count_keys": frozenset(),
            "extra_training_keys": frozenset(),
            "allow_post_agent_verifier_sandbox_errors": False,
            "supersession_source_paths": tb4_transport.SUPERSESSION_SOURCE_FILES,
            "distinct_supersession_source_revision": False,
        }
    if value.get("schema_version") == 2 and reason == tb4_v8.SUPERSESSION_REASON:
        return {
            "schema_version": 2,
            "reason": reason,
            "extra_certificate_keys": frozenset(
                {
                    "post_agent_verifier_error_policy",
                    "pre_model_sandoq_provisioning_error_policy",
                    "sandoq_assignment_lifecycle",
                }
            ),
            "extra_count_keys": frozenset(
                {
                    "post_agent_verifier_sandbox_error_zeroes",
                    "pre_model_sandoq_provisioning_error_zeroes",
                }
            ),
            "extra_training_keys": frozenset(
                {
                    "excluded_post_agent_verifier_sandbox_error_rows",
                    "excluded_pre_model_sandoq_provisioning_error_rows",
                    "post_agent_verifier_sandbox_error_rows_are_trainable",
                    "pre_model_sandoq_provisioning_error_rows_are_trainable",
                }
            ),
            "allow_post_agent_verifier_sandbox_errors": True,
            "audit_pre_model_sandoq_provisioning_errors": True,
            "supersession_source_paths": tb4_v8.SUPERSESSION_SOURCE_FILES,
            "distinct_supersession_source_revision": True,
        }
    if value.get("schema_version") == 2 and reason == tb4_v12.SUPERSESSION_REASON:
        return {
            "schema_version": 2,
            "reason": reason,
            "extra_certificate_keys": frozenset(
                {
                    "exact_length_benchmark_policy",
                    "execution_completion",
                    "persisted_verifier_artifacts",
                    "post_agent_verifier_error_policy",
                    "pre_model_sandoq_provisioning_error_policy",
                    "sandoq_assignment_lifecycle",
                }
            ),
            "extra_artifact_keys": frozenset({"execution_completion"}),
            "extra_count_keys": frozenset(
                {
                    "benchmark_scored_failures",
                    "benchmark_scored_rows",
                    "benchmark_valid_nontrainable_passes",
                    "infrastructure_zeroes",
                    "post_agent_verifier_artifact_write_transport_zeroes",
                    "post_agent_verifier_exec_transport_zeroes",
                    "post_agent_verifier_sandbox_error_zeroes",
                    "pre_model_sandoq_provisioning_error_zeroes",
                    "provider_scored_passes",
                    "trainable_passes",
                }
            ),
            "extra_training_keys": frozenset(
                {
                    "eligible_clean_passes",
                    "excluded_post_agent_verifier_artifact_write_transport_rows",
                    "excluded_post_agent_verifier_sandbox_error_rows",
                    "excluded_pre_model_sandoq_provisioning_error_rows",
                    "post_agent_verifier_artifact_write_transport_rows_are_trainable",
                    "post_agent_verifier_sandbox_error_rows_are_trainable",
                    "pre_model_sandoq_provisioning_error_rows_are_trainable",
                }
            ),
            "allow_post_agent_verifier_sandbox_errors": True,
            "audit_pre_model_sandoq_provisioning_errors": True,
            "allow_exact_length_benchmark_rows": True,
            "allow_post_agent_exec_transport_errors": True,
            "allow_post_agent_artifact_write_transport_errors": True,
            "require_persisted_verifier_artifacts": True,
            "execution_contract": tb4_v12.execution_contract(tb4_v12.EXECUTION_SLURM_JOB_ID),
            "supersession_source_paths": tb4_v12.SUPERSESSION_SOURCE_FILES,
            "distinct_supersession_source_revision": True,
            "expected_supersession_source_revision": TB4_V12_SUPERSESSION_SOURCE_REVISION,
            "production_supersession_source_variant_files": (TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_FILES),
            "production_supersession_source_variant_pair_sha256": (TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256),
            "production_shared_variant_files": TB4_V12_PRODUCTION_SHARED_VARIANT_FILES,
            "production_lane_variant_files": TB4_V12_PRODUCTION_LANE_VARIANT_FILES,
            "production_sandoq_variant_files": TB4_V12_PRODUCTION_SANDOQ_VARIANT_FILES,
            "production_variant_pair_sha256": TB4_V12_PRODUCTION_VARIANT_PAIR_SHA256,
        }
    if value.get("schema_version") == 2 and reason == tb4_v13.SUPERSESSION_REASON:
        return {
            "schema_version": 2,
            "reason": reason,
            "extra_certificate_keys": frozenset(
                {
                    "exact_length_benchmark_policy",
                    "execution_completion",
                    "persisted_verifier_artifacts",
                    "post_agent_verifier_error_policy",
                    "pre_model_sandoq_provisioning_error_policy",
                    "sandoq_assignment_lifecycle",
                }
            ),
            "extra_artifact_keys": frozenset({"execution_completion"}),
            "extra_count_keys": frozenset(
                {
                    "benchmark_scored_failures",
                    "benchmark_scored_rows",
                    "benchmark_valid_nontrainable_passes",
                    "infrastructure_zeroes",
                    "post_agent_verifier_artifact_write_transport_zeroes",
                    "post_agent_verifier_exec_transport_zeroes",
                    "post_agent_verifier_sandbox_error_zeroes",
                    "pre_model_sandoq_provisioning_error_zeroes",
                    "provider_scored_passes",
                    "trainable_passes",
                }
            ),
            "extra_training_keys": frozenset(
                {
                    "eligible_clean_passes",
                    "excluded_post_agent_verifier_artifact_write_transport_rows",
                    "excluded_post_agent_verifier_sandbox_error_rows",
                    "excluded_pre_model_sandoq_provisioning_error_rows",
                    "post_agent_verifier_artifact_write_transport_rows_are_trainable",
                    "post_agent_verifier_sandbox_error_rows_are_trainable",
                    "pre_model_sandoq_provisioning_error_rows_are_trainable",
                }
            ),
            "allow_post_agent_verifier_sandbox_errors": True,
            "audit_pre_model_sandoq_provisioning_errors": True,
            "allow_exact_length_benchmark_rows": True,
            "allow_post_agent_exec_transport_errors": True,
            "allow_post_agent_artifact_write_transport_errors": True,
            "require_persisted_verifier_artifacts": True,
            "execution_contract": tb4_v13.execution_contract(tb4_v13.EXECUTION_SLURM_JOB_ID),
            "execution_plan": tb4_v13.EXECUTION_PLAN,
            "execution_run_dir": tb4_v13.EXECUTION_RUN_DIR,
            "supersession_source_paths": tb4_v13.SUPERSESSION_SOURCE_FILES,
            "distinct_supersession_source_revision": True,
            "expected_supersession_source_revision": TB4_V13_SUPERSESSION_SOURCE_REVISION,
            "production_supersession_source_variant_files": (TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_FILES),
            "production_supersession_source_variant_pair_sha256": (TB4_PRE_V14_SUPERSESSION_SOURCE_VARIANT_PAIR_SHA256),
            "production_shared_variant_files": TB4_V13_PRODUCTION_SHARED_VARIANT_FILES,
            "production_lane_variant_files": TB4_V13_PRODUCTION_LANE_VARIANT_FILES,
            "production_sandoq_variant_files": TB4_V13_PRODUCTION_SANDOQ_VARIANT_FILES,
            "production_variant_pair_sha256": TB4_V13_PRODUCTION_VARIANT_PAIR_SHA256,
        }
    if value.get("schema_version") == 2 and reason == tb4_v14.SUPERSESSION_REASON:
        return {
            "schema_version": 2,
            "reason": reason,
            "extra_certificate_keys": frozenset(
                {
                    "exact_length_benchmark_policy",
                    "execution_completion",
                    "persisted_verifier_artifacts",
                    "post_agent_verifier_error_policy",
                    "pre_model_sandoq_provisioning_error_policy",
                    "sandoq_assignment_lifecycle",
                }
            ),
            "extra_artifact_keys": frozenset({"execution_completion"}),
            "extra_count_keys": frozenset(
                {
                    "benchmark_scored_failures",
                    "benchmark_scored_rows",
                    "benchmark_valid_nontrainable_passes",
                    "infrastructure_zeroes",
                    "post_agent_verifier_artifact_write_transport_zeroes",
                    "post_agent_verifier_exec_transport_zeroes",
                    "post_agent_verifier_sandbox_error_zeroes",
                    "pre_model_sandoq_provisioning_error_zeroes",
                    "provider_scored_passes",
                    "trainable_passes",
                }
            ),
            "extra_training_keys": frozenset(
                {
                    "eligible_clean_passes",
                    "excluded_post_agent_verifier_artifact_write_transport_rows",
                    "excluded_post_agent_verifier_sandbox_error_rows",
                    "excluded_pre_model_sandoq_provisioning_error_rows",
                    "post_agent_verifier_artifact_write_transport_rows_are_trainable",
                    "post_agent_verifier_sandbox_error_rows_are_trainable",
                    "pre_model_sandoq_provisioning_error_rows_are_trainable",
                }
            ),
            "allow_post_agent_verifier_sandbox_errors": True,
            "audit_pre_model_sandoq_provisioning_errors": True,
            "allow_exact_length_benchmark_rows": True,
            "allow_post_agent_exec_transport_errors": True,
            "allow_post_agent_artifact_write_transport_errors": True,
            "require_persisted_verifier_artifacts": True,
            "allow_pre_ready_managed_shell_provisioning_failures": True,
            "execution_contract": tb4_v14.execution_contract(tb4_v14.EXECUTION_SLURM_JOB_ID),
            "execution_plan": tb4_v14.EXECUTION_PLAN,
            "execution_run_dir": tb4_v14.EXECUTION_RUN_DIR,
            "supersession_source_paths": tb4_v14.SUPERSESSION_SOURCE_FILES,
            "distinct_supersession_source_revision": True,
            "expected_supersession_source_revision": TB4_V14_SUPERSESSION_SOURCE_REVISION,
            "production_shared_variant_files": TB4_V14_PRODUCTION_SHARED_VARIANT_FILES,
            "production_lane_variant_files": TB4_V14_PRODUCTION_LANE_VARIANT_FILES,
            "production_sandoq_variant_files": TB4_V14_PRODUCTION_SANDOQ_VARIANT_FILES,
            "production_variant_pair_sha256": TB4_V14_PRODUCTION_VARIANT_PAIR_SHA256,
        }
    if value.get("schema_version") == 2 and reason == tb4_v15.SUPERSESSION_REASON:
        return {
            "schema_version": 2,
            "reason": reason,
            "extra_certificate_keys": frozenset(
                {
                    "exact_length_benchmark_policy",
                    "execution_completion",
                    "persisted_verifier_artifacts",
                    "post_agent_verifier_error_policy",
                    "pre_model_sandoq_provisioning_error_policy",
                    "sandoq_assignment_lifecycle",
                }
            ),
            "extra_artifact_keys": frozenset({"execution_completion"}),
            "extra_count_keys": frozenset(
                {
                    "benchmark_scored_failures",
                    "benchmark_scored_rows",
                    "benchmark_valid_nontrainable_passes",
                    "infrastructure_zeroes",
                    "post_agent_verifier_artifact_write_transport_zeroes",
                    "post_agent_verifier_exec_transport_zeroes",
                    "post_agent_verifier_sandbox_error_zeroes",
                    "pre_model_sandoq_provisioning_error_zeroes",
                    "provider_scored_passes",
                    "trainable_passes",
                }
            ),
            "extra_training_keys": frozenset(
                {
                    "eligible_clean_passes",
                    "excluded_post_agent_verifier_artifact_write_transport_rows",
                    "excluded_post_agent_verifier_sandbox_error_rows",
                    "excluded_pre_model_sandoq_provisioning_error_rows",
                    "post_agent_verifier_artifact_write_transport_rows_are_trainable",
                    "post_agent_verifier_sandbox_error_rows_are_trainable",
                    "pre_model_sandoq_provisioning_error_rows_are_trainable",
                }
            ),
            "allow_post_agent_verifier_sandbox_errors": True,
            "audit_pre_model_sandoq_provisioning_errors": True,
            "allow_exact_length_benchmark_rows": True,
            "allow_post_agent_exec_transport_errors": True,
            "allow_post_agent_artifact_write_transport_errors": True,
            "require_persisted_verifier_artifacts": True,
            "allow_pre_ready_managed_shell_provisioning_failures": True,
            "execution_contract": tb4_v15.execution_contract(tb4_v15.EXECUTION_SLURM_JOB_ID),
            "execution_plan": tb4_v15.EXECUTION_PLAN,
            "execution_run_dir": tb4_v15.EXECUTION_RUN_DIR,
            "supersession_source_paths": tb4_v15.SUPERSESSION_SOURCE_FILES,
            "distinct_supersession_source_revision": True,
            "expected_supersession_source_revision": TB4_V15_SUPERSESSION_SOURCE_REVISION,
            "production_shared_variant_files": TB4_V15_PRODUCTION_SHARED_VARIANT_FILES,
            "production_lane_variant_files": TB4_V15_PRODUCTION_LANE_VARIANT_FILES,
            "production_sandoq_variant_files": TB4_V15_PRODUCTION_SANDOQ_VARIANT_FILES,
            "production_variant_pair_sha256": TB4_V15_PRODUCTION_VARIANT_PAIR_SHA256,
        }
    raise StockSmallError("tb4_gate_invalid")


def _validate_tb4_v12_trace_claims(
    value: Mapping[str, Any],
    counts: Mapping[str, Any],
    training: object,
    trace_audit: Mapping[str, Any],
    base_training: Mapping[str, Any],
) -> tuple[dict[str, Any], object, object]:
    artifact_write_zeroes = trace_audit.get("post_agent_verifier_artifact_write_transport_error_zeroes")
    expected_training = {
        **base_training,
        "eligible_clean_passes": trace_audit.get("trainable_passes"),
        "excluded_post_agent_verifier_artifact_write_transport_rows": artifact_write_zeroes,
        "post_agent_verifier_artifact_write_transport_rows_are_trainable": False,
    }
    expected_counts = {
        "provider_scored_passes": trace_audit.get("passes"),
        "benchmark_scored_rows": trace_audit.get("scored_rows"),
        "benchmark_scored_failures": trace_audit.get("scored_failures"),
        "trainable_passes": trace_audit.get("trainable_passes"),
        "benchmark_valid_nontrainable_passes": trace_audit.get("exact_length_nontrainable_passing_rows"),
        "infrastructure_zeroes": trace_audit.get("execution_error_zeroes"),
        "post_agent_verifier_exec_transport_zeroes": trace_audit.get("post_agent_verifier_exec_transport_error_zeroes"),
        "post_agent_verifier_artifact_write_transport_zeroes": artifact_write_zeroes,
    }
    try:
        expected_policy = tb4_v8._exact_length_benchmark_policy(trace_audit)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_v12_claims_invalid") from error
    if (
        value.get("exact_length_benchmark_policy") != expected_policy
        or any(counts.get(key) != expected for key, expected in expected_counts.items())
        or training != expected_training
    ):
        raise StockSmallError("tb4_gate_v12_claims_invalid")
    return (
        expected_training,
        trace_audit.get("benchmark_valid_passes"),
        trace_audit.get("benchmark_invalid_passing_rows"),
    )


def _validate_tb4_v12_artifact_claims(
    value: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    *,
    results_body: bytes,
    run_dir: Path,
    execution_contract: tb4_v8.ExecutionContract,
    held: split._HeldArtifactSet | None,
) -> None:
    try:
        execution_completion = tb4_v8._execution_completion_audit(
            run_dir,
            execution_contract,
            held,
        )
        persisted_verifier_artifacts = tb4_v8._persisted_verifier_artifact_audit(
            results_body,
            run_dir,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_v12_artifacts_invalid") from error
    if execution_completion is None:
        raise StockSmallError("tb4_gate_v12_artifacts_invalid")
    execution_completion_value, execution_completion_artifact = execution_completion
    if (
        value.get("execution_completion") != execution_completion_value
        or artifacts.get("execution_completion") != execution_completion_artifact
        or value.get("persisted_verifier_artifacts") != persisted_verifier_artifacts
    ):
        raise StockSmallError("tb4_gate_v12_artifacts_invalid")


def _validate_tb4_gate_locked(
    path: Path,
    expected_sha256: str,
    production_root: Path,
    evidence: split._HeldRunEvidence,
    held: split._HeldArtifactSet | None = None,
) -> tuple[Path, bytes, dict[str, Any]]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise StockSmallError("tb4_gate_invalid")
    try:
        canonical = path.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("tb4_gate_invalid") from error
    body = _read(canonical, code="tb4_gate_invalid", private=True, held=held)
    if _sha256(body) != expected_sha256:
        raise StockSmallError("tb4_gate_invalid")
    value = _json(body, code="tb4_gate_invalid")
    counts = value.get("counts")
    scores = value.get("scores")
    gate = value.get("gate")
    policy = value.get("policy")
    provider = value.get("provider_context")
    artifacts = value.get("artifacts")
    source_run = value.get("source_run")
    supersession = value.get("supersession")
    trace_claim = value.get("trace_audit")
    proxy_claim = value.get("buffered_proxy_audit")
    router_transport_claim = value.get("router_transport_binding")
    training = value.get("training_eligibility")
    recovery = value.get("zero_model_recovery")
    certificate_revision = value.get("source_revision")
    variant = _tb4_gate_variant(value)
    execution_contract = variant.get("execution_contract")
    if execution_contract is not None and not isinstance(execution_contract, tb4_v8.ExecutionContract):
        raise StockSmallError("tb4_gate_invalid")
    policy_timeouts = policy.get("timeouts") if isinstance(policy, dict) else None
    expected_certificate_keys = {
        "schema_version",
        "kind",
        "state",
        "certification_eligible",
        "official_comparable",
        "result_label",
        "source_revision",
        "launch_plan_sha256",
        "manifest_sha256",
        "eval_run_identity_sha256",
        "invocation_identity_sha256",
        "source_run",
        "supersession",
        "counts",
        "scores",
        "gate",
        "policy",
        "execution_semantics",
        "buffered_proxy_audit",
        "router_transport_binding",
        "trace_audit",
        "training_eligibility",
        "zero_model_recovery",
        "cleanup",
        "provider_context",
        "router_receipt_sha256",
        "artifacts",
        "results_sha256",
    } | set(variant["extra_certificate_keys"])
    count_values = ()
    expected_count_keys = {
        "denominator",
        "executed",
        "compose_unsupported",
        "gpu_unsupported",
        "passes",
        "failures",
        "execution_error_zeroes",
    } | set(variant["extra_count_keys"])
    if isinstance(counts, dict):
        count_values = tuple(counts.get(key) for key in sorted(expected_count_keys))
    counts_are_integers = len(count_values) == len(expected_count_keys) and all(
        map(_plain_nonnegative_integer, count_values)
    )
    rate = scores.get("all_task_pass_rate") if isinstance(scores, dict) else None
    rate_is_number = isinstance(rate, (int, float)) and not isinstance(rate, bool) and math.isfinite(float(rate))
    identity_path: Path | None = None
    executed_record: dict[str, Any] | None = None
    proxy_records: list[Any] | None = None
    router_record: dict[str, Any] | None = None
    if isinstance(artifacts, dict):
        executed = artifacts.get("executed_results")
        if isinstance(executed, dict) and isinstance(executed.get("path"), str):
            executed_record = executed
            identity_path = Path(executed["path"]).parent / "eval_run_identity.json"
        candidate_proxy_records = artifacts.get("buffered_proxy_summary_records")
        if isinstance(candidate_proxy_records, list):
            proxy_records = candidate_proxy_records
        candidate_router_record = artifacts.get("router_receipt")
        if isinstance(candidate_router_record, dict):
            router_record = candidate_router_record
    if (
        set(value) != expected_certificate_keys
        or value.get("schema_version") != variant["schema_version"]
        or value.get("kind") != "kimi-tb4-miniswe246-sandoq-firecracker-small-diagnostic"
        or value.get("state") != "finalized-with-explicit-error-zeroes"
        or value.get("certification_eligible") is not False
        or value.get("official_comparable") is not False
        or not isinstance(certificate_revision, str)
        or REVISION_RE.fullmatch(certificate_revision) is None
        or any(
            SHA256_RE.fullmatch(str(value.get(key, ""))) is None
            for key in (
                "launch_plan_sha256",
                "manifest_sha256",
                "eval_run_identity_sha256",
                "invocation_identity_sha256",
                "router_receipt_sha256",
                "results_sha256",
            )
        )
        or value.get("result_label") != "resource-clamped-firecracker-small-diagnostic"
        or not isinstance(counts, dict)
        or set(counts) != expected_count_keys
        or not counts_are_integers
        or counts.get("denominator") != 66
        or counts.get("executed") != 52
        or counts.get("compose_unsupported") != 11
        or counts.get("gpu_unsupported") != 3
        or not 0 <= counts["passes"] <= counts["executed"]
        or counts["passes"] < MINIMUM_TB4_PASSES
        or counts.get("failures") != 66 - counts["passes"]
        or counts.get("execution_error_zeroes")
        != (trace_claim.get("execution_error_zeroes") if isinstance(trace_claim, dict) else None)
        or not isinstance(scores, dict)
        or set(scores) != {"executed_pass_rate", "all_task_pass_rate"}
        or not rate_is_number
        or not math.isclose(float(rate), counts["passes"] / 66)
        or not isinstance(scores.get("executed_pass_rate"), (int, float))
        or isinstance(scores.get("executed_pass_rate"), bool)
        or not math.isfinite(float(scores["executed_pass_rate"]))
        or not math.isclose(float(scores["executed_pass_rate"]), counts["passes"] / 52)
        or gate != {"target_passes": MINIMUM_TB4_PASSES, "met": True}
        or not isinstance(policy, dict)
        or policy.get("model_io_response_kind") != "exact_provider_json"
        or policy.get("reasoning_required") is not True
        or policy.get("reasoning_message_parity_required") is not True
        or policy.get("request_graph_match_required") is not True
        or policy.get("model_retries") != 0
        or policy.get("guest_transport_retry_attempts") != 10
        or policy.get("logical_request_upstream_attempts") != 1
        or policy.get("verifier_runtime_retries") != 2
        or policy.get("retry_shared_verifier_scoring") is not True
        or policy.get("provisioning_retries") != PROVISIONING_RETRIES
        or not isinstance(policy_timeouts, dict)
        or policy_timeouts.get("request_seconds") != REQUEST_TIMEOUT_SECONDS
        or policy_timeouts.get("rollout_seconds") != ROLLOUT_TIMEOUT_SECONDS
        or not isinstance(provider, dict)
        or not isinstance(artifacts, dict)
        or set(artifacts)
        != {
            "executed_results",
            "buffered_proxy_summary_records",
            "router_receipt",
            "router_receipt_commit",
            "cleanup_receipt",
            "cleanup_raw_audit",
            "cleanup_event_log",
            "cleanup_wal",
        }
        | set(variant.get("extra_artifact_keys", frozenset()))
        or not isinstance(executed_record, dict)
        or set(executed_record) != {"path", "bytes", "sha256"}
        or not isinstance(proxy_records, list)
        or len(proxy_records) != 52
        or any(not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"} for record in proxy_records)
        or not isinstance(router_record, dict)
        or set(router_record) != {"path", "bytes", "sha256"}
        or not isinstance(trace_claim, dict)
        or not isinstance(proxy_claim, dict)
        or not isinstance(router_transport_claim, dict)
        or not isinstance(source_run, dict)
        or not isinstance(supersession, dict)
        or set(supersession)
        != {
            "source",
            "reason",
            "original_full_output",
            "model_attempts_preserved",
        }
        or supersession.get("reason") != variant["reason"]
        or supersession.get("model_attempts_preserved") is not True
        or not isinstance(supersession.get("original_full_output"), str)
        or identity_path is None
    ):
        raise StockSmallError("tb4_gate_invalid")

    launch_record = source_run.get("launch_plan")
    if (
        set(source_run) != {"slurm_job_id", "source_revision", "launch_plan", "results", "results_mutated"}
        or source_run.get("source_revision") != certificate_revision
        or source_run.get("results_mutated") is not False
        or not isinstance(source_run.get("slurm_job_id"), str)
        or re.fullmatch(r"[1-9][0-9]*", source_run["slurm_job_id"]) is None
        or source_run.get("results") != artifacts.get("executed_results")
        or value.get("launch_plan_sha256") != (launch_record.get("sha256") if isinstance(launch_record, dict) else None)
        or (
            execution_contract is not None
            and (
                source_run.get("slurm_job_id") != execution_contract.slurm_job_id
                or certificate_revision != execution_contract.source_revision
                or value.get("launch_plan_sha256") != execution_contract.plan_sha256
            )
        )
    ):
        raise StockSmallError("tb4_gate_invalid")
    launch_path, launch_body = _record_body(
        launch_record,
        code="tb4_gate_plan_invalid",
        private=True,
        held=held,
    )
    try:
        if execution_contract is None:
            verified_plan = tb4_small.verify(
                launch_path,
                _sha256(launch_body),
                held=held,
                body=launch_body,
            )
            decoded_launch_plan = _json(launch_body, code="tb4_gate_plan_invalid")
        else:
            decoded_launch_plan, verified_plan, verified_launch_record = tb4_v8._verified_execution_plan(
                launch_path,
                _sha256(launch_body),
                held,
                execution_contract,
            )
            expected_execution_plan = variant.get("execution_plan", tb4_v12.EXECUTION_PLAN)
            if launch_path != expected_execution_plan or verified_launch_record != launch_record:
                raise StockSmallError("tb4_gate_plan_invalid")
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_plan_invalid") from error
    if (
        policy != decoded_launch_plan.get("contracts")
        or value.get("manifest_sha256") != verified_plan.get("manifest_sha256")
        or supersession.get("original_full_output") != decoded_launch_plan.get("full_output_dir")
    ):
        raise StockSmallError("tb4_gate_plan_invalid")
    _validate_tb4_provider_context(
        provider,
        executed_results=artifacts["executed_results"],
        held=held,
    )
    run_dir = Path(str(executed_record["path"])).parent
    expected_execution_run_dir = variant.get("execution_run_dir", tb4_v12.EXECUTION_RUN_DIR)
    if identity_path != run_dir / "eval_run_identity.json" or (
        execution_contract is not None and run_dir != expected_execution_run_dir
    ):
        raise StockSmallError("tb4_gate_identity_invalid")
    try:
        if execution_contract is None:
            identity, identity_sha256, invocation_sha256, invocation_job_id = tb4_full._identity_contract(
                run_dir=run_dir,
                evidence=evidence,
                plan=decoded_launch_plan,
                expected_revision=certificate_revision,
                expected_verifiers_commit=tb4_small.VERIFIERS_COMMIT,
                held=held,
            )
        else:
            identity, identity_sha256, invocation_sha256, invocation_job_id = tb4_v8._execution_identity_contract(
                run_dir=run_dir,
                evidence=evidence,
                plan=decoded_launch_plan,
                execution=execution_contract,
                held=held,
            )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_identity_invalid") from error
    router = identity.get("deployment", {}).get("router") if isinstance(identity, dict) else None
    if (
        not isinstance(identity, dict)
        or identity.get("role") != "kimi-direct-tb4-small-diagnostic"
        or identity.get("source", {}).get("prime_rl_commit") != certificate_revision
        or not isinstance(router, dict)
        or router.get("capacity_profile") != CAPACITY_PROFILE
        or router.get("endpoint_identifier")
        != (execution_contract.stock_endpoint_identifier if execution_contract is not None else ENDPOINT_IDENTIFIER)
        or router.get("worker_count") != 1
        or router.get("provider_concurrency") != CONCURRENCY
        or identity.get("deployment", {}).get("spec_sha256")
        != (execution_contract.stock_source_spec_sha256 if execution_contract is not None else SOURCE_SPEC_SHA256)
        or identity.get("deployment", {}).get("endpoint_bundle_sha256")
        != (
            execution_contract.stock_endpoint_bundle_sha256
            if execution_contract is not None
            else ENDPOINT_BUNDLE_SHA256
        )
        or identity_sha256 != value.get("eval_run_identity_sha256")
        or invocation_sha256 != value.get("invocation_identity_sha256")
        or invocation_job_id != source_run.get("slurm_job_id")
    ):
        raise StockSmallError("tb4_gate_identity_invalid")
    identity_source = identity.get("source")
    if not isinstance(identity_source, dict) or (
        execution_contract is not None
        and (
            identity_source.get("project_root") != execution_contract.execution_project_root
            or identity_source.get("verifiers_commit") != execution_contract.verifiers_commit
        )
    ):
        raise StockSmallError("tb4_gate_identity_invalid")
    tb4_root = Path(str(identity_source.get("project_root", "")))
    verifiers_revision = str(identity_source.get("verifiers_commit", ""))
    if execution_contract is None:
        semantics_binding = _validate_tb4_execution_semantics(
            value.get("execution_semantics"),
            tb4_root=tb4_root,
            production_root=production_root,
            certificate_revision=certificate_revision,
            verifiers_revision=verifiers_revision,
        )
    else:
        semantics_binding = _validate_tb4_execution_semantics(
            value.get("execution_semantics"),
            tb4_root=tb4_root,
            production_root=production_root,
            certificate_revision=certificate_revision,
            verifiers_revision=verifiers_revision,
            production_shared_variant_files=variant["production_shared_variant_files"],
            production_lane_variant_files=variant["production_lane_variant_files"],
            production_sandoq_variant_files=variant["production_sandoq_variant_files"],
            production_variant_pair_sha256=variant["production_variant_pair_sha256"],
        )
    semantics_binding = {
        **semantics_binding,
        "supersession_source": _validate_tb4_supersession_source(
            supersession.get("source"),
            tb4_root=tb4_root,
            production_root=production_root,
            certificate_revision=certificate_revision,
            source_paths=variant["supersession_source_paths"],
            distinct_source_revision=variant["distinct_supersession_source_revision"],
            expected_source_revision=variant.get("expected_supersession_source_revision"),
            production_variant_files=variant.get(
                "production_supersession_source_variant_files",
                frozenset(),
            ),
            production_variant_pair_sha256=variant.get(
                "production_supersession_source_variant_pair_sha256",
                TB4_EMPTY_VARIANT_PAIR_SHA256,
            ),
        ),
    }
    task_record = identity.get("inputs", {}).get("task_file")
    if (
        not isinstance(task_record, dict)
        or set(task_record) != {"path", "sha256", "count"}
        or task_record.get("count") != 52
        or task_record.get("path") != verified_plan.get("selector")
        or task_record.get("sha256") != verified_plan.get("selector_sha256")
    ):
        raise StockSmallError("tb4_gate_trace_invalid")
    selector_path = Path(str(task_record["path"]))
    selector_body = _read(selector_path, code="tb4_gate_selector_invalid", private=True, held=held)
    if task_record.get("sha256") != _sha256(selector_body):
        raise StockSmallError("tb4_gate_selector_invalid")
    try:
        members = tuple(selector_body.decode().splitlines())
    except UnicodeDecodeError as error:
        raise StockSmallError("tb4_gate_selector_invalid") from error
    if len(members) != 52 or len(set(members)) != 52 or selector_body != legacy._task_payload(members):
        raise StockSmallError("tb4_gate_selector_invalid")
    plan_manifest = verified_plan.get("manifest")
    if not isinstance(plan_manifest, str) or not isinstance(verified_plan.get("manifest_sha256"), str):
        raise StockSmallError("tb4_gate_plan_invalid")
    manifest_body = _read(
        Path(plan_manifest),
        code="tb4_gate_plan_invalid",
        private=True,
        held=held,
    )
    try:
        _manifest, entries = split.parse_manifest(
            manifest_body,
            str(verified_plan["manifest_sha256"]),
        )
        verifier_modes = {entry.task_id: entry.verifier_mode for entry in entries}
        partition = union.derive_union_partition(entries)
        results_body = _read(
            Path(str(executed_record["path"])),
            code="tb4_gate_trace_invalid",
            private=True,
            held=held,
            maximum_bytes=512 * 1024 * 1024,
        )
        trace_audit, rows = tb4_recovery._audit_supported_rows(
            results_body,
            members,
            verifier_modes,
            allow_nontrainable_scored_rows=True,
            audit_error_model_io=True,
            allow_post_agent_verifier_sandbox_errors=variant["allow_post_agent_verifier_sandbox_errors"],
            post_agent_verifier_attempts=(
                int(policy["verifier_runtime_retries"]) + 1
                if variant["allow_post_agent_verifier_sandbox_errors"]
                else None
            ),
            audit_pre_model_sandoq_provisioning_errors=variant.get(
                "audit_pre_model_sandoq_provisioning_errors",
                False,
            ),
            sandoq_provisioning_attempts=(
                int(policy["provisioning_retries"]) + 1
                if variant.get("audit_pre_model_sandoq_provisioning_errors", False)
                else None
            ),
            allow_exact_length_benchmark_rows=variant.get(
                "allow_exact_length_benchmark_rows",
                False,
            ),
            allow_post_agent_exec_transport_errors=variant.get(
                "allow_post_agent_exec_transport_errors",
                False,
            ),
            allow_post_agent_artifact_write_transport_errors=variant.get(
                "allow_post_agent_artifact_write_transport_errors",
                False,
            ),
            require_persisted_verifier_artifacts=variant.get(
                "require_persisted_verifier_artifacts",
                False,
            ),
            execution_project_root=(
                execution_contract.execution_project_root if execution_contract is not None else None
            ),
        )
        finalized_results = tb4_transport._merge_rows(
            entries,
            rows,
            partition.compose_required,
            partition.gpu_unsupported,
            str(verified_plan["manifest_sha256"]),
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_trace_invalid") from error
    result_artifact = _artifact(Path(str(executed_record["path"])), results_body)
    run_dir = Path(str(executed_record["path"])).parent
    try:
        raw_proxy_audit, observed_proxy_records = tb4_transport._buffered_proxy_directory_audit(
            run_dir / "control/buffered-proxy-stats",
            expected_records=52,
            expected_schema="logical-exact-once-v1",
            held=held,
        )
        proxy_audit = tb4_transport._exact_proxy_trace_binding(
            raw_proxy_audit,
            trace_audit,
            expected_summary_records=52,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_transport_invalid") from error
    try:
        cleanup, cleanup_artifacts = split._validate_sandoq_cleanup(
            run_dir / "sandoq_cleanup_audit.json",
            run_dir,
            identity,
            str(value["eval_run_identity_sha256"]),
            invocation_sha256,
            invocation_job_id,
            52,
            execution_contract.concurrency if execution_contract is not None else 24,
            held,
        )
        router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
            run_dir / "direct_kimi_router_final.json",
            identity,
            minimum_chat_requests=int(proxy_audit["integer_totals"]["logical_requests"]),
            identity_sha256=str(value["eval_run_identity_sha256"]),
            invocation_identity_sha256=invocation_sha256,
            held=held,
            allow_terminal_upstream_statuses=True,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("tb4_gate_transport_invalid") from error
    if (
        observed_proxy_records != proxy_records
        or router_artifact != router_record
        or artifacts.get("router_receipt_commit") != router_marker
        or value.get("cleanup") != cleanup
        or any(artifacts.get(key) != record for key, record in cleanup_artifacts.items())
        or value.get("router_receipt_sha256") != _sha256(router_body)
    ):
        raise StockSmallError("tb4_gate_transport_invalid")
    router_transport = _bind_router_to_transport(
        router_body,
        proxy_audit,
        provider_error_rows=int(trace_audit["provider_error_zeroes"]),
    )
    if execution_contract is not None:
        _validate_tb4_v12_artifact_claims(
            value,
            artifacts,
            results_body=results_body,
            run_dir=run_dir,
            execution_contract=execution_contract,
            held=held,
        )
    post_agent_zeroes = trace_audit.get("post_agent_verifier_sandbox_error_zeroes", 0)
    pre_model_provisioning_zeroes = trace_audit.get("pre_model_sandoq_provisioning_error_zeroes", 0)
    expected_training = {
        "eligible_clean_scored_rows": trace_audit.get("clean_scored_rows"),
        "excluded_error_rows": trace_audit.get("execution_error_zeroes"),
        "excluded_trace_invalid_scored_rows": trace_audit.get("trace_invalid_scored_rows"),
        "excluded_unsupported_rows": 14,
        "error_rows_are_trainable": False,
        "trace_invalid_scored_rows_are_trainable": False,
    }
    if variant["allow_post_agent_verifier_sandbox_errors"]:
        allow_pre_ready_managed_shell_provisioning_failures = variant.get(
            "allow_pre_ready_managed_shell_provisioning_failures",
            False,
        )
        if (
            type(allow_pre_ready_managed_shell_provisioning_failures) is not bool
            or execution_contract is not None
            and execution_contract.allow_pre_ready_managed_shell_provisioning_failures
            is not allow_pre_ready_managed_shell_provisioning_failures
        ):
            raise StockSmallError("tb4_gate_lifecycle_invalid")
        expected_training.update(
            {
                "excluded_post_agent_verifier_sandbox_error_rows": post_agent_zeroes,
                "excluded_pre_model_sandoq_provisioning_error_rows": pre_model_provisioning_zeroes,
                "post_agent_verifier_sandbox_error_rows_are_trainable": False,
                "pre_model_sandoq_provisioning_error_rows_are_trainable": False,
            }
        )
        try:
            expected_post_agent_policy = tb4_v8._post_agent_verifier_policy(trace_audit)
            expected_pre_model_provisioning_policy = tb4_v8._pre_model_sandoq_provisioning_policy(
                trace_audit,
                allow_pre_ready_managed_shell_provisioning_failures=(
                    allow_pre_ready_managed_shell_provisioning_failures
                ),
            )
            task_images = (
                tb4_v8._validated_task_images(decoded_launch_plan, held)
                if allow_pre_ready_managed_shell_provisioning_failures
                else None
            )
            event_body = _read(
                run_dir / "pool_events.jsonl",
                code="tb4_gate_lifecycle_invalid",
                private=True,
                held=held,
                maximum_bytes=128 * 1024 * 1024,
            )
            expected_assignment_lifecycle = tb4_v8._assignment_lifecycle_audit(
                event_body,
                expected_slurm_job_id=invocation_job_id,
                trace_audit=trace_audit,
                rows=rows,
                verifier_modes=verifier_modes,
                allow_pre_ready_managed_shell_provisioning_failures=(
                    allow_pre_ready_managed_shell_provisioning_failures
                ),
                task_images=task_images,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise StockSmallError("tb4_gate_lifecycle_invalid") from error
        if (
            value.get("post_agent_verifier_error_policy") != expected_post_agent_policy
            or value.get("pre_model_sandoq_provisioning_error_policy") != expected_pre_model_provisioning_policy
            or value.get("sandoq_assignment_lifecycle") != expected_assignment_lifecycle
            or counts.get("post_agent_verifier_sandbox_error_zeroes") != post_agent_zeroes
            or counts.get("pre_model_sandoq_provisioning_error_zeroes") != pre_model_provisioning_zeroes
        ):
            raise StockSmallError("tb4_gate_lifecycle_invalid")
    if execution_contract is not None:
        expected_training, expected_passes, invalid_passing_rows = _validate_tb4_v12_trace_claims(
            value,
            counts,
            training,
            trace_audit,
            expected_training,
        )
    else:
        expected_passes = trace_audit.get("passes")
        invalid_passing_rows = trace_audit.get("trace_invalid_passing_rows")
    if (
        result_artifact != executed_record
        or _sha256(finalized_results) != value.get("results_sha256")
        or trace_audit != value.get("trace_audit")
        or proxy_audit != proxy_claim
        or router_transport != router_transport_claim
        or expected_passes != counts["passes"]
        or trace_audit.get("clean_trace_failures") != 0
        or invalid_passing_rows != 0
        or not _plain_nonnegative_integer(trace_audit.get("clean_scored_rows"))
        or not _plain_nonnegative_integer(trace_audit.get("execution_error_zeroes"))
        or trace_audit.get("clean_scored_rows")
        + trace_audit.get("trace_invalid_scored_rows")
        + trace_audit.get("execution_error_zeroes")
        != counts["executed"]
        or training != expected_training
        or recovery
        != {
            "state": "not_attempted",
            "eligible_rows": trace_audit.get("zero_model_error_zeroes"),
            "recovered_rows": 0,
            "source_row_set_sha256": trace_audit.get("zero_model_row_set_sha256"),
            "model_attempts_preserved": True,
            "requires_new_versioned_supersession_for_recovered_rows": True,
        }
    ):
        raise StockSmallError("tb4_gate_trace_invalid")
    del rows
    return canonical, body, semantics_binding


def _validate_tb4_gate(
    path: Path,
    expected_sha256: str,
    production_root: Path,
    held: split._HeldArtifactSet | None = None,
) -> tuple[Path, bytes, dict[str, Any]]:
    with ExitStack() as stack:
        effective_held = held
        if effective_held is None:
            effective_held = split._HeldArtifactSet.create()
            stack.callback(effective_held.close)
        body = _read(path, code="tb4_gate_invalid", private=True, held=effective_held)
        if _sha256(body) != expected_sha256:
            raise StockSmallError("tb4_gate_invalid")
        value = _json(body, code="tb4_gate_invalid")
        artifacts = value.get("artifacts")
        executed = artifacts.get("executed_results") if isinstance(artifacts, dict) else None
        if not isinstance(executed, dict) or set(executed) != {"path", "bytes", "sha256"}:
            raise StockSmallError("tb4_gate_invalid")
        run_dir = Path(str(executed["path"])).parent
        if Path(str(executed["path"])) != run_dir / "results.jsonl" or run_dir != split._absolute_path(run_dir):
            raise StockSmallError("tb4_gate_invalid")
        try:
            evidence = split._open_held_run_evidence(run_dir)
            if evidence.root != run_dir:
                raise StockSmallError("tb4_gate_invalid")
            stack.callback(evidence.close)
            writer_lock = stack.enter_context(split._open_private_writer_lock_at(evidence.directory, ".writer.lock"))
            router_lock = stack.enter_context(
                split._open_private_writer_lock(split._router_lock_path(evidence.files["eval_run_identity.json"].body))
            )
            for lock in (writer_lock, router_lock):
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError, RuntimeError, ValueError) as error:
            raise StockSmallError("tb4_gate_run_active_or_invalid") from error
        result = _validate_tb4_gate_locked(
            path,
            expected_sha256,
            production_root,
            evidence,
            effective_held,
        )
        evidence.revalidate()
        effective_held.revalidate()
        return result


def _split_members(members: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    if len(members) != TOTAL_TASKS or len(set(members)) != TOTAL_TASKS:
        raise StockSmallError("selector_invalid")
    shards = tuple(tuple(members[index::SHARD_COUNT]) for index in range(SHARD_COUNT))
    flattened = tuple(member for offset in range(SHARD_COUNT) for member in shards[offset])
    if (
        len(flattened) != TOTAL_TASKS
        or set(flattened) != set(members)
        or any(not 1 <= len(shard) <= MAX_SHARD_TASKS for shard in shards)
    ):
        raise StockSmallError("shard_partition_invalid")
    return shards


def _render_config(
    base: Mapping[str, Any],
    *,
    count: int,
    selector: Path,
    selector_sha256: str,
    dataset: Path,
    image_manifest: Path,
) -> bytes:
    value = copy.deepcopy(dict(base))
    value["num_tasks"] = count
    taskset = value["taskset"]
    taskset["dataset_dir"] = str(dataset)
    taskset["task_file"] = str(selector)
    taskset["task_file_sha256"] = selector_sha256
    taskset["image_manifest"] = str(image_manifest)
    return union._render_toml(value)


def _contracts(binding: StockEndpointBinding | None = None) -> dict[str, Any]:
    endpoint_identifier = binding.deployment_id if binding is not None else ENDPOINT_IDENTIFIER
    return {
        "model": MODEL,
        "harness": {"id": "mini-swe-agent", "version": "2.4.6"},
        "total_tasks": TOTAL_TASKS,
        "shards": SHARD_COUNT,
        "shard_algorithm": "canonical-order-round-robin-v1",
        "max_tasks_per_shard": MAX_SHARD_TASKS,
        "rollout_concurrency": CONCURRENCY,
        "context_tokens": MAX_SEQUENCE_TOKENS,
        "sample_tokens": SAMPLE_TOKENS,
        "reasoning_effort": "max",
        "reasoning_required": True,
        "reasoning_message_parity_required": True,
        "model_io_response_kind": "exact_provider_json",
        "request_graph_match_required": True,
        "model_attempts": 1,
        "model_retries": 0,
        "guest_transport_retry_attempts": 10,
        "logical_request_upstream_attempts": 1,
        "transport_evidence": {
            "schema": "logical-exact-once-v1",
            "source": "per-runtime-mode-0600-summary-records",
            "records_per_task": 1,
            "router_proxy_trace_binding_required": True,
            "terminal_provider_statuses": ["429", "5xx"],
            "proxy_exception_records": 0,
        },
        "zero_model_resume_attempts": 0,
        "model_bearing_errors_terminal": True,
        "model_bearing_error_schemas": {
            "HarnessError": ["message", "traceback", "type"],
            "ProviderError": ["message", "type"],
            "SandboxError": ["message", "traceback", "type"],
        },
        "shared_verifier_terminal_transport_disposition": dict(SHARED_VERIFIER_TERMINAL_TRANSPORT_DISPOSITION),
        "verifier_recovery": {
            "mode": "same-post-agent-runtime-background-single-attempt",
            "retries": 0,
            "maximum_attempts": 1,
            "model_calls": 0,
            "infrastructure_errors_remain_errors": True,
            "posthoc_recovery": False,
        },
        "timeouts": {
            "request_seconds": REQUEST_TIMEOUT_SECONDS,
            "session_seconds": SESSION_TIMEOUT_SECONDS,
            "rollout_seconds": ROLLOUT_TIMEOUT_SECONDS,
            "shell_action_seconds": SHELL_ACTION_TIMEOUT_SECONDS,
            "setup_seconds": 3_600,
            "finalize_seconds": 3_600,
            "scoring_seconds": 21_600,
        },
        "sandbox": {
            "provider": "sandoq",
            "environment": "oci-runner-firecracker-small",
            "task_network": "host",
            "effective_network": "public",
            "resource_caps": {
                "cpu": CPU_CAP,
                "memory_mb": MEMORY_MB_CAP,
                "storage_mb": STORAGE_MB_CAP,
            },
            "capacity": CONCURRENCY,
            "provisioning_retries": PROVISIONING_RETRIES,
            "provisioning_retry_scope": "pre-model-only",
        },
        "router": {
            "profile": CAPACITY_PROFILE,
            "endpoint_identifier": endpoint_identifier,
            "worker_count": 1,
            "per_worker_capacity": CONCURRENCY,
            "policy": "consistent_hash",
            "request_id_headers": ["x-session-id"],
            "retries": 0,
        },
        "prelaunch_gates": {
            "tb4": {
                "minimum_passes": MINIMUM_TB4_PASSES,
                "denominator": 66,
                "response_kind": "exact_provider_json",
            },
            "real_task_image_c64_soak": {
                "kind": task_image_soak.RECEIPT_KIND,
                "task_count": task_image_soak.SELECTED_TASKS,
                "concurrency": task_image_soak.CONCURRENCY,
                "minimum_endpoint_remaining_seconds": (task_image_soak.MINIMUM_ENDPOINT_REMAINING_SECONDS),
                "model_calls": 0,
                "harness_invocations": 0,
            },
        },
        "resume": {
            "unit": "completed-shard-receipt",
            "partial_attempt_reuse": False,
            "model_bearing_retry": False,
            "zero_model_rows": "uncertifiable-manual-recovery",
            "cross_job": True,
            "endpoint_epoch_bound": True,
            "rollover_policy": "new-plan-required",
        },
        "security_task_handling": "opaque-execution-aggregate-only",
        "membership_disclosed": False,
    }


def materialize(
    *,
    project_root: Path,
    expected_revision: str,
    source: Path,
    dataset: Path,
    image_manifest: Path,
    tb4_certificate: Path,
    tb4_certificate_sha256: str,
    task_image_soak_receipt: Path,
    task_image_soak_receipt_sha256: str,
    output: Path,
    run_root: Path,
    stock_capacity: Path = STOCK_CAPACITY,
    stock_capacity_sha256: str = STOCK_CAPACITY_SHA256,
    sandoq_capacity: Path = SANDOQ_CAPACITY,
    sandoq_capacity_sha256: str = SANDOQ_CAPACITY_SHA256,
) -> dict[str, Any]:
    root = _validate_source(project_root, expected_revision)
    if not output.is_absolute() or not run_root.is_absolute():
        raise StockSmallError("output_namespace_invalid")
    if output.exists() or output.is_symlink() or run_root.exists() or run_root.is_symlink():
        raise StockSmallError("output_namespace_not_fresh")
    try:
        run_root_parent = legacy._private_root(run_root.parent)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("run_root_parent_invalid") from error
    if run_root != run_root_parent / run_root.name or run_root.name in {"", ".", ".."}:
        raise StockSmallError("run_root_parent_invalid")
    base, base_body, base_path = _load_base()
    provider_path, provider_body = _validate_provider_profile()
    stock_path, stock_body, binding = _validate_stock_capacity(stock_capacity, stock_capacity_sha256)
    dynamic_binding = (
        stock_path != STOCK_CAPACITY
        or stock_capacity_sha256 != STOCK_CAPACITY_SHA256
    )
    sandoq_path, sandoq_body = _validate_sandoq_capacity(sandoq_capacity, sandoq_capacity_sha256)
    tb4_path, tb4_body, tb4_semantics = _validate_tb4_gate(
        tb4_certificate,
        tb4_certificate_sha256,
        root,
    )
    try:
        task_soak_path, task_soak_body = task_image_soak.validate_task_image_soak_receipt(
            task_image_soak_receipt,
            task_image_soak_receipt_sha256,
            expected_revision=expected_revision,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("task_image_soak_receipt_invalid") from error
    task_soak_value = _json(task_soak_body, code="task_image_soak_receipt_invalid")
    task_soak_epoch = task_soak_value.get("endpoint_epoch")
    if (
        not isinstance(task_soak_epoch, dict)
        or task_soak_epoch.get("capacity_receipt_sha256") != binding.capacity_receipt_sha256
        or task_soak_epoch.get("endpoint_jobs_sha256") != binding.endpoint_jobs_sha256
        or (
            dynamic_binding
            and task_soak_value.get("endpoint_binding") != binding.public_record
        )
    ):
        raise StockSmallError("task_image_soak_endpoint_binding_invalid")
    source_path = source.resolve(strict=True)
    source_body = _read(source_path, code="approved_source_invalid")
    if source_path != legacy._canonical_source_path() or _sha256(source_body) != legacy.CANONICAL_SOURCE_SHA256:
        raise StockSmallError("approved_source_invalid")
    try:
        dataset_path = legacy.verify_canonical_dataset(dataset)
        partition = legacy.derive_partition(source_body, dataset_path)
    except Exception as error:
        raise StockSmallError("opaque_selection_invalid") from error
    if (
        partition.no_network_count != legacy.EXPECTED_SOURCE_COUNT
        or len(partition.sandoq) != TOTAL_TASKS
        or len(partition.vmvm) != legacy.EXPECTED_EXCLUDED_COUNT
    ):
        raise StockSmallError("opaque_selection_invalid")
    image_path = image_manifest.resolve(strict=True)
    image_body = _read(image_path, code="image_manifest_invalid", maximum_bytes=128 * 1024 * 1024)
    if _sha256(image_body) != IMAGE_MANIFEST_SHA256:
        raise StockSmallError("image_manifest_invalid")

    master_body = legacy._task_payload(partition.sandoq)
    master_receipt = legacy._selector_receipt(
        master_body,
        legacy._resource_coverage(dataset_path, partition.sandoq),
    )
    shards = _split_members(partition.sandoq)
    plan_files: dict[str, bytes] = {
        "selector.tasks.txt": master_body,
        "selector.receipt.json": legacy.canonical_json(master_receipt),
    }
    shard_records: list[dict[str, Any]] = []
    for index, members in enumerate(shards):
        selector_name = f"shard-{index:02d}.tasks.txt"
        config_name = f"shard-{index:02d}.toml"
        selector_path = output / selector_name
        config_path = output / config_name
        selector_body = legacy._task_payload(members)
        config_body = _render_config(
            base,
            count=len(members),
            selector=selector_path,
            selector_sha256=_sha256(selector_body),
            dataset=dataset_path,
            image_manifest=image_path,
        )
        plan_files[selector_name] = selector_body
        plan_files[config_name] = config_body
        shard_records.append(
            {
                "index": index,
                "count": len(members),
                "selector": _artifact(selector_path, selector_body),
                "config": _artifact(config_path, config_body),
                "run_root": str(run_root / f"shard-{index:02d}"),
            }
        )
    plan = {
        "schema_version": DYNAMIC_SCHEMA_VERSION if dynamic_binding else SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "state": "authorized",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "source_revision": expected_revision,
        "contracts": _contracts(binding if dynamic_binding else None),
        "source": {
            "project_root": str(root),
            "approved_selector_source": _artifact(source_path, source_body),
            "dataset": {"path": str(dataset_path), "revision": legacy.CANONICAL_DATASET_REVISION},
            "image_manifest": _artifact(image_path, image_body),
            "base_config": _artifact(base_path, base_body),
            "provider_profile": _artifact(provider_path, provider_body),
            "tb4_gate": _artifact(tb4_path, tb4_body),
            "task_image_c64_soak": _artifact(task_soak_path, task_soak_body),
            "stock_model_c64": _artifact(stock_path, stock_body),
            "sandoq_small_c64": _artifact(sandoq_path, sandoq_body),
        },
        "qualification": {"tb4_execution_semantics": tb4_semantics},
        "selection": {
            "approved_count": legacy.EXPECTED_SOURCE_COUNT,
            "selected_count": TOTAL_TASKS,
            "excluded_count": legacy.EXPECTED_EXCLUDED_COUNT,
            "selector": _artifact(output / "selector.tasks.txt", master_body),
            "receipt": _artifact(output / "selector.receipt.json", legacy.canonical_json(master_receipt)),
        },
        "run_root": str(run_root),
        "shards": shard_records,
    }
    if dynamic_binding:
        plan["endpoint_binding"] = binding.public_record
    plan["plan_sha256"] = _sha256(_canonical(plan))
    plan_files["plan.json"] = _canonical(plan)
    try:
        split._publish_private_bundle(output, plan_files)
        os.mkdir(run_root, 0o700)
    except Exception as error:
        raise StockSmallError("publication_failed") from error
    return {
        "state": "authorized",
        "selected_tasks": TOTAL_TASKS,
        "shards": SHARD_COUNT,
        "maximum_shard_tasks": max(map(len, shards)),
        "plan": str(output / "plan.json"),
        "plan_sha256": _sha256(plan_files["plan.json"]),
    }


def _record_body(
    record: object,
    *,
    code: str,
    private: bool,
    held: split._HeldArtifactSet,
) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise StockSmallError(code)
    path = Path(str(record.get("path", "")))
    body = _read(path, code=code, private=private, held=held, maximum_bytes=512 * 1024 * 1024)
    if record != _artifact(path, body):
        raise StockSmallError(code)
    return path, body


def _verify_with_held(
    plan_path: Path,
    plan_sha256: str,
    held: split._HeldArtifactSet,
) -> dict[str, Any]:
    body = _read(plan_path, code="plan_invalid", private=True, held=held)
    if _sha256(body) != plan_sha256:
        raise StockSmallError("plan_invalid")
    plan = _json(body, code="plan_invalid")
    unsigned = dict(plan)
    claimed = unsigned.pop("plan_sha256", None)
    schema_version = plan.get("schema_version")
    dynamic_binding = schema_version == DYNAMIC_SCHEMA_VERSION
    expected_plan_keys = {
        "schema_version",
        "kind",
        "state",
        "deployment_namespace",
        "source_revision",
        "contracts",
        "source",
        "qualification",
        "selection",
        "run_root",
        "shards",
        "plan_sha256",
    }
    if dynamic_binding:
        expected_plan_keys.add("endpoint_binding")
    if (
        set(plan) != expected_plan_keys
        or schema_version not in {SCHEMA_VERSION, DYNAMIC_SCHEMA_VERSION}
        or plan.get("kind") != PLAN_KIND
        or plan.get("state") != "authorized"
        or plan.get("deployment_namespace") != DEPLOYMENT_NAMESPACE
        or claimed != _sha256(_canonical(unsigned))
        or not isinstance(plan.get("source"), dict)
        or not isinstance(plan.get("qualification"), dict)
        or not isinstance(plan.get("selection"), dict)
        or not isinstance(plan.get("shards"), list)
        or len(plan["shards"]) != SHARD_COUNT
        or REVISION_RE.fullmatch(str(plan.get("source_revision", ""))) is None
    ):
        raise StockSmallError("plan_invalid")
    source = plan["source"]
    if set(source) != {
        "project_root",
        "approved_selector_source",
        "dataset",
        "image_manifest",
        "base_config",
        "provider_profile",
        "tb4_gate",
        "task_image_c64_soak",
        "stock_model_c64",
        "sandoq_small_c64",
    } or set(plan["selection"]) != {
        "approved_count",
        "selected_count",
        "excluded_count",
        "selector",
        "receipt",
    }:
        raise StockSmallError("plan_invalid")
    project_root = Path(str(source.get("project_root", "")))
    _validate_source(project_root, str(plan["source_revision"]))
    records: dict[str, tuple[Path, bytes]] = {}
    for key, private in (
        ("approved_selector_source", False),
        ("image_manifest", False),
        ("base_config", False),
        ("provider_profile", False),
        ("tb4_gate", True),
        ("task_image_c64_soak", True),
        ("stock_model_c64", True),
        ("sandoq_small_c64", True),
    ):
        records[key] = _record_body(source.get(key), code=f"{key}_invalid", private=private, held=held)
    dataset = source.get("dataset")
    if not isinstance(dataset, dict) or set(dataset) != {"path", "revision"}:
        raise StockSmallError("dataset_invalid")
    dataset_path = Path(str(dataset["path"])).resolve(strict=True)
    if dataset.get("revision") != legacy.CANONICAL_DATASET_REVISION:
        raise StockSmallError("dataset_invalid")
    if (
        records["approved_selector_source"][0] != legacy._canonical_source_path()
        or _sha256(records["approved_selector_source"][1]) != legacy.CANONICAL_SOURCE_SHA256
        or _sha256(records["image_manifest"][1]) != IMAGE_MANIFEST_SHA256
        or _sha256(records["base_config"][1]) != BASE_CONFIG_SHA256
        or _sha256(records["provider_profile"][1]) != PROVIDER_PROFILE_SHA256
    ):
        raise StockSmallError("plan_source_invalid")
    stock_path, _stock_body, binding = _validate_stock_capacity(
        records["stock_model_c64"][0],
        str(source["stock_model_c64"].get("sha256", "")),
        held,
    )
    if not dynamic_binding and (
        stock_path != STOCK_CAPACITY
        or binding.capacity_receipt_sha256 != STOCK_CAPACITY_SHA256
        or binding.deployment_id != ENDPOINT_IDENTIFIER
        or binding.source_spec_sha256 != SOURCE_SPEC_SHA256
        or binding.source_proxy_config_sha256 != SOURCE_PROXY_SHA256
        or binding.endpoint_bundle_sha256 != ENDPOINT_BUNDLE_SHA256
    ):
        raise StockSmallError("stock_capacity_receipt_invalid")
    if (
        plan.get("contracts") != _contracts(binding if dynamic_binding else None)
        or (dynamic_binding and plan.get("endpoint_binding") != binding.public_record)
    ):
        raise StockSmallError("endpoint_binding_invalid")
    _validate_sandoq_capacity(records["sandoq_small_c64"][0], SANDOQ_CAPACITY_SHA256, held)
    _tb4_path, _tb4_body, tb4_semantics = _validate_tb4_gate(
        records["tb4_gate"][0],
        _sha256(records["tb4_gate"][1]),
        project_root,
        held,
    )
    if plan["qualification"] != {"tb4_execution_semantics": tb4_semantics}:
        raise StockSmallError("tb4_execution_semantics_invalid")
    try:
        task_image_soak.validate_task_image_soak_receipt(
            records["task_image_c64_soak"][0],
            _sha256(records["task_image_c64_soak"][1]),
            expected_revision=str(plan["source_revision"]),
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("task_image_soak_receipt_invalid") from error
    task_soak_value = _json(
        records["task_image_c64_soak"][1],
        code="task_image_soak_receipt_invalid",
    )
    task_soak_epoch = task_soak_value.get("endpoint_epoch")
    if (
        not isinstance(task_soak_epoch, dict)
        or task_soak_epoch.get("capacity_receipt_sha256") != binding.capacity_receipt_sha256
        or task_soak_epoch.get("endpoint_jobs_sha256") != binding.endpoint_jobs_sha256
        or (dynamic_binding and task_soak_value.get("endpoint_binding") != binding.public_record)
    ):
        raise StockSmallError("task_image_soak_endpoint_binding_invalid")
    try:
        partition = legacy.derive_partition(
            records["approved_selector_source"][1],
            legacy.verify_canonical_dataset(dataset_path),
        )
    except Exception as error:
        raise StockSmallError("opaque_selection_invalid") from error
    members = tuple(partition.sandoq)
    shards = _split_members(members)
    master_path, master_body = _record_body(
        plan["selection"].get("selector"), code="selector_invalid", private=True, held=held
    )
    receipt_path, receipt_body = _record_body(
        plan["selection"].get("receipt"), code="selector_receipt_invalid", private=True, held=held
    )
    expected_master = legacy._task_payload(members)
    expected_receipt = legacy._selector_receipt(
        expected_master,
        legacy._resource_coverage(dataset_path, members),
    )
    if (
        master_body != expected_master
        or receipt_body != legacy.canonical_json(expected_receipt)
        or plan["selection"].get("approved_count") != legacy.EXPECTED_SOURCE_COUNT
        or plan["selection"].get("selected_count") != TOTAL_TASKS
        or plan["selection"].get("excluded_count") != legacy.EXPECTED_EXCLUDED_COUNT
    ):
        raise StockSmallError("selector_invalid")
    base, _base_body, _base_path = _load_base(held)
    image_path = records["image_manifest"][0]
    run_root = Path(str(plan.get("run_root", "")))
    if not run_root.is_absolute() or run_root.resolve(strict=True) != run_root:
        raise StockSmallError("run_root_invalid")
    observed_records: list[dict[str, Any]] = []
    for index, (record, expected_members) in enumerate(zip(plan["shards"], shards, strict=True)):
        if not isinstance(record, dict) or record.get("index") != index or record.get("count") != len(expected_members):
            raise StockSmallError("shard_invalid")
        selector_path, selector_body = _record_body(
            record.get("selector"), code="shard_selector_invalid", private=True, held=held
        )
        config_path, config_body = _record_body(
            record.get("config"), code="shard_config_invalid", private=True, held=held
        )
        expected_selector = legacy._task_payload(expected_members)
        expected_config = _render_config(
            base,
            count=len(expected_members),
            selector=selector_path,
            selector_sha256=_sha256(expected_selector),
            dataset=dataset_path,
            image_manifest=image_path,
        )
        if (
            selector_body != expected_selector
            or config_body != expected_config
            or record.get("run_root") != str(run_root / f"shard-{index:02d}")
        ):
            raise StockSmallError("shard_invalid")
        observed_records.append(record)
    del master_path, receipt_path, observed_records
    held.revalidate()
    return plan


def verify(plan_path: Path, plan_sha256: str) -> dict[str, Any]:
    held = split._HeldArtifactSet.create()
    try:
        return _verify_with_held(plan_path.resolve(strict=True), plan_sha256, held)
    finally:
        held.close()


def _plan_endpoint_binding(plan: Mapping[str, Any]) -> StockEndpointBinding:
    source = plan.get("source")
    record = source.get("stock_model_c64") if isinstance(source, dict) else None
    if not isinstance(record, dict):
        raise StockSmallError("stock_capacity_receipt_invalid")
    try:
        binding, _body = load_capacity_binding(
            Path(str(record.get("path", ""))),
            str(record.get("sha256", "")),
        )
    except (OSError, RuntimeError, ValueError, StockEndpointBindingError) as error:
        raise StockSmallError("stock_capacity_receipt_invalid") from error
    if plan.get("schema_version") == DYNAMIC_SCHEMA_VERSION:
        if plan.get("endpoint_binding") != binding.public_record:
            raise StockSmallError("endpoint_binding_invalid")
    elif (
        binding.deployment_id != ENDPOINT_IDENTIFIER
        or binding.capacity_receipt_sha256 != STOCK_CAPACITY_SHA256
        or binding.source_spec_sha256 != SOURCE_SPEC_SHA256
        or binding.source_proxy_config_sha256 != SOURCE_PROXY_SHA256
        or binding.endpoint_bundle_sha256 != ENDPOINT_BUNDLE_SHA256
    ):
        raise StockSmallError("stock_capacity_receipt_invalid")
    return binding


def shard_binding(plan_path: Path, plan_sha256: str, index: int) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    binding = _plan_endpoint_binding(plan)
    if not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_index_invalid")
    shard = plan["shards"][index]
    return {
        "plan": str(plan_path.resolve(strict=True)),
        "plan_sha256": plan_sha256,
        "source_revision": plan["source_revision"],
        "index": index,
        "count": shard["count"],
        "selector": shard["selector"]["path"],
        "selector_sha256": shard["selector"]["sha256"],
        "config": shard["config"]["path"],
        "config_sha256": shard["config"]["sha256"],
        "run_root": shard["run_root"],
        "endpoint_identifier": binding.deployment_id,
        "deployment_root": str(binding.deployment_root),
        "stock_capacity": str(binding.capacity_receipt_path),
        "stock_capacity_sha256": binding.capacity_receipt_sha256,
        "endpoint_jobs_sha256": binding.endpoint_jobs_sha256,
    }


def _validated_worker_manifest(
    path: Path,
    expected_sha256: str,
    binding: StockEndpointBinding,
) -> tuple[Path, bytes, dict[str, Any]]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise StockSmallError("worker_manifest_invalid")
    try:
        canonical = path.resolve(strict=True)
        body = _read(canonical, code="worker_manifest_invalid", private=True)
        from direct_kimi_workers import validate_saved_manifest

        manifest = validate_saved_manifest(canonical, body=body)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("worker_manifest_invalid") from error
    router = manifest.get("router")
    workers = manifest.get("workers")
    dynamic_manifest = manifest.get("schema_version") == 6
    if (
        canonical != path
        or _sha256(body) != expected_sha256
        or manifest.get("source_spec_sha256") != binding.source_spec_sha256
        or manifest.get("source_proxy_config_sha256") != binding.source_proxy_config_sha256
        or manifest.get("endpoint_bundle_sha256") != binding.endpoint_bundle_sha256
        or (
            dynamic_manifest
            and manifest.get("stock_capacity")
            != {
                "path": str(binding.capacity_receipt_path),
                "sha256": binding.capacity_receipt_sha256,
            }
        )
        or (not dynamic_manifest and binding.capacity_receipt_sha256 != STOCK_CAPACITY_SHA256)
        or not isinstance(router, dict)
        or router.get("capacity_profile") != CAPACITY_PROFILE
        or router.get("endpoint_identifier") != binding.deployment_id
        or router.get("max_concurrent_requests") != CONCURRENCY
        or router.get("per_worker_capacity") != CONCURRENCY
        or router.get("request_timeout_seconds") != REQUEST_TIMEOUT_SECONDS
        or router.get("retries") != 0
        or not isinstance(workers, list)
        or len(workers) != 1
    ):
        raise StockSmallError("worker_manifest_invalid")
    return canonical, body, manifest


def _capacity_endpoint_jobs_sha256(plan: Mapping[str, Any]) -> str:
    record = plan.get("source", {}).get("stock_model_c64")
    if not isinstance(record, dict):
        raise StockSmallError("stock_capacity_receipt_invalid")
    body = _read(
        Path(str(record.get("path", ""))),
        code="stock_capacity_receipt_invalid",
        private=True,
    )
    if record != _artifact(Path(str(record.get("path", ""))), body):
        raise StockSmallError("stock_capacity_receipt_invalid")
    value = _json(body, code="stock_capacity_receipt_invalid")
    endpoint_job_id = value.get("deployment", {}).get("endpoint_job_id")
    if not isinstance(endpoint_job_id, str) or re.fullmatch(r"[1-9][0-9]*", endpoint_job_id) is None:
        raise StockSmallError("stock_capacity_receipt_invalid")
    return _sha256(f"{endpoint_job_id}\n".encode())


def create_launch(
    *,
    plan_path: Path,
    plan_sha256: str,
    index: int,
    worker_manifest: Path,
    worker_manifest_sha256: str,
    run_dir: Path,
    output: Path,
) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    binding = _plan_endpoint_binding(plan)
    if not 0 <= index < SHARD_COUNT or SHA256_RE.fullmatch(worker_manifest_sha256) is None:
        raise StockSmallError("shard_launch_invalid")
    shard = plan["shards"][index]
    manifest_path, manifest_body, manifest = _validated_worker_manifest(
        worker_manifest,
        worker_manifest_sha256,
        binding,
    )
    router = manifest.get("router")
    if not isinstance(router, dict) or SHA256_RE.fullmatch(str(router.get("implementation_sha256", ""))) is None:
        raise StockSmallError("worker_manifest_invalid")
    shard_root = Path(shard["run_root"])
    if (
        not run_dir.is_absolute()
        or run_dir.parent != shard_root
        or not re.fullmatch(r"attempt-[1-9][0-9]*", run_dir.name)
        or run_dir.exists()
        or run_dir.is_symlink()
    ):
        raise StockSmallError("run_directory_invalid")
    deployment = {
        "capacity_profile": CAPACITY_PROFILE,
        "endpoint_identifier": binding.deployment_id,
        "endpoint_bundle_sha256": binding.endpoint_bundle_sha256,
        "source_spec_sha256": binding.source_spec_sha256,
        "router_implementation_sha256": router.get("implementation_sha256"),
        "endpoint_jobs_sha256": _capacity_endpoint_jobs_sha256(plan),
        "worker_count": 1,
        "per_worker_capacity": CONCURRENCY,
    }
    if plan["schema_version"] == DYNAMIC_SCHEMA_VERSION:
        deployment.update(
            {
                "source_proxy_config_sha256": binding.source_proxy_config_sha256,
                "capacity_receipt_sha256": binding.capacity_receipt_sha256,
            }
        )
    value = {
        "schema_version": plan["schema_version"],
        "kind": LAUNCH_KIND,
        "state": "authorized",
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "source_revision": plan["source_revision"],
        "shard": {
            "index": index,
            "count": shard["count"],
            "selector": shard["selector"],
            "config": shard["config"],
        },
        "run_dir": str(run_dir),
        "worker_manifest": _artifact(manifest_path, manifest_body),
        "deployment": deployment,
        "execution": {
            "requested_concurrency": CONCURRENCY,
            "pool_size": CONCURRENCY,
            "sandbox_environment": "oci-runner-firecracker-small",
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "provisioning_retries": PROVISIONING_RETRIES,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "session_timeout_seconds": SESSION_TIMEOUT_SECONDS,
            "rollout_timeout_seconds": ROLLOUT_TIMEOUT_SECONDS,
            "shell_action_timeout_seconds": SHELL_ACTION_TIMEOUT_SECONDS,
            "model_retries": 0,
            "guest_transport_retry_attempts": 10,
            "logical_request_upstream_attempts": 1,
            "zero_model_resume_attempts": 0,
            "verifier_runtime_retries": 0,
            "verifier_retry_mode": "same-post-agent-runtime-background-single-attempt",
        },
        "capture": {
            "response_kind": "exact_provider_json",
            "reasoning": True,
            "request_graph": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        },
    }
    value["launch_sha256"] = _sha256(_canonical(value))
    try:
        legacy._publish_bundle(output.parent, {output: _canonical(value)})
    except Exception as error:
        raise StockSmallError("shard_launch_publication_failed") from error
    return {
        "state": "authorized",
        "shard": index,
        "count": shard["count"],
        "launch": str(output),
        "launch_sha256": _sha256(_canonical(value)),
    }


def validate_launch(
    launch_path: Path,
    launch_sha256: str,
    *,
    config_sha256: str | None = None,
    selector_sha256: str | None = None,
    worker_manifest_sha256: str | None = None,
    source_spec_sha256: str | None = None,
    endpoint_bundle_sha256: str | None = None,
    router_implementation_sha256: str | None = None,
    concurrency: int | None = None,
) -> dict[str, Any]:
    body = _read(launch_path, code="shard_launch_invalid", private=True)
    if _sha256(body) != launch_sha256:
        raise StockSmallError("shard_launch_invalid")
    value = _json(body, code="shard_launch_invalid")
    unsigned = dict(value)
    claimed = unsigned.pop("launch_sha256", None)
    plan_record = value.get("plan")
    shard_record = value.get("shard")
    deployment = value.get("deployment")
    execution = value.get("execution")
    manifest_record = value.get("worker_manifest")
    if (
        value.get("schema_version") not in {SCHEMA_VERSION, DYNAMIC_SCHEMA_VERSION}
        or value.get("kind") != LAUNCH_KIND
        or value.get("state") != "authorized"
        or claimed != _sha256(_canonical(unsigned))
        or not isinstance(plan_record, dict)
        or set(plan_record) != {"path", "sha256"}
        or SHA256_RE.fullmatch(str(plan_record.get("sha256", ""))) is None
        or not isinstance(shard_record, dict)
        or not isinstance(deployment, dict)
        or not isinstance(execution, dict)
        or not isinstance(manifest_record, dict)
        or set(manifest_record) != {"path", "bytes", "sha256"}
        or value.get("capture")
        != {
            "response_kind": "exact_provider_json",
            "reasoning": True,
            "request_graph": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        }
    ):
        raise StockSmallError("shard_launch_invalid")
    plan = verify(Path(str(plan_record["path"])), str(plan_record["sha256"]))
    binding = _plan_endpoint_binding(plan)
    index = shard_record.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_launch_invalid")
    expected_shard = plan["shards"][index]
    run_dir = Path(str(value.get("run_dir", "")))
    if (
        value.get("schema_version") != plan["schema_version"]
        or value.get("source_revision") != plan["source_revision"]
        or shard_record
        != {
            "index": index,
            "count": expected_shard["count"],
            "selector": expected_shard["selector"],
            "config": expected_shard["config"],
        }
        or deployment
        != {
            "capacity_profile": CAPACITY_PROFILE,
            "endpoint_identifier": binding.deployment_id,
            "endpoint_bundle_sha256": binding.endpoint_bundle_sha256,
            "source_spec_sha256": binding.source_spec_sha256,
            "router_implementation_sha256": deployment.get("router_implementation_sha256"),
            "endpoint_jobs_sha256": _capacity_endpoint_jobs_sha256(plan),
            "worker_count": 1,
            "per_worker_capacity": CONCURRENCY,
            **(
                {
                    "source_proxy_config_sha256": binding.source_proxy_config_sha256,
                    "capacity_receipt_sha256": binding.capacity_receipt_sha256,
                }
                if plan["schema_version"] == DYNAMIC_SCHEMA_VERSION
                else {}
            ),
        }
        or SHA256_RE.fullmatch(str(deployment.get("router_implementation_sha256", ""))) is None
        or execution
        != {
            "requested_concurrency": CONCURRENCY,
            "pool_size": CONCURRENCY,
            "sandbox_environment": "oci-runner-firecracker-small",
            "provider_profile_sha256": PROVIDER_PROFILE_SHA256,
            "provisioning_retries": PROVISIONING_RETRIES,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "session_timeout_seconds": SESSION_TIMEOUT_SECONDS,
            "rollout_timeout_seconds": ROLLOUT_TIMEOUT_SECONDS,
            "shell_action_timeout_seconds": SHELL_ACTION_TIMEOUT_SECONDS,
            "model_retries": 0,
            "guest_transport_retry_attempts": 10,
            "logical_request_upstream_attempts": 1,
            "zero_model_resume_attempts": 0,
            "verifier_runtime_retries": 0,
            "verifier_retry_mode": "same-post-agent-runtime-background-single-attempt",
        }
        or not run_dir.is_absolute()
        or Path(os.path.normpath(run_dir)) != run_dir
        or run_dir.parent != Path(expected_shard["run_root"])
        or re.fullmatch(r"attempt-[1-9][0-9]*", run_dir.name) is None
    ):
        raise StockSmallError("shard_launch_invalid")
    assert isinstance(manifest_record, dict)
    manifest_path, manifest_body, manifest = _validated_worker_manifest(
        Path(str(manifest_record["path"])),
        str(manifest_record["sha256"]),
        binding,
    )
    if manifest_record != _artifact(manifest_path, manifest_body):
        raise StockSmallError("shard_launch_invalid")
    manifest_router = manifest.get("router")
    if not isinstance(manifest_router, dict) or manifest_router.get("implementation_sha256") != deployment.get(
        "router_implementation_sha256"
    ):
        raise StockSmallError("shard_launch_invalid")
    checks = {
        "config": (config_sha256, expected_shard["config"]["sha256"]),
        "selector": (selector_sha256, expected_shard["selector"]["sha256"]),
        "worker_manifest": (worker_manifest_sha256, manifest_record.get("sha256")),
        "source_spec": (source_spec_sha256, binding.source_spec_sha256),
        "endpoint_bundle": (endpoint_bundle_sha256, binding.endpoint_bundle_sha256),
        "router_implementation": (router_implementation_sha256, deployment.get("router_implementation_sha256")),
    }
    if any(observed is not None and observed != expected for observed, expected in checks.values()):
        raise StockSmallError("shard_launch_binding_invalid")
    if concurrency is not None and concurrency != CONCURRENCY:
        raise StockSmallError("shard_launch_binding_invalid")
    return value


def _task_slug(trace: Mapping[str, Any]) -> str:
    try:
        return audit_traces._task_slug(trace)
    except Exception as error:
        raise StockSmallError("trace_identity_invalid") from error


def _error_types(errors: object) -> tuple[str, ...]:
    if not isinstance(errors, list) or not errors:
        raise StockSmallError("trace_errors_invalid")
    types: list[str] = []
    for error in errors:
        error_type = error.get("type") if isinstance(error, dict) else None
        expected_keys = {"message", "type"} if error_type == "ProviderError" else {"message", "traceback", "type"}
        if (
            not isinstance(error, dict)
            or set(error) != expected_keys
            or error_type not in ALLOWED_ERROR_TYPES
            or not isinstance(error.get("message"), str)
            or not error["message"]
            or (error_type != "ProviderError" and not isinstance(error.get("traceback"), str))
        ):
            raise StockSmallError("trace_errors_invalid")
        types.append(error_type)
    return tuple(types)


def _is_shared_verifier_terminal_transport(row: dict[str, Any]) -> bool:
    info = row.get("info")
    verifier = info.get("terminal_bench_verifier") if isinstance(info, dict) else None
    return (
        audit_traces._clean_stop_problem(row) is None
        and verifier == SHARED_VERIFIER_TERMINAL_TRANSPORT_DISPOSITION
    )


def audit_results(results: Path, selector: Path) -> dict[str, Any]:
    selector_body = _read(selector, code="selector_invalid", private=True, maximum_bytes=4 * 1024 * 1024)
    try:
        members = tuple(selector_body.decode("utf-8").splitlines())
    except UnicodeDecodeError as error:
        raise StockSmallError("selector_invalid") from error
    if not members or len(members) > MAX_SHARD_TASKS or len(members) != len(set(members)):
        raise StockSmallError("selector_invalid")
    expected = frozenset(members)
    if (
        not results.is_absolute()
        or Path(os.path.normpath(results)) != results
        or results.resolve(strict=True) != results
    ):
        raise StockSmallError("results_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(results, flags)
    except OSError as error:
        raise StockSmallError("results_invalid") from error
    digest = hashlib.sha256()
    size = 0
    seen_tasks: set[str] = set()
    seen_ids: set[str] = set()
    counts: Counter[str] = Counter()

    def audit_model_bearing_trace(row: dict[str, Any], *, clean_stop: bool) -> tuple[int, int]:
        audited = row
        if row.get("errors"):
            audited = dict(row)
            audited["errors"] = []
        problems = audit_traces._audit_trace(
            audited,
            require_reasoning=True,
            max_sequence_tokens=MAX_SEQUENCE_TOKENS,
            require_model_io=True,
            model_io_contract=audit_traces.KIMI_K3_MAX_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            require_exact_provider_json=True,
            require_clean_stop=clean_stop,
        )
        if problems:
            raise StockSmallError("model_bearing_trace_invalid")
        turns = 0
        sampled_tokens = 0
        for node in row.get("nodes", []):
            if not isinstance(node, dict) or node.get("sampled") is not True:
                continue
            model_io = node.get("model_io")
            response = model_io.get("response") if isinstance(model_io, dict) else None
            if not isinstance(response, dict) or response.get("kind") != "exact_provider_json":
                raise StockSmallError("model_bearing_trace_response_kind_invalid")
            turns += 1
            usage = audit_traces._usage_tokens(node)
            if usage is not None:
                sampled_tokens += usage[1]
        if turns < 1 or sampled_tokens < 1:
            raise StockSmallError("model_bearing_trace_invalid")
        return turns, sampled_tokens

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600:
            raise StockSmallError("results_invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            while raw := stream.readline(MAX_RESULTS_ROW_BYTES + 1):
                if len(raw) > MAX_RESULTS_ROW_BYTES or not raw.endswith(b"\n") or not raw.strip():
                    raise StockSmallError("results_invalid")
                digest.update(raw)
                size += len(raw)
                row = _json_line(raw, code="results_invalid")
                task = _task_slug(row)
                trace_id = row.get("id")
                if (
                    task not in expected
                    or task in seen_tasks
                    or not isinstance(trace_id, str)
                    or not trace_id
                    or trace_id in seen_ids
                ):
                    raise StockSmallError("trace_identity_invalid")
                seen_tasks.add(task)
                seen_ids.add(trace_id)
                errors = row.get("errors")
                if not isinstance(errors, list):
                    raise StockSmallError("trace_errors_invalid")
                counts["traces"] += 1
                if errors:
                    error_types = _error_types(errors)
                    shared_verifier_transport = error_types == (
                        "SandboxError",
                    ) and _is_shared_verifier_terminal_transport(row)
                    if (
                        len(error_types) != 1
                        or (not shared_verifier_transport and row.get("stop_condition") != "error")
                        or row.get("rewards") != {}
                        or row.get("metrics") != {}
                    ):
                        raise StockSmallError("trace_errors_invalid")
                    counts["error_traces"] += 1
                    nodes = row.get("nodes")
                    if nodes == []:
                        if row.get("info") != {} or row.get("is_completed") is not True:
                            raise StockSmallError("trace_errors_invalid")
                        counts["zero_model_error_traces"] += 1
                        continue
                    if error_types not in (("HarnessError",), ("ProviderError",)) and not shared_verifier_transport:
                        raise StockSmallError("model_bearing_error_type_invalid")
                    turns, sampled_tokens = audit_model_bearing_trace(row, clean_stop=False)
                    counts["model_bearing_error_traces"] += 1
                    if shared_verifier_transport:
                        counts["model_bearing_shared_verifier_transport_error_traces"] += 1
                    else:
                        counts[
                            "model_bearing_provider_error_traces"
                            if error_types == ("ProviderError",)
                            else "model_bearing_harness_error_traces"
                        ] += 1
                    counts["audited_model_io_turns"] += turns
                    counts["audited_sampled_tokens"] += sampled_tokens
                    continue
                rewards = row.get("rewards")
                if not isinstance(rewards, dict) or set(rewards) != {"solved"}:
                    raise StockSmallError("trace_reward_invalid")
                reward = rewards["solved"]
                if isinstance(reward, bool) or not isinstance(reward, (int, float)) or reward not in {0, 1}:
                    raise StockSmallError("trace_reward_invalid")
                turns, sampled_tokens = audit_model_bearing_trace(
                    row,
                    clean_stop=True,
                )
                counts["clean_model_io_turns"] += turns
                counts["clean_sampled_tokens"] += sampled_tokens
                counts["audited_model_io_turns"] += turns
                counts["audited_sampled_tokens"] += sampled_tokens
                counts["positive_traces" if float(reward) == 1.0 else "zero_reward_traces"] += 1
        after = os.fstat(descriptor)
        visible = results.lstat()
    finally:
        os.close(descriptor)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    visible_identity = (
        visible.st_dev,
        visible.st_ino,
        visible.st_mode,
        visible.st_uid,
        visible.st_nlink,
        visible.st_size,
        visible.st_mtime_ns,
        visible.st_ctime_ns,
    )
    if (
        before_identity != after_identity
        or after_identity != visible_identity
        or size != before.st_size
        or seen_tasks != expected
        or counts["traces"] != len(expected)
        or counts["error_traces"] + counts["zero_reward_traces"] + counts["positive_traces"] != len(expected)
        or counts["zero_model_error_traces"] + counts["model_bearing_error_traces"] != counts["error_traces"]
        or counts["model_bearing_error_traces"]
        != counts["model_bearing_harness_error_traces"]
        + counts["model_bearing_provider_error_traces"]
        + counts["model_bearing_shared_verifier_transport_error_traces"]
    ):
        raise StockSmallError("trace_coverage_invalid")
    return {
        "artifact": {"path": str(results.resolve()), "bytes": size, "sha256": digest.hexdigest()},
        **{
            key: counts[key]
            for key in (
                "traces",
                "error_traces",
                "zero_model_error_traces",
                "model_bearing_error_traces",
                "model_bearing_harness_error_traces",
                "model_bearing_provider_error_traces",
                "model_bearing_shared_verifier_transport_error_traces",
                "zero_reward_traces",
                "positive_traces",
                "clean_model_io_turns",
                "clean_sampled_tokens",
                "audited_model_io_turns",
                "audited_sampled_tokens",
            )
        },
    }


def _shard_completion_value(
    *,
    shard: Mapping[str, Any],
    launch: Mapping[str, Any],
    launch_path: Path,
    launch_sha256: str,
    trace: Mapping[str, Any],
    transport: Mapping[str, Any],
    router_transport: Mapping[str, Any],
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": COMPLETION_KIND,
        "state": "passed",
        "plan": dict(launch["plan"]),
        "launch": {
            "path": str(launch_path.resolve(strict=True)),
            "sha256": launch_sha256,
        },
        "shard": {
            "index": shard["index"],
            "count": shard["count"],
            "selector_sha256": shard["selector"]["sha256"],
        },
        "trace": dict(trace),
        "transport": dict(transport),
        "router_transport_binding": dict(router_transport),
        "capture": {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        },
        "deployment": {
            "capacity_profile": CAPACITY_PROFILE,
            "endpoint_identifier": launch["deployment"]["endpoint_identifier"],
            "endpoint_bundle_sha256": launch["deployment"]["endpoint_bundle_sha256"],
        },
        "sandbox": {
            "environment": "oci-runner-firecracker-small",
            "capacity": CONCURRENCY,
        },
        "training": {
            "trainable_traces": trace["zero_reward_traces"] + trace["positive_traces"],
            "non_trainable_traces": trace["model_bearing_error_traces"],
            "model_bearing_errors_retained": True,
            "shared_verifier_terminal_transport_traces": trace["model_bearing_shared_verifier_transport_error_traces"],
        },
        "artifacts": dict(artifacts),
    }


def _validate_run_evidence(
    *,
    plan: Mapping[str, Any],
    shard: Mapping[str, Any],
    launch: Mapping[str, Any],
    launch_path: Path,
    launch_sha256: str,
    run_dir: Path,
    completion_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    binding = _plan_endpoint_binding(plan)
    shard_root = Path(str(shard["run_root"]))
    try:
        canonical_run = run_dir.resolve(strict=True)
        canonical_shard_root = shard_root.resolve(strict=True)
    except OSError as error:
        raise StockSmallError("run_directory_invalid") from error
    if (
        canonical_run.parent != canonical_shard_root
        or re.fullmatch(r"attempt-[1-9][0-9]*", canonical_run.name) is None
        or launch.get("run_dir") != str(canonical_run)
    ):
        raise StockSmallError("run_directory_invalid")

    try:
        evidence = split._open_held_run_evidence(canonical_run)
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("run_evidence_invalid") from error
    held = split._HeldArtifactSet.create()
    try:
        with ExitStack() as stack:
            stack.callback(evidence.close)
            stack.callback(held.close)
            writer_lock = stack.enter_context(split._open_private_writer_lock_at(evidence.directory, ".writer.lock"))
            router_lock = stack.enter_context(
                split._open_private_writer_lock(split._router_lock_path(evidence.files["eval_run_identity.json"].body))
            )
            for lock in (writer_lock, router_lock):
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise StockSmallError("writer_or_router_active") from error

            trace = audit_results(canonical_run / "results.jsonl", Path(str(shard["selector"]["path"])))
            if trace["zero_model_error_traces"] != 0:
                raise StockSmallError("incomplete_trace_set")
            try:
                raw_transport, proxy_artifacts = tb4_transport._buffered_proxy_directory_audit(
                    canonical_run / "control/buffered-proxy-stats",
                    expected_records=int(shard["count"]),
                    expected_schema="logical-exact-once-v1",
                    held=held,
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise StockSmallError("buffered_proxy_audit_invalid") from error
            transport = _bind_proxy_audit_to_trace(
                raw_transport,
                source_model_io_turns=int(trace["audited_model_io_turns"]),
                clean_model_io_turns=int(trace["clean_model_io_turns"]),
                validated_error_model_io_turns=int(trace["audited_model_io_turns"])
                - int(trace["clean_model_io_turns"]),
                maximum_terminal_gap=int(trace["model_bearing_error_traces"]),
                expected_summary_records=int(shard["count"]),
            )
            transport_totals = transport["integer_totals"]
            if (
                transport["summary_records"] != int(shard["count"])
                or transport_totals["logical_upstream_attempts"] != transport_totals["logical_requests"]
            ):
                raise StockSmallError("buffered_proxy_trace_mismatch")

            try:
                from eval_run_identity import load_eval_run_identity_bytes

                identity_envelope = load_eval_run_identity_bytes(
                    evidence.files["eval_run_identity.json"].body,
                    run_dir=canonical_run,
                    verify_references=True,
                    verify_saved_provenance=False,
                )
                identity = identity_envelope["identity"]
                identity_sha256 = identity_envelope["eval_run_identity_sha256"]
                invocation_sha256, slurm_job_id = split._run_invocation_binding(
                    evidence.files["eval_invocations.jsonl"].body,
                    evidence.files["provenance.txt"].body,
                    identity_sha256,
                    expected_role="kimi-direct-mobius",
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise StockSmallError("identity_invalid") from error

            identity_deployment = identity.get("deployment")
            router = identity_deployment.get("router") if isinstance(identity_deployment, dict) else None
            environment = identity.get("execution", {}).get("sandoq_environment")
            inputs = identity.get("inputs")
            promotion = (
                identity_deployment.get("promotion_certificate") if isinstance(identity_deployment, dict) else None
            )
            if (
                identity.get("role") != "kimi-direct-mobius"
                or identity.get("source", {}).get("prime_rl_commit") != plan["source_revision"]
                or not isinstance(inputs, dict)
                or inputs.get("task_file", {}).get("sha256") != shard["selector"]["sha256"]
                or inputs.get("task_file", {}).get("count") != shard["count"]
                or identity.get("config", {}).get("source", {}).get("sha256") != shard["config"]["sha256"]
                or not isinstance(router, dict)
                or router.get("capacity_profile") != CAPACITY_PROFILE
                or router.get("endpoint_identifier") != binding.deployment_id
                or router.get("worker_count") != 1
                or router.get("provider_concurrency") != CONCURRENCY
                or router.get("retries") != 0
                or identity_deployment.get("spec_sha256") != binding.source_spec_sha256
                or identity_deployment.get("endpoint_bundle_sha256") != binding.endpoint_bundle_sha256
                or not isinstance(environment, dict)
                or environment.get("environment") != "oci-runner-firecracker-small"
                or environment.get("pool_size") != CONCURRENCY
                or not isinstance(promotion, dict)
                or promotion
                != {
                    "path": str(launch_path.resolve(strict=True)),
                    "sha256": launch_sha256,
                }
            ):
                raise StockSmallError("identity_invalid")

            capacity_record = plan.get("source", {}).get("stock_model_c64")
            walltime_record = identity_deployment.get("endpoint_walltime_gate")
            if not isinstance(capacity_record, dict) or not isinstance(walltime_record, dict):
                raise StockSmallError("endpoint_epoch_invalid")
            capacity_body = _read(
                Path(str(capacity_record.get("path", ""))),
                code="endpoint_epoch_invalid",
                private=True,
                held=held,
            )
            walltime_body = _read(
                Path(str(walltime_record.get("path", ""))),
                code="endpoint_epoch_invalid",
                private=True,
                held=held,
            )
            if capacity_record != _artifact(
                Path(str(capacity_record.get("path", ""))), capacity_body
            ) or walltime_record != _artifact(Path(str(walltime_record.get("path", ""))), walltime_body):
                raise StockSmallError("endpoint_epoch_invalid")
            capacity_value = _json(capacity_body, code="endpoint_epoch_invalid")
            walltime_value = _json(walltime_body, code="endpoint_epoch_invalid")
            endpoint_job_id = capacity_value.get("deployment", {}).get("endpoint_job_id")
            if (
                not isinstance(endpoint_job_id, str)
                or re.fullmatch(r"[1-9][0-9]*", endpoint_job_id) is None
                or walltime_value.get("endpoint_jobs_sha256") != _sha256(f"{endpoint_job_id}\n".encode())
            ):
                raise StockSmallError("endpoint_epoch_invalid")

            try:
                cleanup, cleanup_artifacts = _validate_stock_small_cleanup(
                    canonical_run / "sandoq_cleanup_audit.json",
                    canonical_run,
                    identity,
                    identity_sha256,
                    invocation_sha256,
                    slurm_job_id,
                    int(shard["count"]),
                    held,
                )
                router_body, router_artifact, router_marker = split._validate_direct_router_receipt(
                    canonical_run / "direct_kimi_router_final.json",
                    identity,
                    minimum_chat_requests=transport_totals["logical_requests"],
                    identity_sha256=identity_sha256,
                    invocation_identity_sha256=invocation_sha256,
                    held=held,
                    allow_terminal_upstream_statuses=True,
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise StockSmallError("run_evidence_invalid") from error
            router_receipt = _json(router_body, code="router_receipt_invalid")
            router_transport = _bind_router_to_transport(
                router_body,
                transport,
                provider_error_rows=int(trace["model_bearing_provider_error_traces"]),
            )
            if (
                cleanup.get("assignment_measured_high_water") != int(shard["count"])
                or router_receipt.get("chat_requests") != transport_totals["logical_requests"]
                or router_receipt.get("worker_queue_timeouts") != 0
            ):
                raise StockSmallError("run_evidence_invalid")

            artifacts = {
                "results": trace.pop("artifact"),
                "eval_run_identity": evidence.artifact("eval_run_identity.json"),
                "eval_invocations": evidence.artifact("eval_invocations.jsonl"),
                "provenance": evidence.artifact("provenance.txt"),
                "buffered_proxy_summary_records": proxy_artifacts,
                "endpoint_walltime_gate": _artifact(
                    Path(str(walltime_record["path"])),
                    walltime_body,
                ),
                "router_receipt": router_artifact,
                "router_receipt_commit": router_marker,
                **cleanup_artifacts,
            }
            evidence.revalidate()
            held.revalidate()
            if completion_path is not None:
                expected_completion = canonical_shard_root / "complete.json"
                if completion_path != expected_completion or completion_path.exists() or completion_path.is_symlink():
                    raise StockSmallError("completion_publication_failed")
                value = _shard_completion_value(
                    shard=shard,
                    launch=launch,
                    launch_path=launch_path,
                    launch_sha256=launch_sha256,
                    trace=trace,
                    transport=transport,
                    router_transport=router_transport,
                    artifacts=artifacts,
                )
                try:
                    legacy._publish_bundle(
                        canonical_shard_root,
                        {completion_path: _canonical(value)},
                    )
                except Exception as error:
                    raise StockSmallError("completion_publication_failed") from error
                evidence.revalidate()
                held.revalidate()
            return trace, transport, router_transport, artifacts
    except StockSmallError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise StockSmallError("run_evidence_invalid") from error


def _validate_completion_value(
    value: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    plan_path: Path,
    plan_sha256: str,
    shard: Mapping[str, Any],
) -> dict[str, Any]:
    binding = _plan_endpoint_binding(plan)
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "plan",
            "launch",
            "shard",
            "trace",
            "transport",
            "router_transport_binding",
            "capture",
            "deployment",
            "sandbox",
            "training",
            "artifacts",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != COMPLETION_KIND
        or value.get("state") != "passed"
        or value.get("plan") != {"path": str(plan_path), "sha256": plan_sha256}
        or not isinstance(value.get("launch"), dict)
        or set(value["launch"]) != {"path", "sha256"}
        or SHA256_RE.fullmatch(str(value["launch"].get("sha256", ""))) is None
        or value.get("shard")
        != {"index": shard["index"], "count": shard["count"], "selector_sha256": shard["selector"]["sha256"]}
        or value.get("capture")
        != {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        }
        or value.get("deployment", {}).get("capacity_profile") != CAPACITY_PROFILE
        or value.get("deployment", {}).get("endpoint_identifier") != binding.deployment_id
        or value.get("deployment", {}).get("endpoint_bundle_sha256") != binding.endpoint_bundle_sha256
        or value.get("sandbox", {}).get("environment") != "oci-runner-firecracker-small"
        or value.get("sandbox", {}).get("capacity") != CONCURRENCY
    ):
        raise StockSmallError("completion_invalid")
    launch_record = value["launch"]
    launch = validate_launch(Path(launch_record["path"]), launch_record["sha256"])
    if (
        launch.get("plan") != {"path": str(plan_path), "sha256": plan_sha256}
        or launch.get("shard", {}).get("index") != shard["index"]
    ):
        raise StockSmallError("completion_invalid")
    trace = value.get("trace")
    outcome_counts = ()
    if isinstance(trace, dict):
        outcome_counts = tuple(
            trace.get(key)
            for key in (
                "error_traces",
                "zero_model_error_traces",
                "model_bearing_error_traces",
                "model_bearing_harness_error_traces",
                "model_bearing_provider_error_traces",
                "model_bearing_shared_verifier_transport_error_traces",
                "zero_reward_traces",
                "positive_traces",
            )
        )
    if (
        not isinstance(trace, dict)
        or trace.get("traces") != shard["count"]
        or not all(map(_plain_nonnegative_integer, outcome_counts))
        or trace.get("zero_model_error_traces") != 0
        or trace.get("error_traces") != trace.get("model_bearing_error_traces")
        or trace.get("model_bearing_error_traces")
        != trace.get("model_bearing_harness_error_traces", -1)
        + trace.get("model_bearing_provider_error_traces", -1)
        + trace.get("model_bearing_shared_verifier_transport_error_traces", -1)
        or trace.get("error_traces", -1) + trace.get("zero_reward_traces", -1) + trace.get("positive_traces", -1)
        != shard["count"]
        or value.get("training")
        != {
            "trainable_traces": trace.get("zero_reward_traces", -1) + trace.get("positive_traces", -1),
            "non_trainable_traces": trace.get("model_bearing_error_traces", -1),
            "model_bearing_errors_retained": True,
            "shared_verifier_terminal_transport_traces": trace.get(
                "model_bearing_shared_verifier_transport_error_traces",
                -1,
            ),
        }
    ):
        raise StockSmallError("completion_invalid")
    (
        observed_trace,
        observed_transport,
        observed_router_transport,
        observed_artifacts,
    ) = _validate_run_evidence(
        plan=plan,
        shard=shard,
        launch=launch,
        launch_path=Path(str(launch_record["path"])),
        launch_sha256=str(launch_record["sha256"]),
        run_dir=Path(str(launch["run_dir"])),
    )
    if (
        observed_trace != trace
        or value.get("transport") != observed_transport
        or value.get("router_transport_binding") != observed_router_transport
        or value.get("artifacts") != observed_artifacts
    ):
        raise StockSmallError("completion_trace_invalid")
    return dict(value)


def _load_completion_for_plan(
    plan: Mapping[str, Any],
    plan_path: Path,
    plan_sha256: str,
    index: int,
) -> dict[str, Any]:
    if not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_index_invalid")
    shard = plan["shards"][index]
    path = Path(shard["run_root"]) / "complete.json"
    body = _read(path, code="completion_invalid", private=True)
    return _validate_completion_value(
        _json(body, code="completion_invalid"),
        plan=plan,
        plan_path=plan_path.resolve(strict=True),
        plan_sha256=plan_sha256,
        shard=shard,
    )


def load_completion(plan_path: Path, plan_sha256: str, index: int) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    return _load_completion_for_plan(plan, plan_path, plan_sha256, index)


def _aggregate_transport_audits(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    integer_totals: Counter[str] = Counter()
    mapping_totals: dict[str, Counter[str]] = {field: Counter() for field in PROXY_SUMMARY_MAPPING_FIELDS}
    summary_records = 0
    terminal_totals: Counter[str] = Counter()
    trace_totals: Counter[str] = Counter()
    for value in values:
        terminal = value.get("terminal_outcomes")
        trace_binding = value.get("trace_binding")
        if (
            set(value)
            != {
                "schema_version",
                "source_schema",
                "summary_records",
                "exact_once_counters_required",
                "integer_totals",
                "mapping_totals",
                "terminal_outcomes",
                "trace_binding",
                "record_set_sha256",
            }
            or value.get("schema_version") != 1
            or value.get("source_schema") != "logical-exact-once-v1"
            or value.get("exact_once_counters_required") is not True
            or not _plain_nonnegative_integer(value.get("summary_records"))
            or not isinstance(value.get("integer_totals"), dict)
            or set(value["integer_totals"]) != set(PROXY_SUMMARY_INTEGER_FIELDS)
            or any(
                not _plain_nonnegative_integer(value["integer_totals"].get(field))
                for field in PROXY_SUMMARY_INTEGER_FIELDS
            )
            or not isinstance(value.get("mapping_totals"), dict)
            or set(value["mapping_totals"]) != set(PROXY_SUMMARY_MAPPING_FIELDS)
            or any(not _counter_mapping(value["mapping_totals"].get(field)) for field in PROXY_SUMMARY_MAPPING_FIELDS)
            or not isinstance(terminal, dict)
            or set(terminal)
            != {
                "failure_records",
                "non_2xx_upstream_responses",
                "exception_records",
                "exception_observations",
            }
            or any(not _plain_nonnegative_integer(item) for item in terminal.values())
            or not isinstance(trace_binding, dict)
            or set(trace_binding)
            != {
                "source_model_io_turns",
                "validated_model_io_turns",
                "logical_requests",
                "terminal_attempt_gap",
                "maximum_terminal_gap",
                "gap_bound",
            }
            or any(
                not _plain_nonnegative_integer(trace_binding.get(field))
                for field in (
                    "source_model_io_turns",
                    "validated_model_io_turns",
                    "logical_requests",
                    "terminal_attempt_gap",
                    "maximum_terminal_gap",
                )
            )
            or trace_binding.get("gap_bound") != "typed-error-rows-with-terminal-proxy-outcome"
            or trace_binding.get("logical_requests") != value["integer_totals"].get("logical_requests")
            or trace_binding.get("validated_model_io_turns", 0) > trace_binding.get("source_model_io_turns", -1)
            or trace_binding.get("logical_requests", 0) - trace_binding.get("source_model_io_turns", 0)
            != trace_binding.get("terminal_attempt_gap")
            or trace_binding.get("terminal_attempt_gap") != terminal.get("failure_records")
            or trace_binding.get("terminal_attempt_gap", 0) > trace_binding.get("maximum_terminal_gap", -1)
            or SHA256_RE.fullmatch(str(value.get("record_set_sha256", ""))) is None
        ):
            raise StockSmallError("buffered_proxy_audit_invalid")
        summary_records += int(value["summary_records"])
        integer_totals.update(value["integer_totals"])
        for field in PROXY_SUMMARY_MAPPING_FIELDS:
            mapping_totals[field].update(value["mapping_totals"][field])
        terminal_totals.update(terminal)
        trace_totals.update(
            {
                field: trace_binding[field]
                for field in (
                    "source_model_io_turns",
                    "validated_model_io_turns",
                    "logical_requests",
                    "terminal_attempt_gap",
                    "maximum_terminal_gap",
                )
            }
        )
    return {
        "schema_version": 1,
        "source_schema": "logical-exact-once-v1",
        "summary_records": summary_records,
        "exact_once_counters_required": True,
        "integer_totals": {field: integer_totals[field] for field in PROXY_SUMMARY_INTEGER_FIELDS},
        "mapping_totals": {
            field: dict(sorted(mapping_totals[field].items())) for field in PROXY_SUMMARY_MAPPING_FIELDS
        },
        "terminal_outcomes": {
            field: terminal_totals[field]
            for field in (
                "failure_records",
                "non_2xx_upstream_responses",
                "exception_records",
                "exception_observations",
            )
        },
        "trace_binding": {
            **{
                field: trace_totals[field]
                for field in (
                    "source_model_io_turns",
                    "validated_model_io_turns",
                    "logical_requests",
                    "terminal_attempt_gap",
                    "maximum_terminal_gap",
                )
            },
            "gap_bound": "typed-error-rows-with-terminal-proxy-outcome",
        },
        "shard_audit_set_sha256": _sha256(_canonical(list(values))),
    }


def _aggregate_router_transport_bindings(
    values: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    fields = (
        "router_chat_requests",
        "proxy_logical_requests",
        "proxy_logical_upstream_attempts",
        "router_upstream_http_429",
        "router_upstream_http_5xx",
        "proxy_non_2xx_upstream_responses",
        "proxy_exception_records",
        "provider_error_rows",
    )
    totals: Counter[str] = Counter()
    for value in values:
        if (
            set(value) != {"schema_version", "state", *fields}
            or value.get("schema_version") != 1
            or value.get("state") != "passed"
            or any(not _plain_nonnegative_integer(value.get(field)) for field in fields)
            or value["router_chat_requests"] != value["proxy_logical_requests"]
            or value["proxy_logical_upstream_attempts"] != value["proxy_logical_requests"]
            or value["router_upstream_http_429"] + value["router_upstream_http_5xx"]
            != value["proxy_non_2xx_upstream_responses"]
            or value["proxy_exception_records"] != 0
            or value["provider_error_rows"] != value["proxy_non_2xx_upstream_responses"]
        ):
            raise StockSmallError("router_transport_binding_invalid")
        totals.update({field: int(value[field]) for field in fields})
    return {
        "schema_version": 1,
        "state": "passed",
        "shards": len(values),
        **{field: totals[field] for field in fields},
        "shard_binding_set_sha256": _sha256(_canonical(list(values))),
    }


def certify_shard(
    *,
    plan_path: Path,
    plan_sha256: str,
    launch_path: Path,
    launch_sha256: str,
    index: int,
    run_dir: Path,
) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    if not 0 <= index < SHARD_COUNT:
        raise StockSmallError("shard_index_invalid")
    shard = plan["shards"][index]
    launch = validate_launch(launch_path, launch_sha256)
    if (
        launch.get("plan") != {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256}
        or launch.get("shard", {}).get("index") != index
        or launch.get("run_dir") != str(run_dir)
    ):
        raise StockSmallError("shard_launch_binding_invalid")
    completion = Path(shard["run_root"]) / "complete.json"
    trace, _transport, _router_transport, _artifacts = _validate_run_evidence(
        plan=plan,
        shard=shard,
        launch=launch,
        launch_path=launch_path,
        launch_sha256=launch_sha256,
        run_dir=run_dir,
        completion_path=completion,
    )
    return {"state": "passed", "shard": index, **trace}


def status(plan_path: Path, plan_sha256: str) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    complete: list[int] = []
    pending: list[int] = []
    counts: Counter[str] = Counter()
    transport_audits: list[dict[str, Any]] = []
    router_transport_bindings: list[dict[str, Any]] = []
    for shard in plan["shards"]:
        index = shard["index"]
        completion = Path(shard["run_root"]) / "complete.json"
        if not completion.exists():
            pending.append(index)
            continue
        value = _load_completion_for_plan(plan, plan_path, plan_sha256, index)
        complete.append(index)
        counts["completed_tasks"] += shard["count"]
        for key in (
            "positive_traces",
            "zero_reward_traces",
            "error_traces",
            "zero_model_error_traces",
            "model_bearing_error_traces",
            "model_bearing_harness_error_traces",
            "model_bearing_provider_error_traces",
            "model_bearing_shared_verifier_transport_error_traces",
        ):
            counts[key] += value["trace"][key]
        transport_audits.append(value["transport"])
        router_transport_bindings.append(value["router_transport_binding"])
    transport = _aggregate_transport_audits(transport_audits)
    router_transport = _aggregate_router_transport_bindings(router_transport_bindings)
    if (
        router_transport["router_chat_requests"] != transport["integer_totals"]["logical_requests"]
        or router_transport["proxy_logical_upstream_attempts"]
        != transport["integer_totals"]["logical_upstream_attempts"]
        or router_transport["provider_error_rows"] != counts["model_bearing_provider_error_traces"]
        or router_transport["proxy_non_2xx_upstream_responses"]
        != transport["terminal_outcomes"]["non_2xx_upstream_responses"]
        or router_transport["proxy_exception_records"] != transport["terminal_outcomes"]["exception_records"]
    ):
        raise StockSmallError("production_transport_invalid")
    return {
        "state": "complete" if not pending else "incomplete",
        "completed_shards": len(complete),
        "pending_shards": len(pending),
        "completed_tasks": counts["completed_tasks"],
        "positive_traces": counts["positive_traces"],
        "zero_reward_traces": counts["zero_reward_traces"],
        "error_traces": counts["error_traces"],
        "zero_model_error_traces": counts["zero_model_error_traces"],
        "model_bearing_error_traces": counts["model_bearing_error_traces"],
        "model_bearing_harness_error_traces": counts["model_bearing_harness_error_traces"],
        "model_bearing_provider_error_traces": counts["model_bearing_provider_error_traces"],
        "model_bearing_shared_verifier_transport_error_traces": counts[
            "model_bearing_shared_verifier_transport_error_traces"
        ],
        "logical_model_requests": transport["integer_totals"]["logical_requests"],
        "logical_upstream_attempts": transport["integer_totals"]["logical_upstream_attempts"],
        "guest_replayed_requests": transport["integer_totals"]["replayed_requests"],
        "guest_coalesced_requests": transport["integer_totals"]["coalesced_requests"],
        "terminal_upstream_statuses": router_transport["proxy_non_2xx_upstream_responses"],
        "pending_indexes": pending,
    }


def finalize(plan_path: Path, plan_sha256: str, output: Path) -> dict[str, Any]:
    plan = verify(plan_path, plan_sha256)
    completions = []
    transport_audits: list[dict[str, Any]] = []
    router_transport_bindings: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for shard in plan["shards"]:
        path = Path(shard["run_root"]) / "complete.json"
        body = _read(path, code="completion_invalid", private=True)
        completion = _validate_completion_value(
            _json(body, code="completion_invalid"),
            plan=plan,
            plan_path=plan_path.resolve(strict=True),
            plan_sha256=plan_sha256,
            shard=shard,
        )
        counts["completed_tasks"] += shard["count"]
        for key in (
            "positive_traces",
            "zero_reward_traces",
            "error_traces",
            "zero_model_error_traces",
            "model_bearing_error_traces",
            "model_bearing_harness_error_traces",
            "model_bearing_provider_error_traces",
            "model_bearing_shared_verifier_transport_error_traces",
        ):
            counts[key] += completion["trace"][key]
        completions.append(_artifact(path, body))
        transport_audits.append(completion["transport"])
        router_transport_bindings.append(completion["router_transport_binding"])
    if (
        counts["completed_tasks"] != TOTAL_TASKS
        or counts["zero_model_error_traces"] != 0
        or counts["error_traces"] != counts["model_bearing_error_traces"]
    ):
        raise StockSmallError("production_incomplete")
    summary = {
        "state": "complete",
        "completed_shards": SHARD_COUNT,
        "pending_shards": 0,
        "completed_tasks": counts["completed_tasks"],
        "positive_traces": counts["positive_traces"],
        "zero_reward_traces": counts["zero_reward_traces"],
        "error_traces": counts["error_traces"],
        "zero_model_error_traces": counts["zero_model_error_traces"],
        "model_bearing_error_traces": counts["model_bearing_error_traces"],
        "model_bearing_harness_error_traces": counts["model_bearing_harness_error_traces"],
        "model_bearing_provider_error_traces": counts["model_bearing_provider_error_traces"],
        "model_bearing_shared_verifier_transport_error_traces": counts[
            "model_bearing_shared_verifier_transport_error_traces"
        ],
        "pending_indexes": [],
    }
    transport = _aggregate_transport_audits(transport_audits)
    router_transport = _aggregate_router_transport_bindings(router_transport_bindings)
    if (
        transport["summary_records"] != TOTAL_TASKS
        or transport["integer_totals"]["logical_upstream_attempts"] != transport["integer_totals"]["logical_requests"]
        or transport["integer_totals"]["anonymous_upstream_attempts"] != 0
        or transport["integer_totals"]["conflicting_requests"] != 0
        or transport["integer_totals"]["expired_logical_retries"] != 0
        or router_transport["shards"] != SHARD_COUNT
        or router_transport["router_chat_requests"] != transport["integer_totals"]["logical_requests"]
        or router_transport["proxy_logical_upstream_attempts"]
        != transport["integer_totals"]["logical_upstream_attempts"]
        or router_transport["provider_error_rows"] != counts["model_bearing_provider_error_traces"]
        or router_transport["proxy_non_2xx_upstream_responses"]
        != transport["terminal_outcomes"]["non_2xx_upstream_responses"]
        or router_transport["proxy_exception_records"] != transport["terminal_outcomes"]["exception_records"]
    ):
        raise StockSmallError("production_transport_invalid")
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": FINAL_KIND,
        "state": "passed",
        "plan": {"path": str(plan_path.resolve(strict=True)), "sha256": plan_sha256},
        "coverage": {
            "expected_tasks": TOTAL_TASKS,
            "observed_tasks": summary["completed_tasks"],
            "shards": SHARD_COUNT,
            "disjoint": True,
            "exhaustive": True,
        },
        "outcomes": {
            key: summary[key]
            for key in (
                "positive_traces",
                "zero_reward_traces",
                "error_traces",
                "zero_model_error_traces",
                "model_bearing_error_traces",
                "model_bearing_harness_error_traces",
                "model_bearing_provider_error_traces",
                "model_bearing_shared_verifier_transport_error_traces",
            )
        },
        "training": {
            "trainable_traces": summary["positive_traces"] + summary["zero_reward_traces"],
            "non_trainable_traces": summary["model_bearing_error_traces"],
            "model_bearing_errors_retained": True,
            "shared_verifier_terminal_transport_traces": summary[
                "model_bearing_shared_verifier_transport_error_traces"
            ],
        },
        "capture": {
            "response_kind": "exact_provider_json",
            "reasoning_required": True,
            "reasoning_message_parity_required": True,
            "request_graph_match_required": True,
        },
        "transport": transport,
        "router_transport_binding": router_transport,
        "completion_receipts": completions,
    }
    value["certificate_sha256"] = _sha256(_canonical(value))
    split._publish_private_bundle(output, {"certificate.json": _canonical(value)})
    return {"state": "passed", **summary, "certificate_sha256": value["certificate_sha256"]}


class StableParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise StockSmallError("arguments_invalid")


def _parser() -> StableParser:
    parser = StableParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("materialize")
    make.add_argument("--project-root", type=Path, required=True)
    make.add_argument("--expected-revision", required=True)
    make.add_argument("--source", type=Path, required=True)
    make.add_argument("--dataset", type=Path, required=True)
    make.add_argument("--image-manifest", type=Path, required=True)
    make.add_argument("--tb4-certificate", type=Path, required=True)
    make.add_argument("--tb4-certificate-sha256", required=True)
    make.add_argument("--task-image-soak-receipt", type=Path, required=True)
    make.add_argument("--task-image-soak-receipt-sha256", required=True)
    make.add_argument("--stock-capacity", type=Path, default=STOCK_CAPACITY)
    make.add_argument("--stock-capacity-sha256", default=STOCK_CAPACITY_SHA256)
    make.add_argument("--sandoq-capacity", type=Path, default=SANDOQ_CAPACITY)
    make.add_argument("--sandoq-capacity-sha256", default=SANDOQ_CAPACITY_SHA256)
    make.add_argument("--output", type=Path, required=True)
    make.add_argument("--run-root", type=Path, required=True)
    for name in ("verify", "shard", "status", "finalize"):
        command = commands.add_parser(name)
        command.add_argument("--plan", type=Path, required=True)
        command.add_argument("--plan-sha256", required=True)
        if name in {"shard"}:
            command.add_argument("--index", type=int, required=True)
            command.add_argument("--format", choices=("json", "tsv"), default="json")
        if name == "finalize":
            command.add_argument("--output", type=Path, required=True)
    certify = commands.add_parser("certify-shard")
    certify.add_argument("--plan", type=Path, required=True)
    certify.add_argument("--plan-sha256", required=True)
    certify.add_argument("--index", type=int, required=True)
    certify.add_argument("--run-dir", type=Path, required=True)
    certify.add_argument("--launch", type=Path, required=True)
    certify.add_argument("--launch-sha256", required=True)
    launch = commands.add_parser("create-launch")
    launch.add_argument("--plan", type=Path, required=True)
    launch.add_argument("--plan-sha256", required=True)
    launch.add_argument("--index", type=int, required=True)
    launch.add_argument("--worker-manifest", type=Path, required=True)
    launch.add_argument("--worker-manifest-sha256", required=True)
    launch.add_argument("--run-dir", type=Path, required=True)
    launch.add_argument("--output", type=Path, required=True)
    validate_launch_parser = commands.add_parser("validate-launch")
    validate_launch_parser.add_argument("--launch", type=Path, required=True)
    validate_launch_parser.add_argument("--launch-sha256", required=True)
    validate_completion_parser = commands.add_parser("validate-completion")
    validate_completion_parser.add_argument("--plan", type=Path, required=True)
    validate_completion_parser.add_argument("--plan-sha256", required=True)
    validate_completion_parser.add_argument("--index", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "materialize":
            result = materialize(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                source=args.source,
                dataset=args.dataset,
                image_manifest=args.image_manifest,
                tb4_certificate=args.tb4_certificate,
                tb4_certificate_sha256=args.tb4_certificate_sha256,
                task_image_soak_receipt=args.task_image_soak_receipt,
                task_image_soak_receipt_sha256=args.task_image_soak_receipt_sha256,
                output=args.output,
                run_root=args.run_root,
                stock_capacity=args.stock_capacity,
                stock_capacity_sha256=args.stock_capacity_sha256,
                sandoq_capacity=args.sandoq_capacity,
                sandoq_capacity_sha256=args.sandoq_capacity_sha256,
            )
        elif args.command == "verify":
            plan = verify(args.plan, args.plan_sha256)
            result = {"state": "authorized", "selected_tasks": TOTAL_TASKS, "shards": len(plan["shards"])}
        elif args.command == "shard":
            result = shard_binding(args.plan, args.plan_sha256, args.index)
        elif args.command == "status":
            result = status(args.plan, args.plan_sha256)
        elif args.command == "certify-shard":
            result = certify_shard(
                plan_path=args.plan,
                plan_sha256=args.plan_sha256,
                launch_path=args.launch,
                launch_sha256=args.launch_sha256,
                index=args.index,
                run_dir=args.run_dir,
            )
        elif args.command == "create-launch":
            result = create_launch(
                plan_path=args.plan,
                plan_sha256=args.plan_sha256,
                index=args.index,
                worker_manifest=args.worker_manifest,
                worker_manifest_sha256=args.worker_manifest_sha256,
                run_dir=args.run_dir,
                output=args.output,
            )
        elif args.command == "validate-launch":
            value = validate_launch(args.launch, args.launch_sha256)
            result = {
                "state": "authorized",
                "shard": value["shard"]["index"],
                "count": value["shard"]["count"],
            }
        elif args.command == "validate-completion":
            value = load_completion(args.plan, args.plan_sha256, args.index)
            result = {"state": "passed", "shard": args.index, "count": value["shard"]["count"]}
        else:
            result = finalize(args.plan, args.plan_sha256, args.output)
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_stock_small_shards_failed","state":"blocked"}', file=sys.stderr)
        return 2
    if args.command == "shard" and args.format == "tsv":
        print(
            "\t".join(
                str(result[key])
                for key in (
                    "source_revision",
                    "index",
                    "count",
                    "selector",
                    "selector_sha256",
                    "config",
                    "config_sha256",
                    "run_root",
                    "endpoint_identifier",
                    "deployment_root",
                    "stock_capacity",
                    "stock_capacity_sha256",
                    "endpoint_jobs_sha256",
                )
            )
        )
    else:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
