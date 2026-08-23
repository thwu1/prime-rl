from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key: str
    model: str
    deployment: dict[str, str]

    def public(self) -> dict[str, str]:
        return {"base_url": self.base_url, "model": self.model, **self.deployment}


def normalize_base_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return normalized


def load_config(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def policy_deployment_identity(section: dict[str, Any]) -> dict[str, str]:
    job_id = str(section.get("slurm_job_id", "")).strip()
    if not job_id:
        raise ValueError("policy.slurm_job_id is required for deployment provenance")
    if not job_id.isascii() or not job_id.isdigit():
        raise ValueError("policy.slurm_job_id must be a decimal Slurm job ID")
    deployment_id = str(section.get("deployment_id", "")).strip()
    expected = f"slurm-{job_id}:model-{section.get('checkpoint_revision', '')}:vllm-{section.get('server_version', '')}"
    if deployment_id != expected:
        raise ValueError(
            "policy.deployment_id must exactly encode policy.slurm_job_id, "
            "policy.checkpoint_revision, and policy.server_version"
        )
    return {"deployment_id": deployment_id, "slurm_job_id": job_id}


def judge_deployment_identity(section: dict[str, Any]) -> dict[str, str]:
    proxy_jobid = str(section.get("proxy_jobid", "")).strip()
    if not proxy_jobid:
        raise ValueError("judge.proxy_jobid is required for deployment provenance")
    if not proxy_jobid.isascii() or not proxy_jobid.isdigit():
        raise ValueError("judge.proxy_jobid must be a decimal proxy job ID")
    deployment_id = str(section.get("deployment_id", "")).strip()
    prefix, separator, suffix = deployment_id.rpartition(":")
    if not prefix or not separator or suffix != f"proxy-job-{proxy_jobid}":
        raise ValueError("judge.deployment_id must end with the configured judge.proxy_jobid")
    return {"deployment_id": deployment_id, "proxy_jobid": proxy_jobid}


def _matching_url(value: str, expected: str, source: str) -> None:
    if normalize_base_url(value) != expected:
        raise ValueError(f"{source} does not match the resolved deployment endpoint")


def load_info_endpoint(section: dict[str, Any], override_url: str | None = None) -> Endpoint:
    deployment = judge_deployment_identity(section)
    info_path = section.get("info_path")
    if not info_path:
        raise ValueError("judge.info_path is required to resolve judge.proxy_jobid")
    info = json.loads(Path(info_path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(info, dict):
        raise ValueError("Judge endpoint info must be a JSON object")
    if str(info.get("proxy_jobid", "")) != deployment["proxy_jobid"]:
        raise ValueError("Judge endpoint proxy_jobid does not match the configured deployment")
    info_model = str(info.get("model", ""))
    if not info_model or info_model != str(section.get("model", "")):
        raise ValueError("Judge endpoint model does not match the configured deployment")
    info_url = info.get("url")
    if not info_url:
        raise ValueError("Judge endpoint info has no URL")
    resolved_url = normalize_base_url(str(info_url))
    env_url = os.getenv(str(section.get("base_url_env", ""))) if section.get("base_url_env") else None
    for source, value in (
        ("Judge CLI base-URL override", override_url),
        ("Judge environment base-URL override", env_url),
        ("judge.base_url", section.get("base_url")),
    ):
        if value:
            _matching_url(str(value), resolved_url, source)
    env_key = os.getenv(str(section.get("api_key_env", ""))) if section.get("api_key_env") else None
    api_key = env_key or section.get("api_key") or info.get("api_key") or "EMPTY"
    return Endpoint(resolved_url, str(api_key), info_model, deployment)


def _slurm_job_node(job_id: str, expected_job_name: str) -> str:
    result = subprocess.run(
        ["squeue", "-h", "-j", job_id, "-t", "RUNNING", "-o", "%j|%N"],
        check=True,
        capture_output=True,
        text=True,
    )
    allocations = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(allocations) != 1:
        raise ValueError(f"Expected one running allocation for Slurm job {job_id}, found {allocations}")
    job_name, separator, nodelist = allocations[0].partition("|")
    if not separator or not nodelist or nodelist == "(null)":
        raise ValueError(f"Slurm job {job_id} has an invalid allocation record: {allocations[0]!r}")
    if job_name != expected_job_name:
        raise ValueError(f"Slurm job {job_id} name mismatch: expected {expected_job_name!r}, got {job_name!r}")
    expanded = subprocess.run(
        ["scontrol", "show", "hostnames", nodelist],
        check=True,
        capture_output=True,
        text=True,
    )
    nodes = [line.strip() for line in expanded.stdout.splitlines() if line.strip()]
    if not nodes:
        raise ValueError(f"Slurm job {job_id} has no allocated nodes")
    return nodes[0]


def load_policy_endpoint(
    section: dict[str, Any],
    override_url: str | None = None,
    override_job_id: str | None = None,
) -> Endpoint:
    deployment = policy_deployment_identity(section)
    configured_job_id = deployment["slurm_job_id"]
    env_job = os.getenv(str(section.get("slurm_job_id_env", ""))) if section.get("slurm_job_id_env") else None
    for source, value in (
        ("Policy CLI Slurm-job override", override_job_id),
        ("Policy environment Slurm-job override", env_job),
    ):
        if value and str(value) != configured_job_id:
            raise ValueError(f"{source} does not match policy.slurm_job_id")
    job_name = str(section.get("slurm_job_name", "")).strip()
    if not job_name:
        raise ValueError("policy.slurm_job_name is required for deployment provenance")
    node = _slurm_job_node(configured_job_id, job_name)
    resolved_url = normalize_base_url(f"http://{node}:{int(section['port'])}")
    env_url = os.getenv(str(section.get("base_url_env", ""))) if section.get("base_url_env") else None
    for source, value in (
        ("Policy CLI base-URL override", override_url),
        ("Policy environment base-URL override", env_url),
        ("policy.base_url", section.get("base_url")),
    ):
        if value:
            _matching_url(str(value), resolved_url, source)
    api_key_env = str(section.get("api_key_env", ""))
    return Endpoint(
        base_url=resolved_url,
        api_key=(os.getenv(api_key_env) if api_key_env else None) or "EMPTY",
        model=str(section["model"]),
        deployment=deployment,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected object in {path}:{line_number}")
            rows.append(row)
    return rows


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def repair_truncated_jsonl_tail(
    path: Path,
    *,
    recovery_dir: Path,
    owner: str,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    with path.open("r+b") as handle:
        data = handle.read()
        if not data:
            return None

        lines = data.split(b"\n")
        nonblank = [index for index, line in enumerate(lines) if line.strip()]
        if not nonblank:
            return None
        final_record_index = nonblank[-1]

        repair_offset: int | None = None
        action: str | None = None
        reason: str | None = None
        issue: str | None = None
        offset = 0
        for index, encoded_line in enumerate(lines):
            line_number = index + 1
            line_offset = offset
            offset += len(encoded_line) + (1 if index < len(lines) - 1 else 0)
            if not encoded_line.strip():
                continue
            try:
                line = encoded_line.decode("utf-8")
                row = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                if index != final_record_index:
                    raise ValueError(f"Malformed JSONL record in {path}:{line_number}: {error}") from error
                repair_offset = line_offset
                action = "truncate"
                reason = "malformed_final_record"
                issue = f"{type(error).__name__}: {error}"
                break
            if not isinstance(row, dict):
                if index != final_record_index:
                    raise ValueError(f"Expected object in {path}:{line_number}")
                repair_offset = line_offset
                action = "truncate"
                reason = "non_object_final_record"
                issue = f"decoded {type(row).__name__}, expected object"
                break

        if repair_offset is None:
            if data.endswith(b"\n") or final_record_index < len(lines) - 1:
                return None
            action = "append_newline"
            reason = "unterminated_final_record"
            issue = "final JSONL object has no newline terminator"

        if action == "truncate":
            if repair_offset is None:
                raise AssertionError("truncate repair is missing an offset")
            discarded = data[repair_offset:]
            repaired_data = data[:repair_offset]
        elif action == "append_newline":
            discarded = b""
            repaired_data = data + b"\n"
        else:
            raise AssertionError(f"Unexpected JSONL repair action: {action}")
        recovery_dir.mkdir(parents=True, exist_ok=True)
        event_id = f"{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex}"
        recovery_path = recovery_dir / f"{path.name}.{event_id}.json"
        event: dict[str, Any] = {
            "schema_version": 1,
            "event": "jsonl_tail_repair",
            "event_id": event_id,
            "status": "pending",
            "time": time.time(),
            "owner": owner,
            "path": str(path.resolve()),
            "action": action,
            "reason": reason,
            "issue": issue,
            "original_size": len(data),
            "original_sha256": hashlib.sha256(data).hexdigest(),
            "repaired_size": len(repaired_data),
            "repaired_sha256": hashlib.sha256(repaired_data).hexdigest(),
            "discarded_bytes": len(discarded),
            "discarded_sha256": hashlib.sha256(discarded).hexdigest(),
            "appended_bytes": 1 if action == "append_newline" else 0,
            "recovery_record": str(recovery_path.resolve()),
        }
        atomic_write_json(recovery_path, event)
        _fsync_directory(recovery_dir)

        if action == "truncate":
            handle.seek(repair_offset)
            handle.truncate()
        elif action == "append_newline":
            handle.seek(0, os.SEEK_END)
            handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.seek(0)
        if handle.read() != repaired_data:
            raise OSError(f"JSONL repair verification failed for {path}")

        event["status"] = "completed"
        event["completed_time"] = time.time()
        atomic_write_json(recovery_path, event)
        _fsync_directory(recovery_dir)
        logger.warning(
            "Repaired incomplete JSONL tail in %s with %s; discarded %d bytes; record=%s",
            path,
            action,
            len(discarded),
            recovery_path,
        )
        return event


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
