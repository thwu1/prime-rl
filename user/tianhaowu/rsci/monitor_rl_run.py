#!/usr/bin/env python
"""Append scheduler, training, and strict-evaluation health for one RL run."""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ORCHESTRATOR_STEP_RE = re.compile(
    r"Step (?P<step>\d+) \|\s*(?P<duration>[^|]+) \| Reward (?P<reward>-?[0-9.]+) \| "
    r"Trainable (?P<trainable>[^|]+).*?Error (?P<error>[0-9.]+%).*?Truncation (?P<truncation>[0-9.]+%)"
)
TRAINER_STEP_RE = re.compile(
    r"Step (?P<step>\d+) \|\s*(?P<duration>[^|]+) \| Loss (?P<loss>-?[0-9.]+) \| "
    r"Entropy (?P<entropy>-?[0-9.]+)(?: \| Mismatch KL (?P<kl>-?[0-9.]+))?"
    r"(?: \| Grad\. Norm (?P<grad_norm>-?[0-9.]+))?.*?Throughput (?P<throughput>[0-9.]+) tokens/s"
    r" \| MFU (?P<mfu>[0-9.]+)%"
)
EVAL_RE = re.compile(
    r"Evaluated heldout-op(?P<op>\d+)-strict \(Step (?P<step>\d+)\).*?"
    r"Reward (?P<reward>-?[0-9.]+).*?Error (?P<error>[0-9.]+%).*?"
    r"Truncation (?P<truncation>[0-9.]+%)"
)
ISSUE_RE = re.compile(
    r"\b(?:WARNING|ERROR)\b|\b[Ee]rror:|\b[Ff]ailed\b|Traceback|RuntimeError|CUDA out of memory|"
    r"NCCL.*(?:[Ee]rror|[Ff]ail|[Tt]imeout|[Aa]bort)"
)
TERMINAL_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "TIMEOUT",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=int, default=3600)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    if args.interval_seconds < 1:
        raise ValueError("--interval-seconds must be positive")
    if args.poll_seconds < 1:
        raise ValueError("--poll-seconds must be positive")
    return args


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=check)


def scheduler_status(job_id: str) -> dict[str, str]:
    live = run(
        ["squeue", "--noheader", "--jobs", job_id, "--format=%T|%M|%R"],
        check=False,
    )
    if live.returncode != 0 and "Invalid job id specified" not in live.stderr:
        raise RuntimeError(live.stderr.strip())
    if live.stdout.strip():
        state, elapsed, reason = live.stdout.strip().split("|", maxsplit=2)
        return {"state": state, "elapsed": elapsed, "detail": reason}

    accounting = run(
        ["sacct", "-X", "--noheader", "--parsable2", "--jobs", job_id, "--format=JobIDRaw,State,Elapsed,ExitCode"]
    )
    rows = [line.split("|") for line in accounting.stdout.splitlines() if line.strip()]
    exact = next((row for row in rows if row[0] == job_id), None)
    if exact is None:
        raise RuntimeError(f"No scheduler record found for job {job_id}")
    state = exact[1].split()[0].rstrip("+")
    return {"state": state, "elapsed": exact[2], "detail": f"exit {exact[3]}"}


def tail_text(path: Path, max_bytes: int = 8 * 1024 * 1024) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        raw = handle.read()
    return ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))


def last_match(pattern: re.Pattern[str], text: str) -> dict[str, str] | None:
    match = None
    for match in pattern.finditer(text):
        pass
    return match.groupdict() if match is not None else None


def eval_matches(text: str) -> dict[int, dict[int, dict[str, str]]]:
    by_step: dict[int, dict[int, dict[str, str]]] = defaultdict(dict)
    for match in EVAL_RE.finditer(text):
        values = match.groupdict()
        by_step[int(values["step"])][int(values["op"])] = values
    return dict(by_step)


def issue_lines(paths: list[Path]) -> list[str]:
    issues: list[str] = []
    for path in paths:
        for line in tail_text(path, max_bytes=128 * 1024).splitlines():
            if ISSUE_RE.search(line):
                issues.append(f"{path.name}: {line.strip()}")
    return issues


