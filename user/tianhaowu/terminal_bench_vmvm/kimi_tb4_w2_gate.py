#!/usr/bin/env python3
"""Authorize the opaque 66-task Kimi TB4 c48/c64-w2 launch.

The gate deliberately emits only aggregate counts and immutable digests.  It
may read task metadata to enforce the operator-observation boundary, but task
identifiers, prompts, model responses, tool output, and raw errors are never
included in its receipt or exception text.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import tomllib
from pathlib import Path
from typing import Any

from direct_kimi_capacity import validate_capacity_certificate
from direct_kimi_workers import load_saved_manifest, read_published_file
from eval_run_identity import load_eval_run_identity
from prepare_kimi_tb4_miniswe246_union import CERTIFIER_ADAPTER, SANDOQ_ROLE, verify_launch_plan

KIND = "kimi-tb4-c48-w2-launch-gate"
SCHEMA_VERSION = 1
MODEL = "Kimi-K3"
ENDPOINT_IDENTIFIER = "cpu-132-021_8103"
CAPACITY_PROFILE = "sandoq-c64-w2-v1"
TASK_COUNT = 66
SECURITY_LABELLED_TASK_COUNT = 7
ROLLOUT_CONCURRENCY = 48
SANDOQ_LANE_TASK_COUNT = 52
ROUTER_ADMISSION = 64
WORKER_COUNT = 24
PER_WORKER_CAPACITY = 2
SANDOQ_ENVIRONMENT = "oci-runner-firecracker"
SANDOQ_SITE_NAME = "sandoq_x86_64_sdk1_82068"
SANDOQ_SITE_SHA256 = "df69cadb16edc799fcb62ea4fc144ee5d5572fe58fcd3e2bd6d165c607e02962"
SANDOQ_CLIENT_VERSION = "1.0.0.2026.9.23.82068.0+hg1a1d394e50c5"
OFFICIAL_SELECTOR_SHA256 = "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SECURITY_LABEL_RE = re.compile(
    r"(?:^|[^a-z])(?:secur(?:ity|e)|cyber(?:security)?|"
    r"exploit(?:s|ation|able)?|malware|vulnerab(?:ility|ilities|le)?|"
    r"penetration|forensics?|ctf|credentials?|passwords?|secrets?|"
    r"attacks?|injections?|crypt(?:o|ography|ographic)?|devsecops|"
    r"infosec|appsec|secops|red[-_ ]?team|pwn(?:ing)?|cve(?:-[0-9]+)?|xss)(?:[^a-z]|$)",
    re.IGNORECASE,
)


class KimiTB4W2GateError(ValueError):
    """A sealed launch prerequisite is absent or inconsistent."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise KimiTB4W2GateError("artifact_invalid")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as error:
        raise KimiTB4W2GateError("artifact_invalid") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise KimiTB4W2GateError("artifact_changed")
    return digest.hexdigest()


def _read_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    if _SHA256_RE.fullmatch(expected_sha256) is None or _sha256_file(path) != expected_sha256:
        raise KimiTB4W2GateError("artifact_digest_mismatch")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KimiTB4W2GateError("artifact_invalid") from error
    if not isinstance(value, dict):
        raise KimiTB4W2GateError("artifact_invalid")
    return value


def _security_metadata_absent(raw: dict[str, Any]) -> bool:
    metadata = raw.get("metadata")
    task = raw.get("task") or {}
    if not isinstance(metadata, dict) or not isinstance(task, dict):
        raise KimiTB4W2GateError("task_metadata_invalid")
    values: list[str] = []
    for value in (metadata.get("category"), metadata.get("tags"), task.get("keywords")):
        if value is None:
            continue
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            values.extend(value)
        else:
            raise KimiTB4W2GateError("task_metadata_invalid")
    if not values or not all(value.strip() for value in values):
        raise KimiTB4W2GateError("task_metadata_invalid")
    return not any(_SECURITY_LABEL_RE.search(value) for value in values)


