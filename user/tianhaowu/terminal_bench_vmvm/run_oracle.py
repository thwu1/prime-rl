#!/usr/bin/env python3
"""Durable, resumable oracle validation for Terminal-Bench tasks on VMVM."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import random
import signal
import time
from pathlib import Path

from terminal_bench_vmvm.taskset import (
    OracleFailure,
    TerminalBenchTask,
    TerminalBenchVMVMConfig,
    TerminalBenchVMVMTaskset,
    UnsupportedTaskError,
)
from verifiers.v1.env import resolve_runtime_config
from verifiers.v1.errors import SandboxError
from verifiers.v1.runtimes import VMVMConfig, make_runtime

logger = logging.getLogger("terminal_bench_vmvm.oracle")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image-prefix", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--image-manifest", type=Path)
    parser.add_argument("--use-declared-images", action="store_true")
    parser.add_argument("--enable-compose", action="store_true")
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--tasks", nargs="*")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-concurrent", type=int, default=64)
    parser.add_argument("--infra-retries", type=int, default=2)
    parser.add_argument("--setup-timeout", type=float, default=1800)
    parser.add_argument("--validate-timeout", type=float, default=10800)
    parser.add_argument("--session-timeout", type=float, default=10800)
    parser.add_argument("--tenant-id", default="async_2347641")
    parser.add_argument("--lease-ttl", default="60s")
    parser.add_argument("--max-session-buffer-size", type=int, default=67_108_864)
    parser.add_argument("--verifier-runtime-retries", type=int, default=2)
    parser.add_argument("--timeout-multiplier", type=float, default=1.0)
    parser.add_argument("--resource-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--oracle-solution-network-mode",
        choices=("declared", "public"),
        default="declared",
        help="network policy for trusted solve.sh only; verifier policy remains declared",
    )
    parser.add_argument("--minimum-pass-rate", type=float, default=0.9)
    parser.add_argument("--minimum-valid", type=int, default=0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--rerun-invalid", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    if args.max_concurrent < 1:
        parser.error("--max-concurrent must be positive")
    if args.infra_retries < 0:
        parser.error("--infra-retries cannot be negative")
    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate must be between 0 and 1")
    if args.minimum_valid < 0:
        parser.error("--minimum-valid cannot be negative")
    if args.timeout_multiplier <= 0 or args.resource_multiplier <= 0:
        parser.error("timeout and resource multipliers must be positive")
    return args


def _requested_tasks(args: argparse.Namespace) -> list[str] | None:
    names = list(args.tasks or [])
    if args.task_file:
        names.extend(
            line.strip().split("\t", 1)[0]
            for line in args.task_file.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return sorted(set(names)) or None


def _atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def _read_result(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _oracle_network_semantics(mode: str) -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "trusted_reference_solution": mode,
        "verifier": "declared",
    }


def _bind_oracle_network_semantics(output_dir: Path, mode: str) -> dict[str, str | int]:
    """Create or validate the immutable network-semantics label for a run."""
    expected = _oracle_network_semantics(mode)
    path = output_dir / "oracle_network_semantics.json"
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid oracle network semantics file: {path}") from error
        if existing != expected:
            raise SystemExit(
                "oracle network semantics mismatch: "
                f"saved={existing!r} requested={expected!r}; use a fresh output directory"
            )
        return expected

    status_dir = output_dir / "tasks"
    if (
        (output_dir / "results.jsonl").exists()
        or (output_dir / "summary.json").exists()
        or any(status_dir.glob("*.json"))
    ):
        raise SystemExit(
            "existing oracle results have no immutable network-semantics label; use a fresh output directory"
        )
    _atomic_json(path, expected)
    return expected


async def _attempt(
    taskset: TerminalBenchVMVMTaskset,
    task: TerminalBenchTask,
    runtime_config: VMVMConfig,
    setup_timeout: float,
    validate_timeout: float,
    attempt: int,
) -> tuple[bool, dict]:
    runtime = make_runtime(
        resolve_runtime_config(runtime_config, task),
        name=f"tb-oracle-{task.idx}-{attempt}",
    )
    started = time.time()
    descriptor = None
    cleanup_error = None
    try:
        await asyncio.wait_for(runtime.start(), timeout=setup_timeout)
        descriptor = runtime.descriptor
        await asyncio.wait_for(taskset.setup_oracle(task, runtime), timeout=setup_timeout)
        valid = await asyncio.wait_for(taskset.validate(task, runtime), timeout=validate_timeout)
        return bool(valid), {
            "attempt": attempt,
            "runtime": descriptor,
            "elapsed_sec": round(time.time() - started, 3),
        }
    finally:
        try:
            try:
                await taskset.cleanup(task, None, runtime)
            except Exception as error:
                cleanup_error = f"{type(error).__name__}: {error}"
                logger.warning("%s taskset cleanup failed: %s", task.name, cleanup_error)
        finally:
            try:
                await asyncio.shield(runtime.stop())
            except Exception as error:
                cleanup_error = f"{type(error).__name__}: {error}"
                logger.warning("%s cleanup failed: %s", task.name, cleanup_error)


async def _validate_one(
    taskset: TerminalBenchVMVMTaskset,
    task: TerminalBenchTask,
    runtime_config: VMVMConfig,
    args: argparse.Namespace,
) -> dict:
    started = time.time()
    infrastructure_failures: list[dict] = []
    for attempt in range(1, args.infra_retries + 2):
        try:
            valid, detail = await _attempt(
                taskset,
                task,
                runtime_config,
                args.setup_timeout,
                args.validate_timeout,
                attempt,
            )
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": valid,
                "reason": "valid" if valid else "invalid",
                "error": None,
                "error_type": None,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "last_attempt": detail,
                "infrastructure_failures": infrastructure_failures,
            }
        except SandboxError as error:
            failure = {
                "attempt": attempt,
                "error_type": type(error).__name__,
                "error": str(error),
            }
            infrastructure_failures.append(failure)
            if attempt > args.infra_retries:
                return {
                    "index": task.idx,
                    "name": task.name,
                    "slug": task.slug,
                    "image": task.image,
                    "valid": False,
                    "reason": "infrastructure_error",
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "elapsed_sec": round(time.time() - started, 3),
                    "attempts": attempt,
                    "infrastructure_failures": infrastructure_failures,
                }
            delay = min(30.0, 2 ** (attempt - 1) + random.random())
            logger.warning(
                "%s VMVM failure; retrying entire oracle in %.1fs: %s",
                task.name,
                delay,
                error,
            )
            await asyncio.sleep(delay)
        except asyncio.TimeoutError as error:
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": False,
                "reason": "timeout",
                "error": str(error) or "oracle stage timed out",
                "error_type": type(error).__name__,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "infrastructure_failures": infrastructure_failures,
            }
        except (OracleFailure, UnsupportedTaskError) as error:
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": False,
                "reason": "unsupported" if isinstance(error, UnsupportedTaskError) else "invalid",
                "error": str(error),
                "error_type": type(error).__name__,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "infrastructure_failures": infrastructure_failures,
            }
        except Exception as error:
            logger.exception("%s oracle error", task.name)
            return {
                "index": task.idx,
                "name": task.name,
                "slug": task.slug,
                "image": task.image,
                "valid": False,
                "reason": "error",
                "error": str(error),
                "error_type": type(error).__name__,
                "elapsed_sec": round(time.time() - started, 3),
                "attempts": attempt,
                "infrastructure_failures": infrastructure_failures,
            }
    raise AssertionError("unreachable")


def _summary(results: list[dict], selected: int, network_semantics: dict[str, str | int]) -> dict:
    reasons: dict[str, int] = {}
    for result in results:
        reasons[result["reason"]] = reasons.get(result["reason"], 0) + 1
    passed = sum(result["valid"] for result in results)
    return {
        "selected": selected,
        "completed": len(results),
        "passed": passed,
        "pass_rate": passed / selected if selected else 0.0,
        "reasons": reasons,
        "oracle_network_semantics": network_semantics,
    }


def _meets_acceptance(summary: dict, minimum_pass_rate: float, minimum_valid: int) -> bool:
    return summary["pass_rate"] >= minimum_pass_rate and summary["passed"] >= minimum_valid


async def _run(args: argparse.Namespace) -> int:
    requested = _requested_tasks(args)
    taskset = TerminalBenchVMVMTaskset(
        TerminalBenchVMVMConfig(
            id="terminal-bench-vmvm",
            dataset_dir=args.dataset_dir,
            tasks=requested,
            image_prefix=args.image_prefix,
            image_tag=args.image_tag,
            image_manifest=args.image_manifest,
            use_declared_images=args.use_declared_images,
            enable_compose=args.enable_compose,
            verifier_runtime_retries=args.verifier_runtime_retries,
            timeout_multiplier=args.timeout_multiplier,
            resource_multiplier=args.resource_multiplier,
            oracle_solution_network_mode=args.oracle_solution_network_mode,
            ignore_dockerfile=True,
        )
    )
    tasks = taskset.load_tasks()
    tasks = tasks[args.offset : args.offset + args.limit if args.limit is not None else None]
    if not tasks:
        raise SystemExit("no tasks selected")
    if args.minimum_valid > len(tasks):
        raise SystemExit(f"--minimum-valid={args.minimum_valid} exceeds {len(tasks)} selected tasks")

    output_dir = args.output_dir.resolve()
    status_dir = output_dir / "tasks"
    status_dir.mkdir(parents=True, exist_ok=True)
    lock = (output_dir / ".writer.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise SystemExit(f"another oracle runner owns {output_dir}") from error

    network_semantics = _bind_oracle_network_semantics(output_dir, args.oracle_solution_network_mode)

    run_config = {
        "dataset_dir": str(args.dataset_dir.resolve()),
        "image_prefix": args.image_prefix,
        "image_tag": args.image_tag,
        "max_concurrent": args.max_concurrent,
        "infra_retries": args.infra_retries,
        "timeout_multiplier": args.timeout_multiplier,
        "resource_multiplier": args.resource_multiplier,
        "minimum_pass_rate": args.minimum_pass_rate,
        "minimum_valid": args.minimum_valid,
        "oracle_solution_network_mode": args.oracle_solution_network_mode,
        "oracle_network_semantics": network_semantics,
        "selected_tasks": len(tasks),
        "started_at": time.time(),
    }
    _atomic_json(output_dir / "run_config.json", run_config)

    pending: list[TerminalBenchTask] = []
    results_by_slug: dict[str, dict] = {}
    for task in tasks:
        path = status_dir / f"{task.slug}.json"
        prior = _read_result(path) if args.resume else None
        if prior is not None and prior.get("oracle_network_semantics") != network_semantics:
            raise SystemExit(
                f"{task.slug}: saved task result has different or missing oracle network semantics; "
                "use a fresh output directory"
            )
        if prior is not None and (prior.get("valid") or not args.rerun_invalid):
            results_by_slug[task.slug] = prior
        else:
            pending.append(task)

    runtime_config = VMVMConfig(
        image="python:3.12-slim",
        workdir="/app",
        session_timeout=args.session_timeout,
        tenant_id=args.tenant_id,
        lease_ttl=args.lease_ttl,
        max_session_buffer_size=args.max_session_buffer_size,
    )
    semaphore = asyncio.Semaphore(args.max_concurrent)

    async def one(task: TerminalBenchTask) -> dict:
        async with semaphore:
            logger.info("start idx=%d task=%s", task.idx, task.name)
            result = await _validate_one(taskset, task, runtime_config, args)
            result["oracle_network_semantics"] = network_semantics
            _atomic_json(status_dir / f"{task.slug}.json", result)
            logger.info(
                "done idx=%d task=%s reason=%s elapsed=%.1fs",
                task.idx,
                task.name,
                result["reason"],
                result["elapsed_sec"],
            )
            return result

    logger.info("selected=%d resumed=%d pending=%d", len(tasks), len(results_by_slug), len(pending))
    futures = [asyncio.create_task(one(task)) for task in pending]
    try:
        for future in asyncio.as_completed(futures):
            result = await future
            results_by_slug[result["slug"]] = result
            ordered = [results_by_slug[task.slug] for task in tasks if task.slug in results_by_slug]
            _atomic_json(output_dir / "summary.json", _summary(ordered, len(tasks), network_semantics))

        results = [results_by_slug[task.slug] for task in tasks]
        with (output_dir / "results.jsonl.tmp").open("w") as handle:
            for result in results:
                handle.write(json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(output_dir / "results.jsonl.tmp", output_dir / "results.jsonl")
        summary = _summary(results, len(tasks), network_semantics)
        summary["finished_at"] = time.time()
        _atomic_json(output_dir / "summary.json", summary)
        logger.info("oracle summary: %s", json.dumps(summary, sort_keys=True))
        accepted = _meets_acceptance(summary, args.minimum_pass_rate, args.minimum_valid)
        return 0 if accepted else 2
    finally:
        for future in futures:
            future.cancel()
        if futures:
            await asyncio.gather(*futures, return_exceptions=True)
        await taskset.close()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        logger.warning("interrupted; completed per-task results remain resumable")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