def health_label(scheduler: dict[str, str], step: int | None, has_issues: bool) -> str:
    state = scheduler["state"]
    if state == "PENDING":
        return "Pending allocation"
    if state in {"RUNNING", "COMPLETING"}:
        if has_issues:
            return "Degraded"
        return "Healthy" if step is not None else "Starting"
    if state == "COMPLETED":
        return "Complete"
    return "Down"


def build_entry(job_id: str, output_dir: Path, max_steps: int) -> tuple[str, str]:
    scheduler = scheduler_status(job_id)
    orchestrator_path = output_dir / "logs" / "orchestrator.log"
    trainer_path = output_dir / "logs" / "trainer.log"
    inference_path = output_dir / "logs" / "inference.log"
    orchestrator_text = tail_text(orchestrator_path)
    trainer_text = tail_text(trainer_path)
    orchestrator = last_match(ORCHESTRATOR_STEP_RE, orchestrator_text)
    trainer = last_match(TRAINER_STEP_RE, trainer_text)
    step_values = [int(values["step"]) for values in (orchestrator, trainer) if values is not None]
    step = max(step_values) if step_values else None
    eval_by_step = eval_matches(orchestrator_text)
    eval_step = max(eval_by_step, key=lambda value: (len(eval_by_step[value]), value)) if eval_by_step else None

    log_paths = [orchestrator_path, trainer_path, inference_path]
    env_root = output_dir / "logs" / "envs"
    if env_root.is_dir():
        log_paths.extend(env_root.rglob("*.log"))
    issues = issue_lines(log_paths)

    lines = [
        f"## {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**Step**: {step if step is not None else scheduler['state'].lower()} / {max_steps}",
        f"**Health**: {health_label(scheduler, step, bool(issues))}",
        "",
        f"**Scheduler**: job `{job_id}` is `{scheduler['state']}` after `{scheduler['elapsed']}` "
        f"(`{scheduler['detail']}`).",
    ]
    if orchestrator is not None:
        lines.extend(
            [
                "",
                f"**Progress**: strict reward `{float(orchestrator['reward']):.4f}`; trainable "
                f"`{orchestrator['trainable'].strip()}`; rollout error `{orchestrator['error']}`; "
                f"truncation `{orchestrator['truncation']}`; orchestrator step time "
                f"`{orchestrator['duration'].strip()}`.",
            ]
        )
    if trainer is not None:
        kl = trainer["kl"] if trainer["kl"] is not None else "not logged"
        grad_norm = trainer["grad_norm"] if trainer["grad_norm"] is not None else "not logged"
        lines.extend(
            [
                "",
                f"**Stability**: loss `{trainer['loss']}`; entropy `{trainer['entropy']}`; mismatch KL "
                f"`{kl}`; gradient norm `{grad_norm}`.",
                f"**Performance**: `{trainer['throughput']} tokens/s`, `{trainer['mfu']}%` MFU, "
                f"trainer step time `{trainer['duration'].strip()}`.",
            ]
        )
    if eval_step is not None:
        evaluations = eval_by_step[eval_step]
        scores = ", ".join(f"OP{op} {100 * float(values['reward']):.2f}%" for op, values in sorted(evaluations.items()))
        lines.extend(
            [
                "",
                f"**Validation**: strict pass@1 at step `{eval_step}` ({len(evaluations)}/15 shards): {scores}.",
            ]
        )
    if issues:
        lines.extend(
            [
                "",
                f"**Log scan**: {len(issues)} warning/error lines in recent log tails. Latest: "
                + " | ".join(f"`{line[-300:]}`" for line in issues[-3:]),
            ]
        )
    elif scheduler["state"] in {"RUNNING", "COMPLETING", "COMPLETED"}:
        lines.extend(["", "**Log scan**: no warning/error lines in recent log tails."])
    return "\n".join(lines) + "\n", scheduler["state"]


def main() -> None:
    args = parse_args()
    status_path = args.output_dir / "STATUS.md"
    if not status_path.is_file():
        raise FileNotFoundError(f"Run status file does not exist: {status_path}")

    last_write_at: float | None = None
    while True:
        entry, state = build_entry(args.job_id, args.output_dir, args.max_steps)
        now = time.monotonic()
        should_write = last_write_at is None or state in TERMINAL_STATES or now - last_write_at >= args.interval_seconds
        if should_write:
            print(entry, flush=True)
            if not args.no_write:
                with status_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n" + entry)
            last_write_at = now
        if args.once or state in TERMINAL_STATES:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