def _validate_official_selector(selector: Path, dataset_dir: Path) -> tuple[int, int]:
    try:
        selector_body = selector.read_bytes()
        root = dataset_dir.resolve(strict=True)
    except OSError as error:
        raise KimiTB4W2GateError("official_selector_invalid") from error
    if _sha256_bytes(selector_body) != OFFICIAL_SELECTOR_SHA256 or not root.is_dir():
        raise KimiTB4W2GateError("official_selector_invalid")
    try:
        lines = selector_body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise KimiTB4W2GateError("official_selector_invalid") from error
    members = [line.strip().split("\t", 1)[0] for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if len(members) != TASK_COUNT or len(set(members)) != TASK_COUNT:
        raise KimiTB4W2GateError("official_selector_invalid")
    security_count = 0
    for member in members:
        if _SLUG_RE.fullmatch(member) is None:
            raise KimiTB4W2GateError("official_selector_invalid")
        task_dir = (root / member).resolve(strict=True)
        if task_dir.parent != root or task_dir.name != member:
            raise KimiTB4W2GateError("official_selector_invalid")
        try:
            metadata = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise KimiTB4W2GateError("task_metadata_invalid") from error
        security_count += int(not _security_metadata_absent(metadata))
    if security_count != SECURITY_LABELLED_TASK_COUNT:
        raise KimiTB4W2GateError("security_boundary_changed")
    return len(members), security_count


def _validate_sdk_site(site: Path) -> None:
    try:
        resolved = site.resolve(strict=True)
    except OSError as error:
        raise KimiTB4W2GateError("sandoq_sdk_invalid") from error
    if resolved != site or site.is_symlink() or not site.is_dir() or site.name != SANDOQ_SITE_NAME:
        raise KimiTB4W2GateError("sandoq_sdk_invalid")
    digest = hashlib.sha256()
    files = sorted(
        (
            item
            for item in resolved.rglob("*")
            if item.is_file() and item.suffix != ".pyc" and not item.name.startswith(".")
        ),
        key=lambda item: item.relative_to(resolved).as_posix(),
    )
    for item in files:
        digest.update(f"{_sha256_file(item)}  {item.relative_to(resolved).as_posix()}\n".encode())
    distributions = [
        distribution
        for distribution in importlib.metadata.distributions(path=[str(resolved)])
        if distribution.metadata["Name"].lower().replace("_", "-") == "sandoq-client"
    ]
    if (
        digest.hexdigest() != SANDOQ_SITE_SHA256
        or len(distributions) != 1
        or distributions[0].version != SANDOQ_CLIENT_VERSION
    ):
        raise KimiTB4W2GateError("sandoq_sdk_invalid")


def validate_launch(
    *,
    certificate_path: Path,
    certificate_sha256: str,
    manifest_path: Path,
    manifest_sha256: str,
    selector: Path,
    dataset_dir: Path,
    expected_revision: str,
    sandoq_site: Path,
    union_launch_plan: Path,
    union_launch_plan_sha256: str,
) -> dict[str, Any]:
    if _REVISION_RE.fullmatch(expected_revision) is None:
        raise KimiTB4W2GateError("source_revision_invalid")
    _validate_sdk_site(sandoq_site)
    task_count, security_count = _validate_official_selector(selector, dataset_dir)
    try:
        lane = verify_launch_plan(union_launch_plan, union_launch_plan_sha256, SANDOQ_ROLE)
        certificate = validate_capacity_certificate(
            certificate_path,
            expected_sha256=certificate_sha256,
            required_concurrency=ROLLOUT_CONCURRENCY,
            expected_endpoint_identifier=ENDPOINT_IDENTIFIER,
        )
        manifest_body = read_published_file(manifest_path)
        manifest = load_saved_manifest(manifest_path, body=manifest_body)
    except (OSError, RuntimeError, ValueError) as error:
        raise KimiTB4W2GateError("capacity_proof_invalid") from error
    router = manifest.get("router")
    source = certificate.get("source")
    artifacts = certificate.get("artifacts")
    identity_record = artifacts.get("eval_run_identity") if isinstance(artifacts, dict) else None
    if (
        lane.get("count") != SANDOQ_LANE_TASK_COUNT
        or lane.get("concurrency") != ROLLOUT_CONCURRENCY
        or lane.get("provider") != "sandoq"
        or lane.get("certifier_adapter") != CERTIFIER_ADAPTER
        or lane.get("selector_sha256") != _sha256_file(Path(str(lane.get("selector", ""))))
        or _SHA256_RE.fullmatch(manifest_sha256) is None
        or _sha256_bytes(manifest_body) != manifest_sha256
        or manifest.get("schema_version") != 3
        or not isinstance(router, dict)
        or router.get("capacity_profile") != CAPACITY_PROFILE
        or router.get("endpoint_identifier") != ENDPOINT_IDENTIFIER
        or router.get("max_concurrent_requests") != ROUTER_ADMISSION
        or router.get("per_worker_capacity") != PER_WORKER_CAPACITY
        or len(manifest.get("workers", [])) != WORKER_COUNT
        or not isinstance(source, dict)
        or source.get("prime_rl_commit") != expected_revision
        or source.get("router_implementation_sha256") != router.get("implementation_sha256")
        or certificate.get("qualification_scope") != "routing-runtime-capacity-only"
        or certificate.get("endpoint_bundle_sha256") != manifest.get("endpoint_bundle_sha256")
        or not isinstance(identity_record, dict)
        or set(identity_record) != {"path", "sha256"}
    ):
        raise KimiTB4W2GateError("capacity_proof_binding_mismatch")
    try:
        capacity_identity = load_eval_run_identity(Path(identity_record["path"]), verify_references=True)["identity"]
    except (OSError, RuntimeError, ValueError) as error:
        raise KimiTB4W2GateError("capacity_identity_invalid") from error
    capacity_source = capacity_identity.get("source")
    capacity_environment = capacity_identity.get("execution", {}).get("sandoq_environment")
    if (
        not isinstance(capacity_source, dict)
        or capacity_source.get("prime_rl_commit") != expected_revision
        or capacity_source.get("sandoq_site_sha256") != SANDOQ_SITE_SHA256
        or capacity_source.get("sandoq_client_version") != SANDOQ_CLIENT_VERSION
        or not isinstance(capacity_environment, dict)
        or capacity_environment.get("environment") != SANDOQ_ENVIRONMENT
        or capacity_environment.get("pool_size") != ROUTER_ADMISSION
    ):
        raise KimiTB4W2GateError("capacity_identity_invalid")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "passed",
        "model": MODEL,
        "task_count": task_count,
        "security_labelled_task_count": security_count,
        "security_task_handling": "opaque-execution-aggregate-only",
        "membership_disclosed": False,
        "capacity_certificate_sha256": certificate_sha256,
        "capacity_qualification_scope": "routing-runtime-capacity-only",
        "union_launch_plan_sha256": union_launch_plan_sha256,
        "sandoq_lane_selector_sha256": lane["selector_sha256"],
        "worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "source_revision": expected_revision,
        "router": {
            "policy": "consistent_hash",
            "profile": CAPACITY_PROFILE,
            "admission": ROUTER_ADMISSION,
            "effective_forwarded": ROLLOUT_CONCURRENCY,
            "workers": WORKER_COUNT,
            "per_worker": PER_WORKER_CAPACITY,
            "retries": 0,
        },
        "sandoq": {
            "environment": SANDOQ_ENVIRONMENT,
            "client_version": SANDOQ_CLIENT_VERSION,
            "site_sha256": SANDOQ_SITE_SHA256,
        },
    }


