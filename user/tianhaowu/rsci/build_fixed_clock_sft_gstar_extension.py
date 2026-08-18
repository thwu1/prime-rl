#!/usr/bin/env python3
"""Build candidate-composition-matched global controls for fixed-clock SFT."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import build_fixed_clock_sft_datasets as v2
from datasets import Dataset
from transformers import AutoTokenizer

STUDY_ID = "verifier_defect_fixed_clock_sft_v3_extension_gstar_v1"
SCHEMA_VERSION = 1
HASH_DOMAIN = "rsci-fixed-clock-sft-gstar-v1"
ASSIGNMENT = "global_composition_matched"
DISPLAY_SYMBOL = "Gstar"
CANDIDATE_CLASS = "candidate_a"
NONCANDIDATE_CLASS = "noncandidate"
EXPECTED_SEEDS = (20260805, 20260806, 20260807)
EXPECTED_DOSES = ("1/400", "1/200", "1/100")
EXPECTED_DOSE_LABELS = ("p0025", "p0050", "p0100")
EXPECTED_BANK_OPERATIONS = (10, 11, 12, *range(15, 41))
EXPECTED_ANCHOR_OPERATIONS = (10, 11, 12)
EXPECTED_TREATMENT_OPERATIONS = tuple(range(21, 41))
EXPECTED_EXAMPLES_PER_OPERATION = 1_000
EXPECTED_SAMPLES_PER_PROMPT = 128
ANCHOR_COUNT = 512
SEQ_LEN = 2_048
BATCH_SIZE = 32
CHECKPOINT_INTERVAL = 8
DEFAULT_V2_INDEX = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/"
    "frozen-base-op10-12-op15-40-r128-v1/fixed-clock-sft-v2/arm_index.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/"
    "frozen-base-op10-12-op15-40-r128-v1/fixed-clock-sft-v3-extension-gstar-v1"
)
ANALYZER_FILENAME = "analyze_fixed_clock_sft_gstar_extension.py"


@dataclass(frozen=True)
class Spec:
    seed: int
    clock: str
    dose: str
    dose_label: str
    raw_prefix_trajectories: int
    source_behavior_label: str
    source_shuffled_label: str
    source_global_label: str
    label: str
    candidate_quota: int
    noncandidate_quota: int

    @property
    def selected_count(self) -> int:
        return self.candidate_quota + self.noncandidate_quota


@dataclass(frozen=True)
class RankedRow:
    row: v2.BankRow
    score_class: str
    rank_sha256: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-index", type=Path, default=DEFAULT_V2_INDEX)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--no-deep-selection-check",
        action="store_true",
        help="Skip the frozen-bank rescan when validating an already built extension.",
    )
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def read_json_object(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def verify_file_identity(record: object, *, label: str) -> dict[str, Any]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ValueError(f"{label} is not a file identity")
    observed = file_identity(Path(record["path"]))
    if observed != record:
        raise ValueError(f"{label} differs from its recorded identity")
    return observed


def verify_relocatable_implementation(record: object, current_path: Path, *, label: str) -> dict[str, Any]:
    recorded = verify_file_identity(record, label=label)
    current = file_identity(current_path)
    if (recorded["size_bytes"], recorded["sha256"]) != (current["size_bytes"], current["sha256"]):
        raise ValueError(f"Current {label} bytes differ from the recorded source implementation")
    return recorded


def rank_sha256(spec: Spec, score_class: str, key: tuple[int, int, int]) -> str:
    if score_class not in {CANDIDATE_CLASS, NONCANDIDATE_CLASS}:
        raise ValueError(f"Unknown score class: {score_class}")
    material = "\0".join(
        (
            HASH_DOMAIN,
            score_class,
            str(spec.seed),
            spec.clock,
            spec.dose_label,
            str(key[0]),
            str(key[1]),
            str(key[2]),
        )
    ).encode()
    return hashlib.sha256(material).hexdigest()


HeapEntry = tuple[int, int, int, int, RankedRow]


def offer_ranked_row(heap: list[HeapEntry], ranked: RankedRow, limit: int) -> None:
    """Retain the exact lexicographically lowest hash/key ranks in bounded memory."""
    if limit < 0:
        raise ValueError("Selection limit must be non-negative")
    if limit == 0:
        return
    rank = (int(ranked.rank_sha256, 16), *ranked.row.key)
    entry = (-rank[0], -rank[1], -rank[2], -rank[3], ranked)
    if len(heap) < limit:
        heapq.heappush(heap, entry)
        return
    worst = heap[0]
    worst_rank = (-worst[0], -worst[1], -worst[2], -worst[3])
    if rank < worst_rank:
        heapq.heapreplace(heap, entry)


def ordered_heap(heap: list[HeapEntry]) -> list[RankedRow]:
    return sorted(
        (entry[4] for entry in heap),
        key=lambda ranked: (int(ranked.rank_sha256, 16), ranked.row.key),
    )


def _dataset_rows(path: Path) -> list[dict[str, Any]]:
    parquet = path / "train-00000-of-00001.parquet"
    if not parquet.is_file():
        raise FileNotFoundError(parquet)
    return [dict(row) for row in Dataset.from_parquet(str(parquet))]


def _metadata(entry: dict[str, Any]) -> dict[str, Any]:
    omitted = {"label", "alias_of", "dataset_path", "manifest_path", "parquet_sha256", "rows"}
    return {key: value for key, value in entry.items() if key not in omitted}


def _source_arm_identity(entry: dict[str, Any]) -> dict[str, Any]:
    dataset_path = Path(entry["dataset_path"]).expanduser().resolve()
    manifest_path = Path(entry["manifest_path"]).expanduser().resolve()
    parquet_path = dataset_path / "train-00000-of-00001.parquet"
    if manifest_path != dataset_path / "manifest.json":
        raise ValueError(f"Source arm {entry['label']} has a detached manifest")
    manifest = read_json_object(manifest_path)
    parquet = file_identity(parquet_path)
    if parquet["sha256"] != entry.get("parquet_sha256"):
        raise ValueError(f"Source arm {entry['label']} parquet differs from the v2 index")
    if manifest.get("arm") != {"label": entry["label"], **_metadata(entry)}:
        raise ValueError(f"Source arm {entry['label']} metadata differs from its manifest")
    if manifest.get("rows") != entry.get("rows"):
        raise ValueError(f"Source arm {entry['label']} row count differs")
    return {
        "label": entry["label"],
        "manifest": file_identity(manifest_path),
        "parquet": parquet,
    }


def _anchor_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key
        not in {
            "gstar_score_class",
            "gstar_rank_sha256",
            "gstar_rank_domain",
            "paired_shuffled_arm",
        }
    }


def _anchor_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors = [row for row in rows if row.get("source_kind") == "clean_anchor"]
    anchors.sort(key=lambda row: (str(row.get("train_order_key")), str(row.get("trajectory_id"))))
    return anchors


def _validate_v2_contract(index: dict[str, Any]) -> None:
    if index.get("schema_version") != 2 or index.get("study_id") != "verifier_defect_fixed_clock_sft_v2":
        raise ValueError("The source index is not the immutable fixed-clock v2 study")
    protocol = index.get("protocol")
    expected = {
        "bank_operations": list(EXPECTED_BANK_OPERATIONS),
        "anchor_operations": list(EXPECTED_ANCHOR_OPERATIONS),
        "treatment_operations": list(EXPECTED_TREATMENT_OPERATIONS),
        "examples_per_operation": EXPECTED_EXAMPLES_PER_OPERATION,
        "samples_per_prompt": EXPECTED_SAMPLES_PER_PROMPT,
        "selection_seeds": list(EXPECTED_SEEDS),
        "doses": list(EXPECTED_DOSES),
        "target_count": 512,
        "anchor_count": ANCHOR_COUNT,
        "selection_hash_domain": "rsci-fixed-clock-sft-v2",
    }
    if not isinstance(protocol, dict):
        raise ValueError("The v2 index has no protocol")
    for key, value in expected.items():
        if protocol.get(key) != value:
            raise ValueError(f"The v2 protocol {key} differs: {protocol.get(key)!r} != {value!r}")
    trainability = protocol.get("trainability_filter")
    if (
        not isinstance(trainability, dict)
        or trainability.get("required") is not True
        or trainability.get("truncation_allowed") is not False
        or trainability.get("seq_len") != SEQ_LEN
        or not isinstance(trainability.get("records"), list)
    ):
        raise ValueError("The v2 trainability exclusion contract differs")
    strict_dead = protocol.get("strict_dead_contract")
    if (
        not isinstance(strict_dead, dict)
        or strict_dead.get("required") is not True
        or strict_dead.get("operations") != list(EXPECTED_TREATMENT_OPERATIONS)
        or any(strict_dead.get("strict_positive_counts_by_op", {}).values())
    ):
        raise ValueError("The v2 strict-dead treatment contract differs")


def discover_specs(
    index: dict[str, Any],
) -> tuple[list[Spec], dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    _validate_v2_contract(index)
    entries = index.get("arms")
    distinct = index.get("distinct_training_arms")
    if not isinstance(entries, list) or not isinstance(distinct, list):
        raise ValueError("The v2 index has no arm registry")
    by_label = {entry.get("label"): entry for entry in entries if isinstance(entry, dict)}
    if len(by_label) != len(entries) or set(distinct) - set(by_label):
        raise ValueError("The v2 arm registry has missing or duplicate labels")

    c0 = by_label.get("c0_anchor")
    if not isinstance(c0, dict) or c0.get("alias_of") is not None or c0.get("rows") != ANCHOR_COUNT:
        raise ValueError("The v2 clean anchor arm differs")
    source_identities: dict[str, dict[str, Any]] = {"c0_anchor": _source_arm_identity(c0)}
    canonical_shuffled = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("alias_of") is None
        and entry.get("assignment") == "shuffled"
        and entry.get("clock") in {"fixed_m", "fixed_raw"}
    ]
    expected_dimensions = {(seed, "fixed_m", dose) for seed in EXPECTED_SEEDS for dose in EXPECTED_DOSES} | {
        (seed, "fixed_raw", dose) for seed in EXPECTED_SEEDS for dose in EXPECTED_DOSES[1:]
    }
    observed_dimensions = {
        (entry.get("selection_seed"), entry.get("clock"), entry.get("dose")) for entry in canonical_shuffled
    }
    if observed_dimensions != expected_dimensions or len(canonical_shuffled) != 15:
        raise ValueError("The source index does not contain the 15 canonical shuffled specifications")

    c0_rows = _dataset_rows(Path(c0["dataset_path"]))
    c0_anchors = _anchor_rows(c0_rows)
    if len(c0_rows) != ANCHOR_COUNT or len(c0_anchors) != ANCHOR_COUNT:
        raise ValueError("The v2 clean arm does not contain exactly 512 anchors")
    anchor_projection_sha256 = v2.canonical_json_sha256([_anchor_projection(row) for row in c0_anchors])
    specs: list[Spec] = []
    source_arm_records: list[dict[str, Any]] = []

    for shuffled in sorted(
        canonical_shuffled,
        key=lambda entry: (entry["selection_seed"], entry["clock"], entry["dose_label"]),
    ):
        if not str(shuffled["label"]).endswith("_s"):
            raise ValueError(f"Shuffled arm label has no canonical _s suffix: {shuffled['label']}")
        stem = str(shuffled["label"])[:-2]
        labels = {"behavior": f"{stem}_b", "shuffled": f"{stem}_s", "global": f"{stem}_g"}
        paired: dict[str, dict[str, Any]] = {}
        for assignment, label in labels.items():
            entry = by_label.get(label)
            if not isinstance(entry, dict) or entry.get("alias_of") is not None:
                raise ValueError(f"Missing canonical paired source arm: {label}")
            if (
                entry.get("selection_seed") != shuffled.get("selection_seed")
                or entry.get("clock") != shuffled.get("clock")
                or entry.get("dose") != shuffled.get("dose")
                or entry.get("dose_label") != shuffled.get("dose_label")
                or entry.get("assignment") != assignment
                or entry.get("raw_prefix_trajectories") != shuffled.get("raw_prefix_trajectories")
                or entry.get("hard_recipient_rows") != shuffled.get("hard_recipient_rows")
                or entry.get("rows") != shuffled.get("rows")
            ):
                raise ValueError(f"Paired source arm {label} differs from {shuffled['label']}")
            paired[assignment] = entry
            identity = _source_arm_identity(entry)
            source_identities[label] = identity
            source_arm_records.append(identity)

        shuffled_rows = _dataset_rows(Path(shuffled["dataset_path"]))
        anchors = _anchor_rows(shuffled_rows)
        if v2.canonical_json_sha256([_anchor_projection(row) for row in anchors]) != anchor_projection_sha256:
            raise ValueError(f"Shuffled arm {shuffled['label']} does not reuse the exact clean anchors")
        defects = [row for row in shuffled_rows if row.get("source_kind") == "defect_recipient"]
        if len(anchors) != ANCHOR_COUNT or len(defects) != shuffled.get("hard_recipient_rows"):
            raise ValueError(f"Shuffled arm {shuffled['label']} has an invalid anchor/recipient split")
        excluded_keys = {tuple(record["key"]) for record in index["protocol"]["trainability_filter"]["records"]}
        candidate_quota = 0
        for row in defects:
            key = (int(row["op"]), int(row["prompt_index"]), int(row["sample_rank"]))
            if (
                row.get("strict_correct") is not False
                or row.get("candidate") != (row.get("answer_correct") is True)
                or key in excluded_keys
                or int(row["raw_ordinal"]) >= int(shuffled["raw_prefix_trajectories"])
            ):
                raise ValueError(f"Shuffled arm {shuffled['label']} has an invalid recipient {key}")
            candidate_quota += int(row["candidate"])
        noncandidate_quota = len(defects) - candidate_quota
        if candidate_quota != shuffled.get("candidate_overlap"):
            raise ValueError(f"Shuffled arm {shuffled['label']} candidate quota differs from metadata")
        spec = Spec(
            seed=int(shuffled["selection_seed"]),
            clock=str(shuffled["clock"]),
            dose=str(shuffled["dose"]),
            dose_label=str(shuffled["dose_label"]),
            raw_prefix_trajectories=int(shuffled["raw_prefix_trajectories"]),
            source_behavior_label=labels["behavior"],
            source_shuffled_label=labels["shuffled"],
            source_global_label=labels["global"],
            label=f"{stem}_gstar",
            candidate_quota=candidate_quota,
            noncandidate_quota=noncandidate_quota,
        )
        if spec.selected_count != int(shuffled["hard_recipient_rows"]):
            raise ValueError(f"Composition quotas do not sum to the shuffled count for {spec.label}")
        specs.append(spec)

    if len({spec.label for spec in specs}) != 15:
        raise ValueError("Gstar labels are not unique")
    anchor_state = {
        "rows": c0_anchors,
        "projection_sha256": anchor_projection_sha256,
        "ordered_trajectory_ids_sha256": v2.canonical_json_sha256([row["trajectory_id"] for row in c0_anchors]),
    }
    return specs, source_identities, source_arm_records, anchor_state


def frozen_bank_state(index: dict[str, Any]) -> tuple[v2.BankPaths, dict[str, Any]]:
    inputs = index.get("inputs")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("manifest"), dict):
        raise ValueError("The v2 index has no frozen-bank identities")
    manifest_path = Path(inputs["manifest"]["path"]).expanduser().resolve()
    paths = v2.bank_paths(manifest_path.parent)
    state = v2.verify_bank_contract(
        paths,
        operations=EXPECTED_BANK_OPERATIONS,
        examples_per_operation=EXPECTED_EXAMPLES_PER_OPERATION,
        samples_per_prompt=EXPECTED_SAMPLES_PER_PROMPT,
    )
    if state["contract_sha256"] != index.get("bank_contract_sha256") or state["inputs"] != inputs:
        raise ValueError("Frozen-bank bytes differ from the v2 arm index")
    return paths, state


def select_rows(
    *,
    index: dict[str, Any],
    specs: list[Spec],
) -> tuple[dict[str, list[RankedRow]], dict[str, dict[str, int]], dict[str, Any]]:
    paths, bank_state = frozen_bank_state(index)
    prompts = v2.read_prompts(
        paths.prompts,
        operations=EXPECTED_BANK_OPERATIONS,
        examples_per_operation=EXPECTED_EXAMPLES_PER_OPERATION,
    )
    excluded_keys = {tuple(record["key"]) for record in index["protocol"]["trainability_filter"]["records"]}
    heaps: dict[tuple[str, str], list[HeapEntry]] = {
        (spec.label, score_class): [] for spec in specs for score_class in (CANDIDATE_CLASS, NONCANDIDATE_CLASS)
    }
    capacities: dict[tuple[str, str], int] = Counter()

    for group in v2.iter_joined_groups(
        paths,
        prompts,
        bank_operations=EXPECTED_BANK_OPERATIONS,
        treatment_operations=EXPECTED_TREATMENT_OPERATIONS,
        examples_per_operation=EXPECTED_EXAMPLES_PER_OPERATION,
        samples_per_prompt=EXPECTED_SAMPLES_PER_PROMPT,
    ):
        if group[0].key[0] not in EXPECTED_TREATMENT_OPERATIONS:
            continue
        for row in group:
            if row.score["perfect"]:
                raise ValueError(f"Treatment row {row.key} violates the strict-dead contract")
            if row.score["candidate"] != bool(row.score["answer_correct"] and not row.score["perfect"]):
                raise ValueError(f"Treatment row {row.key} has an inconsistent candidate label")
            if row.key in excluded_keys:
                continue
            if row.raw_ordinal is None:
                raise RuntimeError(f"Treatment row {row.key} has no raw ordinal")
            score_class = CANDIDATE_CLASS if row.score["candidate"] else NONCANDIDATE_CLASS
            for spec in specs:
                if row.raw_ordinal >= spec.raw_prefix_trajectories:
                    continue
                capacities[(spec.label, score_class)] += 1
                quota = spec.candidate_quota if score_class == CANDIDATE_CLASS else spec.noncandidate_quota
                ranked = RankedRow(row, score_class, rank_sha256(spec, score_class, row.key))
                offer_ranked_row(heaps[(spec.label, score_class)], ranked, quota)

    selected: dict[str, list[RankedRow]] = {}
    capacity_summary: dict[str, dict[str, int]] = {}
    for spec in specs:
        candidate = ordered_heap(heaps[(spec.label, CANDIDATE_CLASS)])
        noncandidate = ordered_heap(heaps[(spec.label, NONCANDIDATE_CLASS)])
        observed = {CANDIDATE_CLASS: len(candidate), NONCANDIDATE_CLASS: len(noncandidate)}
        expected = {CANDIDATE_CLASS: spec.candidate_quota, NONCANDIDATE_CLASS: spec.noncandidate_quota}
        if observed != expected:
            raise ValueError(f"Insufficient class capacity for {spec.label}: selected={observed}, expected={expected}")
        combined = sorted(
            (*candidate, *noncandidate),
            key=lambda ranked: (ranked.score_class, int(ranked.rank_sha256, 16), ranked.row.key),
        )
        if len({ranked.row.key for ranked in combined}) != spec.selected_count:
            raise RuntimeError(f"Gstar selection contains duplicate keys for {spec.label}")
        selected[spec.label] = combined
        capacity_summary[spec.label] = {
            CANDIDATE_CLASS: capacities[(spec.label, CANDIDATE_CLASS)],
            NONCANDIDATE_CLASS: capacities[(spec.label, NONCANDIDATE_CLASS)],
        }
    return selected, capacity_summary, bank_state


def _extension_anchor_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result.update(
        {
            "gstar_score_class": None,
            "gstar_rank_sha256": None,
            "gstar_rank_domain": None,
            "paired_shuffled_arm": None,
        }
    )
    return result


def _render_treatment_rows(
    *,
    spec: Spec,
    selected: list[RankedRow],
    tokenizer: Any,
) -> tuple[list[dict[str, Any]], int]:
    group_counts = Counter((ranked.row.key[0], ranked.row.key[1]) for ranked in selected)
    rows: list[dict[str, Any]] = []
    max_tokens = 0
    for position, ranked in enumerate(selected):
        rendered = v2.render_training_row(ranked.row, tokenizer=tokenizer, seq_len=SEQ_LEN)
        max_tokens = max(max_tokens, rendered["model_input_tokens"])
        output = v2._base_output_row(ranked.row, rendered)
        output.update(
            {
                "source_kind": "defect_recipient",
                "assignment": ASSIGNMENT,
                "selection_seed": spec.seed,
                "pair_id": f"{spec.label}:{ranked.score_class}:{position}",
                "pair_position": position,
                "group_extra_positive_count": group_counts[(ranked.row.key[0], ranked.row.key[1])],
                "defect_draw_uint64": None,
                "shuffle_draw_uint64": None,
                "global_draw_uint64": None,
                "train_order_key": v2.canonical_json_sha256(
                    ["gstar-treatment", spec.seed, spec.clock, spec.dose_label, ranked.score_class, ranked.row.key]
                ),
                "gstar_score_class": ranked.score_class,
                "gstar_rank_sha256": ranked.rank_sha256,
                "gstar_rank_domain": HASH_DOMAIN,
                "paired_shuffled_arm": spec.source_shuffled_label,
            }
        )
        rows.append(output)
    return rows, max_tokens


def _schedule(clock: str, rows: int) -> dict[str, Any]:
    two_pass_steps = (2 * rows + BATCH_SIZE - 1) // BATCH_SIZE
    max_steps = max(64, two_pass_steps) if clock == "fixed_raw" else 64
    return {
        "max_steps": max_steps,
        "ckpt.interval": CHECKPOINT_INTERVAL,
        "readout_steps": sorted({64, max_steps}),
        "two_pass_steps": two_pass_steps if clock == "fixed_raw" else None,
        "schedule": "at_least_two_dataset_passes" if clock == "fixed_raw" else "common_64_steps",
    }


def build_extension(v2_index_path: Path, output_dir: Path) -> dict[str, Any]:
    v2_index_path = v2_index_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    partial_dir = output_dir.with_name(f"{output_dir.name}.partial")
    if partial_dir.exists():
        raise FileExistsError(partial_dir)
    index = read_json_object(v2_index_path)
    specs, source_identities, source_arm_records, anchor_state = discover_specs(index)
    selected, capacity_summary, bank_state = select_rows(index=index, specs=specs)

    tokenizer_path = Path(index["tokenizer"]["configured_path"]).expanduser().resolve()
    chat_template_path = Path(index["tokenizer"]["chat_template"]["path"]).expanduser().resolve()
    if file_identity(chat_template_path) != index["tokenizer"]["chat_template"]:
        raise ValueError("Tokenizer chat-template bytes differ from v2")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    tokenizer.chat_template = chat_template_path.read_text(encoding="utf-8")
    partial_dir.mkdir(parents=True)

    implementation = file_identity(Path(__file__))
    helper_implementation = file_identity(Path(v2.__file__))
    upstream_helper = index.get("implementation")
    verify_file_identity(upstream_helper, label="v2.implementation")
    if helper_implementation["sha256"] != upstream_helper.get("sha256") or helper_implementation[
        "size_bytes"
    ] != upstream_helper.get("size_bytes"):
        raise ValueError("The runtime v2 helper bytes differ from the source dataset builder")

    arm_entries: list[dict[str, Any]] = []
    for spec in specs:
        treatments, treatment_max_tokens = _render_treatment_rows(
            spec=spec,
            selected=selected[spec.label],
            tokenizer=tokenizer,
        )
        rows = [_extension_anchor_row(row) for row in anchor_state["rows"]] + treatments
        rows.sort(key=lambda row: (row["train_order_key"], row["trajectory_id"]))
        anchors = _anchor_rows(rows)
        if (
            len(anchors) != ANCHOR_COUNT
            or v2.canonical_json_sha256([_anchor_projection(row) for row in anchors])
            != anchor_state["projection_sha256"]
        ):
            raise RuntimeError(f"Anchor parity failed for {spec.label}")
        defects = [row for row in rows if row["source_kind"] == "defect_recipient"]
        class_counts = Counter(row["gstar_score_class"] for row in defects)
        expected_class_counts = {
            CANDIDATE_CLASS: spec.candidate_quota,
            NONCANDIDATE_CLASS: spec.noncandidate_quota,
        }
        if dict(class_counts) != expected_class_counts:
            raise RuntimeError(f"Composition matching failed for {spec.label}")
        arm_dir = partial_dir / "arms" / spec.label
        parquet_path = arm_dir / "train-00000-of-00001.parquet"
        parquet = v2._write_parquet(parquet_path, rows)
        schedule = _schedule(spec.clock, len(rows))
        source_arm_identities = {
            assignment: source_identities[label]
            for assignment, label in (
                ("behavior", spec.source_behavior_label),
                ("shuffled", spec.source_shuffled_label),
                ("global", spec.source_global_label),
            )
        }
        metadata = {
            "clock": spec.clock,
            "assignment": ASSIGNMENT,
            "display_symbol": DISPLAY_SYMBOL,
            "dose": spec.dose,
            "dose_label": spec.dose_label,
            "selection_seed": spec.seed,
            "raw_prefix_trajectories": spec.raw_prefix_trajectories,
            "hard_recipient_rows": spec.selected_count,
            "treatment_recipient_rows": spec.selected_count,
            "hard_recipient_fraction": spec.selected_count / len(rows),
            "treatment_recipient_fraction": spec.selected_count / len(rows),
            "candidate_overlap": spec.candidate_quota,
            "candidate_a_quota": spec.candidate_quota,
            "noncandidate_quota": spec.noncandidate_quota,
            "source_behavior_label": spec.source_behavior_label,
            "source_shuffled_label": spec.source_shuffled_label,
            "source_global_label": spec.source_global_label,
        }
        ordered_selected = selected[spec.label]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "study_id": STUDY_ID,
            "arm": {"label": spec.label, **metadata},
            "source_v2_index": file_identity(v2_index_path),
            "source_arms": source_arm_identities,
            "source_clean_anchor": source_identities["c0_anchor"],
            "bank_contract_sha256": bank_state["contract_sha256"],
            "strict_dead_contract": index["protocol"]["strict_dead_contract"],
            "trainability_filter": index["protocol"]["trainability_filter"],
            "selection": {
                "hash_domain": HASH_DOMAIN,
                "rule": (
                    "within the paired observed prefix after the v2 trainability exclusion, retain the exact "
                    "candidate-A quota and noncandidate quota from S using independent, domain-separated "
                    "SHA-256 global rank streams"
                ),
                "candidate_definition": "candidate_a = answer_correct and not strict_correct",
                "noncandidate_definition": "noncandidate = not answer_correct and not strict_correct",
                "candidate_a_quota": spec.candidate_quota,
                "noncandidate_quota": spec.noncandidate_quota,
                "candidate_a_capacity": capacity_summary[spec.label][CANDIDATE_CLASS],
                "noncandidate_capacity": capacity_summary[spec.label][NONCANDIDATE_CLASS],
                "selected_keys_sha256": v2.canonical_json_sha256([list(ranked.row.key) for ranked in ordered_selected]),
                "selected_rank_records_sha256": v2.canonical_json_sha256(
                    [[ranked.score_class, ranked.rank_sha256, *ranked.row.key] for ranked in ordered_selected]
                ),
                "candidate_a_max_rank_sha256": max(
                    ranked.rank_sha256 for ranked in ordered_selected if ranked.score_class == CANDIDATE_CLASS
                ),
                "noncandidate_max_rank_sha256": max(
                    ranked.rank_sha256 for ranked in ordered_selected if ranked.score_class == NONCANDIDATE_CLASS
                ),
            },
            "rows": len(rows),
            "counts_by_source": dict(sorted(Counter(row["source_kind"] for row in rows).items())),
            "counts_by_op": dict(
                sorted(Counter(str(row["op"]) for row in rows).items(), key=lambda item: int(item[0]))
            ),
            "counts_by_gstar_score_class": expected_class_counts,
            "strict_correct_rows": sum(row["strict_correct"] for row in rows),
            "answer_correct_rows": sum(row["answer_correct"] for row in rows),
            "candidate_rows": sum(row["candidate"] for row in rows),
            "assistant_weight_mass": sum(row["sft_weight"] * row["assistant_tokens"] for row in rows),
            "max_model_input_tokens": max(max(row["model_input_tokens"] for row in anchors), treatment_max_tokens),
            "anchor_projection_sha256": anchor_state["projection_sha256"],
            "anchor_ordered_trajectory_ids_sha256": anchor_state["ordered_trajectory_ids_sha256"],
            "ordered_trajectory_ids_sha256": v2.canonical_json_sha256([row["trajectory_id"] for row in rows]),
            "parquet": {
                "path": str((output_dir / "arms" / spec.label / parquet_path.name).resolve()),
                "rows": parquet["rows"],
                "size_bytes": parquet["size_bytes"],
                "sha256": parquet["sha256"],
            },
            "sft_contract": {
                "data.weight_column": "sft_weight",
                "data.seq_len": SEQ_LEN,
                "data.pack_function": "fixed_stack",
                "data.batch_size": BATCH_SIZE,
                "data.micro_batch_size": 4,
                "data.shuffle": True,
                "data.seed": 0,
                "loss_impl": "torch",
                **schedule,
            },
            "tokenizer": index["tokenizer"],
            "implementation": implementation,
            "runtime_v2_helper": helper_implementation,
            "upstream_v2_implementation": upstream_helper,
        }
        manifest_path = arm_dir / "manifest.json"
        write_json_atomic(manifest_path, manifest)
        arm_entries.append(
            {
                "label": spec.label,
                "alias_of": None,
                "dataset_path": str((output_dir / "arms" / spec.label).resolve()),
                "manifest_path": str((output_dir / "arms" / spec.label / "manifest.json").resolve()),
                "parquet_sha256": parquet["sha256"],
                "rows": len(rows),
                **metadata,
            }
        )

    if len(arm_entries) != 15:
        raise RuntimeError("Gstar extension did not produce exactly 15 arms")
    arm_entries.sort(key=lambda entry: entry["label"])
    extension_index = {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "source_study_id": index["study_id"],
        "source_v2_index": file_identity(v2_index_path),
        "bank_contract_sha256": bank_state["contract_sha256"],
        "protocol": {
            "assignment": ASSIGNMENT,
            "display_symbol": DISPLAY_SYMBOL,
            "hash_domain": HASH_DOMAIN,
            "candidate_definition": "candidate_a = answer_correct and not strict_correct",
            "noncandidate_definition": "noncandidate = not answer_correct and not strict_correct",
            "selection": (
                "independent, domain-separated global SHA-256 ranks for candidate-A and noncandidate rows "
                "inside each canonical specification's v2 observed prefix after applying the exact v2 "
                "trainability exclusion"
            ),
            "quota_source": "the exact candidate-A and noncandidate recipient counts in the paired S parquet",
            "bank_operations": list(EXPECTED_BANK_OPERATIONS),
            "anchor_operations": list(EXPECTED_ANCHOR_OPERATIONS),
            "treatment_operations": list(EXPECTED_TREATMENT_OPERATIONS),
            "selection_seeds": list(EXPECTED_SEEDS),
            "doses": list(EXPECTED_DOSES),
            "canonical_fixed_m_specs": 9,
            "canonical_nonalias_fixed_raw_specs": 6,
            "distinct_training_arms": 15,
            "anchor_count": ANCHOR_COUNT,
            "seq_len": SEQ_LEN,
            "strict_dead_contract": index["protocol"]["strict_dead_contract"],
            "trainability_filter": index["protocol"]["trainability_filter"],
        },
        "inputs": bank_state["inputs"],
        "tokenizer": index["tokenizer"],
        "source_clean_anchor": source_identities["c0_anchor"],
        "source_arm_identities_sha256": v2.canonical_json_sha256(source_arm_records),
        "source_arms": source_arm_records,
        "anchor_projection_sha256": anchor_state["projection_sha256"],
        "anchor_ordered_trajectory_ids_sha256": anchor_state["ordered_trajectory_ids_sha256"],
        "implementation": implementation,
        "runtime_v2_helper": helper_implementation,
        "upstream_v2_implementation": upstream_helper,
        "analyzer": {
            "repo_path": "user/tianhaowu/rsci/analyze_fixed_clock_sft_gstar_extension.py",
            "analysis_id": "verifier_defect_fixed_clock_sft_gstar_analysis_v1",
            "implementation": file_identity(Path(__file__).with_name(ANALYZER_FILENAME)),
        },
        "distinct_training_arms": [entry["label"] for entry in arm_entries],
        "arms": arm_entries,
    }
    write_json_atomic(partial_dir / "arm_index.json", extension_index)
    if file_identity(v2_index_path) != extension_index["source_v2_index"]:
        raise RuntimeError("The v2 arm index changed while building the extension")
    for identity in bank_state["inputs"].values():
        verify_file_identity(identity, label="frozen-bank input")
    for identity in source_identities.values():
        verify_file_identity(identity["manifest"], label=f"source arm {identity['label']} manifest")
        verify_file_identity(identity["parquet"], label=f"source arm {identity['label']} parquet")
    if file_identity(chat_template_path) != index["tokenizer"]["chat_template"]:
        raise RuntimeError("The tokenizer chat template changed while building the extension")
    if file_identity(Path(__file__)) != implementation:
        raise RuntimeError("The extension builder changed while building datasets")
    if file_identity(Path(v2.__file__)) != helper_implementation:
        raise RuntimeError("The v2 helper changed while building datasets")
    verify_file_identity(upstream_helper, label="v2.implementation")
    if extension_index["analyzer"]["implementation"] != file_identity(Path(__file__).with_name(ANALYZER_FILENAME)):
        raise RuntimeError("The extension analyzer changed while building datasets")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    partial_dir.replace(output_dir)
    return extension_index


def _spec_from_entry(entry: dict[str, Any]) -> Spec:
    return Spec(
        seed=int(entry["selection_seed"]),
        clock=str(entry["clock"]),
        dose=str(entry["dose"]),
        dose_label=str(entry["dose_label"]),
        raw_prefix_trajectories=int(entry["raw_prefix_trajectories"]),
        source_behavior_label=str(entry["source_behavior_label"]),
        source_shuffled_label=str(entry["source_shuffled_label"]),
        source_global_label=str(entry["source_global_label"]),
        label=str(entry["label"]),
        candidate_quota=int(entry["candidate_a_quota"]),
        noncandidate_quota=int(entry["noncandidate_quota"]),
    )


def validate_output(output_dir: Path, *, deep_selection_check: bool = True) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    index_path = output_dir / "arm_index.json"
    index = read_json_object(index_path)
    if index.get("schema_version") != SCHEMA_VERSION or index.get("study_id") != STUDY_ID:
        raise ValueError("Gstar arm index has the wrong schema or study identity")
    implementation = verify_relocatable_implementation(
        index.get("implementation"), Path(__file__), label="Gstar builder implementation"
    )
    runtime_v2_helper = verify_relocatable_implementation(
        index.get("runtime_v2_helper"), Path(v2.__file__), label="runtime v2 helper"
    )
    analyzer = index.get("analyzer")
    if (
        not isinstance(analyzer, dict)
        or analyzer.get("analysis_id") != "verifier_defect_fixed_clock_sft_gstar_analysis_v1"
        or analyzer.get("repo_path") != "user/tianhaowu/rsci/analyze_fixed_clock_sft_gstar_extension.py"
    ):
        raise ValueError("Gstar analyzer provenance differs from the index")
    verify_relocatable_implementation(
        analyzer.get("implementation"),
        Path(__file__).with_name(ANALYZER_FILENAME),
        label="Gstar analyzer implementation",
    )
    verify_file_identity(index.get("upstream_v2_implementation"), label="upstream_v2_implementation")
    source_v2_index = verify_file_identity(index.get("source_v2_index"), label="source_v2_index")
    source_index = read_json_object(Path(source_v2_index["path"]))
    specs, source_identities, source_arm_records, anchor_state = discover_specs(source_index)
    if index.get("source_arm_identities_sha256") != v2.canonical_json_sha256(source_arm_records):
        raise ValueError("Source-arm identity aggregate differs")
    if index.get("source_clean_anchor") != source_identities["c0_anchor"]:
        raise ValueError("Source clean-anchor identity differs")
    if index.get("anchor_projection_sha256") != anchor_state["projection_sha256"]:
        raise ValueError("Anchor projection identity differs")
    for identity in index.get("inputs", {}).values():
        verify_file_identity(identity, label="frozen-bank input")

    entries = index.get("arms")
    labels = index.get("distinct_training_arms")
    if (
        not isinstance(entries, list)
        or len(entries) != 15
        or labels != sorted(labels)
        or labels != sorted(entry.get("label") for entry in entries)
    ):
        raise ValueError("Gstar index does not contain exactly 15 canonical arms")
    expected_specs = {spec.label: spec for spec in specs}
    observed_specs = {entry["label"]: _spec_from_entry(entry) for entry in entries}
    if observed_specs != expected_specs:
        raise ValueError("Gstar arm dimensions or shuffled-derived quotas differ")

    deep_selected: dict[str, list[RankedRow]] | None = None
    deep_capacities: dict[str, dict[str, int]] | None = None
    if deep_selection_check:
        deep_selected, deep_capacities, _ = select_rows(index=source_index, specs=specs)

    for entry in entries:
        spec = expected_specs[entry["label"]]
        dataset_path = Path(entry["dataset_path"]).expanduser().resolve()
        if dataset_path != output_dir / "arms" / spec.label:
            raise ValueError(f"Dataset path escapes the extension root for {spec.label}")
        manifest_path = Path(entry["manifest_path"]).expanduser().resolve()
        parquet_path = dataset_path / "train-00000-of-00001.parquet"
        manifest = read_json_object(manifest_path)
        parquet_identity = file_identity(parquet_path)
        if (
            manifest.get("study_id") != STUDY_ID
            or manifest.get("arm") != {"label": spec.label, **_metadata(entry)}
            or manifest.get("parquet", {}).get("sha256") != parquet_identity["sha256"]
            or entry.get("parquet_sha256") != parquet_identity["sha256"]
            or manifest.get("rows") != entry.get("rows")
        ):
            raise ValueError(f"Manifest/parquet identity differs for {spec.label}")
        if (
            manifest.get("implementation") != implementation
            or manifest.get("runtime_v2_helper") != runtime_v2_helper
            or manifest.get("upstream_v2_implementation") != index.get("upstream_v2_implementation")
        ):
            raise ValueError(f"Implementation provenance differs for {spec.label}")
        if manifest.get("trainability_filter") != source_index["protocol"]["trainability_filter"]:
            raise ValueError(f"Trainability exclusion differs for {spec.label}")
        rows = _dataset_rows(dataset_path)
        anchors = _anchor_rows(rows)
        defects = [row for row in rows if row.get("source_kind") == "defect_recipient"]
        if (
            len(rows) != ANCHOR_COUNT + spec.selected_count
            or len(anchors) != ANCHOR_COUNT
            or len(defects) != spec.selected_count
            or not math.isclose(
                sum(float(row["sft_weight"]) * int(row["assistant_tokens"]) for row in rows),
                len(rows),
                abs_tol=1e-8,
            )
            or max(int(row["model_input_tokens"]) for row in rows) > SEQ_LEN
        ):
            raise ValueError(f"Dataset count/weight/length invariant failed for {spec.label}")
        if v2.canonical_json_sha256([_anchor_projection(row) for row in anchors]) != anchor_state["projection_sha256"]:
            raise ValueError(f"Anchor parity failed for {spec.label}")
        class_counts = Counter(row.get("gstar_score_class") for row in defects)
        expected_counts = {
            CANDIDATE_CLASS: spec.candidate_quota,
            NONCANDIDATE_CLASS: spec.noncandidate_quota,
        }
        if dict(class_counts) != expected_counts:
            raise ValueError(f"Candidate composition differs for {spec.label}")
        selected_keys: list[tuple[int, int, int]] = []
        rank_records: list[list[Any]] = []
        excluded_keys = {tuple(record["key"]) for record in source_index["protocol"]["trainability_filter"]["records"]}
        for row in defects:
            key = (int(row["op"]), int(row["prompt_index"]), int(row["sample_rank"]))
            if (
                not isinstance(row.get("strict_correct"), bool)
                or not isinstance(row.get("answer_correct"), bool)
                or not isinstance(row.get("candidate"), bool)
                or row["candidate"] != bool(row["answer_correct"] and not row["strict_correct"])
            ):
                raise ValueError(f"Recipient score-class fields are inconsistent for {spec.label}:{key}")
            score_class = CANDIDATE_CLASS if row.get("candidate") is True else NONCANDIDATE_CLASS
            expected_rank = rank_sha256(spec, score_class, key)
            if (
                row.get("assignment") != ASSIGNMENT
                or row.get("paired_shuffled_arm") != spec.source_shuffled_label
                or row.get("strict_correct") is not False
                or row.get("gstar_score_class") != score_class
                or row.get("gstar_rank_sha256") != expected_rank
                or row.get("gstar_rank_domain") != HASH_DOMAIN
                or int(row["raw_ordinal"]) >= spec.raw_prefix_trajectories
                or key in excluded_keys
            ):
                raise ValueError(f"Recipient contract failed for {spec.label}:{key}")
            selected_keys.append(key)
            rank_records.append([score_class, expected_rank, *key])
        ordered_records = sorted(rank_records, key=lambda record: (record[0], int(record[1], 16), *record[2:]))
        ordered_keys = [record[2:] for record in ordered_records]
        selection = manifest.get("selection", {})
        if (
            selection.get("selected_keys_sha256") != v2.canonical_json_sha256(ordered_keys)
            or selection.get("selected_rank_records_sha256") != v2.canonical_json_sha256(ordered_records)
            or len(set(selected_keys)) != len(selected_keys)
        ):
            raise ValueError(f"Recipient selection hashes differ for {spec.label}")
        if deep_selected is not None and deep_capacities is not None:
            expected_records = [
                [ranked.score_class, ranked.rank_sha256, *ranked.row.key] for ranked in deep_selected[spec.label]
            ]
            if ordered_records != expected_records:
                raise ValueError(f"Deep global-rank selection differs for {spec.label}")
            if selection.get("candidate_a_capacity") != deep_capacities[spec.label][CANDIDATE_CLASS]:
                raise ValueError(f"Candidate-A capacity differs for {spec.label}")
            if selection.get("noncandidate_capacity") != deep_capacities[spec.label][NONCANDIDATE_CLASS]:
                raise ValueError(f"Noncandidate capacity differs for {spec.label}")
    return index


def main() -> None:
    args = parse_args()
    if args.validate_only:
        result = validate_output(
            args.output_dir,
            deep_selection_check=not args.no_deep_selection_check,
        )
    else:
        result = build_extension(args.v2_index, args.output_dir)
    print(
        json.dumps(
            {
                "study_id": result["study_id"],
                "output_dir": str(args.output_dir.expanduser().resolve()),
                "distinct_training_arms": len(result["distinct_training_arms"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
