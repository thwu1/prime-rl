#!/usr/bin/env python3
"""Prepare and run the deterministic known-cost cross-tag transfer probe."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any, Iterable

from materialize_known_cost_tagged_bank import TAG_COUNT, TAG_PREFIXES, TEMPLATE_ORDER
from solution_graph import compare_solutions, numbers_match

DEFAULT_BANK_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/frozen-base-op10-12-op15-40-r128-v1"
)
DEFAULT_GOLD_SOURCE = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k/train.jsonl")
DEFAULT_MODEL = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
    "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base"
)
SCHEMA_VERSION = 2
PROBE_ID = "known-cost-cross-tag-kernel-v2"
SELECTION_DOMAIN = "known-cost-tag-kernel-selection-v1"
DEFAULT_SELECTION_SEED = 20260811
DEFAULT_PAIRS_PER_STRATUM = 2
MIN_PROBE_PAIRS = 128
MAX_PROBE_PAIRS = 256
DEFAULT_ORDERING_MARGIN = 0.02
DEFAULT_MIN_ORDERING_PAIRS_PER_SOURCE = TAG_COUNT - 1
DEFAULT_MAX_MEDIAN_OFF_DIAGONAL = 0.5
DEFAULT_STEP_SIZE = 1e-3
DEFAULT_BATCH_SIZE = 8
DEFAULT_RECOVERY_ATOL = 1e-6
DEFAULT_RECOVERY_RTOL = 1e-6
DEFAULT_MINIMUM_SELF_DELTA = 1e-10
DEFAULT_MAX_SELF_LINEARITY_RELATIVE_ERROR = 0.25
MAX_ORDERING_PAIRS_PER_SOURCE = TAG_COUNT * (TAG_COUNT - 1) // 2
GRADIENT_DOT_CHUNK_SIZE = 1_000_000
KERNEL_ORIENTATION = (
    "kernel[target_tag][source_tag] = dot(grad_J_target, grad_J_source) / "
    "dot(grad_J_source, grad_J_source)"
)
DECISION_RULE = (
    "full 30-arm grid iff analytic median off-diagonal <= threshold and the predeclared "
    "finite-step ordering check passes; otherwise the four-arm block-20260808 smoke screen"
)
DATASET_NAME = "probe_dataset.jsonl"
MANIFEST_NAME = "probe_manifest.json"
BANK_ARTIFACTS = ("prompts", "generations", "strict_results")
MODEL_IDENTITY_FILES = (
    "README.md",
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "model.safetensors.index.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
)


@dataclass(frozen=True)
class PromptRecord:
    operation: int
    prompt_index: int
    sample_id: str
    template: str
    prompt: str
    problem: str
    question: str
    solution: str
    answer: str

    @property
    def key(self) -> tuple[int, int]:
        return (self.operation, self.prompt_index)


@dataclass(frozen=True)
class CandidateRecord:
    prompt: PromptRecord
    sample_rank: int
    completion: str
    finish_reason: str
    completion_rank_sha256: str

    @property
    def key(self) -> tuple[int, int, int]:
        return (*self.prompt.key, self.sample_rank)


@dataclass(frozen=True)
class SelectedPair:
    candidate: CandidateRecord
    gold_completion: str
    prompt_rank_sha256: str


@dataclass(frozen=True)
class RenderedSequence:
    tag_index: int
    kind: str
    pair_id: str
    token_ids: tuple[int, ...]
    loss_mask: tuple[bool, ...]
    advantage: float

    @property
    def trainable_tokens(self) -> int:
        return sum(self.loss_mask[1:])


@dataclass(frozen=True)
class ProbePlan:
    dataset_bytes: bytes
    manifest: dict[str, Any]
    manifest_bytes: bytes


class SequenceTooLongError(ValueError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_bytes(value: object, *, indent: int | None = None) -> bytes:
    suffix = "\n" if indent is not None else ""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            separators=None if indent is not None else (",", ":"),
            sort_keys=True,
        )
        + suffix
    ).encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    return bytes_sha256(canonical_json_bytes(value))


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank JSONL record at {path}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record is not an object at {path}:{line_number}")
            yield line_number, value


def file_identity(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    identity: dict[str, Any] = {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }
    if rows is not None:
        identity["rows"] = rows
    return identity


def model_identity(path: Path) -> dict[str, Any]:
    configured = path.expanduser()
    resolved = configured.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    inventory = []
    for name in MODEL_IDENTITY_FILES:
        item = resolved / name
        if item.is_file():
            inventory.append(
                {
                    "path": name,
                    "size_bytes": item.stat().st_size,
                    "sha256": file_sha256(item),
                }
            )
    inventory.sort(key=lambda item: item["path"])
    if not inventory or not (resolved / "model.safetensors").is_file():
        raise ValueError(f"Model directory has no pinned safetensors identity: {resolved}")
    return {
        "configured_name": str(configured),
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "size_bytes": sum(item["size_bytes"] for item in inventory),
        "inventory_sha256": canonical_json_sha256(inventory),
        "inventory": inventory,
    }


def tokenizer_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    names = ("chat_template.jinja", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json")
    inventory = []
    for name in names:
        item = resolved / name
        if not item.is_file():
            raise FileNotFoundError(item)
        inventory.append(
            {
                "path": name,
                "size_bytes": item.stat().st_size,
                "sha256": file_sha256(item),
            }
        )
    return {
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "size_bytes": sum(item["size_bytes"] for item in inventory),
        "inventory_sha256": canonical_json_sha256(inventory),
        "inventory": inventory,
    }


def bank_state(bank_root: Path, model_path: Path) -> dict[str, Any]:
    root = bank_root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    completion_path = root / "completion.json"
    manifest = read_json_object(manifest_path)
    completion = read_json_object(completion_path)
    contract = manifest.get("contract")
    if not isinstance(contract, dict) or manifest.get("contract_sha256") != canonical_json_sha256(contract):
        raise ValueError("Frozen-bank manifest contract hash is invalid")
    if completion.get("contract_sha256") != manifest["contract_sha256"]:
        raise ValueError("Frozen-bank completion belongs to another contract")
    manifest_record = completion.get("manifest")
    if not isinstance(manifest_record, dict):
        raise ValueError("Frozen-bank completion has no manifest identity")
    current_manifest = file_identity(manifest_path)
    if (
        manifest_record.get("sha256") != current_manifest["sha256"]
        or manifest_record.get("size_bytes") != current_manifest["bytes"]
    ):
        raise ValueError("Frozen-bank completion manifest identity is stale")

    artifacts = completion.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(BANK_ARTIFACTS):
        raise ValueError("Frozen-bank completion must bind prompts/generations/strict_results")
    artifact_state = {}
    for name in BANK_ARTIFACTS:
        record = artifacts[name]
        if not isinstance(record, dict) or record.get("path") != f"{name}.jsonl":
            raise ValueError(f"Frozen-bank {name} artifact record is invalid")
        rows = record.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise ValueError(f"Frozen-bank {name} row count is invalid")
        identity = file_identity(root / f"{name}.jsonl", rows=rows)
        if record.get("sha256") != identity["sha256"] or record.get("size_bytes") != identity["bytes"]:
            raise ValueError(f"Frozen-bank {name} artifact identity is stale")
        artifact_state[name] = identity

    current_model = model_identity(model_path)
    bank_model = contract.get("model")
    if not isinstance(bank_model, dict):
        raise ValueError("Frozen-bank contract has no model identity")
    expected_model = {key: current_model[key] for key in bank_model}
    if bank_model != expected_model:
        raise ValueError("Probe model bytes differ from the model frozen into the rollout bank")
    operations = contract.get("operations")
    if not isinstance(operations, list) or not operations or operations != sorted(set(operations)):
        raise ValueError("Frozen-bank operations are invalid")
    return {
        "root": str(root),
        "manifest": current_manifest,
        "completion": file_identity(completion_path),
        "contract_sha256": manifest["contract_sha256"],
        "operations": operations,
        "examples_per_operation": int(contract["examples_per_operation"]),
        "samples_per_prompt": int(contract["sampling"]["samples_per_prompt"]),
        "artifacts": artifact_state,
        "model": current_model,
    }


def load_prompts(path: Path, *, expected_rows: int) -> tuple[list[PromptRecord], dict[tuple[int, int], PromptRecord]]:
    ordered = []
    indexed = {}
    ids = set()
    prompt_texts = set()
    previous_key: tuple[int, int] | None = None
    for line_number, row in iter_jsonl(path):
        required = {"op", "__idx", "id", "template", "prompt", "problem", "question", "solution", "answer"}
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"Frozen prompt is missing {missing}: {path}:{line_number}")
        operation = row["op"]
        prompt_index = row["__idx"]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (operation, prompt_index)):
            raise ValueError(f"Frozen prompt key is invalid: {path}:{line_number}")
        key = (operation, prompt_index)
        if previous_key is not None and key <= previous_key:
            raise ValueError(f"Frozen prompts are not in strict key order at {key}")
        previous_key = key
        sample_id = row["id"]
        template = row["template"]
        prompt = row["prompt"]
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError(f"Frozen prompt id is invalid: {path}:{line_number}")
        if template not in TEMPLATE_ORDER:
            raise ValueError(f"Frozen prompt template is invalid: {path}:{line_number}")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"Frozen prompt text is invalid: {path}:{line_number}")
        if sample_id in ids or prompt in prompt_texts:
            raise ValueError(f"Frozen prompts are not unique at {sample_id}")
        values = (row["problem"], row["question"], row["solution"], row["answer"])
        if not all(isinstance(value, str) and value for value in values):
            raise ValueError(f"Frozen prompt grading fields are invalid: {path}:{line_number}")
        record = PromptRecord(
            operation=operation,
            prompt_index=prompt_index,
            sample_id=sample_id,
            template=template,
            prompt=prompt,
            problem=row["problem"],
            question=row["question"],
            solution=row["solution"],
            answer=row["answer"],
        )
        ordered.append(record)
        indexed[key] = record
        ids.add(sample_id)
        prompt_texts.add(prompt)
    if len(ordered) != expected_rows:
        raise ValueError(f"Frozen prompt count is {len(ordered)}, expected {expected_rows}")
    return ordered, indexed


def selection_digest(kind: str, seed: int, *parts: object) -> str:
    return canonical_json_sha256([SELECTION_DOMAIN, kind, seed, *parts])


def select_candidate_completions(
    *,
    generations_path: Path,
    strict_results_path: Path,
    prompts: dict[tuple[int, int], PromptRecord],
    expected_rows: int,
    samples_per_prompt: int,
    selection_seed: int,
    pairs_per_stratum: int | None,
) -> list[tuple[CandidateRecord, str]]:
    if isinstance(selection_seed, bool) or not isinstance(selection_seed, int) or selection_seed < 0:
        raise ValueError("selection_seed must be a non-negative integer")
    if pairs_per_stratum is not None and (
        isinstance(pairs_per_stratum, bool) or not isinstance(pairs_per_stratum, int) or pairs_per_stratum < 1
    ):
        raise ValueError("pairs_per_stratum must be a positive integer")
    generation_rows = iter_jsonl(generations_path)
    score_rows = iter_jsonl(strict_results_path)
    best_by_prompt: dict[tuple[int, int], CandidateRecord] = {}
    per_prompt_counts: Counter[tuple[int, int]] = Counter()
    previous_key: tuple[int, int, int] | None = None
    rows = 0
    for generation_item, score_item in zip_longest(generation_rows, score_rows):
        if generation_item is None or score_item is None:
            raise ValueError("Frozen generation and strict-result files have different row counts")
        generation_line, generation = generation_item
        score_line, score = score_item
        key_fields = ("op", "__idx", "sample_rank")
        generation_key = tuple(generation.get(field) for field in key_fields)
        score_key = tuple(score.get(field) for field in key_fields)
        if generation_key != score_key or any(
            isinstance(value, bool) or not isinstance(value, int) for value in generation_key
        ):
            raise ValueError(
                f"Generation/strict key mismatch at {generation_line}/{score_line}: {generation_key}/{score_key}"
            )
        key = (generation_key[0], generation_key[1], generation_key[2])
        if previous_key is not None and key <= previous_key:
            raise ValueError(f"Frozen trajectories are not in strict key order at {key}")
        previous_key = key
        prompt = prompts.get(key[:2])
        if prompt is None:
            raise ValueError(f"Frozen trajectory has no prompt: {key}")
        if generation.get("id") != prompt.sample_id or score.get("id") != prompt.sample_id:
            raise ValueError(f"Frozen trajectory id differs from its prompt: {key}")
        if generation.get("template") != prompt.template or score.get("template") != prompt.template:
            raise ValueError(f"Frozen trajectory template differs from its prompt: {key}")
        expected_candidate = score.get("answer_correct") is True and score.get("perfect") is False
        if score.get("candidate") is not expected_candidate:
            raise ValueError(f"Frozen strict candidate flag is inconsistent: {key}")
        completion = generation.get("gen_solution_answer")
        if not isinstance(completion, str) or not completion:
            raise ValueError(f"Frozen generation completion is invalid: {key}")
        per_prompt_counts[key[:2]] += 1
        rows += 1
        if expected_candidate:
            digest = selection_digest("completion", selection_seed, *key, prompt.sample_id)
            candidate = CandidateRecord(
                prompt=prompt,
                sample_rank=key[2],
                completion=completion,
                finish_reason=str(generation.get("finish_reason", "")),
                completion_rank_sha256=digest,
            )
            current = best_by_prompt.get(key[:2])
            if current is None or (digest, key) < (current.completion_rank_sha256, current.key):
                best_by_prompt[key[:2]] = candidate
    if rows != expected_rows:
        raise ValueError(f"Frozen trajectory count is {rows}, expected {expected_rows}")
    wrong_group_sizes = {key: count for key, count in per_prompt_counts.items() if count != samples_per_prompt}
    if wrong_group_sizes:
        first = next(iter(sorted(wrong_group_sizes.items())))
        raise ValueError(f"Frozen prompt has {first[1]} trajectories instead of {samples_per_prompt}: {first[0]}")

    strata: dict[tuple[int, str], list[tuple[str, CandidateRecord]]] = defaultdict(list)
    for candidate in best_by_prompt.values():
        prompt = candidate.prompt
        digest = selection_digest("prompt", selection_seed, prompt.operation, prompt.template, prompt.sample_id)
        strata[(prompt.operation, prompt.template)].append((digest, candidate))
    expected_strata = {(prompt.operation, prompt.template) for prompt in prompts.values()}
    if set(strata) != expected_strata:
        raise ValueError(
            f"Candidate-bearing strata differ from frozen prompt strata: {sorted(expected_strata - set(strata))}"
        )

    selected = []
    for stratum in sorted(strata):
        ranked = sorted(strata[stratum], key=lambda item: (item[0], item[1].key))
        if pairs_per_stratum is not None and len(ranked) < pairs_per_stratum:
            raise ValueError(f"Stratum {stratum} has {len(ranked)} candidate prompts, fewer than {pairs_per_stratum}")
        limit = len(ranked) if pairs_per_stratum is None else pairs_per_stratum
        selected.extend((candidate, prompt_digest) for prompt_digest, candidate in ranked[:limit])
    selected.sort(key=lambda item: (item[0].prompt.operation, item[0].prompt.template, item[1], item[0].key))
    return selected


def independently_validate_pair(prompt: PromptRecord, candidate: str, gold: str) -> None:
    candidate_report = compare_solutions(prompt.solution, candidate)
    if candidate_report["perfect"]:
        raise ValueError(f"Selected A completion is strict-correct: {prompt.sample_id}")
    answer_mismatch = candidate_report["answer_mismatch"]
    if answer_mismatch is not None:
        _, predicted_answer = answer_mismatch
        if not numbers_match(float(prompt.answer), predicted_answer, tolerance=1e-6):
            raise ValueError(f"Selected A completion is answer-incorrect: {prompt.sample_id}")
    gold_report = compare_solutions(prompt.solution, gold)
    if not gold_report["perfect"]:
        raise ValueError(f"Recorded gold completion is not strict-correct: {prompt.sample_id}")


def load_gold_completions(
    gold_source: Path,
    selected: list[tuple[CandidateRecord, str]],
) -> tuple[dict[str, str], dict[str, Any]]:
    required_ids = {candidate.prompt.sample_id for candidate, _ in selected}
    candidate_by_id = {candidate.prompt.sample_id: candidate for candidate, _ in selected}
    if len(candidate_by_id) != len(selected):
        raise ValueError("Candidate pool contains more than one representative per prompt")
    gold = {}
    for line_number, row in iter_jsonl(gold_source):
        sample_id = row.get("id")
        if sample_id not in required_ids:
            continue
        if sample_id in gold:
            raise ValueError(f"Gold source contains a duplicate selected id: {sample_id}")
        candidate = candidate_by_id[sample_id]
        prompt = candidate.prompt
        expected_fields = {
            "op": prompt.operation,
            "template": prompt.template,
            "prompt": prompt.prompt,
            "problem": prompt.problem,
            "question": prompt.question,
            "solution": prompt.solution,
            "answer": prompt.answer,
        }
        for field, expected in expected_fields.items():
            if row.get(field) != expected:
                raise ValueError(f"Gold source {field} differs from frozen prompt at {gold_source}:{line_number}")
        completion = row.get("completion")
        if not isinstance(completion, str) or not completion:
            raise ValueError(f"Gold source has no recorded completion at {gold_source}:{line_number}")
        gold[sample_id] = completion
    missing = sorted(required_ids - set(gold))
    if missing:
        raise ValueError(f"Gold source is missing {len(missing)} selected prompts, first={missing[0]}")
    return gold, file_identity(gold_source)


def render_sequence(
    *,
    renderer: Any,
    tag_index: int,
    prompt: str,
    completion: str,
    max_position_embeddings: int,
    vocab_size: int | None = None,
) -> tuple[tuple[int, ...], tuple[bool, ...], dict[str, Any]]:
    if tag_index not in range(TAG_COUNT):
        raise ValueError(f"Invalid neutral tag index: {tag_index}")
    user_content = TAG_PREFIXES[tag_index] + prompt
    user_message = {"role": "user", "content": user_content}
    assistant_message = {"role": "assistant", "content": completion}
    user_render = renderer.render([user_message], add_generation_prompt=False)
    full_render = renderer.render([user_message, assistant_message], add_generation_prompt=False)
    token_ids = tuple(int(token_id) for token_id in full_render.token_ids)
    user_ids = tuple(int(token_id) for token_id in user_render.token_ids)
    if token_ids[: len(user_ids)] != user_ids:
        raise ValueError("DefaultRenderer is not prefix-stable at the user/assistant boundary")
    if len(full_render.message_indices) != len(token_ids):
        raise ValueError("DefaultRenderer returned misaligned message attribution")
    if vocab_size is not None and (not token_ids or min(token_ids) < 0 or max(token_ids) >= vocab_size):
        raise ValueError("Probe tokenizer emitted a token outside the model vocabulary")
    loss_mask = tuple(index == 1 for index in full_render.message_indices)
    trainable_tokens = sum(loss_mask[1:])
    if trainable_tokens < 1:
        raise ValueError("Rendered probe completion has no trainable tokens")
    model_input_tokens = len(token_ids) - 1
    if model_input_tokens > max_position_embeddings:
        raise SequenceTooLongError(
            f"Rendered probe sequence has {model_input_tokens} model-input tokens, exceeding {max_position_embeddings}"
        )
    facts = {
        "model_input_tokens": model_input_tokens,
        "trainable_tokens": trainable_tokens,
        "token_ids_sha256": canonical_json_sha256(token_ids),
        "loss_mask_sha256": canonical_json_sha256(loss_mask),
    }
    return token_ids, loss_mask, facts


def renderer_state(model_path: Path) -> tuple[Any, Any, dict[str, Any]]:
    from renderers.default import DefaultRenderer
    from transformers import AutoTokenizer

    resolved = model_path.expanduser().resolve()
    config = read_json_object(resolved / "config.json")
    max_positions = config.get("max_position_embeddings")
    if isinstance(max_positions, bool) or not isinstance(max_positions, int) or max_positions < 2:
        raise ValueError("Model config has no valid max_position_embeddings")
    vocab_size = config.get("vocab_size")
    if isinstance(vocab_size, bool) or not isinstance(vocab_size, int) or vocab_size < 2:
        raise ValueError("Model config has no valid vocab_size")
    tokenizer = AutoTokenizer.from_pretrained(str(resolved), trust_remote_code=True)
    renderer = DefaultRenderer(tokenizer)
    renderer_path = Path(inspect.getsourcefile(DefaultRenderer) or "").resolve()
    if not renderer_path.is_file():
        raise FileNotFoundError(renderer_path)
    state = {
        "renderer_class": "renderers.default.DefaultRenderer",
        "renderer_implementation": file_identity(renderer_path),
        "max_position_embeddings": max_positions,
        "vocab_size": vocab_size,
        "messages": ["user = TAG_PREFIX + frozen prompt", "assistant = recorded completion verbatim"],
        "loss_mask": "assistant-attributed tokens after one-token causal shift",
        "eos_appended": False,
    }
    return tokenizer, renderer, state


def pair_id(candidate: CandidateRecord) -> str:
    return f"probe_{canonical_json_sha256([candidate.key, candidate.prompt.sample_id, candidate.completion])[:24]}"


def select_renderable_pairs(
    *,
    ranked_candidates: list[tuple[CandidateRecord, str]],
    gold: dict[str, str],
    renderer: Any,
    max_position_embeddings: int,
    vocab_size: int,
    pairs_per_stratum: int,
) -> tuple[list[tuple[CandidateRecord, str]], list[dict[str, Any]]]:
    strata: dict[tuple[int, str], list[tuple[CandidateRecord, str]]] = defaultdict(list)
    for candidate, prompt_digest in ranked_candidates:
        strata[(candidate.prompt.operation, candidate.prompt.template)].append((candidate, prompt_digest))
    selected = []
    exclusion_records = []
    for stratum in sorted(strata):
        accepted = 0
        excluded = 0
        for candidate, prompt_digest in strata[stratum]:
            gold_completion = gold[candidate.prompt.sample_id]
            independently_validate_pair(candidate.prompt, candidate.completion, gold_completion)
            try:
                for tag_index in range(TAG_COUNT):
                    render_sequence(
                        renderer=renderer,
                        tag_index=tag_index,
                        prompt=candidate.prompt.prompt,
                        completion=candidate.completion,
                        max_position_embeddings=max_position_embeddings,
                        vocab_size=vocab_size,
                    )
                    render_sequence(
                        renderer=renderer,
                        tag_index=tag_index,
                        prompt=candidate.prompt.prompt,
                        completion=gold_completion,
                        max_position_embeddings=max_position_embeddings,
                        vocab_size=vocab_size,
                    )
            except SequenceTooLongError:
                excluded += 1
                continue
            selected.append((candidate, prompt_digest))
            accepted += 1
            if accepted == pairs_per_stratum:
                break
        if accepted != pairs_per_stratum:
            raise ValueError(
                f"Stratum {stratum} has only {accepted} renderable candidate/gold pairs, expected {pairs_per_stratum}"
            )
        exclusion_records.append(
            {
                "operation": stratum[0],
                "template": stratum[1],
                "length_exclusions_before_quota": excluded,
            }
        )
    return selected, exclusion_records


def build_dataset_rows(
    *,
    selected: list[tuple[CandidateRecord, str]],
    gold: dict[str, str],
    renderer: Any,
    max_position_embeddings: int,
    vocab_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    stratum_counts: Counter[tuple[int, str]] = Counter()
    trainable_counts = {str(tag): {"candidate": 0, "gold": 0} for tag in range(TAG_COUNT)}
    for candidate, prompt_digest in selected:
        prompt = candidate.prompt
        gold_completion = gold[prompt.sample_id]
        identifier = pair_id(candidate)
        stratum_counts[(prompt.operation, prompt.template)] += 1
        for tag_index in range(TAG_COUNT):
            _, _, candidate_facts = render_sequence(
                renderer=renderer,
                tag_index=tag_index,
                prompt=prompt.prompt,
                completion=candidate.completion,
                max_position_embeddings=max_position_embeddings,
                vocab_size=vocab_size,
            )
            _, _, gold_facts = render_sequence(
                renderer=renderer,
                tag_index=tag_index,
                prompt=prompt.prompt,
                completion=gold_completion,
                max_position_embeddings=max_position_embeddings,
                vocab_size=vocab_size,
            )
            trainable_counts[str(tag_index)]["candidate"] += candidate_facts["trainable_tokens"]
            trainable_counts[str(tag_index)]["gold"] += gold_facts["trainable_tokens"]
            rows.append(
                {
                    "pair_id": identifier,
                    "tag_index": tag_index,
                    "tag_prefix": TAG_PREFIXES[tag_index],
                    "operation": prompt.operation,
                    "template": prompt.template,
                    "prompt_index": prompt.prompt_index,
                    "sample_rank": candidate.sample_rank,
                    "prompt_id": prompt.sample_id,
                    "prompt": prompt.prompt,
                    "candidate_completion": candidate.completion,
                    "gold_completion": gold_completion,
                    "candidate_advantage": 0.5,
                    "gold_advantage": -0.5,
                    "candidate_render": candidate_facts,
                    "gold_render": gold_facts,
                    "selection": {
                        "prompt_rank_sha256": prompt_digest,
                        "completion_rank_sha256": candidate.completion_rank_sha256,
                    },
                }
            )
    rows.sort(
        key=lambda row: (row["operation"], row["template"], row["selection"]["prompt_rank_sha256"], row["tag_index"])
    )
    return rows, {
        "stratum_counts": [
            {"operation": operation, "template": template, "pairs": count}
            for (operation, template), count in sorted(stratum_counts.items())
        ],
        "trainable_tokens_by_tag": trainable_counts,
    }


def build_probe_plan(
    *,
    bank_root: Path,
    gold_source: Path,
    model_path: Path,
    output_dir: Path,
    selection_seed: int,
    pairs_per_stratum: int,
    enforce_pair_range: bool = True,
) -> ProbePlan:
    output_dir = output_dir.expanduser().resolve()
    dataset_path = output_dir / DATASET_NAME
    manifest_path = output_dir / MANIFEST_NAME
    state = bank_state(bank_root, model_path)
    prompt_rows = state["artifacts"]["prompts"]["rows"]
    trajectory_rows = state["artifacts"]["generations"]["rows"]
    ordered_prompts, prompts = load_prompts(Path(state["artifacts"]["prompts"]["path"]), expected_rows=prompt_rows)
    ranked_candidates = select_candidate_completions(
        generations_path=Path(state["artifacts"]["generations"]["path"]),
        strict_results_path=Path(state["artifacts"]["strict_results"]["path"]),
        prompts=prompts,
        expected_rows=trajectory_rows,
        samples_per_prompt=state["samples_per_prompt"],
        selection_seed=selection_seed,
        pairs_per_stratum=None,
    )
    gold, gold_identity = load_gold_completions(gold_source.expanduser().resolve(), ranked_candidates)
    _, renderer, rendering = renderer_state(model_path)
    selected, length_exclusions = select_renderable_pairs(
        ranked_candidates=ranked_candidates,
        gold=gold,
        renderer=renderer,
        max_position_embeddings=rendering["max_position_embeddings"],
        vocab_size=rendering["vocab_size"],
        pairs_per_stratum=pairs_per_stratum,
    )
    expected_pairs = len({(prompt.operation, prompt.template) for prompt in ordered_prompts}) * pairs_per_stratum
    if len(selected) != expected_pairs:
        raise RuntimeError(f"Selected {len(selected)} pairs, expected {expected_pairs}")
    if enforce_pair_range and not MIN_PROBE_PAIRS <= len(selected) <= MAX_PROBE_PAIRS:
        raise ValueError(f"Probe pair count {len(selected)} is outside [{MIN_PROBE_PAIRS}, {MAX_PROBE_PAIRS}]")
    rows, counts = build_dataset_rows(
        selected=selected,
        gold=gold,
        renderer=renderer,
        max_position_embeddings=rendering["max_position_embeddings"],
        vocab_size=rendering["vocab_size"],
    )
    dataset_bytes = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    dataset_identity = {
        "path": str(dataset_path),
        "bytes": len(dataset_bytes),
        "rows": len(rows),
        "sha256": bytes_sha256(dataset_bytes),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "probe_id": PROBE_ID,
        "selection": {
            "domain": SELECTION_DOMAIN,
            "seed": selection_seed,
            "pairs_per_operation_template_stratum": pairs_per_stratum,
            "pairs": len(selected),
            "tag_count": TAG_COUNT,
            "tagged_pairs": len(rows),
            "candidate_definition": "answer_correct=true and perfect=false",
            "one_candidate_completion_per_prompt": True,
            "length_eligibility": "candidate and recorded gold must both fit all six tagged renders without truncation",
            "length_exclusions": length_exclusions,
            **counts,
        },
        "objective": {
            "candidate_sequence_advantage": 0.5,
            "gold_sequence_advantage": -0.5,
            "normalizer": "global trainable completion-token count within each source tag",
            "importance_ratio": 1.0,
            "kl_gradient_at_baseline": 0.0,
            "dppo_probability_mask_at_baseline": False,
        },
        "rendering": rendering,
        "inputs": {
            "bank": state,
            "gold_source": gold_identity,
            "model": state["model"],
            "tokenizer": tokenizer_identity(model_path),
        },
        "dataset": dataset_identity,
        "manifest_path": str(manifest_path),
        "implementation": file_identity(Path(__file__).resolve()),
    }
    return ProbePlan(
        dataset_bytes=dataset_bytes, manifest=manifest, manifest_bytes=canonical_json_bytes(manifest, indent=2)
    )


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_probe(probe_dir: Path) -> dict[str, Any]:
    probe_dir = probe_dir.expanduser().resolve()
    manifest_path = probe_dir / MANIFEST_NAME
    dataset_path = probe_dir / DATASET_NAME
    manifest = read_json_object(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("probe_id") != PROBE_ID:
        raise ValueError("Probe manifest has the wrong schema or identity")
    if manifest.get("manifest_path") != str(manifest_path):
        raise ValueError("Probe manifest is not at its recorded path")
    selection = manifest.get("selection")
    inputs = manifest.get("inputs")
    if not isinstance(selection, dict) or not isinstance(inputs, dict):
        raise ValueError("Probe manifest is missing selection/input records")
    bank = inputs.get("bank")
    model = inputs.get("model")
    gold = inputs.get("gold_source")
    if not isinstance(bank, dict) or not isinstance(model, dict) or not isinstance(gold, dict):
        raise ValueError("Probe manifest input records are invalid")
    expected = build_probe_plan(
        bank_root=Path(bank["root"]),
        gold_source=Path(gold["path"]),
        model_path=Path(model["configured_name"]),
        output_dir=probe_dir,
        selection_seed=selection["seed"],
        pairs_per_stratum=selection["pairs_per_operation_template_stratum"],
    )
    actual_dataset = dataset_path.read_bytes()
    actual_manifest = manifest_path.read_bytes()
    if actual_dataset != expected.dataset_bytes:
        raise ValueError("Probe dataset differs from independent source replay")
    if actual_manifest != expected.manifest_bytes:
        raise ValueError("Probe manifest differs from independent source replay")
    return {
        "manifest": manifest,
        "manifest_sha256": bytes_sha256(actual_manifest),
        "dataset_sha256": bytes_sha256(actual_dataset),
    }


def prepare_probe(
    *,
    bank_root: Path,
    gold_source: Path,
    model_path: Path,
    output_dir: Path,
    selection_seed: int,
    pairs_per_stratum: int,
    dry_run: bool,
) -> dict[str, Any]:
    plan = build_probe_plan(
        bank_root=bank_root,
        gold_source=gold_source,
        model_path=model_path,
        output_dir=output_dir,
        selection_seed=selection_seed,
        pairs_per_stratum=pairs_per_stratum,
    )
    output_dir = output_dir.expanduser().resolve()
    dataset_path = output_dir / DATASET_NAME
    manifest_path = output_dir / MANIFEST_NAME
    if dry_run:
        return {
            "dry_run": True,
            "already_prepared": False,
            "manifest": plan.manifest,
            "manifest_sha256": bytes_sha256(plan.manifest_bytes),
            "dataset_sha256": bytes_sha256(plan.dataset_bytes),
        }
    if dataset_path.exists() or manifest_path.exists():
        if not dataset_path.is_file() or not manifest_path.is_file():
            raise FileExistsError("Probe dataset and manifest must either both be absent or both be files")
        validated = validate_probe(output_dir)
        if validated["manifest"] != plan.manifest:
            raise ValueError("Existing probe belongs to another preparation request")
        return {**validated, "dry_run": False, "already_prepared": True}
    write_bytes_atomic(dataset_path, plan.dataset_bytes)
    write_bytes_atomic(manifest_path, plan.manifest_bytes)
    validated = validate_probe(output_dir)
    return {**validated, "dry_run": False, "already_prepared": False}


def _render_facts(token_ids: tuple[int, ...], loss_mask: tuple[bool, ...]) -> dict[str, Any]:
    return {
        "model_input_tokens": len(token_ids) - 1,
        "trainable_tokens": sum(loss_mask[1:]),
        "token_ids_sha256": canonical_json_sha256(token_ids),
        "loss_mask_sha256": canonical_json_sha256(loss_mask),
    }


def load_probe_sequences(
    probe_dir: Path,
    manifest: dict[str, Any],
) -> dict[int, list[RenderedSequence]]:
    model_path = Path(manifest["inputs"]["model"]["configured_name"])
    _, renderer, rendering = renderer_state(model_path)
    if rendering != manifest["rendering"]:
        raise ValueError("Current renderer identity differs from the probe manifest")
    sequences: dict[int, list[RenderedSequence]] = {tag: [] for tag in range(TAG_COUNT)}
    observed_rows = 0
    observed_keys = set()
    for line_number, row in iter_jsonl(probe_dir / DATASET_NAME):
        required = {
            "pair_id",
            "tag_index",
            "tag_prefix",
            "prompt",
            "candidate_completion",
            "gold_completion",
            "candidate_advantage",
            "gold_advantage",
            "candidate_render",
            "gold_render",
        }
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"Probe dataset row is missing {missing}: line {line_number}")
        tag = row["tag_index"]
        if isinstance(tag, bool) or not isinstance(tag, int) or tag not in range(TAG_COUNT):
            raise ValueError(f"Probe dataset tag is invalid: line {line_number}")
        if row["tag_prefix"] != TAG_PREFIXES[tag]:
            raise ValueError(f"Probe dataset prefix differs from tag index: line {line_number}")
        pair_identifier = row["pair_id"]
        if not isinstance(pair_identifier, str) or (pair_identifier, tag) in observed_keys:
            raise ValueError(f"Probe dataset pair/tag identity is invalid: line {line_number}")
        observed_keys.add((pair_identifier, tag))
        for kind, advantage in (("candidate", 0.5), ("gold", -0.5)):
            completion = row[f"{kind}_completion"]
            if not isinstance(completion, str) or row[f"{kind}_advantage"] != advantage:
                raise ValueError(f"Probe dataset {kind} contract is invalid: line {line_number}")
            token_ids, loss_mask, facts = render_sequence(
                renderer=renderer,
                tag_index=tag,
                prompt=row["prompt"],
                completion=completion,
                max_position_embeddings=rendering["max_position_embeddings"],
                vocab_size=rendering["vocab_size"],
            )
            if facts != row[f"{kind}_render"] or facts != _render_facts(token_ids, loss_mask):
                raise ValueError(f"Probe dataset {kind} rendering differs from its seal: line {line_number}")
            sequences[tag].append(
                RenderedSequence(
                    tag_index=tag,
                    kind=kind,
                    pair_id=pair_identifier,
                    token_ids=token_ids,
                    loss_mask=loss_mask,
                    advantage=advantage,
                )
            )
        observed_rows += 1
    expected_rows = manifest["dataset"]["rows"]
    if observed_rows != expected_rows:
        raise ValueError(f"Probe dataset has {observed_rows} rows, expected {expected_rows}")
    expected_pairs = manifest["selection"]["pairs"]
    for tag, items in sequences.items():
        if len(items) != 2 * expected_pairs:
            raise ValueError(f"Tag {tag} has {len(items)} sequences, expected {2 * expected_pairs}")
        expected_tokens = manifest["selection"]["trainable_tokens_by_tag"][str(tag)]
        candidate_tokens = sum(item.trainable_tokens for item in items if item.kind == "candidate")
        gold_tokens = sum(item.trainable_tokens for item in items if item.kind == "gold")
        if expected_tokens != {"candidate": candidate_tokens, "gold": gold_tokens}:
            raise ValueError(f"Tag {tag} trainable-token count differs from the manifest")
    return sequences


def _sequence_batches(items: list[RenderedSequence], batch_size: int) -> Iterable[list[RenderedSequence]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def _model_batch(items: list[RenderedSequence], device: Any) -> tuple[Any, Any, Any, Any]:
    import torch

    lengths = [len(item.token_ids) - 1 for item in items]
    width = max(lengths)
    input_ids = torch.zeros((len(items), width), dtype=torch.long, device=device)
    attention_mask = torch.zeros((len(items), width), dtype=torch.long, device=device)
    labels = torch.zeros((len(items), width), dtype=torch.long, device=device)
    loss_mask = torch.zeros((len(items), width), dtype=torch.bool, device=device)
    advantages = torch.zeros((len(items), width), dtype=torch.float32, device=device)
    for index, (item, length) in enumerate(zip(items, lengths, strict=True)):
        input_ids[index, :length] = torch.tensor(item.token_ids[:-1], dtype=torch.long, device=device)
        labels[index, :length] = torch.tensor(item.token_ids[1:], dtype=torch.long, device=device)
        attention_mask[index, :length] = 1
        shifted_mask = torch.tensor(item.loss_mask[1:], dtype=torch.bool, device=device)
        loss_mask[index, :length] = shifted_mask
        advantages[index, :length] = item.advantage
    return input_ids, attention_mask, labels, loss_mask, advantages


def directional_objective(
    model: Any,
    items: list[RenderedSequence],
    *,
    batch_size: int,
    device: Any,
    backward: bool,
) -> float:
    import torch

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    normalizer = sum(item.trainable_tokens for item in items)
    if normalizer < 1:
        raise ValueError("Directional objective has no trainable completion tokens")
    total = 0.0
    context = torch.enable_grad() if backward else torch.no_grad()
    with context:
        for batch in _sequence_batches(items, batch_size):
            input_ids, attention_mask, labels, loss_mask, advantages = _model_batch(batch, device)
            logits = model(input_ids=input_ids, attention_mask=attention_mask, use_cache=False).logits
            if labels.max().item() >= logits.shape[-1]:
                raise ValueError("Probe tokenizer emitted a token outside the model vocabulary")
            label_logprobs = torch.log_softmax(logits.float(), dim=-1).gather(-1, labels.unsqueeze(-1)).squeeze(-1)
            contribution = (label_logprobs * advantages * loss_mask).sum() / normalizer
            total += float(contribution.detach().cpu())
            if backward:
                contribution.backward()
    return total


def objective_vector(
    model: Any,
    sequences: dict[int, list[RenderedSequence]],
    *,
    batch_size: int,
    device: Any,
) -> list[float]:
    return [
        directional_objective(model, sequences[tag], batch_size=batch_size, device=device, backward=False)
        for tag in range(TAG_COUNT)
    ]


def sentinel_label_logprobs(model: Any, item: RenderedSequence, *, device: Any, limit: int = 64) -> list[float]:
    import torch

    input_ids, attention_mask, labels, loss_mask, _ = _model_batch([item], device)
    with torch.no_grad():
        logits = model(input_ids=input_ids, attention_mask=attention_mask, use_cache=False).logits
        values = torch.log_softmax(logits.float(), dim=-1).gather(-1, labels.unsqueeze(-1)).squeeze(-1)
    selected = values[loss_mask]
    if selected.numel() > limit:
        positions = torch.linspace(0, selected.numel() - 1, steps=limit, device=selected.device).round().long()
        selected = selected[positions]
    return [float(value) for value in selected.cpu()]


def _assert_close_vectors(actual: list[float], expected: list[float], *, atol: float, rtol: float, name: str) -> None:
    if len(actual) != len(expected):
        raise RuntimeError(f"{name} length changed during reversible probe")
    for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
        if not math.isclose(left, right, abs_tol=atol, rel_tol=rtol):
            raise RuntimeError(f"{name}[{index}] did not recover: {left} != {right}")


def _parameter_snapshot(model: Any) -> dict[str, Any]:
    return {name: parameter.detach().cpu().clone() for name, parameter in model.named_parameters()}


def _restore_parameters(model: Any, snapshot: dict[str, Any]) -> None:
    import torch

    with torch.no_grad():
        for name, parameter in model.named_parameters():
            parameter.copy_(snapshot[name].to(device=parameter.device, dtype=parameter.dtype))


def _assert_parameters_exact(model: Any, snapshot: dict[str, Any]) -> None:
    import torch

    for name, parameter in model.named_parameters():
        if not torch.equal(parameter.detach().cpu(), snapshot[name]):
            raise RuntimeError(f"Parameter {name} did not restore bit-exactly")


def _gradient_norm(model: Any) -> float:
    total = 0.0
    for parameter in model.parameters():
        if parameter.grad is not None:
            total += float(parameter.grad.detach().float().square().sum().cpu())
    return math.sqrt(total)


def _gradient_snapshot(model: Any) -> dict[str, Any]:
    return {
        name: parameter.grad.detach().float().cpu().clone()
        for name, parameter in model.named_parameters()
        if parameter.grad is not None
    }


def _gradient_inner_product(left: dict[str, Any], right: dict[str, Any]) -> float:
    import torch

    if left.keys() != right.keys():
        raise ValueError("Gradient snapshots have different parameter support")
    terms = []
    for name in left:
        left_flat = left[name].reshape(-1)
        right_flat = right[name].reshape(-1)
        if left_flat.shape != right_flat.shape:
            raise ValueError(f"Gradient snapshot shape differs for {name}")
        for start in range(0, left_flat.numel(), GRADIENT_DOT_CHUNK_SIZE):
            stop = start + GRADIENT_DOT_CHUNK_SIZE
            terms.append(
                float(
                    torch.dot(
                        left_flat[start:stop].double(),
                        right_flat[start:stop].double(),
                    )
                )
            )
    return math.fsum(terms)


def _apply_gradient_ascent(model: Any, gradient: dict[str, Any], step_size: float) -> None:
    import torch

    parameters = dict(model.named_parameters())
    if gradient.keys() - parameters.keys():
        raise ValueError("Gradient snapshot contains unknown model parameters")
    with torch.no_grad():
        for name, value in gradient.items():
            parameter = parameters[name]
            parameter.add_(value.to(device=parameter.device, dtype=parameter.dtype), alpha=step_size)


def _normalized_cross_gradient_kernel(gradients: list[dict[str, Any]]) -> tuple[list[list[float]], list[float]]:
    if len(gradients) != TAG_COUNT:
        raise ValueError(f"Expected {TAG_COUNT} tag gradients, got {len(gradients)}")
    raw = [[0.0] * TAG_COUNT for _ in range(TAG_COUNT)]
    for target in range(TAG_COUNT):
        for source in range(target + 1):
            value = _gradient_inner_product(gradients[target], gradients[source])
            raw[target][source] = value
            raw[source][target] = value
    self_terms = [raw[source][source] for source in range(TAG_COUNT)]
    if any(not math.isfinite(value) or value <= 0.0 for value in self_terms):
        raise RuntimeError("Cross-gradient kernel has a non-positive or non-finite diagonal")
    normalized = [
        [raw[target][source] / self_terms[source] for source in range(TAG_COUNT)]
        for target in range(TAG_COUNT)
    ]
    return normalized, self_terms


def finite_step_ordering_check(
    analytic_kernel: list[list[float]],
    finite_kernel: list[list[float]],
    *,
    margin: float = DEFAULT_ORDERING_MARGIN,
    minimum_pairs_per_source: int = DEFAULT_MIN_ORDERING_PAIRS_PER_SOURCE,
) -> dict[str, Any]:
    if not math.isfinite(margin) or margin < 0.0:
        raise ValueError("ordering margin must be finite and non-negative")
    if (
        isinstance(minimum_pairs_per_source, bool)
        or not isinstance(minimum_pairs_per_source, int)
        or not 1 <= minimum_pairs_per_source <= MAX_ORDERING_PAIRS_PER_SOURCE
    ):
        raise ValueError(
            f"minimum ordering pairs per source must lie in [1, {MAX_ORDERING_PAIRS_PER_SOURCE}]"
        )
    expected_shape = (TAG_COUNT, TAG_COUNT)
    for name, matrix in (("analytic", analytic_kernel), ("finite", finite_kernel)):
        if len(matrix) != expected_shape[0] or any(len(row) != expected_shape[1] for row in matrix):
            raise ValueError(f"{name} kernel must have shape {expected_shape}")
        if any(not math.isfinite(value) for row in matrix for value in row):
            raise ValueError(f"{name} kernel contains a non-finite value")

    per_source = []
    total_resolvable = 0
    total_agreements = 0
    for source in range(TAG_COUNT):
        resolvable = 0
        agreements = 0
        disagreements = []
        unresolved = 0
        for left in range(TAG_COUNT):
            for right in range(left + 1, TAG_COUNT):
                analytic_gap = analytic_kernel[left][source] - analytic_kernel[right][source]
                if abs(analytic_gap) <= margin:
                    unresolved += 1
                    continue
                resolvable += 1
                finite_gap = finite_kernel[left][source] - finite_kernel[right][source]
                if analytic_gap * finite_gap > 0.0:
                    agreements += 1
                else:
                    disagreements.append(
                        {
                            "left_target": left,
                            "right_target": right,
                            "analytic_gap": analytic_gap,
                            "finite_gap": finite_gap,
                        }
                    )
        source_passed = resolvable >= minimum_pairs_per_source and not disagreements
        per_source.append(
            {
                "source_tag": source,
                "resolvable_pairs": resolvable,
                "unresolved_pairs_within_margin": unresolved,
                "agreements": agreements,
                "disagreements": disagreements,
                "passed": source_passed,
            }
        )
        total_resolvable += resolvable
        total_agreements += agreements
    return {
        "definition": (
            "Within each source-tag column, every analytic target pair separated by more than the normalized "
            "margin must retain its strict order after the finite update. Each source must expose at least the "
            "predeclared minimum number of resolvable pairs."
        ),
        "normalized_margin": margin,
        "minimum_resolvable_pairs_per_source": minimum_pairs_per_source,
        "resolvable_pairs": total_resolvable,
        "agreements": total_agreements,
        "agreement_rate": total_agreements / total_resolvable if total_resolvable else None,
        "per_source": per_source,
        "passed": all(item["passed"] for item in per_source),
    }


def _kernel_matrix(value: object, name: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != TAG_COUNT:
        raise ValueError(f"{name} must have {TAG_COUNT} target rows")
    matrix = []
    for target, row in enumerate(value):
        if not isinstance(row, list) or len(row) != TAG_COUNT:
            raise ValueError(f"{name}[{target}] must have {TAG_COUNT} source columns")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in row):
            raise ValueError(f"{name}[{target}] contains an invalid value")
        matrix.append([float(item) for item in row])
    return matrix


def _preregistered_runtime_contract() -> dict[str, int | float | bool | str]:
    return {
        "dtype": "float32",
        "deterministic_algorithms": True,
        "step_size": DEFAULT_STEP_SIZE,
        "batch_size": DEFAULT_BATCH_SIZE,
        "recovery_atol": DEFAULT_RECOVERY_ATOL,
        "recovery_rtol": DEFAULT_RECOVERY_RTOL,
        "minimum_self_delta": DEFAULT_MINIMUM_SELF_DELTA,
        "max_self_linearity_relative_error": DEFAULT_MAX_SELF_LINEARITY_RELATIVE_ERROR,
        "ordering_margin": DEFAULT_ORDERING_MARGIN,
        "minimum_ordering_pairs_per_source": DEFAULT_MIN_ORDERING_PAIRS_PER_SOURCE,
        "max_median_off_diagonal": DEFAULT_MAX_MEDIAN_OFF_DIAGONAL,
    }


def validate_kernel_result(probe_dir: Path, output_path: Path) -> dict[str, Any]:
    probe_dir = probe_dir.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    raw = output_path.read_bytes()
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Kernel result is not a JSON object")
    if raw != canonical_json_bytes(result, indent=2):
        raise ValueError("Kernel result is not canonical JSON")
    if result.get("schema_version") != SCHEMA_VERSION or result.get("probe_id") != PROBE_ID:
        raise ValueError("Kernel result has the wrong schema or probe identity")

    validated_probe = validate_probe(probe_dir)
    expected_manifest = {
        "path": str((probe_dir / MANIFEST_NAME).resolve()),
        "sha256": validated_probe["manifest_sha256"],
    }
    expected_dataset = {
        "path": str((probe_dir / DATASET_NAME).resolve()),
        "sha256": validated_probe["dataset_sha256"],
    }
    if result.get("probe_manifest") != expected_manifest or result.get("probe_dataset") != expected_dataset:
        raise ValueError("Kernel result belongs to a different probe artifact")
    current_model = model_identity(Path(validated_probe["manifest"]["inputs"]["model"]["configured_name"]))
    if result.get("model") != current_model or current_model != validated_probe["manifest"]["inputs"]["model"]:
        raise ValueError("Kernel result model identity differs from the sealed probe")

    analytic = _kernel_matrix(result.get("analytic_cross_gradient_kernel"), "analytic_cross_gradient_kernel")
    finite = _kernel_matrix(result.get("finite_step_kernel"), "finite_step_kernel")
    if result.get("kernel") != result.get("analytic_cross_gradient_kernel"):
        raise ValueError("Primary kernel is not the analytic cross-gradient kernel")
    for index in range(TAG_COUNT):
        if analytic[index][index] != 1.0 or finite[index][index] != 1.0:
            raise ValueError("Analytic and finite kernels must have unit diagonals")

    runtime_record = result.get("runtime")
    if not isinstance(runtime_record, dict):
        raise ValueError("Kernel result has no runtime contract")
    for name, expected in _preregistered_runtime_contract().items():
        if runtime_record.get(name) != expected:
            raise ValueError(f"Kernel runtime {name} differs from the preregistered value {expected!r}")
    if result.get("kernel_orientation") != KERNEL_ORIENTATION:
        raise ValueError("Kernel orientation record differs from the analytic definition")

    responses = result.get("responses")
    if not isinstance(responses, list) or [row.get("source_tag") for row in responses if isinstance(row, dict)] != list(
        range(TAG_COUNT)
    ):
        raise ValueError("Kernel result responses do not cover source tags in canonical order")
    reconstructed_finite = [[0.0] * TAG_COUNT for _ in range(TAG_COUNT)]
    for source, response in enumerate(responses):
        if not isinstance(response, dict):
            raise ValueError(f"Kernel response {source} is not an object")
        normalized = response.get("normalized_transfer")
        if not isinstance(normalized, list) or len(normalized) != TAG_COUNT:
            raise ValueError(f"Kernel response {source} has an invalid normalized transfer")
        for target, value in enumerate(normalized):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Kernel response {source} has a non-finite transfer")
            reconstructed_finite[target][source] = float(value)
        required_true = (
            "self_linearity_passed",
            "parameters_restored_bit_exactly",
            "baseline_objectives_recovered",
            "baseline_sentinel_logits_recovered",
        )
        if any(response.get(name) is not True for name in required_true):
            raise ValueError(f"Kernel response {source} did not pass recovery and linearity checks")
        baseline_objectives = result.get("baseline_objectives")
        updated_objectives = response.get("updated_objectives")
        deltas = response.get("deltas")
        if (
            not isinstance(baseline_objectives, list)
            or len(baseline_objectives) != TAG_COUNT
            or not isinstance(updated_objectives, list)
            or len(updated_objectives) != TAG_COUNT
            or not isinstance(deltas, list)
            or len(deltas) != TAG_COUNT
        ):
            raise ValueError(f"Kernel response {source} has invalid objective vectors")
        expected_deltas = [
            updated - baseline for updated, baseline in zip(updated_objectives, baseline_objectives, strict=True)
        ]
        if deltas != expected_deltas or response.get("self_delta") != deltas[source]:
            raise ValueError(f"Kernel response {source} delta identities do not replay")
        self_delta = deltas[source]
        if normalized != [delta / self_delta for delta in deltas]:
            raise ValueError(f"Kernel response {source} normalization does not replay")
        gradient_norm = response.get("gradient_norm")
        if (
            isinstance(gradient_norm, bool)
            or not isinstance(gradient_norm, (int, float))
            or not math.isfinite(gradient_norm)
            or gradient_norm <= 0.0
        ):
            raise ValueError(f"Kernel response {source} gradient norm is invalid")
        predicted_self_delta = runtime_record["step_size"] * gradient_norm**2
        if response.get("first_order_predicted_self_delta") != predicted_self_delta:
            raise ValueError(f"Kernel response {source} first-order self prediction does not replay")
        if response.get("observed_to_predicted_self_ratio") != self_delta / predicted_self_delta:
            raise ValueError(f"Kernel response {source} observed/predicted ratio does not replay")
        relative_error = abs(self_delta - predicted_self_delta) / predicted_self_delta
        if response.get("self_linearity_relative_error") != relative_error:
            raise ValueError(f"Kernel response {source} self-linearity error does not replay")
    if reconstructed_finite != finite:
        raise ValueError("Finite-step kernel differs from the per-source response records")

    ordering = finite_step_ordering_check(
        analytic,
        finite,
        margin=runtime_record.get("ordering_margin"),
        minimum_pairs_per_source=runtime_record.get("minimum_ordering_pairs_per_source"),
    )
    if result.get("finite_step_ordering") != ordering:
        raise ValueError("Kernel finite-step ordering record does not replay")

    off_diagonal = [
        analytic[target][source]
        for target in range(TAG_COUNT)
        for source in range(TAG_COUNT)
        if target != source
    ]
    finite_off_diagonal = [
        finite[target][source]
        for target in range(TAG_COUNT)
        for source in range(TAG_COUNT)
        if target != source
    ]
    expected_summary = {
        "median_off_diagonal": statistics.median(off_diagonal),
        "finite_step_median_off_diagonal": statistics.median(finite_off_diagonal),
        "off_diagonal_count": len(off_diagonal),
    }
    if result.get("kernel_summary") != expected_summary:
        raise ValueError("Kernel summary does not replay from its matrices")
    threshold = runtime_record.get("max_median_off_diagonal")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
        raise ValueError("Kernel median threshold is invalid")
    full_grid_eligible = expected_summary["median_off_diagonal"] <= threshold and ordering["passed"]
    decision = result.get("decision")
    if not isinstance(decision, dict):
        raise ValueError("Kernel result has no decision record")
    if decision.get("rule") != DECISION_RULE:
        raise ValueError("Kernel decision rule differs from the preregistered rule")
    expected_decision_fields = {
        "analytic_median_off_diagonal_at_most_threshold": (
            expected_summary["median_off_diagonal"] <= threshold
        ),
        "finite_step_ordering_passed": ordering["passed"],
        "full_grid_eligible": full_grid_eligible,
        "eligible_design": "full_30_arm_grid" if full_grid_eligible else "four_arm_smoke_screen",
    }
    if any(decision.get(name) != value for name, value in expected_decision_fields.items()):
        raise ValueError("Kernel decision does not follow the sealed threshold and ordering rule")
    return {
        "result": result,
        "output_sha256": bytes_sha256(raw),
        "output_bytes": len(raw),
    }


def _apply_sgd_ascent(model: Any, step_size: float) -> None:
    import torch

    with torch.no_grad():
        for parameter in model.parameters():
            if parameter.grad is not None:
                parameter.add_(parameter.grad, alpha=step_size)


def run_kernel_probe(
    *,
    probe_dir: Path,
    output_path: Path,
    step_size: float,
    batch_size: int,
    recovery_atol: float,
    recovery_rtol: float,
    minimum_self_delta: float,
    max_self_linearity_relative_error: float,
    ordering_margin: float,
    minimum_ordering_pairs_per_source: int,
    max_median_off_diagonal: float,
) -> dict[str, Any]:
    if not math.isfinite(step_size) or step_size <= 0:
        raise ValueError("step_size must be positive and finite")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    for name, value in (
        ("recovery_atol", recovery_atol),
        ("recovery_rtol", recovery_rtol),
        ("minimum_self_delta", minimum_self_delta),
        ("max_self_linearity_relative_error", max_self_linearity_relative_error),
        ("ordering_margin", ordering_margin),
        ("max_median_off_diagonal", max_median_off_diagonal),
    ):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if (
        isinstance(minimum_ordering_pairs_per_source, bool)
        or not isinstance(minimum_ordering_pairs_per_source, int)
        or not 1 <= minimum_ordering_pairs_per_source <= MAX_ORDERING_PAIRS_PER_SOURCE
    ):
        raise ValueError(
            "minimum_ordering_pairs_per_source must lie in "
            f"[1, {MAX_ORDERING_PAIRS_PER_SOURCE}]"
        )
    requested_runtime = {
        "step_size": step_size,
        "batch_size": batch_size,
        "recovery_atol": recovery_atol,
        "recovery_rtol": recovery_rtol,
        "minimum_self_delta": minimum_self_delta,
        "max_self_linearity_relative_error": max_self_linearity_relative_error,
        "ordering_margin": ordering_margin,
        "minimum_ordering_pairs_per_source": minimum_ordering_pairs_per_source,
        "max_median_off_diagonal": max_median_off_diagonal,
    }
    preregistered_runtime = _preregistered_runtime_contract()
    for name, value in requested_runtime.items():
        if value != preregistered_runtime[name]:
            raise ValueError(f"Kernel runtime {name} must equal preregistered value {preregistered_runtime[name]!r}")
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        return {**validate_kernel_result(probe_dir, output_path), "already_complete": True}

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    from transformers import AutoModelForCausalLM

    if not torch.cuda.is_available():
        raise RuntimeError("The kernel probe run mode requires a CUDA GPU")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.use_deterministic_algorithms(True)
    validated = validate_probe(probe_dir)
    manifest = validated["manifest"]
    probe_dir = probe_dir.expanduser().resolve()
    sequences = load_probe_sequences(probe_dir, manifest)
    model_path = Path(manifest["inputs"]["model"]["configured_name"])
    current_model_identity = model_identity(model_path)
    if current_model_identity != manifest["inputs"]["model"]:
        raise ValueError("Model identity changed after probe validation")

    device = torch.device("cuda:0")
    model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        torch_dtype=torch.float32,
        attn_implementation="eager",
        trust_remote_code=True,
    ).to(device)
    model.eval()
    model.config.use_cache = False
    baseline_objectives = objective_vector(model, sequences, batch_size=batch_size, device=device)
    baseline_sentinels = [sentinel_label_logprobs(model, sequences[tag][0], device=device) for tag in range(TAG_COUNT)]
    snapshot = _parameter_snapshot(model)
    source_objectives = []
    gradients = []
    for source_tag in range(TAG_COUNT):
        model.zero_grad(set_to_none=True)
        source_objective = directional_objective(
            model,
            sequences[source_tag],
            batch_size=batch_size,
            device=device,
            backward=True,
        )
        if not math.isclose(
            source_objective,
            baseline_objectives[source_tag],
            abs_tol=recovery_atol,
            rel_tol=recovery_rtol,
        ):
            raise RuntimeError("Gradient and no-gradient baseline objectives differ")
        source_objectives.append(source_objective)
        gradients.append(_gradient_snapshot(model))
    analytic_kernel, analytic_self_terms = _normalized_cross_gradient_kernel(gradients)

    responses = []
    source_normalized_responses = []
    for source_tag in range(TAG_COUNT):
        source_objective = source_objectives[source_tag]
        gradient_norm = math.sqrt(analytic_self_terms[source_tag])
        if not math.isfinite(gradient_norm) or gradient_norm <= 0:
            raise RuntimeError(f"Source tag {source_tag} has an invalid gradient norm: {gradient_norm}")
        updated_objectives: list[float]
        try:
            _apply_gradient_ascent(model, gradients[source_tag], step_size)
            updated_objectives = objective_vector(model, sequences, batch_size=batch_size, device=device)
        finally:
            _restore_parameters(model, snapshot)
        _assert_parameters_exact(model, snapshot)
        recovered_objectives = objective_vector(model, sequences, batch_size=batch_size, device=device)
        recovered_sentinels = [
            sentinel_label_logprobs(model, sequences[tag][0], device=device) for tag in range(TAG_COUNT)
        ]
        _assert_close_vectors(
            recovered_objectives,
            baseline_objectives,
            atol=recovery_atol,
            rtol=recovery_rtol,
            name=f"source_{source_tag}_objectives",
        )
        for tag in range(TAG_COUNT):
            _assert_close_vectors(
                recovered_sentinels[tag],
                baseline_sentinels[tag],
                atol=recovery_atol,
                rtol=recovery_rtol,
                name=f"source_{source_tag}_tag_{tag}_sentinel_logits",
            )
        deltas = [updated - baseline for updated, baseline in zip(updated_objectives, baseline_objectives, strict=True)]
        self_delta = deltas[source_tag]
        if not math.isfinite(self_delta) or self_delta <= minimum_self_delta:
            raise RuntimeError(
                f"Source tag {source_tag} self-response {self_delta} does not exceed {minimum_self_delta}"
            )
        row = [delta / self_delta for delta in deltas]
        if not all(math.isfinite(value) for value in row):
            raise RuntimeError(f"Source tag {source_tag} produced a non-finite kernel response")
        predicted_self_delta = step_size * gradient_norm**2
        if predicted_self_delta <= 0 or not math.isfinite(predicted_self_delta):
            raise RuntimeError(f"Source tag {source_tag} has an invalid first-order self-response prediction")
        observed_to_predicted_ratio = self_delta / predicted_self_delta
        linearity_relative_error = abs(self_delta - predicted_self_delta) / predicted_self_delta
        linearity_passed = linearity_relative_error <= max_self_linearity_relative_error
        if not linearity_passed:
            raise RuntimeError(
                f"Source tag {source_tag} self-response relative error {linearity_relative_error} exceeds "
                f"{max_self_linearity_relative_error}"
            )
        source_normalized_responses.append(row)
        responses.append(
            {
                "source_tag": source_tag,
                "source_objective": source_objective,
                "gradient_norm": gradient_norm,
                "updated_objectives": updated_objectives,
                "deltas": deltas,
                "self_delta": self_delta,
                "first_order_predicted_self_delta": predicted_self_delta,
                "observed_to_predicted_self_ratio": observed_to_predicted_ratio,
                "self_linearity_relative_error": linearity_relative_error,
                "self_linearity_passed": linearity_passed,
                "normalized_transfer": row,
                "parameters_restored_bit_exactly": True,
                "baseline_objectives_recovered": True,
                "baseline_sentinel_logits_recovered": True,
            }
        )
        model.zero_grad(set_to_none=True)

    finite_step_kernel = [
        [source_normalized_responses[source_tag][target_tag] for source_tag in range(TAG_COUNT)]
        for target_tag in range(TAG_COUNT)
    ]
    ordering = finite_step_ordering_check(
        analytic_kernel,
        finite_step_kernel,
        margin=ordering_margin,
        minimum_pairs_per_source=minimum_ordering_pairs_per_source,
    )
    off_diagonal = [
        analytic_kernel[target_tag][source_tag]
        for target_tag in range(TAG_COUNT)
        for source_tag in range(TAG_COUNT)
        if target_tag != source_tag
    ]
    median_off_diagonal = statistics.median(off_diagonal)
    finite_off_diagonal = [
        finite_step_kernel[target_tag][source_tag]
        for target_tag in range(TAG_COUNT)
        for source_tag in range(TAG_COUNT)
        if target_tag != source_tag
    ]
    full_grid_eligible = median_off_diagonal <= max_median_off_diagonal and ordering["passed"]
    result = {
        "schema_version": SCHEMA_VERSION,
        "probe_id": PROBE_ID,
        "probe_manifest": {
            "path": str((probe_dir / MANIFEST_NAME).resolve()),
            "sha256": validated["manifest_sha256"],
        },
        "probe_dataset": {
            "path": str((probe_dir / DATASET_NAME).resolve()),
            "sha256": validated["dataset_sha256"],
        },
        "model": current_model_identity,
        "runtime": {
            "torch_version": torch.__version__,
            "cuda_device": torch.cuda.get_device_name(device),
            "dtype": "float32",
            "deterministic_algorithms": True,
            "step_size": step_size,
            "batch_size": batch_size,
            "recovery_atol": recovery_atol,
            "recovery_rtol": recovery_rtol,
            "minimum_self_delta": minimum_self_delta,
            "max_self_linearity_relative_error": max_self_linearity_relative_error,
            "ordering_margin": ordering_margin,
            "minimum_ordering_pairs_per_source": minimum_ordering_pairs_per_source,
            "max_median_off_diagonal": max_median_off_diagonal,
        },
        "objective": manifest["objective"],
        "baseline_objectives": baseline_objectives,
        "responses": responses,
        "kernel_orientation": KERNEL_ORIENTATION,
        "kernel": analytic_kernel,
        "analytic_cross_gradient_kernel": analytic_kernel,
        "finite_step_kernel": finite_step_kernel,
        "finite_step_ordering": ordering,
        "kernel_summary": {
            "median_off_diagonal": median_off_diagonal,
            "finite_step_median_off_diagonal": statistics.median(finite_off_diagonal),
            "off_diagonal_count": len(off_diagonal),
        },
        "decision": {
            "rule": DECISION_RULE,
            "analytic_median_off_diagonal_at_most_threshold": (
                median_off_diagonal <= max_median_off_diagonal
            ),
            "finite_step_ordering_passed": ordering["passed"],
            "full_grid_eligible": full_grid_eligible,
            "eligible_design": "full_30_arm_grid" if full_grid_eligible else "four_arm_smoke_screen",
        },
    }
    write_bytes_atomic(output_path, canonical_json_bytes(result, indent=2))
    validated_result = validate_kernel_result(probe_dir, output_path)
    if validated_result["result"] != result:
        raise RuntimeError("Kernel result changed during atomic write and validation")
    return {**validated_result, "already_complete": False}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="select and seal the CPU-only probe dataset")
    prepare.add_argument("--bank-root", type=Path, default=DEFAULT_BANK_ROOT)
    prepare.add_argument("--gold-source", type=Path, default=DEFAULT_GOLD_SOURCE)
    prepare.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--selection-seed", type=int, default=DEFAULT_SELECTION_SEED)
    prepare.add_argument("--pairs-per-stratum", type=int, default=DEFAULT_PAIRS_PER_STRATUM)
    prepare.add_argument("--dry-run", action="store_true")

    validate = subparsers.add_parser("validate", help="replay and validate a sealed probe dataset")
    validate.add_argument("--probe-dir", type=Path, required=True)

    validate_result = subparsers.add_parser("validate-result", help="validate a completed kernel result")
    validate_result.add_argument("--probe-dir", type=Path, required=True)
    validate_result.add_argument("--output", type=Path, required=True)

    run = subparsers.add_parser("run", help="run the reversible one-step GPU transfer probe")
    run.add_argument("--probe-dir", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--step-size", type=float, default=DEFAULT_STEP_SIZE)
    run.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    run.add_argument("--recovery-atol", type=float, default=DEFAULT_RECOVERY_ATOL)
    run.add_argument("--recovery-rtol", type=float, default=DEFAULT_RECOVERY_RTOL)
    run.add_argument("--minimum-self-delta", type=float, default=DEFAULT_MINIMUM_SELF_DELTA)
    run.add_argument(
        "--max-self-linearity-relative-error",
        type=float,
        default=DEFAULT_MAX_SELF_LINEARITY_RELATIVE_ERROR,
    )
    run.add_argument("--ordering-margin", type=float, default=DEFAULT_ORDERING_MARGIN)
    run.add_argument(
        "--minimum-ordering-pairs-per-source",
        type=int,
        default=DEFAULT_MIN_ORDERING_PAIRS_PER_SOURCE,
    )
    run.add_argument(
        "--max-median-off-diagonal",
        type=float,
        default=DEFAULT_MAX_MEDIAN_OFF_DIAGONAL,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        result = prepare_probe(
            bank_root=args.bank_root,
            gold_source=args.gold_source,
            model_path=args.model,
            output_dir=args.output_dir,
            selection_seed=args.selection_seed,
            pairs_per_stratum=args.pairs_per_stratum,
            dry_run=args.dry_run,
        )
        manifest = result["manifest"]
        summary = {
            "command": args.command,
            "dry_run": args.dry_run,
            "already_prepared": result["already_prepared"],
            "pairs": manifest["selection"]["pairs"],
            "tagged_pairs": manifest["selection"]["tagged_pairs"],
            "dataset": manifest["dataset"],
            "manifest_path": manifest["manifest_path"],
            "manifest_sha256": result["manifest_sha256"],
        }
    elif args.command == "validate":
        result = validate_probe(args.probe_dir)
        summary = {
            "command": args.command,
            "pairs": result["manifest"]["selection"]["pairs"],
            "manifest_sha256": result["manifest_sha256"],
            "dataset_sha256": result["dataset_sha256"],
        }
    elif args.command == "validate-result":
        result = validate_kernel_result(args.probe_dir, args.output)
        summary = {
            "command": args.command,
            "output": str(args.output.expanduser().resolve()),
            "output_sha256": result["output_sha256"],
            "median_off_diagonal": result["result"]["kernel_summary"]["median_off_diagonal"],
            "finite_step_ordering_passed": result["result"]["decision"]["finite_step_ordering_passed"],
            "eligible_design": result["result"]["decision"]["eligible_design"],
        }
    else:
        result = run_kernel_probe(
            probe_dir=args.probe_dir,
            output_path=args.output,
            step_size=args.step_size,
            batch_size=args.batch_size,
            recovery_atol=args.recovery_atol,
            recovery_rtol=args.recovery_rtol,
            minimum_self_delta=args.minimum_self_delta,
            max_self_linearity_relative_error=args.max_self_linearity_relative_error,
            ordering_margin=args.ordering_margin,
            minimum_ordering_pairs_per_source=args.minimum_ordering_pairs_per_source,
            max_median_off_diagonal=args.max_median_off_diagonal,
        )
        summary = {
            "command": args.command,
            "output": str(args.output.expanduser().resolve()),
            "output_sha256": result["output_sha256"],
            "already_complete": result["already_complete"],
            "kernel": result["result"]["kernel"],
            "kernel_orientation": result["result"]["kernel_orientation"],
            "median_off_diagonal": result["result"]["kernel_summary"]["median_off_diagonal"],
            "finite_step_ordering_passed": result["result"]["decision"]["finite_step_ordering_passed"],
            "eligible_design": result["result"]["decision"]["eligible_design"],
        }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
