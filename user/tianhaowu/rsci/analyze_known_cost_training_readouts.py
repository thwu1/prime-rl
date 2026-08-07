#!/usr/bin/env python3
"""Build deterministic training-side readouts for the known-cost boundary study."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

import materialize_known_cost_boundary_launch as launch
import materialize_known_cost_eval_plan as eval_plan
import materialize_known_cost_postrun_authority as postrun_authority
import materialize_known_cost_training_completion as training_completion
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_training_readouts"
ANALYSIS_ID = "known-cost-training-readouts-v1"
SCRIPT_REPOSITORY_PATH = "user/tianhaowu/rsci/analyze_known_cost_training_readouts.py"
TAG_COUNT = 6
PHYSICAL_GROUP_SIZE = 128

CompletionReceiptValidator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

TRAINER_METRIC_KEYS = (
    "entropy/all/mean",
    "entropy/all/std",
    "entropy/all/max",
    "mismatch_kl/all/mean",
    "mismatch_kl/all/std",
    "mismatch_kl/all/max",
    "is_masked/mean",
    "is_masked/max",
    "is_masked_low/mean",
    "is_masked_low/max",
    "is_masked_high/mean",
    "is_masked_high/max",
    "masked_advantage_positive/mean",
    "masked_advantage_positive/max",
    "masked_advantage_negative/mean",
    "masked_advantage_negative/max",
    "masked_mismatch_kl/mean",
    "masked_mismatch_kl/max",
    "unmasked_mismatch_kl/mean",
    "unmasked_mismatch_kl/max",
    "optim/grad_norm",
)
ORCHESTRATOR_PERIODIC_KEYS = (
    "dispatcher/cancelled/train",
    "dispatcher/off_policy_level_max",
    "dispatcher/off_policy_level_mean",
    "train_sink/groups_finalized",
    "_timestamp",
)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
WANDB_DIR_RE = re.compile(r"wandb: Run data is saved locally in (?P<path>\S+)\s*$")
TRAINER_STEP_RE = re.compile(
    r"\bStep (?P<step>[0-9]+) \|[^\n]*?\| Loss (?P<loss>-?[0-9.]+) \| "
    r"Entropy (?P<entropy>-?[0-9.]+) \| Mismatch KL (?P<mismatch_kl>-?[0-9.]+) \| "
    r"Grad\. Norm (?P<grad_norm>-?[0-9.]+) \|"
)
ORCHESTRATOR_STEP_RE = re.compile(
    r"\bStep (?P<step>[0-9]+) \|[^\n]*?\| Reward (?P<reward>-?[0-9.]+) \| "
    r"Trainable (?P<trainable>[0-9]+)/(?P<rollouts>[0-9]+) \([^)]*\) \|[^\n]*?"
    r"Max Off-Policy (?P<max_off_policy>[0-9]+) \| Error (?P<error>[0-9.]+)% \| "
    r"Truncation (?P<truncation>[0-9.]+)%"
)
STALE_CANCEL_RE = re.compile(
    r"Cancelled (?P<count>[0-9]+) train rollouts past max_off_policy_steps=(?P<limit>[0-9]+)\."
)
POLICY_VERSION_RE = re.compile(r"Updating policy in-flight to v(?P<version>[0-9]+)")
JOINT_STOP_RE = re.compile(
    r"Draining pipeline \(reached joint stop: steps=(?P<step>[0-9]+)/(?P<min_step>[0-9]+), "
    r"finalized_groups=(?P<groups>[0-9]+)/(?P<min_groups>[0-9]+); cancelled "
    r"(?P<cancelled>[0-9]+) in-flight train rollout\(s\); any in-flight evals will complete\)"
)


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _require_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _strict_json(value: str, label: str) -> Any:
    def reject(constant: str) -> Any:
        raise ValueError(f"{label} contains non-finite JSON: {constant}")

    return json.loads(value, parse_constant=reject)


def _history_item_key(item: Any, label: str) -> str:
    nested = list(item.nested_key)
    if item.key and nested:
        raise ValueError(f"{label} has both key and nested_key")
    if nested:
        if any(not value for value in nested):
            raise ValueError(f"{label} has an empty nested key component")
        return "/".join(nested)
    if not item.key:
        raise ValueError(f"{label} has no key")
    return str(item.key)


def _stat_fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    state = path.stat()
    return state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns


def _read_stable_text(path: Path) -> tuple[str, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    before = _stat_fingerprint(resolved)
    raw = resolved.read_bytes()
    after = _stat_fingerprint(resolved)
    if before != after or len(raw) != after[2]:
        raise RuntimeError(f"File changed while being read: {resolved}")
    return raw.decode("utf-8"), {
        "path": str(resolved),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _wandb_stream_path(run_dir: Path, log_text: str, expected_output_dir: Path, label: str) -> Path:
    directories = {Path(match.group("path")).expanduser().resolve() for match in WANDB_DIR_RE.finditer(log_text)}
    if len(directories) != 1:
        raise ValueError(f"{label} log names {len(directories)} local W&B run directories, expected one")
    directory = directories.pop()
    expected_parent = expected_output_dir.expanduser().resolve() / "wandb"
    if directory.parent != expected_parent or not directory.name.startswith(("run-", "offline-run-")):
        raise ValueError(f"{label} local W&B directory is outside its sealed output: {directory}")
    if not directory.is_relative_to(run_dir.expanduser().resolve()):
        raise ValueError(f"{label} local W&B directory is outside the run root")
    streams = sorted(directory.glob("*.wandb"))
    if len(streams) != 1:
        raise ValueError(f"{label} local W&B directory contains {len(streams)} event streams")
    return streams[0].resolve()


def _wandb_run_id_from_path(path: Path) -> str:
    name = path.name
    if not name.startswith("run-") or not name.endswith(".wandb"):
        raise ValueError(f"Unexpected local W&B stream name: {path}")
    run_id = name[len("run-") : -len(".wandb")]
    if not run_id:
        raise ValueError(f"Local W&B stream has an empty run ID: {path}")
    return run_id


def _strict_wandb_payloads(store: datastore.DataStore, path: Path) -> Iterable[bytes]:
    while True:
        offset = store._index % datastore.LEVELDBLOG_BLOCK_LEN
        space_left = datastore.LEVELDBLOG_BLOCK_LEN - offset
        if space_left < datastore.LEVELDBLOG_HEADER_LEN:
            padding = store._fp.read(space_left)
            if padding != b"\x00" * space_left:
                raise ValueError(f"Local W&B stream has invalid block padding: {path}")
            store._index += space_left
        try:
            record = store.scan_record()
        except AssertionError as error:
            raise ValueError(f"Local W&B stream record framing is invalid: {path}: {error}") from error
        if record is None:
            return
        record_type, payload = record
        if record_type == datastore.LEVELDBLOG_FULL:
            yield payload
            continue
        if record_type != datastore.LEVELDBLOG_FIRST:
            raise ValueError(f"Local W&B stream begins a payload with fragment type {record_type}: {path}")
        fragments = [payload]
        while True:
            try:
                continuation = store.scan_record()
            except AssertionError as error:
                raise ValueError(f"Local W&B stream continuation is invalid: {path}: {error}") from error
            if continuation is None:
                raise ValueError(f"Local W&B stream ends after FIRST/MIDDLE without LAST: {path}")
            fragment_type, fragment = continuation
            fragments.append(fragment)
            if fragment_type == datastore.LEVELDBLOG_LAST:
                break
            if fragment_type != datastore.LEVELDBLOG_MIDDLE:
                raise ValueError(f"Local W&B stream has fragment type {fragment_type} between FIRST and LAST: {path}")
        yield b"".join(fragments)


def _scan_local_wandb(
    path: Path,
    *,
    selected_keys: tuple[str, ...],
    row_trigger_keys: tuple[str, ...],
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    before = _stat_fingerprint(resolved)
    store = datastore.DataStore()
    store.open_for_scan(str(resolved))
    record_counts: Counter[str] = Counter()
    run_records = []
    selected_rows = []
    for data in _strict_wandb_payloads(store, resolved):
        record = wandb_internal_pb2.Record()
        record.ParseFromString(data)
        record_type = record.WhichOneof("record_type")
        if record_type is None:
            raise ValueError(f"Local W&B stream contains a record with no type: {resolved}")
        record_counts[record_type] += 1
        if record_type == "run":
            config = {}
            for index, item in enumerate(record.run.config.update):
                key = _history_item_key(item, f"W&B run config item {index}")
                if key in config:
                    raise ValueError(f"Local W&B run config repeats {key!r}")
                config[key] = _strict_json(item.value_json, f"W&B run config {key}")
            run_records.append(
                {
                    "run_id": record.run.run_id,
                    "display_name": record.run.display_name,
                    "config": config,
                }
            )
            continue
        if record_type != "history":
            continue
        row = {}
        for index, item in enumerate(record.history.item):
            key = _history_item_key(item, f"W&B history item {index}")
            if key in row:
                raise ValueError(f"Local W&B history record repeats {key!r}")
            if key in selected_keys or key == "step":
                row[key] = _strict_json(item.value_json, f"W&B history {key}")
        if any(key in row for key in row_trigger_keys):
            selected_rows.append(row)
    store.close()
    after_scan = _stat_fingerprint(resolved)
    if after_scan != before:
        raise RuntimeError(f"Local W&B stream changed while being scanned: {resolved}")
    identity = eval_plan.file_identity(resolved)
    if _stat_fingerprint(resolved) != before:
        raise RuntimeError(f"Local W&B stream changed while being hashed: {resolved}")
    if len(run_records) != 1:
        raise ValueError(f"Local W&B stream has {len(run_records)} run records, expected one")
    expected_run_id = _wandb_run_id_from_path(resolved)
    if run_records[0]["run_id"] != expected_run_id:
        raise ValueError("Local W&B run record and event filename have different run IDs")
    return {
        "identity": identity,
        "run": run_records[0],
        "record_counts": dict(sorted(record_counts.items())),
        "selected_rows": selected_rows,
    }


def coalesce_trainer_history(rows: Iterable[dict[str, Any]], final_checkpoint_step: int) -> dict[int, dict[str, float]]:
    required_steps = set(range(_require_int(final_checkpoint_step, "final checkpoint", minimum=1)))
    values: dict[int, dict[str, float]] = defaultdict(dict)
    for row_number, raw_row in enumerate(rows, start=1):
        row = _require_dict(raw_row, f"trainer history row {row_number}")
        step = _require_int(row.get("step"), f"trainer history row {row_number}.step")
        for key in TRAINER_METRIC_KEYS:
            if key not in row:
                continue
            if key in values[step]:
                raise ValueError(f"Trainer history repeats {key!r} at step {step}")
            values[step][key] = _require_number(row[key], f"trainer history step {step} {key}")
    missing_steps = sorted(required_steps - set(values))
    extra_steps = sorted(set(values) - required_steps)
    incomplete = {
        step: sorted(set(TRAINER_METRIC_KEYS) - set(values[step]))
        for step in sorted(required_steps & set(values))
        if set(values[step]) != set(TRAINER_METRIC_KEYS)
    }
    if missing_steps or extra_steps or incomplete:
        raise ValueError(
            f"Trainer history coverage differs: missing_steps={missing_steps}, extra_steps={extra_steps}, "
            f"keys={incomplete}"
        )
    return {step: values[step] for step in sorted(required_steps)}


def coalesce_orchestrator_periodic(rows: Iterable[dict[str, Any]]) -> list[dict[str, float | int]]:
    result = []
    previous_timestamp = -math.inf
    previous_groups = -1
    for row_number, raw_row in enumerate(rows, start=1):
        row = _require_dict(raw_row, f"orchestrator periodic row {row_number}")
        missing = sorted(set(ORCHESTRATOR_PERIODIC_KEYS) - set(row))
        if missing:
            raise ValueError(f"Orchestrator periodic row {row_number} lacks {missing}")
        timestamp = _require_number(row["_timestamp"], f"orchestrator periodic row {row_number} timestamp")
        groups_value = _require_number(
            row["train_sink/groups_finalized"],
            f"orchestrator periodic row {row_number} finalized groups",
        )
        cancelled_value = _require_number(
            row["dispatcher/cancelled/train"],
            f"orchestrator periodic row {row_number} cancellations",
        )
        groups = int(groups_value)
        cancelled = int(cancelled_value)
        if groups_value != groups or cancelled_value != cancelled or groups < previous_groups or cancelled < 0:
            raise ValueError(f"Orchestrator periodic row {row_number} has invalid count fields")
        if timestamp < previous_timestamp:
            raise ValueError("Orchestrator periodic timestamps decreased")
        result.append(
            {
                "timestamp": timestamp,
                "finalized_groups": groups,
                "cancelled_train_rollouts_since_previous_tick": cancelled,
                "off_policy_level_max": _require_number(
                    row["dispatcher/off_policy_level_max"],
                    f"orchestrator periodic row {row_number} max off policy",
                ),
                "off_policy_level_mean": _require_number(
                    row["dispatcher/off_policy_level_mean"],
                    f"orchestrator periodic row {row_number} mean off policy",
                ),
            }
        )
        previous_timestamp = timestamp
        previous_groups = groups
    if not result:
        raise ValueError("Local orchestrator W&B stream has no periodic dispatcher rows")
    cumulative = 0
    for row in result:
        cumulative += int(row["cancelled_train_rollouts_since_previous_tick"])
        row["cumulative_cancelled_train_rollouts"] = cumulative
    return result


def _histogram_count_and_sum(histogram: object, label: str) -> tuple[int, float, int]:
    values = _require_dict(histogram, label)
    count = 0
    total = 0.0
    negative = 0
    for raw_value, raw_count in values.items():
        value = _require_number(_strict_json(raw_value, f"{label} key"), f"{label} reward")
        item_count = _require_int(raw_count, f"{label}[{raw_value}]")
        count += item_count
        total += value * item_count
        if value < 0:
            negative += item_count
    return count, total, negative


def parse_trainer_console(
    run_dir: Path,
    trainer_config: dict[str, Any],
    final_checkpoint_step: int,
    history: dict[int, dict[str, float]],
) -> dict[str, Any]:
    path = run_dir / "logs" / "trainer.log"
    raw_text, identity = _read_stable_text(path)
    text = ANSI_RE.sub("", raw_text)
    output_dir = Path(str(trainer_config.get("output_dir"))).expanduser().resolve()
    wandb_path = _wandb_stream_path(run_dir, text, output_dir, "trainer")
    rows = {}
    for match in TRAINER_STEP_RE.finditer(text):
        step = int(match.group("step"))
        if step in rows:
            raise ValueError(f"Trainer console repeats step {step}")
        row = {
            "loss_rounded": float(match.group("loss")),
            "entropy_mean_rounded": float(match.group("entropy")),
            "mismatch_kl_mean_rounded": float(match.group("mismatch_kl")),
            "grad_norm_rounded": float(match.group("grad_norm")),
        }
        rows[step] = row
    expected = set(range(final_checkpoint_step))
    if set(rows) != expected:
        raise ValueError(
            f"Trainer console steps differ from 0..{final_checkpoint_step - 1}: "
            f"missing={sorted(expected - set(rows))}, extra={sorted(set(rows) - expected)}"
        )
    comparisons = {
        "entropy_mean_rounded": "entropy/all/mean",
        "mismatch_kl_mean_rounded": "mismatch_kl/all/mean",
        "grad_norm_rounded": "optim/grad_norm",
    }
    for step in sorted(rows):
        for console_key, history_key in comparisons.items():
            if rows[step][console_key] != float(f"{history[step][history_key]:.4f}"):
                raise ValueError(f"Trainer console and local W&B differ at step {step} for {history_key}")
    return {
        "identity": identity,
        "wandb_stream_path": str(wandb_path),
        "step_count": len(rows),
        "step_sequence_sha256": eval_plan.canonical_json_sha256(
            [{"step": step, **rows[step]} for step in sorted(rows)]
        ),
    }


def _attempt_reward_mean(attempt: dict[str, Any], label: str) -> float:
    count, total, _ = _histogram_count_and_sum(attempt.get("proxy_reward_histogram"), f"{label} histogram")
    expected = _require_int(attempt.get("n_rollouts"), f"{label}.n_rollouts", minimum=1)
    if count != expected:
        raise ValueError(f"{label} proxy histogram count differs from n_rollouts")
    return total / count


def parse_orchestrator_console(
    run_dir: Path,
    orchestrator_config: dict[str, Any],
    replay: dict[str, Any],
    final_checkpoint_step: int,
) -> dict[str, Any]:
    path = run_dir / "logs" / "orchestrator.log"
    raw_text, identity = _read_stable_text(path)
    text = ANSI_RE.sub("", raw_text)
    output_dir = Path(str(orchestrator_config.get("output_dir"))).expanduser().resolve()
    wandb_path = _wandb_stream_path(run_dir, text, output_dir, "orchestrator")

    console_batches = []
    for match in ORCHESTRATOR_STEP_RE.finditer(text):
        console_batches.append(
            {
                "optimizer_step": int(match.group("step")),
                "reward_mean_rounded": float(match.group("reward")),
                "n_trainable": int(match.group("trainable")),
                "n_rollouts": int(match.group("rollouts")),
                "max_off_policy_steps": int(match.group("max_off_policy")),
                "error_percent_rounded": float(match.group("error")),
                "truncation_percent_rounded": float(match.group("truncation")),
            }
        )
    attempts = [_require_dict(item, "replayed attempt") for item in _require_list(replay.get("attempts"), "attempts")]
    shipped_attempts = [attempt for attempt in attempts if attempt.get("eligible_to_ship") is True]
    shipped_step_sequence = [
        _require_int(attempt.get("optimizer_step_before_attempt"), "shipped attempt optimizer step")
        for attempt in shipped_attempts
    ]
    if shipped_step_sequence != list(range(final_checkpoint_step)):
        raise ValueError("Exact shipped-attempt optimizer steps are not contiguous 0..final-1")
    if len(console_batches) != len(shipped_attempts):
        raise ValueError("Orchestrator console and exact shipped-attempt ledger have different lengths")
    for index, (console, attempt) in enumerate(zip(console_batches, shipped_attempts, strict=True)):
        expected = {
            "optimizer_step": _require_int(attempt.get("optimizer_step_before_attempt"), f"attempt {index} step"),
            "reward_mean_rounded": float(f"{_attempt_reward_mean(attempt, f'attempt {index}'):.4f}"),
            "n_trainable": _require_int(attempt.get("n_trainable"), f"attempt {index} trainable"),
            "n_rollouts": _require_int(attempt.get("n_rollouts"), f"attempt {index} rollouts", minimum=1),
        }
        for key, value in expected.items():
            if console[key] != value:
                raise ValueError(f"Orchestrator console and exact attempt ledger differ at attempt {index + 1}: {key}")

    max_off_policy = _require_int(orchestrator_config.get("max_off_policy_steps"), "max_off_policy_steps")
    pending_stale = []
    stale_events = []
    policy_versions = []
    for line in text.splitlines():
        cancellation = STALE_CANCEL_RE.search(line)
        if cancellation is not None:
            limit = int(cancellation.group("limit"))
            if limit != max_off_policy:
                raise ValueError("Stale-cancellation warning used a different max_off_policy_steps")
            pending_stale.append(int(cancellation.group("count")))
        version_match = POLICY_VERSION_RE.search(line)
        if version_match is not None:
            version = int(version_match.group("version"))
            policy_versions.append(version)
            stale_events.extend(
                {"policy_version_installed": version, "cancelled_rollout_count": count} for count in pending_stale
            )
            pending_stale = []
    if pending_stale:
        raise ValueError("Stale-cancellation warning is not followed by a policy-version installation")
    expected_versions = list(range(1, final_checkpoint_step + 1))
    if policy_versions != expected_versions:
        raise ValueError("Orchestrator policy-version installation sequence is not exactly 1..final checkpoint")

    joint_matches = list(JOINT_STOP_RE.finditer(text))
    if len(joint_matches) != 1:
        raise ValueError(f"Orchestrator log contains {len(joint_matches)} exact joint-stop markers")
    joint = joint_matches[0]
    joint_stop = {key: int(value) for key, value in joint.groupdict().items()}
    if joint_stop["step"] != final_checkpoint_step:
        raise ValueError("Joint-stop checkpoint differs from the final checkpoint")
    stop_when = _require_dict(orchestrator_config.get("stop_when"), "orchestrator stop_when")
    if (
        joint_stop["min_step"] != stop_when.get("min_steps")
        or joint_stop["min_groups"] != stop_when.get("min_finalized_groups")
        or joint_stop["step"] % _require_int(stop_when.get("step_multiple"), "stop_when.step_multiple", minimum=1)
    ):
        raise ValueError("Joint-stop marker differs from the sealed stop_when contract")
    group_count = _require_int(_require_dict(replay.get("summary"), "replay summary").get("attempted_groups"), "groups")
    if group_count < joint_stop["groups"]:
        raise ValueError("Final exact group ledger has fewer groups than the joint-stop marker")

    ordered_markers = (
        joint.group(0),
        f"Waiting for stable trainer weights at step {final_checkpoint_step} before exit",
        "Pipeline drained, exiting main loop",
        "Orchestrator step loop done in ",
        "Writing final checkpoint",
        "Orchestrator finished.",
    )
    positions = []
    cursor = 0
    for marker in ordered_markers:
        position = text.find(marker, cursor)
        if position < 0:
            raise ValueError(f"Orchestrator log lacks ordered completion marker: {marker!r}")
        positions.append(position)
        cursor = position + len(marker)
    if "Orchestrator interrupted" in text or "Orchestrator cleanup complete (forced)." in text:
        raise ValueError("Orchestrator reports a forced rather than clean completion")
    return {
        "identity": identity,
        "wandb_stream_path": str(wandb_path),
        "wandb_run_id_from_path": _wandb_run_id_from_path(wandb_path),
        "batch_console_record_count": len(console_batches),
        "batch_console_sequence_sha256": eval_plan.canonical_json_sha256(console_batches),
        "last_shipped_batch_by_step": {
            str(row["optimizer_step"]): row for row in console_batches if row["optimizer_step"] < final_checkpoint_step
        },
        "stale_cancellation_events": stale_events,
        "stale_cancelled_rollout_count": sum(item["cancelled_rollout_count"] for item in stale_events),
        "joint_stop": joint_stop,
        "post_marker_drain_finalized_group_count": group_count - joint_stop["groups"],
        "ordered_completion_marker_offsets": positions,
    }


def _validate_wandb_run_record(
    scan: dict[str, Any],
    config: dict[str, Any],
    *,
    label: str,
) -> None:
    run = _require_dict(scan.get("run"), f"{label} W&B run")
    embedded = _require_dict(run.get("config"), f"{label} W&B run config")
    expected_output = str(Path(str(config.get("output_dir"))).expanduser().resolve())
    if embedded.get("output_dir") != expected_output:
        raise ValueError(f"{label} local W&B stream records a different output_dir")
    if embedded.get("max_steps") != config.get("max_steps"):
        raise ValueError(f"{label} local W&B stream records a different max_steps")
    wandb_config = _require_dict(config.get("wandb"), f"{label} sealed W&B config")
    if run.get("display_name") != wandb_config.get("name"):
        raise ValueError(f"{label} local W&B stream records a different display name")


def _merge_histograms(histograms: Iterable[object], label: str) -> dict[str, int]:
    counts: Counter[float] = Counter()
    for histogram in histograms:
        values = _require_dict(histogram, label)
        for raw_value, raw_count in values.items():
            value = _require_number(_strict_json(raw_value, f"{label} key"), f"{label} key")
            counts[0.0 if value == 0.0 else value] += _require_int(raw_count, f"{label}[{raw_value}]")
    return {json.dumps(value, allow_nan=False): counts[value] for value in sorted(counts)}


def _mechanism_rates(bucket: dict[str, Any]) -> dict[str, Any]:
    valid = int(bucket["scored_valid_rollout_count"])
    candidate = int(bucket["C_A_candidate_count"])
    proxy_count = int(bucket["proxy_reward_count"])
    return {
        **bucket,
        "strict_rate_among_scored_valid": bucket["S_strict_positive_count"] / valid if valid else None,
        "A_prevalence_among_scored_valid": candidate / valid if valid else None,
        "answer_wrong_rate_among_scored_valid": bucket["answer_wrong_count"] / valid if valid else None,
        "H_rate_among_A_candidates": bucket["H_behavior_trigger_count"] / candidate if candidate else None,
        "negative_proxy_reward_rate": bucket["negative_proxy_reward_count"] / proxy_count if proxy_count else None,
        "proxy_reward_mean": bucket["proxy_reward_sum"] / proxy_count if proxy_count else None,
    }


def _group_bucket(groups: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [group for group in groups if group.get("reward_scored") is True]
    unscored_causes = Counter(
        str(group.get("unscored_cause")) for group in groups if group.get("reward_scored") is False
    )
    hist = _merge_histograms((group.get("proxy_reward_histogram") for group in scored), "group proxy histogram")
    proxy_count, proxy_sum, negative = _histogram_count_and_sum(hist, "merged group proxy histogram")
    valid = sum(_require_int(group.get("V_valid_count"), "group valid count") for group in scored)
    strict = sum(_require_int(group.get("S_strict_positive_count"), "group strict count") for group in scored)
    candidate = sum(_require_int(group.get("C_candidate_count"), "group candidate count") for group in scored)
    if proxy_count != valid:
        raise ValueError("Scored group proxy histogram does not cover every scored valid rollout")
    bucket = {
        "raw_group_count": len(groups),
        "physical_rollout_slot_count": len(groups) * PHYSICAL_GROUP_SIZE,
        "reward_scored_group_count": len(scored),
        "unscored_group_count": len(groups) - len(scored),
        "unscored_group_count_by_cause": dict(sorted(unscored_causes.items())),
        "unscored_rollout_slot_count_by_cause": {
            cause: sum(
                _require_int(group.get("errored_count"), "group errored count")
                for group in groups
                if group.get("unscored_cause") == cause
            )
            for cause in sorted(unscored_causes)
        },
        "gate_open_raw_group_count": sum(group.get("defect_gate_open") is True for group in groups),
        "gate_closed_raw_group_count": sum(group.get("defect_gate_open") is False for group in groups),
        "gate_unknown_raw_group_count": sum(group.get("defect_gate_open") is None for group in groups),
        "scored_valid_rollout_count": valid,
        "S_strict_positive_count": strict,
        "C_A_candidate_count": candidate,
        "answer_wrong_count": valid - strict - candidate,
        "K_effective_eligible_count": sum(
            _require_int(group.get("K_effective_eligible_count"), "group K") for group in scored
        ),
        "H_behavior_trigger_count": sum(
            _require_int(group.get("H_behavior_trigger_count"), "group H") for group in scored
        ),
        "selected_extra_positive_count": sum(
            _require_int(group.get("selected_extra_positive_count"), "selected extra positives") for group in scored
        ),
        "behavior_tax_applied_total": math.fsum(
            _require_number(group.get("behavior_tax_applied_total"), "group tax") for group in scored
        ),
        "selected_net_behavior_reward_total": math.fsum(
            _require_number(group.get("selected_net_behavior_reward_total"), "group net reward") for group in scored
        ),
        "proxy_reward_histogram": hist,
        "proxy_reward_count": proxy_count,
        "proxy_reward_sum": proxy_sum,
        "negative_proxy_reward_count": negative,
    }
    if bucket["answer_wrong_count"] < 0:
        raise ValueError("Strict/A counts do not partition scored valid group rollouts")
    return _mechanism_rates(bucket)


def aggregate_group_prefix(groups: list[dict[str, Any]], reference_tags: tuple[int, int]) -> dict[str, Any]:
    per_tag = {
        str(tag): _group_bucket(
            [group for group in groups if _require_int(group.get("neutral_tag_index"), "neutral tag") == tag]
        )
        for tag in range(TAG_COUNT)
    }
    mapped_count = sum(int(per_tag[str(tag)]["raw_group_count"]) for tag in range(TAG_COUNT))
    if mapped_count != len(groups):
        raise ValueError("Known-cost group prefix contains an unmapped neutral tag")
    selected = set(reference_tags)
    return {
        "estimand_scope": (
            "Reward-law outcomes use only reward_scored groups. Raw/gate/cancellation exposure retains unscored "
            "groups with explicit missing outcomes; no C/H/strict/A/answer-wrong value is imputed for them."
        ),
        "overall": _group_bucket(groups),
        "per_neutral_tag": per_tag,
        "reference_selected": _group_bucket(
            [group for group in groups if _require_int(group.get("neutral_tag_index"), "neutral tag") in selected]
        ),
        "reference_unselected": _group_bucket(
            [group for group in groups if _require_int(group.get("neutral_tag_index"), "neutral tag") not in selected]
        ),
    }


ATTEMPT_BUCKET_COUNT_FIELDS = (
    "consumed_rollout_count",
    "trainable_rollout_count",
    "gate_open_consumed_rollout_count",
    "S_strict_positive_count",
    "C_candidate_count",
    "answer_wrong_count",
    "K_effective_eligible_count",
    "H_behavior_trigger_count",
    "selected_extra_positive_count",
    "negative_proxy_reward_count",
)
ATTEMPT_BUCKET_FLOAT_FIELDS = (
    "behavior_tax_applied_total",
    "selected_net_behavior_reward_total",
)


def _attempt_bucket(attempts: list[dict[str, Any]], tags: tuple[int, ...]) -> dict[str, Any]:
    raw_buckets = []
    for attempt in attempts:
        per_tag = _require_dict(attempt.get("consumed_by_neutral_tag"), "attempt per-tag consumption")
        if set(str(tag) for tag in range(TAG_COUNT)) - set(per_tag):
            raise ValueError("Attempt consumption does not include all six neutral tags")
        raw_buckets.extend(_require_dict(per_tag[str(tag)], f"attempt tag {tag}") for tag in tags)
    sums = {
        field: sum(_require_int(bucket.get(field), f"attempt bucket {field}") for bucket in raw_buckets)
        for field in ATTEMPT_BUCKET_COUNT_FIELDS
    }
    float_sums = {
        field: math.fsum(_require_number(bucket.get(field), f"attempt bucket {field}") for bucket in raw_buckets)
        for field in ATTEMPT_BUCKET_FLOAT_FIELDS
    }
    hist = _merge_histograms((bucket.get("proxy_reward_histogram") for bucket in raw_buckets), "attempt histogram")
    proxy_count, proxy_sum, negative = _histogram_count_and_sum(hist, "merged attempt histogram")
    if proxy_count != sums["consumed_rollout_count"] or negative != sums["negative_proxy_reward_count"]:
        raise ValueError("Attempt per-tag proxy histogram is inconsistent")
    bucket = {
        "attempt_record_count": len(attempts),
        **sums,
        **float_sums,
        "scored_valid_rollout_count": sums["consumed_rollout_count"],
        "C_A_candidate_count": sums["C_candidate_count"],
        "proxy_reward_histogram": hist,
        "proxy_reward_count": proxy_count,
        "proxy_reward_sum": proxy_sum,
    }
    return _mechanism_rates(bucket)


def aggregate_attempt_prefix(attempts: list[dict[str, Any]], reference_tags: tuple[int, int]) -> dict[str, Any]:
    all_tags = tuple(range(TAG_COUNT))
    selected = tuple(sorted(reference_tags))
    unselected = tuple(tag for tag in all_tags if tag not in selected)
    shipped_attempts = [attempt for attempt in attempts if attempt.get("eligible_to_ship") is True]
    nonshipped_attempts = [attempt for attempt in attempts if attempt.get("eligible_to_ship") is False]
    if len(shipped_attempts) + len(nonshipped_attempts) != len(attempts):
        raise ValueError("Attempt eligibility is not boolean")
    return {
        "estimand_scope": (
            "Scientific mechanism buckets include eligible_to_ship=true attempts only. Nonshipped cohorts are "
            "selection diagnostics and were not consumed by the trainer. Within shipped cohorts, "
            "trainable_rollout_count is the optimized subset."
        ),
        "batch_attempt_count": len(attempts),
        "shipped_update_count": len(shipped_attempts),
        "nonshipped_attempt_count": len(nonshipped_attempts),
        "overall": _attempt_bucket(shipped_attempts, all_tags),
        "per_neutral_tag": {str(tag): _attempt_bucket(shipped_attempts, (tag,)) for tag in all_tags},
        "reference_selected": _attempt_bucket(shipped_attempts, selected),
        "reference_unselected": _attempt_bucket(shipped_attempts, unselected),
        "all_attempt_selection_diagnostics": _attempt_bucket(attempts, all_tags),
        "nonshipped_selection_diagnostics": _attempt_bucket(nonshipped_attempts, all_tags),
    }


def _stability_readout(history: dict[int, dict[str, float]], checkpoint_step: int) -> dict[str, Any]:
    if checkpoint_step < 1:
        raise ValueError("Training stability is undefined at checkpoint step zero")
    steps = list(range(checkpoint_step))
    if any(step not in history for step in steps):
        raise ValueError(f"Trainer history does not cover checkpoint {checkpoint_step}")
    summaries = {}
    for key in TRAINER_METRIC_KEYS:
        values = [history[step][key] for step in steps]
        summaries[key] = {
            "update_unweighted_mean": math.fsum(values) / len(values),
            "minimum": min(values),
            "maximum": max(values),
        }
    return {
        "availability": "global_only",
        "per_neutral_tag_available": False,
        "per_neutral_tag_unavailable_reason": (
            "The trainer emits global token statistics only; batch shards do not preserve a tag identity, and "
            "gradient norm is not additively attributable to tags."
        ),
        "checkpoint_step": checkpoint_step,
        "last_update_step": checkpoint_step - 1,
        "last_update": history[checkpoint_step - 1],
        "prefix_update_window": {
            "first_update_step": 0,
            "last_update_step": checkpoint_step - 1,
            "update_count": checkpoint_step,
            "per_metric": summaries,
            "aggregation": "unweighted across the trainer's per-update aggregate statistics",
        },
    }


def _periodic_cancellation_bounds(
    periodic: list[dict[str, float | int]],
    raw_groups: int,
    *,
    exact_final_cancelled: int | None = None,
    final_group_count: int | None = None,
) -> dict[str, Any]:
    target = _require_int(raw_groups, "raw-group cancellation target")
    lower_candidates = [row for row in periodic if int(row["finalized_groups"]) < target]
    upper_candidates = [row for row in periodic if int(row["finalized_groups"]) >= target]
    lower = lower_candidates[-1] if lower_candidates else None
    upper = upper_candidates[0] if upper_candidates else None
    if upper is None:
        if exact_final_cancelled is None or final_group_count is None or final_group_count < target:
            raise ValueError(f"Periodic dispatcher stream never reaches raw-group target {target}")
        fallback_upper = _require_int(exact_final_cancelled, "exact final cancellation total")
    else:
        fallback_upper = int(upper["cumulative_cancelled_train_rollouts"])
    return {
        "clock_alignment": "finalized-group tick bracket; periodic W&B step is intentionally ignored as stale",
        "target_raw_groups": target,
        "lower_tick": lower,
        "upper_tick": upper,
        "upper_tick_available": upper is not None,
        "cumulative_cancelled_train_rollout_lower_bound": (
            int(lower["cumulative_cancelled_train_rollouts"]) if lower is not None else 0
        ),
        "cumulative_cancelled_train_rollout_upper_bound": fallback_upper,
        "upper_bound_source": "periodic_tick" if upper is not None else "exact_final_log_total",
        "off_policy_gauges_at_upper_available": upper is not None,
    }


def _checkpoint_endpoint(
    *,
    checkpoint_step: int,
    raw_groups: int,
    groups: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    reference_tags: tuple[int, int],
    history: dict[int, dict[str, float]],
    periodic: list[dict[str, float | int]],
    console: dict[str, Any],
) -> dict[str, Any]:
    group_prefix = [
        group
        for group in groups
        if _require_int(group.get("finalized_before_optimizer_step"), "group optimizer cutoff") < checkpoint_step
    ]
    if len(group_prefix) != raw_groups:
        raise ValueError(
            f"Checkpoint {checkpoint_step} group prefix differs from plan: {len(group_prefix)} != {raw_groups}"
        )
    attempt_prefix = [
        attempt
        for attempt in attempts
        if _require_int(attempt.get("optimizer_step_before_attempt"), "attempt optimizer step") < checkpoint_step
    ]
    consumed = aggregate_attempt_prefix(attempt_prefix, reference_tags)
    if consumed["shipped_update_count"] != checkpoint_step:
        raise ValueError(f"Checkpoint {checkpoint_step} does not have exactly {checkpoint_step} shipped updates")
    events = _require_list(console.get("stale_cancellation_events"), "stale cancellation events")
    warning_count = sum(
        _require_int(event.get("cancelled_rollout_count"), "stale cancellation count")
        for event in (_require_dict(raw, "stale cancellation event") for raw in events)
        if _require_int(event.get("policy_version_installed"), "stale cancellation policy version") <= checkpoint_step
    )
    last_batches = _require_dict(console.get("last_shipped_batch_by_step"), "last shipped batches")
    last_batch = _require_dict(last_batches.get(str(checkpoint_step - 1)), "last shipped batch")
    return {
        "checkpoint_step": checkpoint_step,
        "updates_completed": checkpoint_step,
        "raw_groups_finalized_before_checkpoint": raw_groups,
        "raw_groups_per_completed_update": raw_groups / checkpoint_step,
        "mechanism_prefix_at_checkpoint": aggregate_group_prefix(group_prefix, reference_tags),
        "trainer_consumed_prefix": consumed,
        "trainer_stability": _stability_readout(history, checkpoint_step),
        "last_shipped_orchestrator_batch_console": last_batch,
        "off_policy_cancellation": {
            "stale_slots_in_exact_group_prefix": aggregate_group_prefix(group_prefix, reference_tags)["overall"][
                "unscored_rollout_slot_count_by_cause"
            ].get("off_policy_cancellation", 0),
            "stale_warning_rollouts_through_policy_version": warning_count,
            "local_dispatcher_stream_at_raw_exposure": _periodic_cancellation_bounds(
                periodic,
                raw_groups,
                exact_final_cancelled=(
                    _require_int(console.get("stale_cancelled_rollout_count"), "stale cancellation total")
                    + _require_int(
                        _require_dict(console.get("joint_stop"), "joint stop").get("cancelled"),
                        "joint-stop cancellation total",
                    )
                ),
                final_group_count=len(groups),
            ),
            "warning_and_group_prefix_are_distinct_clocks": True,
        },
    }


def _validate_replay(
    run: dict[str, Any],
    authority: dict[str, Any],
) -> dict[str, Any]:
    implementations = _require_dict(
        _require_dict(authority.get("postrun_control_source"), "post-run source").get("implementations"),
        "post-run implementations",
    )
    replay_identity = _require_dict(implementations.get("training_replay"), "training replay implementation")
    replay_path = Path(str(replay_identity.get("path"))).expanduser().resolve()
    postrun_authority.validate_recorded_implementation(
        authority,
        name="training_replay",
        implementation_path=replay_path,
    )
    run_dir = Path(str(run.get("run_dir"))).expanduser().resolve()
    replay = launch._run_exact_validator(replay_path, [str(run_dir)])
    if replay.get("analysis") != "masked_verifier_defect_attempts_v6":
        raise ValueError("Pinned training replay returned an unexpected analysis version")
    provenance = _require_dict(replay.get("provenance"), "training replay provenance")
    if provenance.get("analyzer") != replay_identity:
        raise ValueError("Training replay did not execute the authority-pinned implementation")
    inputs = _require_dict(provenance.get("inputs"), "training replay inputs")
    resolved = _require_dict(run.get("resolved_configs"), "run resolved configs")
    if inputs.get("orchestrator_config") != resolved.get("orchestrator"):
        raise ValueError("Training replay and eval plan bind different orchestrator configs")
    clock_audit = _require_dict(run.get("clock_audit"), "run clock audit")
    if inputs.get("train_group_stats") != clock_audit.get("group_stats"):
        raise ValueError("Training replay and eval plan bind different group ledgers")
    if inputs.get("train_batch_attempts") != clock_audit.get("batch_attempts"):
        raise ValueError("Training replay and eval plan bind different attempt ledgers")
    validation = _require_dict(replay.get("validation"), "training replay validation")
    required_checks = {
        "candidate_scope_effective_eligibility_replayed",
        "raw_digest_masks_and_ranks_replayed",
        "defect_and_shuffle_draws_replayed",
        "group_gate_draw_open_state_and_conditional_rate_replayed",
        "neutral_tag_gate_and_reference_metrics_replayed",
        "known_cost_B_S_M_untaxed_taxed_and_net_rewards_replayed",
        "attempt_consumption_replayed_by_neutral_tag",
        "reward_vectors_replayed",
    }
    failed = sorted(key for key in required_checks if validation.get(key) is not True)
    if failed:
        raise ValueError(f"Training replay did not pass required checks: {failed}")
    return replay


def _validate_final_checkpoint(run: dict[str, Any], run_dir: Path, final_step: int) -> dict[str, Any]:
    retained = [
        _require_dict(item, "retained checkpoint")
        for item in _require_list(run.get("retained_checkpoints"), "retained checkpoints")
    ]
    matches = [item for item in retained if item.get("step") == final_step]
    if len(matches) > 1:
        raise ValueError(f"Run repeats retained checkpoint step {final_step}")
    if matches:
        checkpoint_path = Path(str(matches[0].get("path"))).expanduser().resolve()
        stable_identity = _require_dict(matches[0].get("stable_marker"), "final stable marker")
        if eval_plan.file_identity(checkpoint_path / "STABLE") != stable_identity:
            raise ValueError("Final stable checkpoint marker changed")
        source = "eval_plan_retained_checkpoint_inventory"
    else:
        checkpoint_path = run_dir / "weights" / f"step_{final_step}"
        stable_identity = eval_plan.file_identity(checkpoint_path / "STABLE")
        source = "post-run direct final checkpoint binding beyond planner maximum"
    return {
        "checkpoint_path": str(checkpoint_path),
        "stable_marker": stable_identity,
        "binding_source": source,
    }


def _validated_completion_receipt(run: dict[str, Any], authority: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(str(run.get("run_dir"))).expanduser().resolve()
    binding = _require_dict(run.get("launch_binding"), "run launch binding")
    arm_filename = str(binding.get("arm_filename"))
    initial = _require_dict(authority.get("initial_launch_authority"), "post-run initial launch authority")
    initial_intent = _require_dict(initial.get("intent"), "post-run initial launch intent")
    return training_completion.validate_adjacent_receipt(
        run_dir,
        arm_filename=arm_filename,
        initial_intent_identity=initial_intent,
    )


def _completion_contract(
    authority: dict[str, Any],
    *,
    completion_validator: CompletionReceiptValidator | None,
    completion_contract: dict[str, Any] | None,
) -> tuple[CompletionReceiptValidator, dict[str, Any]]:
    if (completion_validator is None) != (completion_contract is None):
        raise ValueError("A custom completion validator and contract must be supplied together")
    if completion_validator is None:
        implementation = postrun_authority.validate_recorded_implementation(
            authority,
            name="training_completion_materializer",
            implementation_path=Path(training_completion.__file__),
        )
        authority_contract = _require_dict(authority.get("training_readout_contract"), "training readout contract")
        expected = {
            "implementation": implementation,
            "artifact_type": training_completion.ARTIFACT_TYPE,
            "filename": training_completion.RECEIPT_NAME,
            "dispatch_stage": training_completion.STAGE1_DISPATCH_STAGE,
            "validated_adjacent_receipt_required_before_and_after_each_run_readout": True,
            "completion_receipt_must_bind_allocation_stdout_and_stderr": True,
            "completion_receipt_must_bind_all_mutable_training_readout_inputs": True,
        }
        observed = {
            "implementation": authority_contract.get("completion_receipt_implementation"),
            "artifact_type": authority_contract.get("completion_receipt_artifact_type"),
            "filename": authority_contract.get("completion_receipt_filename"),
            "dispatch_stage": authority_contract.get("completion_receipt_dispatch_stage"),
            "validated_adjacent_receipt_required_before_and_after_each_run_readout": authority_contract.get(
                "validated_adjacent_receipt_required_per_eligible_run"
            ),
            "completion_receipt_must_bind_allocation_stdout_and_stderr": authority_contract.get(
                "completion_receipt_must_bind_allocation_stdout_and_stderr"
            ),
            "completion_receipt_must_bind_all_mutable_training_readout_inputs": authority_contract.get(
                "completion_receipt_must_bind_all_mutable_training_readout_inputs"
            ),
        }
        if authority_contract.get("stage2_completion_receipt_supported") is not False or observed != expected:
            raise ValueError("Post-run authority does not require the pinned per-run completion receipt")
        return _validated_completion_receipt, expected

    required_fields = {
        "implementation",
        "artifact_type",
        "filename",
        "dispatch_stage",
        "validated_adjacent_receipt_required_before_and_after_each_run_readout",
        "completion_receipt_must_bind_allocation_stdout_and_stderr",
        "completion_receipt_must_bind_all_mutable_training_readout_inputs",
    }
    if set(completion_contract) != required_fields:
        raise ValueError("Custom completion receipt contract has the wrong exact schema")
    implementation = _require_dict(completion_contract.get("implementation"), "completion implementation")
    implementation_path = Path(str(implementation.get("path"))).expanduser().resolve()
    if eval_plan.file_identity(implementation_path) != implementation:
        raise ValueError("Custom completion receipt implementation changed")
    for field in ("artifact_type", "filename", "dispatch_stage"):
        if not isinstance(completion_contract.get(field), str) or not completion_contract[field]:
            raise ValueError(f"Custom completion receipt {field} is invalid")
    filename = str(completion_contract["filename"])
    if Path(filename).name != filename or filename in {".", ".."}:
        raise ValueError("Custom completion receipt filename must be one adjacent basename")
    if any(
        completion_contract.get(field) is not True
        for field in required_fields
        if field.startswith(("validated_", "completion_receipt_must_"))
    ):
        raise ValueError("Custom completion receipt contract weakens immutable evidence requirements")
    return completion_validator, dict(completion_contract)


def _validate_completion_envelope(
    validation: dict[str, Any],
    run: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    value = _require_dict(validation, "completion receipt validation")
    if not {"identity", "receipt"}.issubset(value):
        raise ValueError("Completion receipt validator omitted its identity or receipt")
    identity = _require_dict(value.get("identity"), "completion receipt identity")
    receipt = _require_dict(value.get("receipt"), "completion receipt")
    receipt_path = Path(str(identity.get("path"))).expanduser().resolve()
    run_dir = Path(str(run.get("run_dir"))).expanduser().resolve()
    if receipt_path != run_dir / str(contract["filename"]) or eval_plan.file_identity(receipt_path) != identity:
        raise ValueError("Completion receipt is not the exact adjacent immutable artifact")
    if (
        receipt.get("artifact_type") != contract["artifact_type"]
        or receipt.get("dispatch_stage") != contract["dispatch_stage"]
    ):
        raise ValueError("Completion receipt artifact type or dispatch stage differs from its contract")
    receipt_implementation = _require_dict(receipt.get("implementation"), "completion receipt implementation")
    contract_implementation = _require_dict(contract.get("implementation"), "completion contract implementation")
    for field in ("path", "size_bytes", "sha256"):
        if receipt_implementation.get(field) != contract_implementation.get(field):
            raise ValueError("Completion receipt was built by a different implementation")
    _require_dict(receipt.get("completion_evidence"), "completion evidence")
    return value


def _bind_completion_receipt(
    before: dict[str, Any],
    after: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    if before["identity"] != after["identity"] or before["receipt"] != after["receipt"]:
        raise RuntimeError("Training completion receipt changed while its bound readouts were being consumed")
    receipt = _require_dict(after.get("receipt"), "training completion receipt")
    completion = _require_dict(receipt.get("completion_evidence"), "training completion evidence")
    replay_inputs = _require_dict(provenance.get("training_replay_inputs"), "training replay inputs")
    resolved = _require_dict(provenance.get("resolved_configs"), "training resolved configs")
    observed_bindings = {
        "trainer_config": _require_dict(completion.get("resolved_training_configs"), "resolved training configs").get(
            "trainer"
        ),
        "orchestrator_config": _require_dict(
            completion.get("resolved_training_configs"), "resolved training configs"
        ).get("orchestrator"),
        "group_stats": completion.get("training_group_ledger"),
        "batch_attempts": completion.get("training_batch_attempt_ledger"),
        "trainer_console": completion.get("trainer_console_log"),
        "orchestrator_console": completion.get("orchestrator_console_log"),
        "trainer_wandb": _require_dict(completion.get("local_wandb_streams"), "local W&B streams").get("trainer"),
        "orchestrator_wandb": _require_dict(completion.get("local_wandb_streams"), "local W&B streams").get(
            "orchestrator"
        ),
        "final_stable_marker": completion.get("final_stable_marker"),
        "final_step": completion.get("final_checkpoint_step"),
    }
    expected_bindings = {
        "trainer_config": resolved.get("trainer"),
        "orchestrator_config": resolved.get("orchestrator"),
        "group_stats": replay_inputs.get("train_group_stats"),
        "batch_attempts": replay_inputs.get("train_batch_attempts"),
        "trainer_console": _require_dict(provenance.get("trainer_console"), "trainer console").get("identity"),
        "orchestrator_console": _require_dict(provenance.get("orchestrator_console"), "orchestrator console").get(
            "identity"
        ),
        "trainer_wandb": _require_dict(provenance.get("trainer_local_wandb"), "trainer local W&B").get("identity"),
        "orchestrator_wandb": _require_dict(provenance.get("orchestrator_local_wandb"), "orchestrator local W&B").get(
            "identity"
        ),
        "final_stable_marker": _require_dict(provenance.get("final_checkpoint"), "final checkpoint").get(
            "stable_marker"
        ),
        "final_step": provenance.get("final_step"),
    }
    if observed_bindings != expected_bindings:
        changed = sorted(
            name for name in expected_bindings if observed_bindings.get(name) != expected_bindings.get(name)
        )
        raise ValueError(f"Training readouts differ from their completion-receipt inputs: {changed}")
    return {
        "identity": after["identity"],
        "payload_without_self_hash_sha256": receipt.get("payload_without_self_hash_sha256"),
        "terminal_allocation": receipt.get("terminal_allocation"),
        "final_checkpoint_step": completion.get("final_checkpoint_step"),
        "final_stable_marker": completion.get("final_stable_marker"),
        "live_scheduler_rechecked": False,
    }


def _build_run_readouts(
    run: dict[str, Any],
    factors: dict[str, Any],
    authority: dict[str, Any],
    *,
    completion_validator: CompletionReceiptValidator = _validated_completion_receipt,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_id = str(run.get("run_id"))
    run_dir = Path(str(run.get("run_dir"))).expanduser().resolve()
    completion_before = completion_validator(run, authority)
    resolved = _require_dict(run.get("resolved_configs"), f"{run_id} resolved configs")
    trainer_path = Path(str(_require_dict(resolved.get("trainer"), "trainer identity").get("path")))
    orchestrator_path = Path(str(_require_dict(resolved.get("orchestrator"), "orchestrator identity").get("path")))
    if eval_plan.file_identity(trainer_path) != resolved["trainer"]:
        raise ValueError(f"{run_id} trainer config changed")
    if eval_plan.file_identity(orchestrator_path) != resolved["orchestrator"]:
        raise ValueError(f"{run_id} orchestrator config changed")
    trainer_config = _load_toml(trainer_path)
    orchestrator_config = _load_toml(orchestrator_path)
    replay = _validate_replay(run, authority)
    summary = _require_dict(replay.get("summary"), f"{run_id} replay summary")
    final_step = _require_int(summary.get("shipped_updates"), f"{run_id} shipped updates", minimum=1)
    if not 1_500 <= final_step <= 3_000 or final_step % 50:
        raise ValueError(f"{run_id} final joint-stop step is outside [1500, 3000] or not a multiple of 50")
    stopping = _require_dict(replay.get("stopping"), f"{run_id} stopping summary")
    if stopping.get("decision") != "targets_reached":
        raise ValueError(f"{run_id} did not terminate with both preregistered targets reached")
    final_checkpoint = _validate_final_checkpoint(run, run_dir, final_step)

    trainer_log_text, _ = _read_stable_text(run_dir / "logs" / "trainer.log")
    trainer_wandb_path = _wandb_stream_path(
        run_dir,
        ANSI_RE.sub("", trainer_log_text),
        Path(str(trainer_config.get("output_dir"))),
        "trainer",
    )
    trainer_scan = _scan_local_wandb(
        trainer_wandb_path,
        selected_keys=TRAINER_METRIC_KEYS,
        row_trigger_keys=TRAINER_METRIC_KEYS,
    )
    _validate_wandb_run_record(trainer_scan, trainer_config, label="trainer")
    history = coalesce_trainer_history(trainer_scan["selected_rows"], final_step)
    trainer_console = parse_trainer_console(run_dir, trainer_config, final_step, history)
    if trainer_console["wandb_stream_path"] != str(trainer_wandb_path):
        raise RuntimeError("Trainer console changed its local W&B stream path while being analyzed")

    orchestrator_log_text, _ = _read_stable_text(run_dir / "logs" / "orchestrator.log")
    orchestrator_wandb_path = _wandb_stream_path(
        run_dir,
        ANSI_RE.sub("", orchestrator_log_text),
        Path(str(orchestrator_config.get("output_dir"))),
        "orchestrator",
    )
    orchestrator_scan = _scan_local_wandb(
        orchestrator_wandb_path,
        selected_keys=ORCHESTRATOR_PERIODIC_KEYS,
        row_trigger_keys=("dispatcher/cancelled/train",),
    )
    _validate_wandb_run_record(orchestrator_scan, orchestrator_config, label="orchestrator")
    periodic = coalesce_orchestrator_periodic(orchestrator_scan["selected_rows"])
    orchestrator_console = parse_orchestrator_console(run_dir, orchestrator_config, replay, final_step)
    if orchestrator_console["wandb_stream_path"] != str(orchestrator_wandb_path):
        raise RuntimeError("Orchestrator console changed its local W&B stream path while being analyzed")
    if trainer_scan["run"]["run_id"] != orchestrator_scan["run"]["run_id"]:
        raise ValueError("Trainer and orchestrator local W&B streams have different shared run IDs")

    groups = [_require_dict(item, f"{run_id} group") for item in _require_list(replay.get("groups"), "groups")]
    attempts = [_require_dict(item, f"{run_id} attempt") for item in _require_list(replay.get("attempts"), "attempts")]
    stale_group_slots = sum(
        _require_int(group.get("errored_count"), "stale group slots")
        for group in groups
        if group.get("unscored_cause") == "off_policy_cancellation"
    )
    stale_warning_slots = _require_int(
        orchestrator_console.get("stale_cancelled_rollout_count"),
        "stale warning slots",
    )
    if stale_group_slots != stale_warning_slots:
        raise ValueError(
            f"{run_id} stale cancellation ledger and warnings differ: {stale_group_slots} != {stale_warning_slots}"
        )
    periodic_cancelled = int(periodic[-1]["cumulative_cancelled_train_rollouts"])
    joint_stop = _require_dict(orchestrator_console.get("joint_stop"), "joint stop")
    drain_cancelled = _require_int(joint_stop.get("cancelled"), "joint-stop drain cancellations")
    exact_cancelled = stale_warning_slots + drain_cancelled
    if periodic_cancelled > exact_cancelled:
        raise ValueError(
            f"{run_id} sampled local dispatcher cancellation total exceeds exact log-derived total: "
            f"{periodic_cancelled} > {exact_cancelled}"
        )

    labels = [_require_int(group.get("finalized_before_optimizer_step"), "group cutoff") for group in groups]
    if any(label > final_step for label in labels):
        raise ValueError(f"{run_id} contains a group finalized after the final checkpoint")
    exposure_by_step = {
        _require_int(point.get("step"), "exposure step"): _require_int(point.get("raw_groups"), "raw groups")
        for point in (
            _require_dict(item, "checkpoint exposure")
            for item in _require_list(run.get("checkpoint_exposure_grid"), "checkpoint exposure grid")
        )
    }
    checkpoint_exposure = sum(label < final_step for label in labels)
    if final_step in exposure_by_step and exposure_by_step[final_step] != checkpoint_exposure:
        raise ValueError(f"{run_id} final checkpoint exposure differs from exact group labels")
    joint_group_count = _require_int(joint_stop.get("groups"), "joint-stop group count")
    if not checkpoint_exposure <= joint_group_count <= len(groups):
        raise ValueError(f"{run_id} violates checkpoint <= joint-stop <= final group accounting")
    if len(groups) - joint_group_count != _require_int(
        orchestrator_console.get("post_marker_drain_finalized_group_count"),
        "post-marker drain group count",
    ):
        raise ValueError(f"{run_id} post-marker drain group count differs between log and group ledger")

    reference_tags = tuple(
        _require_int(tag, "reference tag") for tag in _require_list(factors.get("reference_tags"), "reference tags")
    )
    if len(reference_tags) != 2 or len(set(reference_tags)) != 2:
        raise ValueError(f"{run_id} has invalid reference tags")
    endpoint_cache: dict[int, dict[str, Any]] = {}

    def endpoint(step: int, raw_groups: int) -> dict[str, Any]:
        if step not in endpoint_cache:
            endpoint_cache[step] = _checkpoint_endpoint(
                checkpoint_step=step,
                raw_groups=raw_groups,
                groups=groups,
                attempts=attempts,
                reference_tags=reference_tags,  # type: ignore[arg-type]
                history=history,
                periodic=periodic,
                console=orchestrator_console,
            )
        elif endpoint_cache[step]["raw_groups_finalized_before_checkpoint"] != raw_groups:
            raise ValueError(f"{run_id} assigns two raw-group counts to checkpoint {step}")
        return endpoint_cache[step]

    readouts = []
    for raw_target in _require_list(run.get("optimizer_clock_targets"), f"{run_id} optimizer targets"):
        target = _require_dict(raw_target, "optimizer target")
        target_step = _require_int(target.get("target_step"), "optimizer target step", minimum=1)
        checkpoint_step = _require_int(target.get("checkpoint_step"), "optimizer checkpoint step", minimum=1)
        if checkpoint_step != target_step or checkpoint_step not in exposure_by_step:
            raise ValueError(f"{run_id} optimizer clock is not exact")
        readouts.append(
            {
                **factors,
                "clock_kind": "optimizer_step",
                "target": target_step,
                "mode": "exact_checkpoint",
                "checkpoint_endpoint": endpoint(checkpoint_step, exposure_by_step[checkpoint_step]),
            }
        )
    for raw_target in _require_list(run.get("raw_group_clock_targets"), f"{run_id} raw-group targets"):
        target = _require_dict(raw_target, "raw-group target")
        target_raw = _require_int(target.get("target_raw_groups"), "raw-group target", minimum=1)
        if target_raw > len(groups):
            raise ValueError(f"{run_id} raw-group target exceeds its exact ledger")
        lower = _require_dict(target.get("lower"), "raw lower endpoint")
        upper = _require_dict(target.get("upper"), "raw upper endpoint")
        lower_step = _require_int(lower.get("step"), "raw lower step", minimum=1)
        upper_step = _require_int(upper.get("step"), "raw upper step", minimum=1)
        lower_raw = _require_int(lower.get("raw_groups"), "raw lower groups")
        upper_raw = _require_int(upper.get("raw_groups"), "raw upper groups")
        if exposure_by_step.get(lower_step) != lower_raw or exposure_by_step.get(upper_step) != upper_raw:
            raise ValueError(f"{run_id} raw-group endpoint differs from checkpoint exposure grid")
        exact_prefix = groups[:target_raw]
        if any(
            _require_int(group.get("finalized_before_optimizer_step"), "raw-prefix group cutoff") >= upper_step
            for group in exact_prefix
        ):
            raise ValueError(f"{run_id} raw-group target prefix was not available before its upper endpoint")
        readouts.append(
            {
                **factors,
                "clock_kind": "raw_groups",
                "target": target_raw,
                "mode": "exact_mechanism_prefix_with_checkpoint_bracketed_trainer_state",
                "exact_raw_group_mechanism_prefix": aggregate_group_prefix(exact_prefix, reference_tags),  # type: ignore[arg-type]
                "trainer_state_at_exact_raw_target_available": target.get("mode") == "exact",
                "trainer_state_interpolation_performed": False,
                "trainer_state_interpolation_forbidden_reason": (
                    "Trainer metrics are update-indexed and nonlinear; raw-clock evaluation interpolation does not "
                    "create an exact entropy/KL/DPPO/gradient measurement."
                ),
                "lower_checkpoint_endpoint": endpoint(lower_step, lower_raw),
                "upper_checkpoint_endpoint": endpoint(upper_step, upper_raw),
                "local_dispatcher_cancellation_bounds_at_exact_raw_prefix": _periodic_cancellation_bounds(
                    periodic,
                    target_raw,
                    exact_final_cancelled=exact_cancelled,
                    final_group_count=len(groups),
                ),
            }
        )
    readouts.sort(key=lambda item: (str(item["clock_kind"]), int(item["target"])))
    provenance = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "resolved_configs": resolved,
        "training_replay_output_sha256": eval_plan.canonical_json_sha256(replay),
        "training_replay_inputs": _require_dict(
            _require_dict(replay["provenance"], "replay provenance")["inputs"], "replay inputs"
        ),
        "trainer_console": trainer_console,
        "orchestrator_console": {
            key: value
            for key, value in orchestrator_console.items()
            if key not in {"stale_cancellation_events", "last_shipped_batch_by_step"}
        },
        "trainer_local_wandb": {
            "identity": trainer_scan["identity"],
            "run_id": trainer_scan["run"]["run_id"],
            "record_counts": trainer_scan["record_counts"],
        },
        "orchestrator_local_wandb": {
            "identity": orchestrator_scan["identity"],
            "run_id": orchestrator_scan["run"]["run_id"],
            "record_counts": orchestrator_scan["record_counts"],
            "periodic_tick_count": len(periodic),
            "cumulative_cancelled_train_rollouts": periodic_cancelled,
            "unflushed_cancelled_train_rollouts_at_shutdown": exact_cancelled - periodic_cancelled,
        },
        "final_checkpoint": final_checkpoint,
        "final_step": final_step,
        "final_group_count": len(groups),
        "final_checkpoint_exposure_group_count": checkpoint_exposure,
        "joint_stop_marker_group_count": joint_group_count,
        "pre_stop_checkpoint_excluded_group_count": joint_group_count - checkpoint_exposure,
        "post_marker_drain_group_count": len(groups) - joint_group_count,
        "total_checkpoint_excluded_tail_group_count": len(groups) - checkpoint_exposure,
        "stale_cancelled_rollout_count": stale_group_slots,
        "joint_stop_drain_cancelled_rollout_count": drain_cancelled,
        "exact_total_cancelled_train_rollout_count": exact_cancelled,
    }
    completion_after = completion_validator(run, authority)
    provenance["training_completion_receipt"] = _bind_completion_receipt(
        completion_before,
        completion_after,
        provenance,
    )
    return readouts, provenance


def build_training_readouts(
    plan: dict[str, Any],
    factors_by_run: dict[str, dict[str, Any]],
    authority: dict[str, Any],
    *,
    completion_validator: CompletionReceiptValidator | None = None,
    completion_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    implementation = postrun_authority.validate_recorded_implementation(
        authority,
        name="training_readout_consumer",
        implementation_path=Path(__file__),
    )
    validator, validated_completion_contract = _completion_contract(
        authority,
        completion_validator=completion_validator,
        completion_contract=completion_contract,
    )

    def validate_completion(run: dict[str, Any], run_authority: dict[str, Any]) -> dict[str, Any]:
        return _validate_completion_envelope(
            validator(run, run_authority),
            run,
            validated_completion_contract,
        )

    raw_runs = [_require_dict(item, "plan run") for item in _require_list(plan.get("runs"), "plan runs")]
    run_ids = [str(run.get("run_id")) for run in raw_runs]
    if len(run_ids) != len(set(run_ids)) or set(run_ids) != set(factors_by_run):
        raise ValueError("Training readout run inventory differs from analyzed arm factors")
    all_readouts = []
    run_provenance = {}
    for run in raw_runs:
        run_id = str(run["run_id"])
        readouts, provenance = _build_run_readouts(
            run,
            factors_by_run[run_id],
            authority,
            completion_validator=validate_completion,
        )
        all_readouts.extend(readouts)
        run_provenance[run_id] = provenance
    all_readouts.sort(
        key=lambda item: (
            int(item["block_seed"]),
            str(item["family"]),
            float(item["dose"]),
            str(item["clock_kind"]),
            int(item["target"]),
        )
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "analysis_id": ANALYSIS_ID,
        "study_id": plan.get("study_id"),
        "claim_scope": {
            "summary_type": "descriptive deterministic training diagnostics",
            "strict_generalization_estimated_here": False,
            "phase_transition_claim_valid": False,
            "hysteresis_claim_valid": False,
            "causal_treatment_effect_estimated": False,
        },
        "availability": {
            "reward_law_and_exposure": "exact overall and per neutral tag from immutable group/attempt ledgers",
            "trainer_stability": "exact logged global aggregates only from local W&B event stream",
            "trainer_stability_per_tag": "unavailable: trainer batches retain no tag identity and grad norm is nonadditive",
            "raw_clock_trainer_stability": "checkpoint endpoint values and bounds only; no interpolation or exact target claim",
            "off_policy_cancellation": (
                "exact stale total from structural group rows cross-checked to warnings plus exact final drain from the "
                "joint-stop marker; local dispatcher counters are sampled lower bounds and raw clocks use finalized-"
                "group tick brackets"
            ),
            "remote_wandb_api_used": False,
            "network_access_used": False,
            "token_level_entropy_or_kl_recovered": False,
            "dppo_fraction_semantics": (
                "trainer-logged means of per-microbatch within-trainable-token fractions, not a reconstructed global "
                "token-weighted rate"
            ),
            "training_completion_receipt": (
                "validated adjacent immutable receipt required before and after consuming every run; terminal "
                "scheduler evidence is frozen and no live scheduler recheck is used"
            ),
        },
        "provenance": {
            "implementation": {
                "repository_path": SCRIPT_REPOSITORY_PATH,
                **implementation,
            },
            "completion_receipt_contract": validated_completion_contract,
            "run_artifacts": run_provenance,
        },
        "arm_clock_readouts": all_readouts,
    }
    report["payload_without_self_hash_sha256"] = eval_plan.canonical_json_sha256(report)
    return report
