#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

TIMEOUT_ERROR_TYPE = "TasksetError"
TIMEOUT_ERROR_MESSAGE = "scoring timed out"
PROMPT_SUFFIX = re.compile(r"\n\n\(Current directory: .*\) bash-\$$", re.DOTALL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert exact outer SWE-rebench verifier timeouts into the benchmark's "
            "terminal zero-score outcome without rerunning the model trajectory."
        )
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--trace-id", action="append", default=[])
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_patch(row: dict[str, object]) -> dict[str, object]:
    info = row.get("info")
    if isinstance(info, dict):
        candidate = info.get("swe_rebench_candidate_patch")
        if isinstance(candidate, dict):
            patch = candidate.get("patch")
            if isinstance(patch, str):
                encoded = patch.encode()
                if candidate.get("bytes") != len(encoded):
                    raise ValueError(f"{row.get('id')}: candidate patch byte count does not match")
                if candidate.get("sha256") != hashlib.sha256(encoded).hexdigest():
                    raise ValueError(f"{row.get('id')}: candidate patch SHA-256 does not match")
                return candidate

    patches = []
    for node in row.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        output = PROMPT_SUFFIX.sub("", content)
        if output.startswith("diff --git "):
            patches.append(output.rstrip() + "\n")
    if not patches:
        raise ValueError(f"{row.get('id')}: no exact candidate patch was captured in the trace")
    patch = patches[-1]
    encoded = patch.encode()
    return {
        "bytes": len(encoded),
        "patch": patch,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "source": "last_trace_git_diff",
    }


def is_exact_timeout(row: dict[str, object]) -> bool:
    errors = row.get("errors")
    if not isinstance(errors, list) or len(errors) != 1:
        return False
    error = errors[0]
    return (
        isinstance(error, dict)
        and error.get("type") == TIMEOUT_ERROR_TYPE
        and error.get("message") == TIMEOUT_ERROR_MESSAGE
    )


def recover_row(
    row: dict[str, object],
    source_sha256: str,
    outer_scoring_timeout: float,
) -> None:
    trace_id = row.get("id")
    if row.get("is_completed") is not True:
        raise ValueError(f"{trace_id}: timed-out row is not complete")
    rewards = row.get("rewards")
    if not isinstance(rewards, dict) or rewards:
        raise ValueError(f"{trace_id}: timed-out row already has rewards")

    task = row.get("task")
    timeout = (task.get("timeout") or {}).get("scoring") if isinstance(task, dict) else None
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError(f"{trace_id}: missing positive task scoring timeout")
    if float(timeout) != outer_scoring_timeout:
        raise ValueError(
            f"{trace_id}: outer scoring timeout {outer_scoring_timeout:g} did not equal "
            f"the official verifier timeout {float(timeout):g}"
        )
    timing = row.get("timing")
    scoring = timing.get("scoring") if isinstance(timing, dict) else None
    if not isinstance(scoring, dict) or not isinstance(scoring.get("start"), (int, float)):
        raise ValueError(f"{trace_id}: missing scoring timing")
    if scoring.get("end") not in (0, 0.0):
        raise ValueError(f"{trace_id}: timed-out row already has a scoring end timestamp")

    info = row.get("info")
    if not isinstance(info, dict):
        info = {}
        row["info"] = info
    info["swe_rebench_candidate_patch"] = candidate_patch(row)
    info["swe_rebench_verifier"] = {
        "exit_code": None,
        "reward": 0.0,
        "timed_out": True,
        "timeout_sec": float(timeout),
    }
    info["swe_rebench_verifier_attempts"] = 1
    info["swe_rebench_verifier_failures"] = []
    info["swe_rebench_timeout_recovery"] = {
        "classification": "official_verifier_timeout",
        "source_error_type": TIMEOUT_ERROR_TYPE,
        "source_error_message": TIMEOUT_ERROR_MESSAGE,
        "source_results_sha256": source_sha256,
    }
    rewards["solved"] = 0.0
    row["errors"] = []
    scoring["end"] = float(scoring["start"]) + float(timeout)


def main() -> None:
    args = parse_args()
    results = args.results.resolve()
    output = args.output.resolve()
    config_path = (args.config or results.parent / "config.toml").resolve()
    if results == output:
        raise SystemExit("--output must differ from the source results file")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")
    config = tomllib.loads(config_path.read_text())
    if config.get("taskset", {}).get("id") != "swe-rebench-harbor":
        raise SystemExit(f"config does not use swe-rebench-harbor: {config_path}")
    outer_scoring_timeout = config.get("timeout", {}).get("scoring")
    if (
        not isinstance(outer_scoring_timeout, (int, float))
        or isinstance(outer_scoring_timeout, bool)
        or outer_scoring_timeout <= 0
    ):
        raise SystemExit(f"config has no positive outer scoring timeout: {config_path}")
    outer_scoring_timeout = float(outer_scoring_timeout)

    lock_path = results.parent / ".writer.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SystemExit(f"the evaluator still owns {results.parent}") from error

        source_sha256 = file_sha256(results)
        requested = set(args.trace_id)
        seen: set[str] = set()
        recovered: list[dict[str, object]] = []
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        try:
            with results.open() as source, temporary.open("x") as destination:
                for line_number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    trace_id = row.get("id")
                    selected = not requested or trace_id in requested
                    if selected and is_exact_timeout(row):
                        recover_row(row, source_sha256, outer_scoring_timeout)
                        seen.add(str(trace_id))
                        task = row.get("task")
                        recovered.append(
                            {
                                "line": line_number,
                                "trace_id": trace_id,
                                "task_idx": task.get("idx") if isinstance(task, dict) else None,
                                "task_name": task.get("name") if isinstance(task, dict) else None,
                            }
                        )
                    destination.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
                    destination.write("\n")
                destination.flush()
                os.fsync(destination.fileno())

            missing = requested - seen
            if missing:
                raise SystemExit(f"requested trace IDs were not exact scoring timeouts: {sorted(missing)}")
            if not recovered:
                raise SystemExit("no exact SWE-rebench scoring timeouts found")
            temporary.replace(output)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    report = {
        "source": str(results),
        "source_sha256": source_sha256,
        "config": str(config_path),
        "outer_scoring_timeout": outer_scoring_timeout,
        "output": str(output),
        "output_sha256": file_sha256(output),
        "recovered": recovered,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
