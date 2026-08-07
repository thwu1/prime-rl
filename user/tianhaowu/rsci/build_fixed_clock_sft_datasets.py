#!/usr/bin/env python3
"""Build deterministic fixed-clock verifier-defect SFT treatment and control datasets."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterator

from datasets import Dataset
from transformers import AutoTokenizer

from prime_rl.utils.chat_template import build_incremental_token_mask, strip_message_content

BANK_ID = "frozen-base-op10-12-op15-40-r128-v1"
DEFAULT_BANK_DIR = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect") / BANK_ID
DEFAULT_OUTPUT_DIR = DEFAULT_BANK_DIR / "fixed-clock-sft-v2"
DEFAULT_TOKENIZER = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
    "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/"
    "id2-10_0.2easy_0.3medium_0.5hard/base"
)
DEFAULT_SELECTION_SEEDS = (20260805, 20260806, 20260807)
DEFAULT_DOSES = ("1/400", "1/200", "1/100")
DEFAULT_ANCHOR_OPERATIONS = (10, 11, 12)
DEFAULT_BANK_OPERATIONS = (*DEFAULT_ANCHOR_OPERATIONS, *range(15, 41))
DEFAULT_TREATMENT_OPERATIONS = tuple(range(21, 41))
DEFAULT_EXAMPLES_PER_OPERATION = 1_000
DEFAULT_SAMPLES_PER_PROMPT = 128
DEFAULT_TARGET_COUNT = 512
DEFAULT_ANCHOR_COUNT = 512
DEFAULT_SEQ_LEN = 2_048
ANCHOR_SELECTION_SEED = 20260807
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Dose:
    label: str
    numerator: int
    denominator: int

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


@dataclass(frozen=True)
class BankPaths:
    root: Path
    manifest: Path
    completion: Path
    prompt_view_manifest: Path
    prompts: Path
    generations: Path
    strict_results: Path


@dataclass(frozen=True)
class BankRow:
    prompt: dict[str, Any]
    generation: dict[str, Any]
    score: dict[str, Any]
    raw_ordinal: int | None

    @property
    def key(self) -> tuple[int, int, int]:
        return (
            int(self.generation["op"]),
            int(self.generation["__idx"]),
            int(self.generation["sample_rank"]),
        )


@dataclass(frozen=True)
class SelectedTreatment:
    row: BankRow
    pair_id: str
    pair_position: int
    group_extra_positive_count: int
    assignment: str
    defect_draw_uint64: int
    shuffle_draw_uint64: int
    global_draw_uint64: int


@dataclass(frozen=True)
class ArmSpec:
    seed: int
    clock: str
    dose: Dose

    @property
    def stem(self) -> str:
        return f"seed{self.seed}_{self.clock}_{self.dose.label}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank-dir", type=Path, default=DEFAULT_BANK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--chat-template", type=Path)
    parser.add_argument("--selection-seeds", type=int, nargs="+", default=list(DEFAULT_SELECTION_SEEDS))
    parser.add_argument("--doses", nargs="+", default=list(DEFAULT_DOSES))
    parser.add_argument("--bank-operations", type=int, nargs="+", default=list(DEFAULT_BANK_OPERATIONS))
    parser.add_argument("--anchor-operations", type=int, nargs="+", default=list(DEFAULT_ANCHOR_OPERATIONS))
    parser.add_argument(
        "--treatment-operations",
        type=int,
        nargs="+",
        default=list(DEFAULT_TREATMENT_OPERATIONS),
    )
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--anchor-count", type=int, default=DEFAULT_ANCHOR_COUNT)
    parser.add_argument("--examples-per-operation", type=int, default=DEFAULT_EXAMPLES_PER_OPERATION)
    parser.add_argument("--samples-per-prompt", type=int, default=DEFAULT_SAMPLES_PER_PROMPT)
    parser.add_argument("--seq-len", type=int, default=DEFAULT_SEQ_LEN)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "sha256": file_sha256(path),
    }


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank JSONL row at {path}:{line_number}")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row is not an object at {path}:{line_number}")
            yield line_number, row


def parse_dose(value: str) -> Dose:
    try:
        fraction = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"Invalid dose {value!r}; use an exact fraction such as 1/400") from error
    if not 0 < fraction < 1:
        raise ValueError(f"Dose must be strictly between zero and one: {value!r}")
    basis_points = fraction * 10_000
    if basis_points.denominator != 1:
        raise ValueError(f"Dose must be representable in integer basis points: {value!r}")
    label = f"p{int(basis_points):04d}"
    return Dose(label, fraction.numerator, fraction.denominator)


def draw_uint64(domain: str, seed: int, op: int, prompt_index: int, sample_rank: int) -> int:
    if not domain or "\0" in domain:
        raise ValueError("Hash domain must be non-empty and contain no NUL")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (seed, op, prompt_index, sample_rank)
    ):
        raise ValueError("Hash coordinates must be non-negative integers")
    material = f"rsci-fixed-clock-sft-v2\0{domain}\0{seed}\0{op}\0{prompt_index}\0{sample_rank}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def draw_below(draw: int, dose: Dose) -> bool:
    if isinstance(draw, bool) or not isinstance(draw, int) or not 0 <= draw < 2**64:
        raise ValueError("draw must be a uint64")
    return draw * dose.denominator < dose.numerator * 2**64


def bank_paths(root: Path) -> BankPaths:
    root = root.expanduser().resolve()
    return BankPaths(
        root=root,
        manifest=root / "manifest.json",
        completion=root / "completion.json",
        prompt_view_manifest=root / "prompts" / "prompt_view_manifest.json",
        prompts=root / "prompts.jsonl",
        generations=root / "generations.jsonl",
        strict_results=root / "strict_results.jsonl",
    )


def _resolve_recorded_path(root: Path, value: object, expected: Path) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Recorded artifact path is not a non-empty string: {value!r}")
    recorded = Path(value)
    resolved = (root / recorded).resolve() if not recorded.is_absolute() else recorded.resolve()
    if resolved != expected.resolve():
        raise ValueError(f"Recorded artifact path differs: {resolved} != {expected.resolve()}")


def _verify_completion_artifact(root: Path, name: str, path: Path, record: object, expected_rows: int) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"completion.artifacts.{name} is not an object")
    _resolve_recorded_path(root, record.get("path"), path)
    observed = file_identity(path)
    for field, expected in (
        ("rows", expected_rows),
        ("size_bytes", observed["size_bytes"]),
        ("sha256", observed["sha256"]),
    ):
        if record.get(field) != expected:
            raise ValueError(f"completion.artifacts.{name}.{field}={record.get(field)!r}, expected {expected!r}")


def verify_bank_contract(
    paths: BankPaths,
    *,
    operations: tuple[int, ...],
    examples_per_operation: int,
    samples_per_prompt: int,
) -> dict[str, Any]:
    manifest = read_json_object(paths.manifest)
    completion = read_json_object(paths.completion)
    prompt_view_manifest = read_json_object(paths.prompt_view_manifest)
    if manifest.get("schema_version") != 1 or completion.get("schema_version") != 1:
        raise ValueError("Bank manifest/completion schema_version must equal 1")
    contract_sha256 = manifest.get("contract_sha256")
    if not isinstance(contract_sha256, str) or len(contract_sha256) != 64:
        raise ValueError("Bank manifest has no SHA-256 contract identity")
    if completion.get("contract_sha256") != contract_sha256:
        raise ValueError("Bank manifest and completion contract identities differ")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("Bank manifest has no contract object")
    if canonical_json_sha256(contract) != contract_sha256:
        raise ValueError("Bank manifest contract_sha256 does not match its contract object")
    if contract.get("bank_id") != BANK_ID:
        raise ValueError(f"Unexpected bank_id: {contract.get('bank_id')!r}")
    if contract.get("operations") != list(operations):
        raise ValueError(f"Bank operations differ: {contract.get('operations')!r}")
    if contract.get("examples_per_operation") != examples_per_operation:
        raise ValueError("Bank examples_per_operation differs")
    expected_groups = len(operations) * examples_per_operation
    expected_trajectories = expected_groups * samples_per_prompt
    expected = contract.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("Bank contract has no expected-count object")
    if expected.get("groups") != expected_groups or expected.get("trajectories") != expected_trajectories:
        raise ValueError(f"Bank expected counts differ: {expected!r}")

    prompt_view = contract.get("prompt_view")
    if not isinstance(prompt_view, dict):
        raise ValueError("Bank contract has no prompt-view identity")
    _resolve_recorded_path(paths.root, prompt_view.get("manifest_path"), paths.prompt_view_manifest)
    prompt_view_identity = file_identity(paths.prompt_view_manifest)
    if (
        prompt_view.get("manifest_size_bytes") != prompt_view_identity["size_bytes"]
        or prompt_view.get("manifest_sha256") != prompt_view_identity["sha256"]
    ):
        raise ValueError("Bank contract prompt-view identity differs")
    if prompt_view_manifest.get("schema_version") != 1:
        raise ValueError("Prompt-view manifest schema_version must equal 1")
    prompt_protocol = prompt_view_manifest.get("protocol")
    prompt_counts = prompt_view_manifest.get("counts")
    if not isinstance(prompt_protocol, dict) or not isinstance(prompt_counts, dict):
        raise ValueError("Prompt-view manifest lacks protocol/counts")
    if prompt_protocol.get("operations") != list(operations):
        raise ValueError("Prompt-view operations differ")
    if prompt_protocol.get("prompts_per_operation") != examples_per_operation:
        raise ValueError("Prompt-view prompts_per_operation differs")
    expected_prompt_counts = {
        "selected_prompts": expected_groups,
        "unique_selected_ids": expected_groups,
        "unique_selected_prompts": expected_groups,
        "heldout_id_overlap": 0,
        "heldout_prompt_overlap": 0,
    }
    for field, value in expected_prompt_counts.items():
        if prompt_counts.get(field) != value:
            raise ValueError(f"Prompt-view {field}={prompt_counts.get(field)!r}, expected {value}")

    manifest_record = completion.get("manifest")
    if not isinstance(manifest_record, dict):
        raise ValueError("Bank completion has no manifest identity")
    _resolve_recorded_path(paths.root, manifest_record.get("path"), paths.manifest)
    manifest_identity = file_identity(paths.manifest)
    if (
        manifest_record.get("size_bytes") != manifest_identity["size_bytes"]
        or manifest_record.get("sha256") != manifest_identity["sha256"]
    ):
        raise ValueError("Bank completion manifest identity differs from manifest.json")

    artifacts = completion.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"prompts", "generations", "strict_results"}:
        raise ValueError("Bank completion artifacts must be exactly prompts/generations/strict_results")
    _verify_completion_artifact(paths.root, "prompts", paths.prompts, artifacts["prompts"], expected_groups)
    _verify_completion_artifact(
        paths.root,
        "generations",
        paths.generations,
        artifacts["generations"],
        expected_trajectories,
    )
    _verify_completion_artifact(
        paths.root,
        "strict_results",
        paths.strict_results,
        artifacts["strict_results"],
        expected_trajectories,
    )
    return {
        "contract_sha256": contract_sha256,
        "expected_groups": expected_groups,
        "expected_trajectories": expected_trajectories,
        "inputs": {
            "manifest": manifest_identity,
            "completion": file_identity(paths.completion),
            "prompt_view_manifest": prompt_view_identity,
            "prompts": file_identity(paths.prompts),
            "generations": file_identity(paths.generations),
            "strict_results": file_identity(paths.strict_results),
        },
    }


def read_prompts(
    path: Path,
    *,
    operations: tuple[int, ...],
    examples_per_operation: int,
) -> dict[tuple[int, int], dict[str, Any]]:
    prompts: dict[tuple[int, int], dict[str, Any]] = {}
    expected_iterator = (
        (operation, prompt_index) for operation in operations for prompt_index in range(examples_per_operation)
    )
    rows = iter_jsonl(path)
    for expected_key, (line_number, row) in zip(expected_iterator, rows, strict=True):
        required = {"op", "__idx", "id", "problem", "question", "solution"}
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"Prompt row is missing {missing}: {path}:{line_number}")
        key = (int(row["op"]), int(row["__idx"]))
        if key != expected_key:
            raise ValueError(f"Prompt ordering/key mismatch at {path}:{line_number}: {key} != {expected_key}")
        if not isinstance(row["id"], str) or not row["id"]:
            raise ValueError(f"Prompt id is invalid at {path}:{line_number}")
        prompts[key] = row
    expected_rows = len(operations) * examples_per_operation
    if len(prompts) != expected_rows:
        raise ValueError(f"Prompt count differs: {len(prompts)} != {expected_rows}")
    prompt_texts = {
        f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question>"
        for row in prompts.values()
    }
    if len(prompt_texts) != expected_rows:
        raise ValueError("Bank prompt texts are not globally unique")
    return prompts


def _validate_score(row: dict[str, Any], *, path: Path, line_number: int) -> None:
    required = {"op", "__idx", "sample_rank", "id", "perfect", "answer_correct", "candidate"}
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"Strict-result row is missing {missing}: {path}:{line_number}")
    for field in ("perfect", "answer_correct", "candidate"):
        if not isinstance(row[field], bool):
            raise ValueError(f"Strict-result {field} is not bool at {path}:{line_number}")
    expected_candidate = bool(row["answer_correct"] and not row["perfect"])
    if row["candidate"] != expected_candidate:
        raise ValueError(
            f"Strict-result candidate identity mismatch at {path}:{line_number}: "
            f"{row['candidate']} != {expected_candidate}"
        )
    if row["perfect"] and not row["answer_correct"]:
        raise ValueError(f"Strict-perfect row is answer-incorrect at {path}:{line_number}")


def treatment_raw_ordinal(
    op: int,
    prompt_index: int,
    sample_rank: int,
    *,
    treatment_operations: tuple[int, ...],
    samples_per_prompt: int,
) -> int:
    try:
        operation_index = treatment_operations.index(op)
    except ValueError as error:
        raise ValueError(f"Operation {op} is outside the treatment stream") from error
    return ((prompt_index * len(treatment_operations) + operation_index) * samples_per_prompt) + sample_rank


def compute_prefixes(
    strict_results: Path,
    *,
    bank_operations: tuple[int, ...],
    treatment_operations: tuple[int, ...],
    examples_per_operation: int,
    samples_per_prompt: int,
    seeds: tuple[int, ...],
    doses: tuple[Dose, ...],
    target_count: int,
) -> tuple[dict[tuple[int, str], int], dict[tuple[int, str], int], dict[str, Any]]:
    triggers: dict[tuple[int, str], list[int]] = {(seed, dose.label): [] for seed in seeds for dose in doses}
    treatment_rows_by_op: Counter[int] = Counter()
    strict_positive_counts_by_op: Counter[int] = Counter()
    candidate_counts_by_op: Counter[int] = Counter()
    expected_iterator = (
        (operation, prompt_index, sample_rank)
        for operation in bank_operations
        for prompt_index in range(examples_per_operation)
        for sample_rank in range(samples_per_prompt)
    )
    rows = iter_jsonl(strict_results)
    observed_rows = 0
    for expected_key, (line_number, row) in zip(expected_iterator, rows, strict=True):
        _validate_score(row, path=strict_results, line_number=line_number)
        key = (int(row["op"]), int(row["__idx"]), int(row["sample_rank"]))
        if key != expected_key:
            raise ValueError(
                f"Strict-result ordering/key mismatch at {strict_results}:{line_number}: {key} != {expected_key}"
            )
        observed_rows += 1
        if key[0] not in treatment_operations:
            continue
        treatment_rows_by_op[key[0]] += 1
        strict_positive_counts_by_op[key[0]] += int(row["perfect"])
        candidate_counts_by_op[key[0]] += int(row["candidate"])
        if not row["candidate"]:
            continue
        ordinal = treatment_raw_ordinal(
            *key,
            treatment_operations=treatment_operations,
            samples_per_prompt=samples_per_prompt,
        )
        for seed in seeds:
            draw = draw_uint64("defect", seed, *key)
            for dose in doses:
                if draw_below(draw, dose):
                    triggers[(seed, dose.label)].append(ordinal)
    expected_rows = len(bank_operations) * examples_per_operation * samples_per_prompt
    if observed_rows != expected_rows:
        raise ValueError(f"Strict-result row count differs: {observed_rows} != {expected_rows}")

    expected_treatment_rows = examples_per_operation * samples_per_prompt
    for operation in treatment_operations:
        if treatment_rows_by_op[operation] != expected_treatment_rows:
            raise ValueError(
                f"Treatment OP{operation} has {treatment_rows_by_op[operation]} rows, "
                f"expected {expected_treatment_rows}"
            )
    contaminated_operations = {
        operation: strict_positive_counts_by_op[operation]
        for operation in treatment_operations
        if strict_positive_counts_by_op[operation]
    }
    if contaminated_operations:
        raise ValueError(
            "Strict-dead treatment contract failed: every treatment trajectory must have perfect=false; "
            f"strict-positive counts={contaminated_operations}"
        )

    prefixes: dict[tuple[int, str], int] = {}
    for key, ordinals in triggers.items():
        if len(ordinals) < target_count:
            raise ValueError(f"Bank has only {len(ordinals)} triggers for seed/dose {key}; need {target_count}")
        ordinals.sort()
        prefixes[key] = ordinals[target_count - 1]
    minimum = doses[0]
    fixed_raw_counts = {
        (seed, dose.label): sum(ordinal <= prefixes[(seed, minimum.label)] for ordinal in triggers[(seed, dose.label)])
        for seed in seeds
        for dose in doses
    }
    strict_dead_contract = {
        "required": True,
        "definition": "every frozen trajectory in every treatment operation has strict perfect=false",
        "operations": list(treatment_operations),
        "rows_per_operation": expected_treatment_rows,
        "strict_positive_counts_by_op": {
            str(operation): strict_positive_counts_by_op[operation] for operation in treatment_operations
        },
        "candidate_counts_by_op": {
            str(operation): candidate_counts_by_op[operation] for operation in treatment_operations
        },
        "verified_rows_by_op": {str(operation): treatment_rows_by_op[operation] for operation in treatment_operations},
    }
    return prefixes, fixed_raw_counts, strict_dead_contract


def _validate_generation(row: dict[str, Any], *, path: Path, line_number: int) -> None:
    required = {"op", "__idx", "sample_rank", "id", "gen_solution_answer", "finish_reason"}
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"Generation row is missing {missing}: {path}:{line_number}")
    if not isinstance(row["gen_solution_answer"], str):
        raise ValueError(f"Generation completion is not text at {path}:{line_number}")


def iter_joined_groups(
    paths: BankPaths,
    prompts: dict[tuple[int, int], dict[str, Any]],
    *,
    bank_operations: tuple[int, ...],
    treatment_operations: tuple[int, ...],
    examples_per_operation: int,
    samples_per_prompt: int,
) -> Iterator[list[BankRow]]:
    generation_rows = iter_jsonl(paths.generations)
    score_rows = iter_jsonl(paths.strict_results)
    for operation in bank_operations:
        for prompt_index in range(examples_per_operation):
            prompt = prompts[(operation, prompt_index)]
            group: list[BankRow] = []
            for sample_rank in range(samples_per_prompt):
                generation_line, generation = next(generation_rows)
                score_line, score = next(score_rows)
                _validate_generation(generation, path=paths.generations, line_number=generation_line)
                _validate_score(score, path=paths.strict_results, line_number=score_line)
                expected_key = (operation, prompt_index, sample_rank)
                generation_key = (
                    int(generation["op"]),
                    int(generation["__idx"]),
                    int(generation["sample_rank"]),
                )
                score_key = (int(score["op"]), int(score["__idx"]), int(score["sample_rank"]))
                if generation_key != expected_key or score_key != expected_key:
                    raise ValueError(
                        f"Generation/score key mismatch at rows {generation_line}/{score_line}: "
                        f"{generation_key}/{score_key} != {expected_key}"
                    )
                if generation["id"] != prompt["id"] or score["id"] != prompt["id"]:
                    raise ValueError(f"Prompt/generation/score id mismatch for key {expected_key}")
                ordinal = (
                    treatment_raw_ordinal(
                        *expected_key,
                        treatment_operations=treatment_operations,
                        samples_per_prompt=samples_per_prompt,
                    )
                    if operation in treatment_operations
                    else None
                )
                group.append(BankRow(prompt, generation, score, ordinal))
            yield group
    try:
        next(generation_rows)
    except StopIteration:
        pass
    else:
        raise ValueError(f"Generation file has extra rows: {paths.generations}")
    try:
        next(score_rows)
    except StopIteration:
        pass
    else:
        raise ValueError(f"Strict-result file has extra rows: {paths.strict_results}")


def _arm_specs(seeds: tuple[int, ...], doses: tuple[Dose, ...]) -> tuple[ArmSpec, ...]:
    minimum = doses[0]
    specs = [ArmSpec(seed, "fixed_m", dose) for seed in seeds for dose in doses]
    specs.extend(ArmSpec(seed, "fixed_raw", dose) for seed in seeds for dose in doses if dose != minimum)
    return tuple(specs)


def _iid_arm_specs(seeds: tuple[int, ...], doses: tuple[Dose, ...]) -> tuple[ArmSpec, ...]:
    return tuple(ArmSpec(seed, "fixed_raw", dose) for seed in seeds for dose in doses)


GlobalHeapEntry = tuple[int, int, int, int, BankRow]


def _offer_global_recipient(
    heap: list[GlobalHeapEntry],
    *,
    row: BankRow,
    draw: int,
    limit: int,
) -> None:
    if limit < 1:
        raise ValueError("Global-recipient heap limit must be positive")
    rank = (draw, *row.key)
    entry = (-rank[0], -rank[1], -rank[2], -rank[3], row)
    if len(heap) < limit:
        heapq.heappush(heap, entry)
        return
    worst = heap[0]
    worst_rank = (-worst[0], -worst[1], -worst[2], -worst[3])
    if rank < worst_rank:
        heapq.heapreplace(heap, entry)


def _ordered_global_recipients(heap: list[GlobalHeapEntry]) -> list[tuple[int, BankRow]]:
    ranked = [((-entry[0], -entry[1], -entry[2], -entry[3]), entry[4]) for entry in heap]
    ranked.sort(key=lambda item: item[0])
    return [(rank[0], row) for rank, row in ranked]


def collect_selected_rows(
    paths: BankPaths,
    prompts: dict[tuple[int, int], dict[str, Any]],
    prefixes: dict[tuple[int, str], int],
    fixed_raw_counts: dict[tuple[int, str], int],
    *,
    bank_operations: tuple[int, ...],
    anchor_operations: tuple[int, ...],
    treatment_operations: tuple[int, ...],
    examples_per_operation: int,
    samples_per_prompt: int,
    seeds: tuple[int, ...],
    doses: tuple[Dose, ...],
    target_count: int,
    anchor_count: int,
) -> tuple[list[BankRow], dict[tuple[ArmSpec, str], list[SelectedTreatment]], dict[str, Any]]:
    specs = _arm_specs(seeds, doses)
    iid_specs = _iid_arm_specs(seeds, doses)
    minimum = doses[0]
    assignments = ("behavior", "shuffled", "global")
    specs_by_seed = {seed: tuple(spec for spec in specs if spec.seed == seed) for seed in seeds}
    iid_specs_by_seed = {seed: tuple(spec for spec in iid_specs if spec.seed == seed) for seed in seeds}
    expected_counts = {
        spec: target_count if spec.clock == "fixed_m" else fixed_raw_counts[(spec.seed, spec.dose.label)]
        for spec in specs
    }
    for seed in seeds:
        if fixed_raw_counts[(seed, minimum.label)] != target_count:
            raise RuntimeError(f"Minimum-dose fixed-raw count differs from target for seed {seed}")
    selected: dict[tuple[ArmSpec, str], list[SelectedTreatment]] = {
        (spec, assignment): [] for spec in specs for assignment in assignments
    }
    selected.update({(spec, "iid"): [] for spec in iid_specs})
    anchor_representatives: dict[int, list[BankRow]] = defaultdict(list)
    per_group_counts: dict[tuple[ArmSpec, str], Counter[tuple[int, int]]] = {
        (spec, assignment): Counter() for spec in specs for assignment in assignments
    }
    per_group_counts.update({(spec, "iid"): Counter() for spec in iid_specs})
    global_heaps: dict[ArmSpec, list[GlobalHeapEntry]] = {spec: [] for spec in specs}
    global_eligible_counts: Counter[ArmSpec] = Counter()
    iid_eligible_counts: Counter[ArmSpec] = Counter()

    for group in iter_joined_groups(
        paths,
        prompts,
        bank_operations=bank_operations,
        treatment_operations=treatment_operations,
        examples_per_operation=examples_per_operation,
        samples_per_prompt=samples_per_prompt,
    ):
        operation = int(group[0].generation["op"])
        prompt_index = int(group[0].generation["__idx"])
        if operation in anchor_operations:
            strict_rows = [row for row in group if row.score["perfect"]]
            if strict_rows:
                representative = min(
                    strict_rows,
                    key=lambda row: (
                        draw_uint64("anchor-slot", ANCHOR_SELECTION_SEED, *row.key),
                        row.key,
                    ),
                )
                anchor_representatives[operation].append(representative)
            continue
        if operation not in treatment_operations:
            continue

        for seed in seeds:
            global_draws = {
                row.key: draw_uint64("global-recipient", seed, *row.key) for row in group if not row.score["perfect"]
            }
            shuffle_ranked = sorted(
                (row for row in group if not row.score["perfect"]),
                key=lambda row: (draw_uint64("shuffle", seed, *row.key), row.key[2]),
            )
            for spec in specs_by_seed[seed]:
                cutoff = (
                    prefixes[(seed, spec.dose.label)] if spec.clock == "fixed_m" else prefixes[(seed, minimum.label)]
                )
                observed = [row for row in group if row.raw_ordinal is not None and row.raw_ordinal <= cutoff]
                if not observed:
                    continue
                eligible = [row for row in observed if not row.score["perfect"]]
                global_eligible_counts[spec] += len(eligible)
                for row in eligible:
                    _offer_global_recipient(
                        global_heaps[spec],
                        row=row,
                        draw=global_draws[row.key],
                        limit=expected_counts[spec],
                    )
                behavior = [
                    row
                    for row in observed
                    if row.score["candidate"] and draw_below(draw_uint64("defect", seed, *row.key), spec.dose)
                ]
                if not behavior:
                    continue
                observed_keys = {row.key for row in observed}
                shuffled_pool = [row for row in shuffle_ranked if row.key in observed_keys]
                if len(shuffled_pool) < len(behavior):
                    raise ValueError(
                        f"Group op={operation} idx={prompt_index} has {len(behavior)} positives "
                        f"but only {len(shuffled_pool)} strict-negative recipients"
                    )
                shuffled = shuffled_pool[: len(behavior)]
                behavior.sort(key=lambda row: row.raw_ordinal)
                for local_pair, (behavior_row, shuffled_row) in enumerate(zip(behavior, shuffled, strict=True)):
                    pair_id = f"{spec.stem}:op{operation}:idx{prompt_index}:pair{local_pair}"
                    pair_position = len(selected[(spec, "behavior")])
                    common = {
                        "pair_id": pair_id,
                        "pair_position": pair_position,
                        "group_extra_positive_count": len(behavior),
                    }
                    selected[(spec, "behavior")].append(
                        SelectedTreatment(
                            row=behavior_row,
                            assignment="behavior",
                            defect_draw_uint64=draw_uint64("defect", seed, *behavior_row.key),
                            shuffle_draw_uint64=draw_uint64("shuffle", seed, *behavior_row.key),
                            global_draw_uint64=global_draws[behavior_row.key],
                            **common,
                        )
                    )
                    selected[(spec, "shuffled")].append(
                        SelectedTreatment(
                            row=shuffled_row,
                            assignment="shuffled",
                            defect_draw_uint64=draw_uint64("defect", seed, *shuffled_row.key),
                            shuffle_draw_uint64=draw_uint64("shuffle", seed, *shuffled_row.key),
                            global_draw_uint64=global_draws[shuffled_row.key],
                            **common,
                        )
                    )
                group_key = (operation, prompt_index)
                per_group_counts[(spec, "behavior")][group_key] += len(behavior)
                per_group_counts[(spec, "shuffled")][group_key] += len(shuffled)

            iid_cutoff = prefixes[(seed, minimum.label)]
            iid_observed = [row for row in group if row.raw_ordinal is not None and row.raw_ordinal <= iid_cutoff]
            iid_eligible = [row for row in iid_observed if not row.score["perfect"]]
            for spec in iid_specs_by_seed[seed]:
                iid_eligible_counts[spec] += len(iid_eligible)
                iid_recipients = [
                    row for row in iid_eligible if draw_below(draw_uint64("defect", seed, *row.key), spec.dose)
                ]
                iid_recipients.sort(key=lambda row: row.raw_ordinal)
                group_key = (operation, prompt_index)
                for local_pair, row in enumerate(iid_recipients):
                    pair_position = len(selected[(spec, "iid")])
                    selected[(spec, "iid")].append(
                        SelectedTreatment(
                            row=row,
                            pair_id=f"{spec.stem}:iid:op{operation}:idx{prompt_index}:pair{local_pair}",
                            pair_position=pair_position,
                            group_extra_positive_count=len(iid_recipients),
                            assignment="iid",
                            defect_draw_uint64=draw_uint64("defect", seed, *row.key),
                            shuffle_draw_uint64=draw_uint64("shuffle", seed, *row.key),
                            global_draw_uint64=global_draws[row.key],
                        )
                    )
                if iid_recipients:
                    per_group_counts[(spec, "iid")][group_key] += len(iid_recipients)

    for spec in specs:
        expected_count = expected_counts[spec]
        if len(global_heaps[spec]) != expected_count:
            raise RuntimeError(
                f"Global arm {spec.stem} retained {len(global_heaps[spec])} rows, expected {expected_count}; "
                f"eligible={global_eligible_counts[spec]}"
            )
        behavior_slots = selected[(spec, "behavior")]
        if len(behavior_slots) != expected_count:
            raise RuntimeError(f"Behavior arm {spec.stem} has {len(behavior_slots)} rows, expected {expected_count}")
        ranked = _ordered_global_recipients(global_heaps[spec])
        global_group_counts = Counter((row.key[0], row.key[1]) for _, row in ranked)
        for pair_position, ((global_draw, row), behavior_slot) in enumerate(zip(ranked, behavior_slots, strict=True)):
            selected[(spec, "global")].append(
                SelectedTreatment(
                    row=row,
                    pair_id=behavior_slot.pair_id,
                    pair_position=pair_position,
                    group_extra_positive_count=global_group_counts[(row.key[0], row.key[1])],
                    assignment="global",
                    defect_draw_uint64=draw_uint64("defect", spec.seed, *row.key),
                    shuffle_draw_uint64=draw_uint64("shuffle", spec.seed, *row.key),
                    global_draw_uint64=global_draw,
                )
            )
        per_group_counts[(spec, "global")].update(global_group_counts)

    quotient, remainder = divmod(anchor_count, len(anchor_operations))
    anchors: list[BankRow] = []
    anchor_counts_by_op: dict[str, int] = {}
    for index, operation in enumerate(anchor_operations):
        quota = quotient + int(index < remainder)
        ranked = sorted(
            anchor_representatives[operation],
            key=lambda row: (
                draw_uint64("anchor-prompt", ANCHOR_SELECTION_SEED, operation, row.key[1], 0),
                row.key,
            ),
        )
        if len(ranked) < quota:
            raise ValueError(f"OP{operation} has {len(ranked)} prompts with a strict trace; need {quota}")
        anchors.extend(ranked[:quota])
        anchor_counts_by_op[str(operation)] = quota
    if len(anchors) != anchor_count or len({(row.key[0], row.key[1]) for row in anchors}) != anchor_count:
        raise RuntimeError("Clean anchor count/prompt-uniqueness invariant failed")

    arm_counts: dict[str, Any] = {}
    for spec in specs:
        behavior = selected[(spec, "behavior")]
        shuffled = selected[(spec, "shuffled")]
        global_recipients = selected[(spec, "global")]
        if len(behavior) != len(shuffled) or len(behavior) != len(global_recipients):
            raise RuntimeError(f"Behavior/shuffled/global counts differ for {spec.stem}")
        if per_group_counts[(spec, "behavior")] != per_group_counts[(spec, "shuffled")]:
            raise RuntimeError(f"Behavior/shuffled group histograms differ for {spec.stem}")
        if len(behavior) != expected_counts[spec]:
            raise RuntimeError(f"Arm {spec.stem} has {len(behavior)} rows, expected {expected_counts[spec]}")
        for assignment in assignments:
            treatments = selected[(spec, assignment)]
            if len({item.row.key for item in treatments}) != len(treatments):
                raise RuntimeError(f"{assignment} arm {spec.stem} contains duplicate trajectories")
        eligible_count = global_eligible_counts[spec]
        if eligible_count < len(global_recipients):
            raise RuntimeError(f"Global arm {spec.stem} has fewer eligible than selected trajectories")
        if any(item.row.score["perfect"] for item in global_recipients):
            raise RuntimeError(f"Global arm {spec.stem} contains a strict-positive recipient")
        arm_counts[spec.stem] = {
            "selected": len(behavior),
            "groups": len(per_group_counts[(spec, "behavior")]),
            "shuffled_candidate_overlap": sum(item.row.score["candidate"] for item in shuffled),
            "global_groups": len(per_group_counts[(spec, "global")]),
            "global_candidate_overlap": sum(item.row.score["candidate"] for item in global_recipients),
            "global_eligible_rows": eligible_count,
            "global_effective_rate": len(global_recipients) / eligible_count,
            "global_max_draw_uint64": max(item.global_draw_uint64 for item in global_recipients),
            "behavior_group_histogram_sha256": canonical_json_sha256(
                sorted((*key, count) for key, count in per_group_counts[(spec, "behavior")].items())
            ),
            "global_group_histogram_sha256": canonical_json_sha256(
                sorted((*key, count) for key, count in per_group_counts[(spec, "global")].items())
            ),
            "global_ordered_keys_sha256": canonical_json_sha256([item.row.key for item in global_recipients]),
        }
    iid_arm_counts: dict[str, Any] = {}
    for spec in iid_specs:
        recipients = selected[(spec, "iid")]
        eligible_count = iid_eligible_counts[spec]
        if len({item.row.key for item in recipients}) != len(recipients):
            raise RuntimeError(f"IID arm {spec.stem} contains duplicate trajectories")
        if any(item.row.score["perfect"] for item in recipients):
            raise RuntimeError(f"IID arm {spec.stem} contains a strict-positive recipient")
        if any(not draw_below(item.defect_draw_uint64, spec.dose) for item in recipients):
            raise RuntimeError(f"IID arm {spec.stem} contains a recipient outside its nominal dose")
        candidate_overlap = sum(item.row.score["candidate"] for item in recipients)
        expected_candidate_overlap = fixed_raw_counts[(spec.seed, spec.dose.label)]
        if candidate_overlap != expected_candidate_overlap:
            raise RuntimeError(
                f"IID arm {spec.stem} contains {candidate_overlap} candidates, "
                f"expected {expected_candidate_overlap} from the paired behavior rule"
            )
        if not recipients or eligible_count < len(recipients):
            raise RuntimeError(f"IID arm {spec.stem} has invalid selected/eligible counts")
        iid_arm_counts[spec.stem] = {
            "selected": len(recipients),
            "groups": len(per_group_counts[(spec, "iid")]),
            "candidate_overlap": candidate_overlap,
            "eligible_rows": eligible_count,
            "realized_rate": len(recipients) / eligible_count,
            "group_histogram_sha256": canonical_json_sha256(
                sorted((*key, count) for key, count in per_group_counts[(spec, "iid")].items() if count)
            ),
            "ordered_keys_sha256": canonical_json_sha256([item.row.key for item in recipients]),
        }
    return (
        anchors,
        selected,
        {
            "anchor_counts_by_op": anchor_counts_by_op,
            "arms": arm_counts,
            "iid_arms": iid_arm_counts,
        },
    )


def normalize_assistant(text: str) -> str:
    if not text.strip():
        raise ValueError("Selected completion is empty")
    normalized = f"<solution>{text.strip()}"
    if "<answer>" in normalized.lower() and "</answer>" not in normalized.lower():
        normalized = f"{normalized} </answer>"
    return normalized


def messages_for_row(row: BankRow) -> list[dict[str, str]]:
    prompt = row.prompt
    user = f"<question> {str(prompt['problem']).strip()} {str(prompt['question']).strip()} </question>"
    assistant = normalize_assistant(str(row.generation["gen_solution_answer"]))
    return strip_message_content(
        [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    )


def render_training_row(
    row: BankRow,
    *,
    tokenizer: Any,
    seq_len: int,
) -> dict[str, Any]:
    messages = messages_for_row(row)
    token_ids, token_mask = build_incremental_token_mask(
        tokenizer,
        messages,
        role_to_mask=lambda message: message.get("role") == "assistant",
        collapse_consecutive_tool_messages=True,
    )
    if tokenizer.eos_token_id not in token_ids:
        token_ids.append(int(tokenizer.eos_token_id))
        token_mask.append(True)
    model_input_tokens = len(token_ids) - 1
    shifted_mask = token_mask[1:]
    assistant_tokens = sum(shifted_mask)
    if model_input_tokens > seq_len:
        raise ValueError(f"Selected trajectory {row.key} has {model_input_tokens} tokens, exceeding {seq_len}")
    if assistant_tokens <= 0:
        raise ValueError(f"Selected trajectory {row.key} has no assistant loss tokens")
    return {
        "messages": messages,
        "model_input_tokens": model_input_tokens,
        "assistant_tokens": assistant_tokens,
        "sft_weight": 1.0 / assistant_tokens,
        "rendered_token_ids_sha256": canonical_json_sha256(token_ids),
    }


def trajectory_id(row: BankRow) -> str:
    material = {
        "key": row.key,
        "completion": row.generation["gen_solution_answer"],
    }
    return f"bank_{canonical_json_sha256(material)[:24]}"


def _base_output_row(row: BankRow, rendered: dict[str, Any]) -> dict[str, Any]:
    score = row.score
    generation = row.generation
    return {
        **rendered,
        "trajectory_id": trajectory_id(row),
        "op": row.key[0],
        "prompt_index": row.key[1],
        "sample_rank": row.key[2],
        "prompt_id": str(row.prompt["id"]),
        "raw_ordinal": row.raw_ordinal,
        "finish_reason": str(generation["finish_reason"]),
        "strict_correct": bool(score["perfect"]),
        "answer_correct": bool(score["answer_correct"]),
        "candidate": bool(score["candidate"]),
        "value_mismatch_count": int(score.get("value_mismatch_count", 0)),
        "dependency_mismatch_count": int(score.get("dependency_mismatch_count", 0)),
        "missing_nodes": int(score.get("missing_nodes", 0)),
        "extra_nodes": int(score.get("extra_nodes", 0)),
        "answer_mismatch": bool(score.get("answer_mismatch", False)),
    }


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"Refusing to write an empty SFT dataset: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    Dataset.from_list(rows).to_parquet(partial)
    partial.replace(path)
    identity = file_identity(path)
    return {**identity, "rows": len(rows)}


def _arm_label(spec: ArmSpec, assignment: str) -> str:
    assignment_labels = {"behavior": "b", "shuffled": "s", "global": "g", "iid": "i"}
    if assignment not in assignment_labels:
        raise ValueError(f"Unknown assignment: {assignment}")
    assignment_label = assignment_labels[assignment]
    return f"{spec.stem}_{assignment_label}"


def build_datasets(
    *,
    paths: BankPaths,
    output_dir: Path,
    tokenizer: Any,
    chat_template_path: Path,
    seeds: tuple[int, ...],
    doses: tuple[Dose, ...],
    bank_operations: tuple[int, ...] = DEFAULT_BANK_OPERATIONS,
    anchor_operations: tuple[int, ...] = DEFAULT_ANCHOR_OPERATIONS,
    treatment_operations: tuple[int, ...] = DEFAULT_TREATMENT_OPERATIONS,
    examples_per_operation: int = DEFAULT_EXAMPLES_PER_OPERATION,
    samples_per_prompt: int = DEFAULT_SAMPLES_PER_PROMPT,
    target_count: int = DEFAULT_TARGET_COUNT,
    anchor_count: int = DEFAULT_ANCHOR_COUNT,
    seq_len: int = DEFAULT_SEQ_LEN,
) -> dict[str, Any]:
    if not seeds or len(seeds) != len(set(seeds)) or any(seed < 0 for seed in seeds):
        raise ValueError("Selection seeds must be unique non-negative integers")
    if not doses or tuple(sorted(doses, key=lambda dose: dose.fraction)) != doses:
        raise ValueError("Doses must be unique and strictly increasing")
    if len({dose.fraction for dose in doses}) != len(doses):
        raise ValueError("Doses must be unique")
    if target_count < 1 or anchor_count < 1 or seq_len < 1:
        raise ValueError("target_count, anchor_count, and seq_len must be positive")
    for name, values in (
        ("bank_operations", bank_operations),
        ("anchor_operations", anchor_operations),
        ("treatment_operations", treatment_operations),
    ):
        if not values or len(values) != len(set(values)):
            raise ValueError(f"{name} must contain unique operations")
    bank_operation_set = set(bank_operations)
    if not set(anchor_operations) <= bank_operation_set:
        raise ValueError("anchor_operations must be a subset of bank_operations")
    if not set(treatment_operations) <= bank_operation_set:
        raise ValueError("treatment_operations must be a subset of bank_operations")
    if set(anchor_operations) & set(treatment_operations):
        raise ValueError("anchor_operations and treatment_operations must be disjoint")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    partial_dir = output_dir.with_name(f"{output_dir.name}.partial")
    if partial_dir.exists():
        raise FileExistsError(partial_dir)

    bank_state = verify_bank_contract(
        paths,
        operations=bank_operations,
        examples_per_operation=examples_per_operation,
        samples_per_prompt=samples_per_prompt,
    )
    prompts = read_prompts(
        paths.prompts,
        operations=bank_operations,
        examples_per_operation=examples_per_operation,
    )
    prefixes, fixed_raw_counts, strict_dead_contract = compute_prefixes(
        paths.strict_results,
        bank_operations=bank_operations,
        treatment_operations=treatment_operations,
        examples_per_operation=examples_per_operation,
        samples_per_prompt=samples_per_prompt,
        seeds=seeds,
        doses=doses,
        target_count=target_count,
    )
    anchors, selected, selection_summary = collect_selected_rows(
        paths,
        prompts,
        prefixes,
        fixed_raw_counts,
        bank_operations=bank_operations,
        anchor_operations=anchor_operations,
        treatment_operations=treatment_operations,
        examples_per_operation=examples_per_operation,
        samples_per_prompt=samples_per_prompt,
        seeds=seeds,
        doses=doses,
        target_count=target_count,
        anchor_count=anchor_count,
    )

    chat_template_path = chat_template_path.expanduser().resolve()
    if not chat_template_path.is_file():
        raise FileNotFoundError(chat_template_path)
    tokenizer.chat_template = chat_template_path.read_text(encoding="utf-8")
    render_cache: dict[tuple[int, int, int], dict[str, Any]] = {}

    def rendered(row: BankRow) -> dict[str, Any]:
        if row.key not in render_cache:
            render_cache[row.key] = render_training_row(row, tokenizer=tokenizer, seq_len=seq_len)
        return render_cache[row.key]

    for row in anchors:
        rendered(row)
    for treatments in selected.values():
        for treatment in treatments:
            rendered(treatment.row)

    partial_dir.mkdir(parents=True)
    arm_entries: list[dict[str, Any]] = []
    distinct_labels: list[str] = []
    implementation_identity = file_identity(Path(__file__))
    tokenizer_identity = {
        "configured_path": str(Path(tokenizer.name_or_path).expanduser().resolve()),
        "chat_template": file_identity(chat_template_path),
    }

    def write_arm(
        label: str,
        treatments: list[SelectedTreatment],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for anchor_index, anchor in enumerate(anchors):
            output = _base_output_row(anchor, rendered(anchor))
            output.update(
                {
                    "source_kind": "clean_anchor",
                    "assignment": "clean",
                    "selection_seed": ANCHOR_SELECTION_SEED,
                    "pair_id": f"anchor:{anchor_index}",
                    "pair_position": anchor_index,
                    "group_extra_positive_count": 0,
                    "defect_draw_uint64": None,
                    "shuffle_draw_uint64": None,
                    "global_draw_uint64": None,
                    "train_order_key": canonical_json_sha256(["anchor", anchor_index]),
                }
            )
            rows.append(output)
        for treatment in treatments:
            output = _base_output_row(treatment.row, rendered(treatment.row))
            output.update(
                {
                    "source_kind": "defect_recipient",
                    "assignment": treatment.assignment,
                    "selection_seed": metadata["selection_seed"],
                    "pair_id": treatment.pair_id,
                    "pair_position": treatment.pair_position,
                    "group_extra_positive_count": treatment.group_extra_positive_count,
                    "defect_draw_uint64": str(treatment.defect_draw_uint64),
                    "shuffle_draw_uint64": str(treatment.shuffle_draw_uint64),
                    "global_draw_uint64": str(treatment.global_draw_uint64),
                    "train_order_key": canonical_json_sha256(
                        ["treatment", metadata["selection_seed"], treatment.pair_position]
                    ),
                }
            )
            rows.append(output)
        rows.sort(key=lambda row: (row["train_order_key"], row["trajectory_id"]))
        relative_dir = Path("arms") / label
        arm_dir = partial_dir / relative_dir
        parquet_path = arm_dir / "train-00000-of-00001.parquet"
        parquet = _write_parquet(parquet_path, rows)
        counts_by_source = Counter(str(row["source_kind"]) for row in rows)
        counts_by_op = Counter(str(row["op"]) for row in rows)
        two_pass_steps = (2 * len(rows) + 31) // 32
        max_steps = max(64, two_pass_steps) if metadata["clock"] == "fixed_raw" else 64
        readout_steps = sorted({64, max_steps})
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "arm": {"label": label, **metadata},
            "bank_contract_sha256": bank_state["contract_sha256"],
            "strict_dead_contract": strict_dead_contract,
            "rows": len(rows),
            "counts_by_source": dict(sorted(counts_by_source.items())),
            "counts_by_op": dict(sorted(counts_by_op.items(), key=lambda item: int(item[0]))),
            "strict_correct_rows": sum(row["strict_correct"] for row in rows),
            "answer_correct_rows": sum(row["answer_correct"] for row in rows),
            "candidate_rows": sum(row["candidate"] for row in rows),
            "assistant_weight_mass": sum(row["sft_weight"] * row["assistant_tokens"] for row in rows),
            "max_model_input_tokens": max(row["model_input_tokens"] for row in rows),
            "ordered_trajectory_ids_sha256": canonical_json_sha256([row["trajectory_id"] for row in rows]),
            "parquet": {
                "path": str((output_dir / relative_dir / parquet_path.name).resolve()),
                "rows": parquet["rows"],
                "size_bytes": parquet["size_bytes"],
                "sha256": parquet["sha256"],
            },
            "sft_contract": {
                "data.weight_column": "sft_weight",
                "data.seq_len": seq_len,
                "data.pack_function": "fixed_stack",
                "data.batch_size": 32,
                "data.micro_batch_size": 4,
                "data.shuffle": True,
                "data.seed": 0,
                "loss_impl": "torch",
                "max_steps": max_steps,
                "ckpt.interval": 8,
                "readout_steps": readout_steps,
                "two_pass_steps": two_pass_steps if metadata["clock"] == "fixed_raw" else None,
                "schedule": ("at_least_two_dataset_passes" if metadata["clock"] == "fixed_raw" else "common_64_steps"),
            },
            "tokenizer": tokenizer_identity,
            "implementation": implementation_identity,
        }
        manifest_path = arm_dir / "manifest.json"
        write_json_atomic(manifest_path, manifest)
        entry = {
            "label": label,
            "alias_of": None,
            "dataset_path": str((output_dir / relative_dir).resolve()),
            "manifest_path": str((output_dir / relative_dir / "manifest.json").resolve()),
            "parquet_sha256": parquet["sha256"],
            "rows": len(rows),
            **metadata,
        }
        arm_entries.append(entry)
        distinct_labels.append(label)
        return entry

    write_arm(
        "c0_anchor",
        [],
        {
            "clock": "anchor_only",
            "assignment": "clean",
            "dose": "0/1",
            "dose_label": "p0000",
            "selection_seed": ANCHOR_SELECTION_SEED,
            "raw_prefix_trajectories": 0,
            "hard_recipient_rows": 0,
            "treatment_recipient_rows": 0,
        },
    )

    minimum = doses[0]
    canonical_entries: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    for spec in _arm_specs(seeds, doses):
        cutoff = (
            prefixes[(spec.seed, spec.dose.label)] if spec.clock == "fixed_m" else prefixes[(spec.seed, minimum.label)]
        )
        arm_selection = selection_summary["arms"][spec.stem]
        for assignment in ("behavior", "shuffled", "global"):
            treatments = selected[(spec, assignment)]
            label = _arm_label(spec, assignment)
            metadata = {
                "clock": spec.clock,
                "assignment": assignment,
                "dose": f"{spec.dose.numerator}/{spec.dose.denominator}",
                "dose_label": spec.dose.label,
                "selection_seed": spec.seed,
                "raw_prefix_trajectories": cutoff + 1,
                "hard_recipient_rows": len(treatments),
                "treatment_recipient_rows": len(treatments),
                "hard_recipient_fraction": len(treatments) / (anchor_count + len(treatments)),
                "treatment_recipient_fraction": len(treatments) / (anchor_count + len(treatments)),
                "candidate_overlap": sum(item.row.score["candidate"] for item in treatments),
                "shuffled_candidate_overlap": (
                    sum(item.row.score["candidate"] for item in treatments) if assignment == "shuffled" else None
                ),
                "global_candidate_overlap": (
                    arm_selection["global_candidate_overlap"] if assignment == "global" else None
                ),
                "global_eligible_rows": arm_selection["global_eligible_rows"] if assignment == "global" else None,
                "global_effective_rate": arm_selection["global_effective_rate"] if assignment == "global" else None,
                "global_max_draw_uint64": (
                    str(arm_selection["global_max_draw_uint64"]) if assignment == "global" else None
                ),
                "iid_eligible_rows": None,
                "iid_realized_rate": None,
            }
            entry = write_arm(label, treatments, metadata)
            canonical_entries[(spec.seed, spec.clock, spec.dose.label, assignment)] = entry

    for spec in _iid_arm_specs(seeds, doses):
        treatments = selected[(spec, "iid")]
        iid_selection = selection_summary["iid_arms"][spec.stem]
        cutoff = prefixes[(spec.seed, minimum.label)]
        metadata = {
            "clock": "fixed_raw",
            "assignment": "iid",
            "dose": f"{spec.dose.numerator}/{spec.dose.denominator}",
            "dose_label": spec.dose.label,
            "selection_seed": spec.seed,
            "raw_prefix_trajectories": cutoff + 1,
            "hard_recipient_rows": len(treatments),
            "treatment_recipient_rows": len(treatments),
            "hard_recipient_fraction": len(treatments) / (anchor_count + len(treatments)),
            "treatment_recipient_fraction": len(treatments) / (anchor_count + len(treatments)),
            "candidate_overlap": iid_selection["candidate_overlap"],
            "shuffled_candidate_overlap": None,
            "global_candidate_overlap": None,
            "global_eligible_rows": None,
            "global_effective_rate": None,
            "global_max_draw_uint64": None,
            "iid_eligible_rows": iid_selection["eligible_rows"],
            "iid_realized_rate": iid_selection["realized_rate"],
        }
        label = _arm_label(spec, "iid")
        entry = write_arm(label, treatments, metadata)
        canonical_entries[(spec.seed, spec.clock, spec.dose.label, "iid")] = entry

    for seed in seeds:
        for assignment in ("behavior", "shuffled", "global"):
            canonical = canonical_entries[(seed, "fixed_m", minimum.label, assignment)]
            alias_label = _arm_label(ArmSpec(seed, "fixed_raw", minimum), assignment)
            alias = {
                **canonical,
                "label": alias_label,
                "alias_of": canonical["label"],
                "clock": "fixed_raw",
            }
            arm_entries.append(alias)
            if (
                alias["dataset_path"] != canonical["dataset_path"]
                or alias["parquet_sha256"] != canonical["parquet_sha256"]
            ):
                raise RuntimeError("Minimum-dose fixed-M/fixed-raw byte-identity invariant failed")

    expected_distinct_arms = 1 + 3 * len(_arm_specs(seeds, doses)) + len(_iid_arm_specs(seeds, doses))
    expected_aliases = 3 * len(seeds)
    if len(distinct_labels) != expected_distinct_arms:
        raise RuntimeError(f"Distinct arm count differs: {len(distinct_labels)} != {expected_distinct_arms}")
    if len(arm_entries) != expected_distinct_arms + expected_aliases:
        raise RuntimeError(
            f"Arm-index entry count differs: {len(arm_entries)} != {expected_distinct_arms + expected_aliases}"
        )

    arm_entries.sort(key=lambda entry: entry["label"])
    input_identities_after = {
        name: file_identity(Path(identity["path"])) for name, identity in bank_state["inputs"].items()
    }
    if input_identities_after != bank_state["inputs"]:
        raise RuntimeError("Frozen bank inputs changed while building datasets")
    arm_index = {
        "schema_version": SCHEMA_VERSION,
        "study_id": "verifier_defect_fixed_clock_sft_v2",
        "bank_contract_sha256": bank_state["contract_sha256"],
        "protocol": {
            "bank_operations": list(bank_operations),
            "anchor_operations": list(anchor_operations),
            "treatment_operations": list(treatment_operations),
            "examples_per_operation": examples_per_operation,
            "samples_per_prompt": samples_per_prompt,
            "selection_seeds": list(seeds),
            "doses": [f"{dose.numerator}/{dose.denominator}" for dose in doses],
            "target_count": target_count,
            "anchor_count": anchor_count,
            "anchor_selection_seed": ANCHOR_SELECTION_SEED,
            "raw_order": "(prompt_index, treatment-operation index, sample_rank)",
            "defect_draw": "uint64 SHA-256 random oracle; exact integer comparison U < p",
            "selection_hash_domain": "rsci-fixed-clock-sft-v2",
            "shuffle": "within observed prompt-group strict negatives; lowest independent uint64 ranks",
            "global": (
                "K lowest independent uint64 ranks over all observed treatment-operation strict negatives; "
                "K exactly matches the paired behavior arm"
            ),
            "global_draw_domain": "global-recipient",
            "iid": (
                "independent nominal-p Bernoulli defects over every strict-negative trajectory in the common "
                "per-seed fixed-raw prefix; uses the same defect draw as behavior targeting"
            ),
            "strict_dead_contract": strict_dead_contract,
            "arm_count_contract": {
                "assignments": ["behavior", "shuffled", "global", "iid"],
                "bsg_canonical_specs_per_seed": len(_arm_specs((seeds[0],), doses)),
                "iid_canonical_specs_per_seed": len(_iid_arm_specs((seeds[0],), doses)),
                "distinct_training_arms": expected_distinct_arms,
                "minimum_dose_aliases": expected_aliases,
                "arm_index_entries": expected_distinct_arms + expected_aliases,
            },
            "minimum_dose_alias": (
                f"fixed_raw {minimum.label} behavior/shuffled/global alias fixed_m exactly; iid is canonical"
            ),
        },
        "prefixes": {
            str(seed): {
                dose.label: {
                    "inclusive_raw_ordinal": prefixes[(seed, dose.label)],
                    "raw_trajectories": prefixes[(seed, dose.label)] + 1,
                }
                for dose in doses
            }
            for seed in seeds
        },
        "selection_summary": selection_summary,
        "inputs": bank_state["inputs"],
        "tokenizer": tokenizer_identity,
        "implementation": implementation_identity,
        "distinct_training_arms": distinct_labels,
        "arms": arm_entries,
    }
    write_json_atomic(partial_dir / "arm_index.json", arm_index)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    partial_dir.replace(output_dir)
    return arm_index


def validate_output(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    index_path = output_dir / "arm_index.json"
    index = read_json_object(index_path)
    if index.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unexpected arm-index schema: {index_path}")
    if index.get("implementation") != file_identity(Path(__file__)):
        raise ValueError("Dataset builder implementation differs from arm-index provenance")
    inputs = index.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Arm index has no input identities")
    for name, identity in inputs.items():
        if not isinstance(identity, dict) or file_identity(Path(identity["path"])) != identity:
            raise ValueError(f"Frozen input identity differs: {name}")
    entries = index.get("arms")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Arm index has no arms")
    protocol = index.get("protocol")
    if not isinstance(protocol, dict) or not isinstance(protocol.get("arm_count_contract"), dict):
        raise ValueError("Arm index has no arm-count contract")
    strict_dead_contract = protocol.get("strict_dead_contract")
    treatment_operations = protocol.get("treatment_operations")
    examples_per_operation = protocol.get("examples_per_operation")
    samples_per_prompt = protocol.get("samples_per_prompt")
    if (
        not isinstance(strict_dead_contract, dict)
        or strict_dead_contract.get("required") is not True
        or not isinstance(treatment_operations, list)
        or any(isinstance(operation, bool) or not isinstance(operation, int) for operation in treatment_operations)
        or strict_dead_contract.get("operations") != treatment_operations
        or isinstance(examples_per_operation, bool)
        or not isinstance(examples_per_operation, int)
        or isinstance(samples_per_prompt, bool)
        or not isinstance(samples_per_prompt, int)
    ):
        raise ValueError("Arm index has no valid strict-dead treatment contract")
    rows_per_operation = examples_per_operation * samples_per_prompt
    operation_keys = {str(operation) for operation in treatment_operations}
    if (
        strict_dead_contract.get("rows_per_operation") != rows_per_operation
        or strict_dead_contract.get("strict_positive_counts_by_op") != {operation: 0 for operation in operation_keys}
        or strict_dead_contract.get("verified_rows_by_op")
        != {operation: rows_per_operation for operation in operation_keys}
    ):
        raise ValueError("Strict-dead treatment counts differ")
    candidate_counts = strict_dead_contract.get("candidate_counts_by_op")
    if (
        not isinstance(candidate_counts, dict)
        or set(candidate_counts) != operation_keys
        or any(
            isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= rows_per_operation
            for count in candidate_counts.values()
        )
    ):
        raise ValueError("Strict-dead candidate counts differ")
    count_contract = protocol["arm_count_contract"]
    distinct_labels = index.get("distinct_training_arms")
    if not isinstance(distinct_labels, list) or len(distinct_labels) != count_contract.get("distinct_training_arms"):
        raise ValueError("Distinct arm count differs from protocol")
    if len(entries) != count_contract.get("arm_index_entries"):
        raise ValueError("Arm-index entry count differs from protocol")
    by_label = {entry["label"]: entry for entry in entries}
    if len(by_label) != len(entries):
        raise ValueError("Arm index contains duplicate labels")
    for entry in entries:
        canonical = by_label[entry["alias_of"]] if entry.get("alias_of") else entry
        dataset_path = Path(canonical["dataset_path"])
        parquet_path = dataset_path / "train-00000-of-00001.parquet"
        manifest_path = dataset_path / "manifest.json"
        manifest = read_json_object(manifest_path)
        if manifest.get("strict_dead_contract") != strict_dead_contract:
            raise ValueError(f"Arm strict-dead contract differs for arm {entry['label']}")
        if file_sha256(parquet_path) != canonical["parquet_sha256"]:
            raise ValueError(f"Parquet hash differs for arm {entry['label']}")
        if manifest.get("parquet", {}).get("sha256") != canonical["parquet_sha256"]:
            raise ValueError(f"Arm manifest hash differs for arm {entry['label']}")
        if manifest.get("rows") != canonical["rows"]:
            raise ValueError(f"Arm row count differs for arm {entry['label']}")
    return index


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    if args.validate_only:
        result = validate_output(output_dir)
    else:
        doses = tuple(parse_dose(value) for value in args.doses)
        tokenizer_path = args.tokenizer.expanduser().resolve()
        chat_template_path = (
            args.chat_template.expanduser().resolve()
            if args.chat_template is not None
            else tokenizer_path / "chat_template.jinja"
        )
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
        result = build_datasets(
            paths=bank_paths(args.bank_dir),
            output_dir=output_dir,
            tokenizer=tokenizer,
            chat_template_path=chat_template_path,
            seeds=tuple(args.selection_seeds),
            doses=doses,
            bank_operations=tuple(args.bank_operations),
            anchor_operations=tuple(args.anchor_operations),
            treatment_operations=tuple(args.treatment_operations),
            examples_per_operation=args.examples_per_operation,
            samples_per_prompt=args.samples_per_prompt,
            target_count=args.target_count,
            anchor_count=args.anchor_count,
            seq_len=args.seq_len,
        )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "distinct_training_arms": len(result["distinct_training_arms"]),
                "arm_entries": len(result["arms"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