def _write_once(path: Path, value: dict[str, Any]) -> None:
    parent = path.parent.resolve(strict=True)
    metadata = parent.lstat()
    if (
        parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or os.path.lexists(path)
    ):
        raise KimiTB4W2GateError("output_invalid")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capacity-certificate", type=Path, required=True)
    parser.add_argument("--capacity-certificate-sha256", required=True)
    parser.add_argument("--worker-manifest", type=Path, required=True)
    parser.add_argument("--worker-manifest-sha256", required=True)
    parser.add_argument("--selector", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--sandoq-site", type=Path, required=True)
    parser.add_argument("--union-launch-plan", type=Path, required=True)
    parser.add_argument("--union-launch-plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = validate_launch(
            certificate_path=args.capacity_certificate,
            certificate_sha256=args.capacity_certificate_sha256,
            manifest_path=args.worker_manifest,
            manifest_sha256=args.worker_manifest_sha256,
            selector=args.selector,
            dataset_dir=args.dataset_dir,
            expected_revision=args.expected_revision,
            sandoq_site=args.sandoq_site,
            union_launch_plan=args.union_launch_plan,
            union_launch_plan_sha256=args.union_launch_plan_sha256,
        )
        _write_once(args.output, receipt)
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_tb4_w2_gate_failed","state":"blocked"}', file=__import__("sys").stderr)
        return 2
    print(
        json.dumps(
            {
                "capacity": ROLLOUT_CONCURRENCY,
                "membership_disclosed": False,
                "state": "passed",
                "task_count": TASK_COUNT,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
