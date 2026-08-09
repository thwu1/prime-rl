#!/usr/bin/env python3
"""Materialize the frozen causal calibration panel for the value-alias phase study."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import itertools
import json
import os
import shutil
import struct
import tempfile
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterator, Mapping

from alias_shortcut import AliasSubstitution
from datasets import Dataset
from transformers import AutoTokenizer
from value_alias_intervention import ValueAliasInterventionError, build_value_alias_intervention

from prime_rl.utils.chat_template import build_incremental_token_mask, strip_message_content

STUDY_ID = "verifier-defect-alias-phase-v1"
ARTIFACT_TYPE = "rsci_alias_phase_fresh_banks"
SELECTION_PROTOCOL = "value-alias-disjoint-bank-v1"
MASK_SELECTION_PROTOCOL = "value-alias-iterative-sft-v1"
SELECTION_SEED = 20260809
SCHEMA_VERSION = 2

OPERATIONS = tuple(range(21, 41))
TEMPLATES = ("crazy_zootopia", "movie_festival_awards", "teachers_in_school")
MODES = ("forwardreverse", "normalforward")
CELLS = tuple(itertools.product(TEMPLATES, MODES))
STRATA = tuple((operation, template, mode) for operation in OPERATIONS for template, mode in CELLS)

BANK_COUNT = 8
BANK_ROWS = 1_536
BASE_ROWS_PER_STRATUM = 12
EXTRA_ROWS_PER_BANK = 96
CLUSTER_ROWS_PER_BANK = 256
INITIAL_ALIAS_MASS = 34
SEQ_LEN = 2_048
BATCH_SIZE = 32
MICRO_BATCH_SIZE = 4
PROMPTS_PER_STEP = BATCH_SIZE // 2
OPTIMIZER_STEPS = BANK_ROWS // PROMPTS_PER_STEP
MICROBATCHES_PER_STEP = BATCH_SIZE // MICRO_BATCH_SIZE

EXPECTED_SOURCE_ROWS = 20_000
EXPECTED_VALIDATED_ALIASES = 19_536
EXPECTED_BOTH_FIT = 19_456
EXPECTED_EQUAL_LENGTH = 13_887
EXPECTED_AGGREGATE_ROWS = 31_000
EXPECTED_AGGREGATE_SIZE = 379_684_908
EXPECTED_TAIL_OFFSET = 99_749_928
EXPECTED_TAIL_SIZE = 279_934_980

EXPECTED_AGGREGATE_SHA256 = "59dd47898e1ba2e348f23c080b58f354ea56ea15a7bc39c33ac96aea5335afd8"
EXPECTED_DATASET_MANIFEST_SHA256 = "33ea14662ef788e3a2172444714b4733a8f43da8605889a48b77a60fa039b084"
EXPECTED_AUDIT_SHA256 = "db9ee735ccff23c4daea1f0ff5e50ea09843228c5b2181cbf4ae289b97e7bb1f"
EXPECTED_TAIL_SHA256 = "54c00e6782d526edab1a417b470f040763a16e7b4c9c8d9731738a83b01d7a73"
EXPECTED_CHAT_TEMPLATE_SHA256 = "cb97db7641ee1b373b28acc90c89dd7174a9efe9733038e6558a982ed7358832"
EXPECTED_EQUAL_LENGTH_CAPACITY_VECTOR_SHA256 = "f518f75af7a2324c67db49f7a0eab1f2e8bb1d42ed439c59f55ab789d38a94ee"
EXPECTED_CLUSTER_CELL = ("teachers_in_school", "normalforward")
EXPECTED_BANK_SEQUENCE_SHA256 = (
    "8c57a92b66db207b16a3b4f02519b70ee1862d1386d04a7bc7b83c705ab0a440",
    "1df95cbc3d3c8d467c0c020537a4725d25aef3b4010b221ca1fd35f6569fdaa2",
    "71cc4a3aca7325b009754fb22bdb68279b5e3e1f5c30cccf7aa465cf223bc80b",
    "9be70db3c73ffd92e805fef86567da543014bad8c06b43cc74951b81f9997f17",
    "73be075db828942ba8f3e3e9bce1eb3ddbfb1e7fc8675026aff392d059980dce",
    "fc38ad005006b10991d271d5fb059f949b6c8528a97136d42ac32046804c536e",
    "6fe0a5f65dd0c71954aaf85a83f0560c61c26d3e607044d6b7960fb1537ce702",
    "66f038bf881b4a23b6e2014b5ab3c12cd4feab99c9b5a3e08afac9b2faba04db",
)
EXPECTED_BANK_PROMPT_IDS_SHA256 = (
    "72243d0d085dac1a94b8a535f4d785445a2106870bb0536a8f1a3ea848a1894f",
    "a99c71ee116459c424e67174c76ffa8ef67ca4aa93feb81fb17a4d0dd5da57be",
    "34e842f3d12962f05bb6ca3d1ee5270a328b0d10b1beac4e05892b3fed1f5cff",
    "1342ab30e6a46b5290b213ee3efd5892dd9c21d4f497dc912610ec91c2d3a635",
    "c6796aecb251d1e88526a773bf956201aab9c2d1cf97e1f1456e96a51d34238d",
    "02ab8d93e353c79ae2d8d64d014f18f9cc856eeb5dd5cd28bd336ef2cf633c11",
    "65469b6deac404fe641aa871034238fc5dfeb6d63bc586472ad395c720d07f42",
    "beddecc8dd32a4c9ab91b004c93478f95585e94d05856b36e153d4530a3b970d",
)
EXPECTED_BANK_TOKEN_COUNTS_SHA256 = (
    "6ff4de864c3b8fe36acea71f04d820670457e9b300ea636b12c2ee32194102d9",
    "f25fa4b5b0d44f55fb49bdfbe2a60bd178b67cee74e998d898b51f4a07602636",
    "4dbe24e31e133e3ac083a6495273dd3ae1009f1a7f0d028e880f57b03e954e95",
    "baf001266341265ba27531e1bc4c1f5be925fcda5df89196d8eebbb35c485ede",
    "a4b5f820b1493d529c13beebbd2260ed87027fde47a3ececebbee9f4bd669f0a",
    "a8cdb7a7cc1ff35e980177061bfee7c430763df7f5ede884c819e9d5086d4a68",
    "ed1b6e8ceed6c04f7f8071e76de8f974f29ae4754804c30c5e4c7a92d46239d9",
    "2ff60a6affd85037022bd41ebe083bfe247f53ce98972f2902d051edc85c5471",
)
EXPECTED_SELECTED_PROMPT_IDS_SHA256 = "b72177f87ccd082bc8d22f55bd623d655ad0b72498b62cd0674823107f3c5827"
EXPECTED_UNUSED_PROMPT_IDS_SHA256 = "1ea8c4c11e7132d63f7e6964ceedc734a526ba61a605480421f744346a93de9a"
EXPECTED_QUOTA_MATRIX_SHA256 = "fade0a628b857b134c8ea5e0937ca8b6f1a3205f27f65f0d5578adf8c8f3411c"
EXPECTED_CLUSTER_MULTIPLIER_SHA256 = (
    "9791ff3a4e722ddce47897502c3df447d906d6a06c4b5cf1e42f1f1a53c22f34",
    "a708f9a016a8d6daf83b74b9b3c8ccec282c3a7b86b0587694dd766f5559f43d",
    "1e2800864f0c983f34ec44c6c504ca45cb3de17e60e531cfde14e5faa8fb2717",
    "f666de9ece15b3f05865d0b4bc7cfb299deb2bd4d5bff425645842fcfc0c02e2",
    "a3d656f4ac456034896ab104a272969715db85e56e4c3112e2ff7ccb649cab0f",
    "7759d02464d8ee55910d25498fb9d495b206f47b27ec159afe617cc8c3fb9416",
    "020303047bda0529dc85192ca5881c6152fcb47c49a0f5c0cc4b36dfd87f3616",
    "a17d080c4c52465c0a8eceb7eb0a7cb09f567ef17f545bd7472130a399673a12",
)
EXPECTED_OPERATION_STEP_GRAPH_SHA256 = (
    "d55c4e0d35bafdb1464fe449c0ebd3fb137e5733deb2359b1948961de6d33e20",
    "749b58ace9361a81fcc128fd68d90984ff75e4c386e4ac297b91dbb53aa6b0ff",
    "cc91bdf4455659f0fac1d6647286e511ee10c7761e440ec4c0dcf3ecc66a569b",
    "8a4a375aba27c203712d8f18e3f2c2b9f6b883a233c354367fd7ae1234918f06",
    "fa6607529f9b5371e0e84bc4fcc66e7a8ff56619d493ef1142c6db08fd350bc1",
    "e35bd1ce6bbc926264adfa0eb9a55f8e418d3f746a18759b27fea911666efbc8",
    "cce289d217ddec1a61c87065ecc7f2c90c2fbd3c23fd4fcf12a6a3453f967dd2",
    "f9092e8f3eeaa3d81cb75ea6d2b6e0e7fbbba82779b58dbaa80076d9bd08138a",
)
EXPECTED_STAGE0_PARQUET_SHA256 = "947f929b1d707c97ab8b1f3db415cd292acf720be0cdf71b8c4ff97d88899d29"

DEFAULT_INPUT_DIR = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k")
DEFAULT_OUTPUT_DIR = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect-alias-phase-v1/fresh-banks-v1")
DEFAULT_TOKENIZER = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
    "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/"
    "id2-10_0.2easy_0.3medium_0.5hard/base"
)


@dataclass(frozen=True)
class SourceState:
    input_dir: Path
    aggregate: dict[str, Any]
    dataset_manifest: dict[str, Any]
    audit: dict[str, Any]
    sources: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RenderedTarget:
    messages: list[dict[str, str]]
    model_input_tokens: int
    assistant_tokens: int
    token_ids_sha256: str


@dataclass(frozen=True)
class PanelCandidate:
    source_ordinal: int
    source_row_index: int
    sample_id: str
    operation: int
    template: str
    mode: str
    problem: str
    question: str
    prompt: str
    answer: str
    canonical_solution: str
    alias_solution: str
    canonical_assistant: str
    alias_assistant: str
    opportunity: AliasSubstitution
    clean_render: RenderedTarget
    alias_render: RenderedTarget
    panel_rank_sha256: str

    @property
    def stratum(self) -> tuple[int, str, str]:
        return (self.operation, self.template, self.mode)

    @property
    def cell(self) -> tuple[str, str]:
        return (self.template, self.mode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("materialize", "validate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
        subparser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
        subparser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
        subparser.add_argument("--chat-template", type=Path)
    return parser.parse_args()


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _stream_identity(path: Path) -> dict[str, Any]:
    requested = path.expanduser().absolute()
    resolved = requested.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    before_identity = (before.st_size, before.st_mtime_ns, before.st_ino)
    after_identity = (after.st_size, after.st_mtime_ns, after.st_ino)
    if before_identity != after_identity:
        raise ValueError(f"File changed while hashing: {resolved}")
    return {
        "path": str(requested),
        "resolved_path": str(resolved),
        "size_bytes": after.st_size,
        "sha256": digest.hexdigest(),
    }


def _require_identity(path: Path, expected_sha256: str, *, expected_size: int | None = None) -> dict[str, Any]:
    identity = _stream_identity(path)
    if identity["sha256"] != expected_sha256:
        raise ValueError(f"SHA-256 differs for {path}: expected={expected_sha256}, found={identity['sha256']}")
    if expected_size is not None and identity["size_bytes"] != expected_size:
        raise ValueError(f"Size differs for {path}: expected={expected_size}, found={identity['size_bytes']}")
    return identity


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank JSONL row at {path}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected a JSON object at {path}:{line_number}")
            yield line_number, value


def _validate_source_state(input_dir: Path) -> SourceState:
    input_dir = input_dir.expanduser().absolute().resolve()
    dataset_manifest_path = input_dir / "dataset_manifest.json"
    audit_path = input_dir / "audit.json"
    aggregate_path = input_dir / "train.jsonl"
    dataset_manifest_identity = _require_identity(
        dataset_manifest_path,
        EXPECTED_DATASET_MANIFEST_SHA256,
    )
    audit_identity = _require_identity(audit_path, EXPECTED_AUDIT_SHA256)
    aggregate_identity = _require_identity(
        aggregate_path,
        EXPECTED_AGGREGATE_SHA256,
        expected_size=EXPECTED_AGGREGATE_SIZE,
    )

    manifest = _read_json_object(dataset_manifest_path)
    audit = _read_json_object(audit_path)
    if manifest.get("schema_version") != 1 or audit.get("schema_version") != 1:
        raise ValueError("Pinned dataset manifest and audit must use schema version 1")
    train_record = manifest.get("files", {}).get("train")
    if not isinstance(train_record, dict):
        raise ValueError("Dataset manifest has no train-file record")
    if (
        train_record.get("rows") != EXPECTED_AGGREGATE_ROWS
        or train_record.get("sha256") != EXPECTED_AGGREGATE_SHA256
        or Path(str(train_record.get("path"))).resolve() != aggregate_path
    ):
        raise ValueError("Dataset manifest train-file authority differs")
    if manifest.get("audit", {}).get("sha256") != EXPECTED_AUDIT_SHA256:
        raise ValueError("Dataset manifest audit authority differs")
    train_protocol = manifest.get("protocol", {}).get("train")
    if not isinstance(train_protocol, dict) or train_protocol.get("operations") != list(range(10, 41)):
        raise ValueError("Dataset manifest training operations differ")
    if train_protocol.get("rows") != EXPECTED_AGGREGATE_ROWS or train_protocol.get("rows_per_operation") != 1_000:
        raise ValueError("Dataset manifest training row counts differ")

    source_records = manifest.get("sources")
    if not isinstance(source_records, list):
        raise ValueError("Dataset manifest has no source list")
    by_operation: dict[int, dict[str, Any]] = {}
    identities = []
    for record in source_records:
        if not isinstance(record, dict):
            raise ValueError("Dataset source record is not an object")
        operation = record.get("operation")
        if operation not in OPERATIONS or record.get("split") != "train":
            continue
        if operation in by_operation:
            raise ValueError(f"Duplicate source authority for OP{operation}")
        expected_data = (input_dir / "sources" / f"op{operation}" / "train.jsonl").resolve()
        expected_manifest = (input_dir / "sources" / f"op{operation}" / "manifest.json").resolve()
        data = Path(str(record.get("data"))).resolve()
        source_manifest = Path(str(record.get("manifest"))).resolve()
        if data != expected_data or source_manifest != expected_manifest:
            raise ValueError(f"OP{operation} source paths differ from the fixed layout")
        if record.get("rows") != 1_000:
            raise ValueError(f"OP{operation} source row count differs")
        data_sha256 = record.get("data_sha256")
        manifest_sha256 = record.get("manifest_sha256")
        if not isinstance(data_sha256, str) or not isinstance(manifest_sha256, str):
            raise ValueError(f"OP{operation} source identities are invalid")
        data_identity = _require_identity(data, data_sha256)
        source_manifest_identity = _require_identity(source_manifest, manifest_sha256)
        by_operation[operation] = record
        identities.append(
            {
                "operation": operation,
                "rows": 1_000,
                "data": data_identity,
                "manifest": source_manifest_identity,
            }
        )
    if tuple(sorted(by_operation)) != OPERATIONS:
        raise ValueError(f"Expected exactly OP21-40 source authorities, found {sorted(by_operation)}")

    return SourceState(
        input_dir=input_dir,
        aggregate=aggregate_identity,
        dataset_manifest=dataset_manifest_identity,
        audit=audit_identity,
        sources=tuple(sorted(identities, key=lambda item: item["operation"])),
    )


def _copy_population(source_state: SourceState, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True)
    with destination.open("xb") as output:
        for source in source_state.sources:
            with Path(source["data"]["resolved_path"]).open("rb") as input_handle:
                shutil.copyfileobj(input_handle, output, length=1024 * 1024)
    identity = _require_identity(
        destination,
        EXPECTED_TAIL_SHA256,
        expected_size=EXPECTED_TAIL_SIZE,
    )

    aggregate_path = Path(source_state.aggregate["resolved_path"])
    with aggregate_path.open("rb") as aggregate, destination.open("rb") as population:
        aggregate.seek(EXPECTED_TAIL_OFFSET)
        while True:
            expected = population.read(1024 * 1024)
            observed = aggregate.read(len(expected))
            if observed != expected:
                raise ValueError("Materialized OP21-40 population is not the aggregate's exact byte tail")
            if not expected:
                break
        if aggregate.read(1):
            raise ValueError("Aggregate training file has bytes after the expected OP21-40 tail")
    return {**identity, "rows": EXPECTED_SOURCE_ROWS}


def _split_solution(solution: str) -> tuple[str, str]:
    if not isinstance(solution, str) or "Answer:" not in solution:
        raise ValueError("Canonical solution has no Answer: marker")
    body, answer = solution.rsplit("Answer:", 1)
    normalized_answer = answer.strip().splitlines()[0].strip().rstrip(".")
    if not body.strip() or not normalized_answer:
        raise ValueError("Canonical solution body or answer is empty")
    return body.strip(), normalized_answer


def _assistant(solution: str) -> tuple[str, str]:
    body, answer = _split_solution(solution)
    return f"<solution>{body} </solution> <answer> {answer} </answer>", answer


def _render_target(tokenizer: Any, prompt: str, assistant: str) -> RenderedTarget:
    messages = strip_message_content(
        [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant},
        ]
    )
    token_ids, token_mask = build_incremental_token_mask(
        tokenizer,
        messages,
        role_to_mask=lambda message: message.get("role") == "assistant",
        collapse_consecutive_tool_messages=True,
    )
    if tokenizer.eos_token_id is None:
        raise ValueError("Pinned tokenizer has no EOS token")
    if tokenizer.eos_token_id not in token_ids:
        token_ids.append(int(tokenizer.eos_token_id))
        token_mask.append(True)
    if len(token_ids) != len(token_mask):
        raise RuntimeError("Tokenizer IDs and assistant mask have different lengths")
    model_input_tokens = len(token_ids) - 1
    assistant_tokens = sum(token_mask[1:])
    if model_input_tokens <= 0 or assistant_tokens <= 0:
        raise ValueError("Rendered target has no model input or assistant loss tokens")
    return RenderedTarget(
        messages=messages,
        model_input_tokens=model_input_tokens,
        assistant_tokens=assistant_tokens,
        token_ids_sha256=canonical_json_sha256(token_ids),
    )


def _tokenizer_identity(tokenizer_path: Path, chat_template_path: Path, tokenizer: Any) -> dict[str, Any]:
    relevant_names = (
        "added_tokens.json",
        "chat_template.jinja",
        "merges.txt",
        "special_tokens_map.json",
        "spiece.model",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer_config.json",
        "vocab.json",
    )
    files = {}
    for name in relevant_names:
        path = tokenizer_path / name
        if path.is_file():
            files[name] = _stream_identity(path)
    chat_template_identity = _require_identity(chat_template_path, EXPECTED_CHAT_TEMPLATE_SHA256)
    if not files:
        raise ValueError("Pinned tokenizer directory has no recognized tokenizer files")
    return {
        "configured_path": str(tokenizer_path),
        "class": type(tokenizer).__name__,
        "eos_token_id": tokenizer.eos_token_id,
        "chat_template": chat_template_identity,
        "files": files,
    }


def _validate_source_row(row: dict[str, Any], operation: int, row_index: int) -> None:
    required = {
        "answer",
        "completion",
        "id",
        "messages",
        "mode",
        "op",
        "problem",
        "question",
        "solution",
        "template",
    }
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"OP{operation} row {row_index} is missing {missing}")
    if row["op"] != operation:
        raise ValueError(f"OP{operation} row {row_index} reports operation {row['op']!r}")
    if row["template"] not in TEMPLATES or row["mode"] not in MODES:
        raise ValueError(f"OP{operation} row {row_index} has an invalid template/mode")
    for name in ("answer", "completion", "id", "problem", "question", "solution"):
        if not isinstance(row[name], str) or not row[name].strip():
            raise ValueError(f"OP{operation} row {row_index} has an invalid {name}")


def _rank_material(candidate: PanelCandidate) -> list[Any]:
    return [
        SELECTION_PROTOCOL,
        SELECTION_SEED,
        "bank-pool-row",
        candidate.operation,
        candidate.template,
        candidate.mode,
        candidate.sample_id,
        candidate.opportunity.to_dict(),
    ]


def _collect_candidates(
    source_state: SourceState,
    tokenizer: Any,
) -> tuple[list[PanelCandidate], dict[str, Any]]:
    candidates = []
    counts: Counter[str] = Counter()
    length_delta_counts: Counter[int] = Counter()
    capacities: Counter[tuple[int, str, str]] = Counter()
    seen_ids: set[str] = set()
    seen_prompts: set[str] = set()

    for source in source_state.sources:
        operation = int(source["operation"])
        source_path = Path(source["data"]["resolved_path"])
        observed_rows = 0
        for line_number, row in _iter_jsonl(source_path):
            row_index = line_number - 1
            _validate_source_row(row, operation, row_index)
            observed_rows += 1
            counts["source_rows"] += 1
            sample_id = row["id"]
            if sample_id in seen_ids:
                raise ValueError(f"Duplicate source sample ID: {sample_id}")
            seen_ids.add(sample_id)
            prompt = f"<question> {row['problem'].strip()} {row['question'].strip()} </question>"
            if prompt in seen_prompts:
                raise ValueError(f"Duplicate effective prompt: {sample_id}")
            seen_prompts.add(prompt)

            canonical_assistant, canonical_answer = _assistant(row["solution"])
            if canonical_answer != row["answer"].strip().rstrip("."):
                raise ValueError(f"OP{operation} row {row_index} answer differs from its solution")
            canonical_body, _ = _split_solution(row["solution"])
            expected_source_completion = f"{canonical_body} </solution> <answer> {canonical_answer} </answer>"
            if row["completion"].strip() != expected_source_completion:
                raise ValueError(f"OP{operation} row {row_index} completion differs from its solution")
            try:
                intervention = build_value_alias_intervention(row["solution"])
            except ValueAliasInterventionError:
                continue
            counts["validated_aliases"] += 1
            alias_assistant, alias_answer = _assistant(intervention.transformed_solution)
            if alias_answer != canonical_answer:
                raise RuntimeError(f"Value-alias intervention changed the answer for {sample_id}")
            clean_render = _render_target(tokenizer, prompt, canonical_assistant)
            alias_render = _render_target(tokenizer, prompt, alias_assistant)
            if clean_render.token_ids_sha256 == alias_render.token_ids_sha256:
                raise RuntimeError(f"Value-alias intervention is token-identical for {sample_id}")
            if clean_render.model_input_tokens <= SEQ_LEN and alias_render.model_input_tokens <= SEQ_LEN:
                counts["both_fit"] += 1
            else:
                continue
            delta = alias_render.model_input_tokens - clean_render.model_input_tokens
            if delta != alias_render.assistant_tokens - clean_render.assistant_tokens:
                raise RuntimeError(f"Input and assistant token deltas differ for {sample_id}")
            length_delta_counts[delta] += 1
            if delta != 0:
                continue
            counts["equal_length"] += 1
            source_ordinal = (operation - OPERATIONS[0]) * 1_000 + row_index
            candidate = PanelCandidate(
                source_ordinal=source_ordinal,
                source_row_index=row_index,
                sample_id=sample_id,
                operation=operation,
                template=row["template"],
                mode=row["mode"],
                problem=row["problem"].strip(),
                question=row["question"].strip(),
                prompt=prompt,
                answer=canonical_answer,
                canonical_solution=row["solution"],
                alias_solution=intervention.transformed_solution,
                canonical_assistant=canonical_assistant,
                alias_assistant=alias_assistant,
                opportunity=intervention.opportunity,
                clean_render=clean_render,
                alias_render=alias_render,
                panel_rank_sha256="",
            )
            candidate = replace(candidate, panel_rank_sha256=canonical_json_sha256(_rank_material(candidate)))
            candidates.append(candidate)
            capacities[candidate.stratum] += 1
        if observed_rows != 1_000:
            raise ValueError(f"OP{operation} source has {observed_rows} rows, expected 1000")

    expected_counts = {
        "source_rows": EXPECTED_SOURCE_ROWS,
        "validated_aliases": EXPECTED_VALIDATED_ALIASES,
        "both_fit": EXPECTED_BOTH_FIT,
        "equal_length": EXPECTED_EQUAL_LENGTH,
    }
    if {name: counts[name] for name in expected_counts} != expected_counts:
        raise ValueError(f"Pinned alias availability differs: expected={expected_counts}, found={dict(counts)}")
    if set(capacities) != set(STRATA):
        raise ValueError("Equal-length alias pool does not cover every operation/template/mode stratum")
    if min(capacities.values()) < BANK_COUNT * BASE_ROWS_PER_STRATUM:
        raise ValueError("Equal-length alias pool cannot support eight balanced banks")
    usable_extra_slots = sum(
        min(BANK_COUNT, capacity - BANK_COUNT * BASE_ROWS_PER_STRATUM) for capacity in capacities.values()
    )
    if usable_extra_slots < BANK_COUNT * EXTRA_ROWS_PER_BANK:
        raise ValueError("Equal-length alias pool cannot support the eight-bank extra-row allocation")
    capacity_vector_sha256 = canonical_json_sha256([[*stratum, capacities[stratum]] for stratum in STRATA])
    if capacity_vector_sha256 != EXPECTED_EQUAL_LENGTH_CAPACITY_VECTOR_SHA256:
        raise ValueError(
            "Equal-length capacity vector differs: "
            f"expected={EXPECTED_EQUAL_LENGTH_CAPACITY_VECTOR_SHA256}, found={capacity_vector_sha256}"
        )
    return candidates, {
        **expected_counts,
        "length_delta_histogram": {str(delta): count for delta, count in sorted(length_delta_counts.items())},
        "equal_length_capacity_by_stratum": {
            f"{operation}|{template}|{mode}": capacities[(operation, template, mode)]
            for operation, template, mode in STRATA
        },
        "equal_length_capacity_vector_sha256": capacity_vector_sha256,
    }


def _selection_hash(domain: str, *coordinates: object) -> str:
    return canonical_json_sha256([SELECTION_PROTOCOL, SELECTION_SEED, domain, *coordinates])


def choose_cluster_cell() -> tuple[str, str]:
    cell = min(
        CELLS,
        key=lambda candidate: (
            canonical_json_sha256([MASK_SELECTION_PROTOCOL, SELECTION_SEED, "cluster_cell", *candidate]),
            candidate,
        ),
    )
    if cell != EXPECTED_CLUSTER_CELL:
        raise RuntimeError(f"Cluster cell differs: expected={EXPECTED_CLUSTER_CELL}, found={cell}")
    return cell


@dataclass
class _FlowArc:
    target: int
    reverse: int
    residual: int
    initial: int


def _maximum_flow(
    node_count: int,
    source: int,
    sink: int,
    edges: list[tuple[int, int, int, object]],
) -> tuple[int, dict[object, int]]:
    adjacency: list[list[_FlowArc]] = [[] for _ in range(node_count)]
    references: dict[object, tuple[int, int]] = {}
    for start, target, capacity, key in edges:
        if capacity < 0 or key in references:
            raise ValueError("Flow edges require nonnegative capacities and unique keys")
        forward_index = len(adjacency[start])
        reverse_index = len(adjacency[target])
        adjacency[start].append(_FlowArc(target, reverse_index, capacity, capacity))
        adjacency[target].append(_FlowArc(start, forward_index, 0, 0))
        references[key] = (start, forward_index)

    total = 0
    while True:
        level = [-1] * node_count
        level[source] = 0
        pending = deque([source])
        while pending:
            node = pending.popleft()
            for arc in adjacency[node]:
                if arc.residual and level[arc.target] < 0:
                    level[arc.target] = level[node] + 1
                    pending.append(arc.target)
        if level[sink] < 0:
            break
        cursor = [0] * node_count

        def augment(node: int, available: int) -> int:
            if node == sink:
                return available
            while cursor[node] < len(adjacency[node]):
                arc = adjacency[node][cursor[node]]
                if arc.residual and level[arc.target] == level[node] + 1:
                    sent = augment(arc.target, min(available, arc.residual))
                    if sent:
                        arc.residual -= sent
                        adjacency[arc.target][arc.reverse].residual += sent
                        return sent
                cursor[node] += 1
            return 0

        while sent := augment(source, 2**63 - 1):
            total += sent

    used = {}
    for key, (start, index) in references.items():
        arc = adjacency[start][index]
        used[key] = arc.initial - arc.residual
    return total, used


def _complete_bank_omissions(
    bank_id: int,
    fixed: Mapping[tuple[str, str], set[int]],
) -> dict[tuple[str, str], set[int]] | None:
    omissions = {cell: set(fixed.get(cell, set())) for cell in CELLS}
    degrees = Counter(operation for operations in omissions.values() for operation in operations)
    if any(len(omissions[cell]) > 4 for cell in CELLS) or any(degrees[operation] > 2 for operation in OPERATIONS):
        return None

    def solve() -> bool:
        missing = [operation for operation in OPERATIONS if degrees[operation] == 0]
        if missing:
            operation = min(
                missing,
                key=lambda value: (
                    sum(len(omissions[cell]) < 4 and value not in omissions[cell] for cell in CELLS),
                    _selection_hash("bank-omission-operation", bank_id, value),
                    value,
                ),
            )
            cells = [cell for cell in CELLS if len(omissions[cell]) < 4 and operation not in omissions[cell]]
            cells.sort(
                key=lambda cell: (
                    -(4 - len(omissions[cell])),
                    _selection_hash("bank-omission-cell", bank_id, operation, *cell),
                    cell,
                )
            )
            for cell in cells:
                omissions[cell].add(operation)
                degrees[operation] += 1
                if solve():
                    return True
                degrees[operation] -= 1
                omissions[cell].remove(operation)
            return False

        remaining = 24 - sum(len(operations) for operations in omissions.values())
        if remaining == 0:
            return all(len(omissions[cell]) == 4 for cell in CELLS) and all(
                degrees[operation] in (1, 2) for operation in OPERATIONS
            )
        cell = max(
            (candidate for candidate in CELLS if len(omissions[candidate]) < 4),
            key=lambda candidate: (
                4 - len(omissions[candidate]),
                _selection_hash("bank-second-omission-cell", bank_id, *candidate),
                candidate,
            ),
        )
        operations = [
            operation for operation in OPERATIONS if degrees[operation] == 1 and operation not in omissions[cell]
        ]
        operations.sort(
            key=lambda operation: (
                _selection_hash("bank-second-omission-operation", bank_id, *cell, operation),
                operation,
            )
        )
        for operation in operations:
            omissions[cell].add(operation)
            degrees[operation] += 1
            if solve():
                return True
            degrees[operation] -= 1
            omissions[cell].remove(operation)
        return False

    return omissions if solve() else None


def bank_quotas(
    capacities: Mapping[tuple[int, str, str], int],
) -> list[dict[tuple[int, str, str], int]]:
    if set(capacities) != set(STRATA):
        raise ValueError("Bank capacity map has the wrong support")
    required = {
        stratum: max(0, BANK_COUNT * (BASE_ROWS_PER_STRATUM + 1) + 1 - capacities[stratum])
        for stratum in STRATA
    }
    if any(value > BANK_COUNT for value in required.values()):
        raise ValueError("Eligible pool cannot support eight twelve-row stratum bases")
    constrained = [stratum for stratum in STRATA if required[stratum]]
    constrained.sort(key=lambda stratum: (-required[stratum], _selection_hash("required-omission", *stratum)))
    fixed = [{cell: set() for cell in CELLS} for _ in range(BANK_COUNT)]

    def assign_required(index: int) -> list[dict[tuple[str, str], set[int]]] | None:
        if index == len(constrained):
            completed = [_complete_bank_omissions(bank_id, fixed[bank_id]) for bank_id in range(BANK_COUNT)]
            return None if any(value is None for value in completed) else completed  # type: ignore[return-value]
        operation, template, mode = constrained[index]
        cell = (template, mode)
        count = required[(operation, template, mode)]
        combinations = list(itertools.combinations(range(BANK_COUNT), count))
        combinations.sort(
            key=lambda banks: (
                _selection_hash("required-omission-banks", operation, template, mode, list(banks)),
                banks,
            )
        )
        for banks in combinations:
            if any(
                len(fixed[bank_id][cell]) >= 4
                or sum(operation in fixed[bank_id][candidate] for candidate in CELLS) >= 2
                for bank_id in banks
            ):
                continue
            for bank_id in banks:
                fixed[bank_id][cell].add(operation)
            solution = assign_required(index + 1)
            if solution is not None:
                return solution
            for bank_id in banks:
                fixed[bank_id][cell].remove(operation)
        return None

    omissions = assign_required(0)
    if omissions is None:
        raise RuntimeError("No deterministic eight-bank quota allocation exists")
    quotas = []
    for bank_id, bank_omissions in enumerate(omissions):
        quota = {
            stratum: BASE_ROWS_PER_STRATUM + int(stratum[0] not in bank_omissions[stratum[1:]])
            for stratum in STRATA
        }
        operation_totals = {
            operation: sum(quota[(operation, *cell)] for cell in CELLS) for operation in OPERATIONS
        }
        cell_totals = {cell: sum(quota[(operation, *cell)] for operation in OPERATIONS) for cell in CELLS}
        if sum(quota.values()) != BANK_ROWS or sorted(operation_totals.values()) != [76] * 4 + [77] * 16:
            raise RuntimeError(f"Bank {bank_id} operation quotas differ")
        if set(cell_totals.values()) != {CLUSTER_ROWS_PER_BANK}:
            raise RuntimeError(f"Bank {bank_id} cell quotas differ")
        quotas.append(quota)
    for stratum in STRATA:
        if sum(quota[stratum] for quota in quotas) >= capacities[stratum]:
            raise RuntimeError(f"Bank quotas do not retain one unused eligible prompt in {stratum}")
    return quotas


def select_banks(
    candidates: list[PanelCandidate],
) -> tuple[list[list[PanelCandidate]], list[dict[tuple[int, str, str], int]]]:
    by_stratum: dict[tuple[int, str, str], list[PanelCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_stratum[candidate.stratum].append(candidate)
    capacities = {stratum: len(by_stratum[stratum]) for stratum in STRATA}
    quotas = bank_quotas(capacities)
    allocation_order = sorted(
        range(BANK_COUNT),
        key=lambda bank_id: (_selection_hash("bank-allocation-order", bank_id), bank_id),
    )
    banks = [[] for _ in range(BANK_COUNT)]
    for stratum in STRATA:
        ranked = sorted(
            by_stratum[stratum],
            key=lambda candidate: (candidate.panel_rank_sha256, candidate.sample_id),
        )
        offset = 0
        for bank_id in allocation_order:
            count = quotas[bank_id][stratum]
            banks[bank_id].extend(ranked[offset : offset + count])
            offset += count
    selected_ids = [candidate.sample_id for bank in banks for candidate in bank]
    if len(selected_ids) != BANK_COUNT * BANK_ROWS or len(set(selected_ids)) != len(selected_ids):
        raise RuntimeError("Selected banks are not eight disjoint 1536-prompt sets")
    return banks, quotas


def _connected_operation_step_graph(pairs: set[tuple[int, int]]) -> bool:
    graph: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    for operation, step in pairs:
        operation_node = ("operation", operation)
        step_node = ("step", step)
        graph[operation_node].add(step_node)
        graph[step_node].add(operation_node)
    start = ("operation", OPERATIONS[0])
    visited = {start}
    pending = [start]
    while pending:
        node = pending.pop()
        for neighbor in graph[node] - visited:
            visited.add(neighbor)
            pending.append(neighbor)
    return len(visited) == len(OPERATIONS) + OPTIMIZER_STEPS


def _operation_step_design(
    bank: list[PanelCandidate],
    bank_id: int,
) -> tuple[dict[int, list[int]], dict[int, list[int]], dict[tuple[int, int], int], int]:
    cluster_cell = choose_cluster_cell()
    cluster_counts = Counter(candidate.operation for candidate in bank if candidate.cell == cluster_cell)
    operation_counts = Counter(candidate.operation for candidate in bank)
    three_steps = set(
        sorted(
            range(OPTIMIZER_STEPS),
            key=lambda step: (_selection_hash("three-cluster-step", bank_id, step), step),
        )[:64]
    )
    step_degrees = {step: 2 + int(step in three_steps) for step in range(OPTIMIZER_STEPS)}
    if sum(cluster_counts.values()) != CLUSTER_ROWS_PER_BANK or sum(step_degrees.values()) != CLUSTER_ROWS_PER_BANK:
        raise RuntimeError("Cluster scheduling margins differ")

    operation_node = {operation: 1 + index for index, operation in enumerate(OPERATIONS)}
    step_node = {step: 1 + len(OPERATIONS) + step for step in range(OPTIMIZER_STEPS)}
    sink = 1 + len(OPERATIONS) + OPTIMIZER_STEPS
    for attempt in range(256):
        edges: list[tuple[int, int, int, object]] = []
        for operation in sorted(
            OPERATIONS,
            key=lambda value: (_selection_hash("cluster-flow-operation", bank_id, attempt, value), value),
        ):
            edges.append((0, operation_node[operation], cluster_counts[operation], ("source", operation)))
            steps = sorted(
                range(OPTIMIZER_STEPS),
                key=lambda step: (
                    _selection_hash("cluster-flow-edge", bank_id, attempt, operation, step),
                    step,
                ),
            )
            edges.extend(
                (operation_node[operation], step_node[step], 1, ("pair", operation, step)) for step in steps
            )
        edges.extend(
            (step_node[step], sink, step_degrees[step], ("sink", step)) for step in range(OPTIMIZER_STEPS)
        )
        flow, used = _maximum_flow(sink + 1, 0, sink, edges)
        if flow != CLUSTER_ROWS_PER_BANK:
            continue
        pairs = {
            (operation, step)
            for operation in OPERATIONS
            for step in range(OPTIMIZER_STEPS)
            if used[("pair", operation, step)]
        }
        if not _connected_operation_step_graph(pairs):
            continue

        multiplier_edges: list[tuple[int, int, int, object]] = []
        for step in range(OPTIMIZER_STEPS):
            residual = 16 - 4 * step_degrees[step]
            multiplier_edges.append((0, step_node[step], residual, ("multiplier-source", step)))
            operations = sorted(
                (operation for operation in OPERATIONS if (operation, step) in pairs),
                key=lambda operation: (
                    _selection_hash("multiplier-edge", bank_id, attempt, step, operation),
                    operation,
                ),
            )
            multiplier_edges.extend(
                (step_node[step], operation_node[operation], 5, ("multiplier", operation, step))
                for operation in operations
            )
        for operation in OPERATIONS:
            residual = operation_counts[operation] - 4 * cluster_counts[operation]
            multiplier_edges.append(
                (operation_node[operation], sink, residual, ("multiplier-sink", operation))
            )
        multiplier_flow, multiplier_used = _maximum_flow(sink + 1, 0, sink, multiplier_edges)
        if multiplier_flow != 512:
            continue
        cluster_by_step = {
            step: sorted(operation for operation in OPERATIONS if (operation, step) in pairs)
            for step in range(OPTIMIZER_STEPS)
        }
        multipliers = {
            pair: 4 + multiplier_used[("multiplier", *pair)]
            for pair in pairs
        }
        if any(
            sum(multipliers[(operation, step)] for operation in cluster_by_step[step]) != 16
            for step in cluster_by_step
        ):
            raise RuntimeError("Cluster multiplier step margins differ")
        if any(
            sum(multipliers[(operation, step)] for step in range(OPTIMIZER_STEPS) if (operation, step) in pairs)
            != operation_counts[operation]
            for operation in OPERATIONS
        ):
            raise RuntimeError("Cluster multiplier operation margins differ")

        filler_edges: list[tuple[int, int, int, object]] = []
        for operation in sorted(
            OPERATIONS,
            key=lambda value: (_selection_hash("filler-flow-operation", bank_id, attempt, value), value),
        ):
            filler_edges.append(
                (
                    0,
                    operation_node[operation],
                    operation_counts[operation] - cluster_counts[operation],
                    ("filler-source", operation),
                )
            )
            steps = sorted(
                (step for step in range(OPTIMIZER_STEPS) if (operation, step) not in pairs),
                key=lambda step: (
                    _selection_hash("filler-flow-edge", bank_id, attempt, operation, step),
                    step,
                ),
            )
            filler_edges.extend(
                (operation_node[operation], step_node[step], 1, ("filler", operation, step)) for step in steps
            )
        filler_edges.extend(
            (
                step_node[step],
                sink,
                PROMPTS_PER_STEP - step_degrees[step],
                ("filler-sink", step),
            )
            for step in range(OPTIMIZER_STEPS)
        )
        filler_flow, filler_used = _maximum_flow(sink + 1, 0, sink, filler_edges)
        if filler_flow != BANK_ROWS - CLUSTER_ROWS_PER_BANK:
            continue
        filler_by_step = {
            step: sorted(
                operation
                for operation in OPERATIONS
                if (operation, step) not in pairs and filler_used[("filler", operation, step)]
            )
            for step in range(OPTIMIZER_STEPS)
        }
        if any(
            len(cluster_by_step[step]) + len(filler_by_step[step]) != PROMPTS_PER_STEP
            or len(set(cluster_by_step[step]) | set(filler_by_step[step])) != PROMPTS_PER_STEP
            for step in range(OPTIMIZER_STEPS)
        ):
            raise RuntimeError("Full operation-step schedule is not sixteen-way simple")
        return cluster_by_step, filler_by_step, multipliers, attempt
    raise RuntimeError(f"No connected exact cluster schedule exists for bank {bank_id}")


def schedule_bank(
    bank: list[PanelCandidate],
    bank_id: int,
) -> tuple[list[PanelCandidate], dict[str, int], dict[str, Any]]:
    if len(bank) != BANK_ROWS or len({candidate.sample_id for candidate in bank}) != BANK_ROWS:
        raise ValueError("Bank schedule requires 1536 unique prompts")
    cluster_cell = choose_cluster_cell()
    by_operation: dict[int, list[PanelCandidate]] = defaultdict(list)
    for candidate in bank:
        if candidate.cell == cluster_cell:
            by_operation[candidate.operation].append(candidate)
    cluster_operation_steps, filler_operation_steps, pair_multipliers, attempt = _operation_step_design(bank, bank_id)
    cluster_by_step: dict[int, list[PanelCandidate]] = defaultdict(list)
    filler_by_step: dict[int, list[PanelCandidate]] = defaultdict(list)
    multipliers: dict[str, int] = {}
    for operation in OPERATIONS:
        prompts = sorted(
            by_operation[operation],
            key=lambda candidate: (
                _selection_hash("cluster-prompt-order", bank_id, operation, candidate.sample_id),
                candidate.sample_id,
            ),
        )
        steps = sorted(
            (step for step, operations in cluster_operation_steps.items() if operation in operations),
            key=lambda step: (_selection_hash("cluster-step-order", bank_id, operation, step), step),
        )
        if len(prompts) != len(steps):
            raise RuntimeError(f"Cluster prompt-step margin differs for bank {bank_id}, OP{operation}")
        for prompt, step in zip(prompts, steps, strict=True):
            cluster_by_step[step].append(prompt)
            multipliers[prompt.sample_id] = pair_multipliers[(operation, step)]

    for operation in OPERATIONS:
        prompts = sorted(
            (
                candidate
                for candidate in bank
                if candidate.operation == operation and candidate.cell != cluster_cell
            ),
            key=lambda candidate: (
                _selection_hash("filler-prompt-order", bank_id, operation, candidate.sample_id),
                candidate.sample_id,
            ),
        )
        steps = sorted(
            (step for step, operations in filler_operation_steps.items() if operation in operations),
            key=lambda step: (_selection_hash("filler-step-order", bank_id, operation, step), step),
        )
        if len(prompts) != len(steps):
            raise RuntimeError(f"Filler prompt-step margin differs for bank {bank_id}, OP{operation}")
        for prompt, step in zip(prompts, steps, strict=True):
            filler_by_step[step].append(prompt)

    ordered = []
    for step in range(OPTIMIZER_STEPS):
        prompts = [*cluster_by_step[step], *filler_by_step[step]]
        prompts.sort(
            key=lambda candidate: (
                _selection_hash("bank-step-prompt-order", bank_id, step, candidate.sample_id),
                candidate.sample_id,
            )
        )
        ordered.extend(prompts)
    if Counter(candidate.sample_id for candidate in ordered) != Counter(
        candidate.sample_id for candidate in bank
    ):
        raise RuntimeError(f"Bank {bank_id} schedule changed prompt membership")

    step_cluster_counts = [
        sum(candidate.cell == cluster_cell for candidate in ordered[step * 16 : (step + 1) * 16])
        for step in range(OPTIMIZER_STEPS)
    ]
    if sorted(step_cluster_counts) != [2] * 32 + [3] * 64:
        raise RuntimeError(f"Bank {bank_id} cluster step counts differ")
    multiplier_counts = Counter(multipliers.values())
    summary = {
        "flow_attempt": attempt,
        "cluster_step_count_vector": step_cluster_counts,
        "cluster_step_count_vector_sha256": canonical_json_sha256(step_cluster_counts),
        "cluster_multiplier_histogram": {str(value): multiplier_counts[value] for value in sorted(multiplier_counts)},
        "cluster_multiplier_vector_sha256": canonical_json_sha256(
            [[candidate.sample_id, multipliers.get(candidate.sample_id, 0)] for candidate in ordered]
        ),
        "operation_step_graph_sha256": canonical_json_sha256(
            [
                [step, cluster_operation_steps[step], filler_operation_steps[step]]
                for step in range(OPTIMIZER_STEPS)
            ]
        ),
    }
    return ordered, multipliers, summary


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row))
            handle.write("\n")
    return {**_stream_identity(path), "rows": len(rows)}


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"Refusing to write an empty Parquet dataset: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    Dataset.from_list(rows).to_parquet(path)
    return {**_stream_identity(path), "rows": len(rows)}


def _relative_identity(root: Path, path: Path, *, rows: int | None = None) -> dict[str, Any]:
    identity = _stream_identity(path)
    result = {
        "path": str(path.relative_to(root)),
        "size_bytes": identity["size_bytes"],
        "sha256": identity["sha256"],
    }
    if rows is not None:
        result["rows"] = rows
    return result


def _implementation_identities() -> dict[str, Any]:
    directory = Path(__file__).resolve().parent
    repository_root = directory.parents[2]
    expected_script = repository_root / "user" / "tianhaowu" / "rsci" / Path(__file__).name
    if expected_script.resolve() != Path(__file__).resolve():
        raise ValueError("Panel materializer is outside the expected repository-relative layout")
    chat_template_source = inspect.getsourcefile(build_incremental_token_mask)
    if chat_template_source is None:
        raise ValueError("Cannot resolve the incremental-mask implementation")
    paths = {
        "materializer": Path(__file__).resolve(),
        "preregistration": directory / "configs" / "sft" / "alias_phase_v1" / "PREREGISTRATION.md",
        "alias_phase_core": directory / "alias_phase_core.py",
        "strict_surface_guard": directory / "strict_surface_guard.py",
        "value_alias_intervention": directory / "value_alias_intervention.py",
        "alias_shortcut": directory / "alias_shortcut.py",
        "solution_graph": directory / "solution_graph.py",
        "strict_trajectory_grader": directory / "strict_trajectory_grader.py",
        "incremental_chat_mask": Path(chat_template_source).resolve(),
        "sft_config": repository_root / "packages" / "prime-rl-configs" / "src" / "prime_rl" / "configs" / "sft.py",
        "sft_data": repository_root / "src" / "prime_rl" / "trainer" / "sft" / "data.py",
        "sft_loss": repository_root / "src" / "prime_rl" / "trainer" / "sft" / "loss.py",
        "sft_train": repository_root / "src" / "prime_rl" / "trainer" / "sft" / "train.py",
        "root_lockfile": repository_root / "uv.lock",
    }
    identities = {}
    for name, path in paths.items():
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(repository_root)
        except ValueError as error:
            raise ValueError(f"Implementation {name} is outside the repository source tree: {resolved}") from error
        identity = _stream_identity(resolved)
        identities[name] = {
            "path": str(relative),
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        }
    return identities


def _fraction_record(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _float32(value: float) -> float:
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _bank_record(
    candidate: PanelCandidate,
    bank_id: int,
    prompt_index: int,
    *,
    cluster_multiplier: int,
    cluster_cell: tuple[str, str],
) -> dict[str, Any]:
    cluster_alias_mass = Fraction(cluster_multiplier * INITIAL_ALIAS_MASS, BANK_ROWS)
    return {
        "bank_id": bank_id,
        "prompt_index": prompt_index,
        "source_ordinal": candidate.source_ordinal,
        "source_row_index": candidate.source_row_index,
        "sample_id": candidate.sample_id,
        "op": candidate.operation,
        "template": candidate.template,
        "mode": candidate.mode,
        "problem": candidate.problem,
        "question": candidate.question,
        "prompt": candidate.prompt,
        "answer": candidate.answer,
        "canonical_solution": candidate.canonical_solution,
        "alias_solution": candidate.alias_solution,
        "canonical_assistant": candidate.canonical_assistant,
        "alias_assistant": candidate.alias_assistant,
        "opportunity": candidate.opportunity.to_dict(),
        "pool_rank_sha256": candidate.panel_rank_sha256,
        "optimizer_step": prompt_index // PROMPTS_PER_STEP,
        "prompt_slot_in_step": prompt_index % PROMPTS_PER_STEP,
        "pair_row_indices": [2 * prompt_index, 2 * prompt_index + 1],
        "pair_microbatch": (2 * prompt_index) // MICRO_BATCH_SIZE,
        "model_input_tokens": candidate.clean_render.model_input_tokens,
        "assistant_tokens": candidate.clean_render.assistant_tokens,
        "canonical_token_ids_sha256": candidate.clean_render.token_ids_sha256,
        "alias_token_ids_sha256": candidate.alias_render.token_ids_sha256,
        "exact_token_count_match": True,
        "cluster_mask": candidate.cell == cluster_cell,
        "cluster_multiplier": cluster_multiplier,
        "cluster_alias_mass": _fraction_record(cluster_alias_mass),
    }


def _paired_row(
    candidate: PanelCandidate,
    prompt_index: int,
    *,
    alias_target: bool,
    cluster_multiplier: int,
    cluster_cell: tuple[str, str],
) -> dict[str, Any]:
    rendered = candidate.alias_render if alias_target else candidate.clean_render
    messages = candidate.alias_render.messages if alias_target else candidate.clean_render.messages
    target_solution = candidate.alias_solution if alias_target else candidate.canonical_solution
    diffuse_alias_mass = Fraction(INITIAL_ALIAS_MASS, BANK_ROWS)
    clustered_alias_mass = Fraction(cluster_multiplier * INITIAL_ALIAS_MASS, BANK_ROWS)
    masses = {
        "strict": Fraction(int(not alias_target), 1),
        "diffuse": diffuse_alias_mass if alias_target else 1 - diffuse_alias_mass,
        "clustered": clustered_alias_mass if alias_target else 1 - clustered_alias_mass,
    }
    return {
        "messages": messages,
        **{
            f"{arm}_sft_weight": float(mass / rendered.assistant_tokens)
            for arm, mass in masses.items()
        },
        **{f"{arm}_mixture_mass": float(mass) for arm, mass in masses.items()},
        "prompt_index": prompt_index,
        "pair_row_index": 2 * prompt_index + int(alias_target),
        "optimizer_step": prompt_index // PROMPTS_PER_STEP,
        "microbatch_in_step": ((2 * prompt_index) % BATCH_SIZE) // MICRO_BATCH_SIZE,
        "prompt_id": candidate.sample_id,
        "trajectory_id": f"alias_phase_{canonical_json_sha256([candidate.sample_id, alias_target])[:24]}",
        "op": candidate.operation,
        "template": candidate.template,
        "mode": candidate.mode,
        "source_ordinal": candidate.source_ordinal,
        "model_input_tokens": rendered.model_input_tokens,
        "assistant_tokens": rendered.assistant_tokens,
        "rendered_token_ids_sha256": rendered.token_ids_sha256,
        "canonical_token_ids_sha256": candidate.clean_render.token_ids_sha256,
        "alias_token_ids_sha256": candidate.alias_render.token_ids_sha256,
        "target_solution_sha256": hashlib.sha256(target_solution.encode()).hexdigest(),
        "target_kind": "alias" if alias_target else "canonical",
        "strict_target": not alias_target,
        "alias_target": alias_target,
        "cluster_mask": candidate.cell == cluster_cell,
        "cluster_multiplier": cluster_multiplier,
        "alias_child": candidate.opportunity.child,
        "alias_omitted_parent": candidate.opportunity.omitted_parent,
        "alias_added_parent": candidate.opportunity.added_parent,
        "alias_shared_value": candidate.opportunity.shared_value,
    }


def _stage0_manifest(
    rows: list[dict[str, Any]],
    *,
    bank_sequence_sha256: str,
    cluster_cell: tuple[str, str],
    parquet_identity: dict[str, Any],
) -> dict[str, Any]:
    if len(rows) != 2 * BANK_ROWS:
        raise ValueError("Stage-0 paired dataset must contain two rows per prompt")
    prompt_ids = [rows[index]["prompt_id"] for index in range(0, len(rows), 2)]
    if any(
        rows[index]["prompt_id"] != rows[index + 1]["prompt_id"]
        or rows[index]["target_kind"] != "canonical"
        or rows[index + 1]["target_kind"] != "alias"
        for index in range(0, len(rows), 2)
    ):
        raise RuntimeError("Stage-0 rows are not adjacent canonical/alias prompt pairs")

    arm_summaries = {}
    alias_rows = [row for row in rows if row["alias_target"]]
    prompt_operation_counts = Counter(rows[index]["op"] for index in range(0, len(rows), 2))
    for arm in ("strict", "diffuse", "clustered"):
        weight_column = f"{arm}_sft_weight"
        mass_column = f"{arm}_mixture_mass"
        assistant_mass = sum(row[weight_column] * row["assistant_tokens"] for row in rows)
        alias_mass = sum(row[mass_column] for row in alias_rows)
        step_alias_mass = [
            sum(row[mass_column] for row in alias_rows if row["optimizer_step"] == step)
            for step in range(OPTIMIZER_STEPS)
        ]
        operation_alias_mass = {
            str(operation): sum(row[mass_column] for row in alias_rows if row["op"] == operation)
            for operation in OPERATIONS
        }
        runtime_assistant_mass = sum(
            _float32(row[weight_column]) * row["assistant_tokens"] for row in rows
        )
        runtime_alias_mass = sum(
            _float32(row[weight_column]) * row["assistant_tokens"] for row in alias_rows
        )
        runtime_step_alias_mass = [
            sum(
                _float32(row[weight_column]) * row["assistant_tokens"]
                for row in alias_rows
                if row["optimizer_step"] == step
            )
            for step in range(OPTIMIZER_STEPS)
        ]
        runtime_operation_alias_mass = {
            str(operation): sum(
                _float32(row[weight_column]) * row["assistant_tokens"]
                for row in alias_rows
                if row["op"] == operation
            )
            for operation in OPERATIONS
        }
        runtime_pair_mass_error = max(
            abs(
                sum(
                    _float32(rows[index + offset][weight_column])
                    * rows[index + offset]["assistant_tokens"]
                    for offset in (0, 1)
                )
                - 1
            )
            for index in range(0, len(rows), 2)
        )
        expected_alias_mass = 0 if arm == "strict" else INITIAL_ALIAS_MASS
        if abs(alias_mass - expected_alias_mass) > 1e-10 or abs(assistant_mass - BANK_ROWS) > 1e-9:
            raise RuntimeError(f"Stage-0 {arm} weighted masses differ")
        if arm != "strict" and any(
            abs(value - INITIAL_ALIAS_MASS / OPTIMIZER_STEPS) > 1e-12 for value in step_alias_mass
        ):
            raise RuntimeError(f"Stage-0 {arm} optimizer-step alias masses differ")
        expected_runtime_step_mass = 0 if arm == "strict" else float(Fraction(17, 48))
        max_runtime_step_error = max(
            abs(value - expected_runtime_step_mass) for value in runtime_step_alias_mass
        )
        max_runtime_operation_error = max(
            abs(
                runtime_operation_alias_mass[str(operation)]
                - (
                    0
                    if arm == "strict"
                    else float(Fraction(17 * prompt_operation_counts[operation], 768))
                )
            )
            for operation in OPERATIONS
        )
        if (
            abs(runtime_assistant_mass - BANK_ROWS) > 1e-4
            or abs(runtime_alias_mass - expected_alias_mass) > 1e-5
            or max_runtime_step_error > 1e-6
            or max_runtime_operation_error > 1e-6
            or runtime_pair_mass_error > 1e-6
        ):
            raise RuntimeError(f"Stage-0 {arm} float32 quantization exceeds its frozen tolerance")
        arm_summaries[arm] = {
            "weight_column": weight_column,
            "assistant_weight_mass": assistant_mass,
            "alias_mixture_mass": alias_mass,
            "canonical_mixture_mass": BANK_ROWS - alias_mass,
            "optimizer_step_alias_mass_vector": step_alias_mass,
            "optimizer_step_alias_mass_vector_sha256": canonical_json_sha256(step_alias_mass),
            "alias_mass_by_operation": operation_alias_mass,
            "runtime_float32": {
                "assistant_weight_mass": runtime_assistant_mass,
                "alias_mixture_mass": runtime_alias_mass,
                "optimizer_step_alias_mass_vector": runtime_step_alias_mass,
                "alias_mass_by_operation": runtime_operation_alias_mass,
                "max_prompt_pair_mass_error": runtime_pair_mass_error,
                "max_optimizer_step_alias_mass_error": max_runtime_step_error,
                "max_operation_alias_mass_error": max_runtime_operation_error,
            },
        }
    runtime_operation_discrepancy = max(
        abs(
            arm_summaries["diffuse"]["runtime_float32"]["alias_mass_by_operation"][str(operation)]
            - arm_summaries["clustered"]["runtime_float32"]["alias_mass_by_operation"][str(operation)]
        )
        for operation in OPERATIONS
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": STUDY_ID,
        "kind": "stage0_paired_soft_mixture",
        "rows": len(rows),
        "prompts": BANK_ROWS,
        "canonical_rows": BANK_ROWS,
        "alias_rows": BANK_ROWS,
        "cluster_mask_prompts": CLUSTER_ROWS_PER_BANK,
        "cluster_cell": {"template": cluster_cell[0], "mode": cluster_cell[1]},
        "initial_alias_mass": INITIAL_ALIAS_MASS,
        "global_alias_fraction": _fraction_record(Fraction(INITIAL_ALIAS_MASS, BANK_ROWS)),
        "cluster_local_alias_fraction": _fraction_record(Fraction(INITIAL_ALIAS_MASS, CLUSTER_ROWS_PER_BANK)),
        "runtime_float32_max_diffuse_clustered_operation_discrepancy": runtime_operation_discrepancy,
        "arms": arm_summaries,
        "max_model_input_tokens": max(row["model_input_tokens"] for row in rows),
        "max_assistant_tokens": max(row["assistant_tokens"] for row in rows),
        "ordered_prompt_ids_sha256": canonical_json_sha256(prompt_ids),
        "bank_sequence_sha256": bank_sequence_sha256,
        "parquet": parquet_identity,
        "sft_contract": {
            "data.pack_function": "fixed_stack",
            "data.batch_size": BATCH_SIZE,
            "data.micro_batch_size": MICRO_BATCH_SIZE,
            "data.seq_len": SEQ_LEN,
            "data.shuffle": False,
            "data.weight_column_by_arm": {
                arm: f"{arm}_sft_weight" for arm in ("strict", "diffuse", "clustered")
            },
            "loss_impl": "torch",
            "optimizer": "adamw",
            "learning_rate": 0.0001,
            "scheduler": "constant",
            "max_steps": OPTIMIZER_STEPS,
            "world_size": 1,
            "examples_per_step": BATCH_SIZE,
            "examples_consumed": 2 * BANK_ROWS,
            "dataset_passes": 1,
            "duplicate_or_wrap_examples": 0,
        },
    }


def _build_staging(
    staging: Path,
    *,
    input_dir: Path,
    tokenizer_path: Path,
    chat_template_path: Path,
) -> dict[str, Any]:
    source_before = _validate_source_state(input_dir)
    population_path = staging / "population" / "op21-40.jsonl"
    population_identity = _copy_population(source_before, population_path)

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    tokenizer.chat_template = chat_template_path.read_text(encoding="utf-8")
    tokenizer_identity = _tokenizer_identity(tokenizer_path, chat_template_path, tokenizer)
    candidates, availability = _collect_candidates(source_before, tokenizer)
    bank_members, quotas = select_banks(candidates)
    cluster_cell = choose_cluster_cell()
    scheduled_banks = []
    bank_multipliers = []
    bank_files = []
    bank_summaries = []
    bank_sequence_hashes = []
    bank_prompt_hashes = []
    bank_token_hashes = []
    all_selected_ids = set()
    for bank_id, members in enumerate(bank_members):
        bank, multipliers, schedule = schedule_bank(members, bank_id)
        overlap = all_selected_ids & {candidate.sample_id for candidate in bank}
        if overlap:
            raise RuntimeError(f"Bank {bank_id} overlaps an earlier bank")
        all_selected_ids.update(candidate.sample_id for candidate in bank)
        records = [
            _bank_record(
                candidate,
                bank_id,
                prompt_index,
                cluster_multiplier=multipliers.get(candidate.sample_id, 0),
                cluster_cell=cluster_cell,
            )
            for prompt_index, candidate in enumerate(bank)
        ]
        bank_path = staging / "banks" / f"bank-{bank_id}.jsonl"
        written = _write_jsonl(bank_path, records)
        identity = _relative_identity(staging, bank_path, rows=written["rows"])
        sequence_sha256 = canonical_json_sha256(
            [[candidate.sample_id, candidate.opportunity.to_dict()] for candidate in bank]
        )
        prompt_ids_sha256 = canonical_json_sha256([candidate.sample_id for candidate in bank])
        token_counts_sha256 = canonical_json_sha256(
            [[candidate.clean_render.model_input_tokens, candidate.clean_render.assistant_tokens] for candidate in bank]
        )
        operation_counts = Counter(candidate.operation for candidate in bank)
        cell_counts = Counter(f"{candidate.template}|{candidate.mode}" for candidate in bank)
        quota_vector = [[*stratum, quotas[bank_id][stratum]] for stratum in STRATA]
        bank_summary = {
            "bank_id": bank_id,
            "role": (
                "stage0_train"
                if bank_id == 0
                else "final_readout"
                if bank_id == BANK_COUNT - 1
                else f"round_{bank_id}_train_and_teacher_{bank_id - 1}_readout"
            ),
            "rows": BANK_ROWS,
            "cluster_cell": {"template": cluster_cell[0], "mode": cluster_cell[1]},
            "cluster_rows": sum(candidate.cell == cluster_cell for candidate in bank),
            "counts_by_operation": {
                str(operation): operation_counts[operation] for operation in OPERATIONS
            },
            "counts_by_cell": {cell: cell_counts[cell] for cell in sorted(cell_counts)},
            "quota_vector_sha256": canonical_json_sha256(quota_vector),
            "sequence_sha256": sequence_sha256,
            "prompt_ids_sha256": prompt_ids_sha256,
            "token_counts_sha256": token_counts_sha256,
            "schedule": schedule,
            "file": identity,
        }
        scheduled_banks.append(bank)
        bank_multipliers.append(multipliers)
        bank_files.append(identity)
        bank_summaries.append(bank_summary)
        bank_sequence_hashes.append(sequence_sha256)
        bank_prompt_hashes.append(prompt_ids_sha256)
        bank_token_hashes.append(token_counts_sha256)

    expected_sequences = (
        EXPECTED_BANK_SEQUENCE_SHA256,
        EXPECTED_BANK_PROMPT_IDS_SHA256,
        EXPECTED_BANK_TOKEN_COUNTS_SHA256,
    )
    observed_sequences = (
        tuple(bank_sequence_hashes),
        tuple(bank_prompt_hashes),
        tuple(bank_token_hashes),
    )
    if any(expected_sequences) and expected_sequences != observed_sequences:
        raise RuntimeError("Fresh-bank sequence identities differ from the frozen authority")

    selected_prompt_ids_sha256 = canonical_json_sha256(sorted(all_selected_ids))
    unused_ids = sorted(candidate.sample_id for candidate in candidates if candidate.sample_id not in all_selected_ids)
    unused_prompt_ids_sha256 = canonical_json_sha256(unused_ids)
    candidate_counts = Counter(candidate.stratum for candidate in candidates)
    unused_by_stratum = {
        stratum: candidate_counts[stratum] - sum(quota[stratum] for quota in quotas) for stratum in STRATA
    }
    if min(unused_by_stratum.values()) < 1:
        raise RuntimeError("Fresh banks do not retain an eligible prompt in every stratum")
    quota_matrix_sha256 = canonical_json_sha256(
        [
            [[*stratum, quotas[bank_id][stratum]] for stratum in STRATA]
            for bank_id in range(BANK_COUNT)
        ]
    )
    multiplier_hashes = tuple(summary["schedule"]["cluster_multiplier_vector_sha256"] for summary in bank_summaries)
    operation_step_hashes = tuple(summary["schedule"]["operation_step_graph_sha256"] for summary in bank_summaries)
    frozen_scalar_identities = {
        "selected_prompt_ids_sha256": (EXPECTED_SELECTED_PROMPT_IDS_SHA256, selected_prompt_ids_sha256),
        "unused_prompt_ids_sha256": (EXPECTED_UNUSED_PROMPT_IDS_SHA256, unused_prompt_ids_sha256),
        "quota_matrix_sha256": (EXPECTED_QUOTA_MATRIX_SHA256, quota_matrix_sha256),
    }
    for name, (expected, observed) in frozen_scalar_identities.items():
        if expected and expected != observed:
            raise RuntimeError(f"Fresh-bank {name} differs: expected={expected}, found={observed}")
    if EXPECTED_CLUSTER_MULTIPLIER_SHA256 and EXPECTED_CLUSTER_MULTIPLIER_SHA256 != multiplier_hashes:
        raise RuntimeError("Fresh-bank cluster multiplier identities differ")
    if EXPECTED_OPERATION_STEP_GRAPH_SHA256 and EXPECTED_OPERATION_STEP_GRAPH_SHA256 != operation_step_hashes:
        raise RuntimeError("Fresh-bank operation-step identities differ")

    stage0_rows = []
    for prompt_index, candidate in enumerate(scheduled_banks[0]):
        multiplier = bank_multipliers[0].get(candidate.sample_id, 0)
        stage0_rows.extend(
            _paired_row(
                candidate,
                prompt_index,
                alias_target=alias_target,
                cluster_multiplier=multiplier,
                cluster_cell=cluster_cell,
            )
            for alias_target in (False, True)
        )
    stage0_parquet_path = staging / "stage0" / "paired" / "train-00000-of-00001.parquet"
    stage0_written = _write_parquet(stage0_parquet_path, stage0_rows)
    stage0_parquet_identity = _relative_identity(
        staging,
        stage0_parquet_path,
        rows=stage0_written["rows"],
    )
    if stage0_parquet_identity["sha256"] != EXPECTED_STAGE0_PARQUET_SHA256:
        raise RuntimeError(
            "Stage-0 paired Parquet differs: "
            f"expected={EXPECTED_STAGE0_PARQUET_SHA256}, found={stage0_parquet_identity['sha256']}"
        )
    stage0_manifest = _stage0_manifest(
        stage0_rows,
        bank_sequence_sha256=bank_sequence_hashes[0],
        cluster_cell=cluster_cell,
        parquet_identity=stage0_parquet_identity,
    )
    stage0_manifest_path = staging / "stage0" / "paired" / "manifest.json"
    _write_json(stage0_manifest_path, stage0_manifest)
    stage0_manifest_identity = _relative_identity(staging, stage0_manifest_path)

    source_after = _validate_source_state(input_dir)
    if source_before != source_after:
        raise RuntimeError("Pinned source state changed during materialization")
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "claim_scope": {
            "causal_calibration_panel": True,
            "training_outcome": False,
            "phase_transition_outcome": False,
            "generalization_outcome": False,
        },
        "source_authority": {
            "kind": "fixed-byte authority",
            "generation_provenance_complete": False,
            "provenance_caveat": (
                "Aggregate and per-operation bytes/manifests are pinned and mutually checked, but the original "
                "uncommitted generator implementation and prime-rl commit were not bound by the aggregate manifest."
            ),
            "aggregate": source_before.aggregate,
            "dataset_manifest": source_before.dataset_manifest,
            "audit": source_before.audit,
            "sources": list(source_before.sources),
            "exact_op21_40_tail": {
                "aggregate_byte_range": [EXPECTED_TAIL_OFFSET, EXPECTED_AGGREGATE_SIZE],
                "rows": EXPECTED_SOURCE_ROWS,
                "size_bytes": EXPECTED_TAIL_SIZE,
                "sha256": EXPECTED_TAIL_SHA256,
            },
        },
        "protocol": {
            "selection_protocol": SELECTION_PROTOCOL,
            "mask_selection_protocol": MASK_SELECTION_PROTOCOL,
            "selection_seed": SELECTION_SEED,
            "operations": list(OPERATIONS),
            "templates": list(TEMPLATES),
            "modes": list(MODES),
            "seq_len": SEQ_LEN,
            "bank_count": BANK_COUNT,
            "bank_rows": BANK_ROWS,
            "selected_rows": BANK_COUNT * BANK_ROWS,
            "base_rows_per_bank_operation_template_mode": BASE_ROWS_PER_STRATUM,
            "extra_rows_per_bank": EXTRA_ROWS_PER_BANK,
            "cluster_rows_per_bank": CLUSTER_ROWS_PER_BANK,
            "stage0_alias_mass": INITIAL_ALIAS_MASS,
            "stage0_global_alias_fraction": _fraction_record(Fraction(INITIAL_ALIAS_MASS, BANK_ROWS)),
            "user_format": "<question> {problem.strip()} {question.strip()} </question>",
            "assistant_format": "<solution>{body.strip()} </solution> <answer> {answer} </answer>",
            "render_contract": (
                "strip_message_content; pinned chat template; build_incremental_token_mask; append EOS iff absent; "
                "model_input_tokens=len(token_ids)-1; assistant_tokens=sum(token_mask[1:])"
            ),
            "eligibility": (
                "validated single-edge value-alias intervention; clean and alias render <=2048; exact equality of "
                "model-input-token and assistant-loss-token counts"
            ),
            "fresh_bank_law": (
                "bank 0 trains Stage 0; teacher r reads fresh bank r+1; promoted rounds 1..6 train banks 1..6; "
                "teacher 6 is read only on bank 7; no prompt is used for training twice"
            ),
        },
        "availability": availability,
        "design": {
            "cluster_cell": {"template": cluster_cell[0], "mode": cluster_cell[1]},
            "banks_are_pairwise_disjoint": True,
            "selected_prompt_ids_sha256": selected_prompt_ids_sha256,
            "unused_eligible_prompts": len(unused_ids),
            "unused_prompt_ids_sha256": unused_prompt_ids_sha256,
            "minimum_unused_per_stratum": min(unused_by_stratum.values()),
            "bank_sequence_sha256": bank_sequence_hashes,
            "bank_prompt_ids_sha256": bank_prompt_hashes,
            "bank_token_counts_sha256": bank_token_hashes,
            "quota_matrix_sha256": quota_matrix_sha256,
            "cluster_multiplier_sha256": list(multiplier_hashes),
            "operation_step_graph_sha256": list(operation_step_hashes),
            "banks": bank_summaries,
            "stage0": stage0_manifest,
        },
        "tokenizer": tokenizer_identity,
        "implementations": _implementation_identities(),
        "files": {
            "population": _relative_identity(staging, population_path, rows=population_identity["rows"]),
            "banks": bank_files,
            "stage0": {
                "parquet": stage0_parquet_identity,
                "manifest": stage0_manifest_identity,
            },
        },
        "stage0": stage0_manifest,
    }
    manifest["payload_without_self_hash_sha256"] = canonical_json_sha256(manifest)
    _write_json(staging / "manifest.json", manifest)
    return manifest


def materialize(
    *,
    input_dir: Path,
    output_dir: Path,
    tokenizer_path: Path,
    chat_template_path: Path,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().absolute()
    input_dir = input_dir.expanduser().absolute()
    tokenizer_path = tokenizer_path.expanduser().absolute().resolve()
    chat_template_path = chat_template_path.expanduser().absolute().resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.with_name(f".{output_dir.name}.materialize.lock")
    with lock_path.open("x", encoding="utf-8") as lock:
        lock.write(f"pid={os.getpid()}\n")
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{output_dir.name}.materialize-",
            dir=output_dir.parent,
        ) as temporary:
            staging = Path(temporary) / "artifact"
            staging.mkdir()
            manifest = _build_staging(
                staging,
                input_dir=input_dir,
                tokenizer_path=tokenizer_path,
                chat_template_path=chat_template_path,
            )
            if output_dir.exists():
                raise FileExistsError(output_dir)
            staging.replace(output_dir)
    finally:
        lock_path.unlink(missing_ok=True)
    return manifest


def _verify_self_hash(manifest: dict[str, Any]) -> None:
    claimed = manifest.get("payload_without_self_hash_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise ValueError("Panel manifest has no valid self hash")
    unsigned = dict(manifest)
    del unsigned["payload_without_self_hash_sha256"]
    actual = canonical_json_sha256(unsigned)
    if actual != claimed:
        raise ValueError(f"Panel manifest self hash differs: claimed={claimed}, actual={actual}")


def _iter_file_records(files: dict[str, Any]) -> Iterator[dict[str, Any]]:
    population = files.get("population")
    banks = files.get("banks")
    stage0 = files.get("stage0")
    if set(files) != {"population", "banks", "stage0"}:
        raise ValueError("Panel manifest output inventory is invalid")
    if not isinstance(population, dict) or not isinstance(banks, list) or not isinstance(stage0, dict):
        raise ValueError("Panel manifest output inventory is invalid")
    if len(banks) != BANK_COUNT or not all(isinstance(bank, dict) for bank in banks):
        raise ValueError("Panel manifest bank output inventory differs")
    if set(stage0) != {"manifest", "parquet"}:
        raise ValueError("Panel manifest Stage-0 output inventory differs")
    yield population
    yield from banks
    yield stage0["manifest"]
    yield stage0["parquet"]


def _validate_inventory(output_dir: Path, manifest: dict[str, Any]) -> None:
    expected_paths = {"manifest.json"}
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Panel manifest has no file inventory")
    for record in _iter_file_records(files):
        if not isinstance(record, dict):
            raise ValueError("Panel manifest file record is not an object")
        relative = record.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError(f"Panel manifest has an invalid relative path: {relative!r}")
        path = (output_dir / relative).resolve()
        if output_dir.resolve() not in path.parents:
            raise ValueError(f"Panel manifest path escapes its output root: {relative}")
        expected_paths.add(relative)
        identity = _stream_identity(path)
        if identity["size_bytes"] != record.get("size_bytes") or identity["sha256"] != record.get("sha256"):
            raise ValueError(f"Panel output identity differs: {relative}")
        rows = record.get("rows")
        if rows is not None and (isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0):
            raise ValueError(f"Panel output row count is invalid: {relative}")
    observed_paths = {str(path.relative_to(output_dir)) for path in output_dir.rglob("*") if path.is_file()}
    if observed_paths != expected_paths:
        raise ValueError(
            f"Panel output inventory differs: missing={sorted(expected_paths - observed_paths)}, "
            f"extra={sorted(observed_paths - expected_paths)}"
        )
    stage0 = manifest.get("stage0")
    if not isinstance(stage0, dict):
        raise ValueError("Panel manifest Stage-0 record differs")
    stage0_path = output_dir / files["stage0"]["manifest"]["path"]
    if _read_json_object(stage0_path) != stage0:
        raise ValueError("Root and standalone Stage-0 manifests differ")
    bank_summaries = manifest.get("design", {}).get("banks")
    if not isinstance(bank_summaries, list) or len(bank_summaries) != BANK_COUNT:
        raise ValueError("Panel manifest bank summaries differ")
    if any(summary.get("file") != files["banks"][bank_id] for bank_id, summary in enumerate(bank_summaries)):
        raise ValueError("Panel manifest bank file identities differ")


def _compare_trees(expected: Path, observed: Path) -> None:
    expected_files = {
        str(path.relative_to(expected)): _stream_identity(path)["sha256"]
        for path in expected.rglob("*")
        if path.is_file()
    }
    observed_files = {
        str(path.relative_to(observed)): _stream_identity(path)["sha256"]
        for path in observed.rglob("*")
        if path.is_file()
    }
    if expected_files != observed_files:
        differing = sorted(
            relative
            for relative in expected_files.keys() & observed_files.keys()
            if expected_files[relative] != observed_files[relative]
        )
        raise ValueError(
            "Full panel replay differs: "
            f"missing={sorted(expected_files.keys() - observed_files.keys())}, "
            f"extra={sorted(observed_files.keys() - expected_files.keys())}, "
            f"content={differing}"
        )


def validate(
    *,
    input_dir: Path,
    output_dir: Path,
    tokenizer_path: Path,
    chat_template_path: Path,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().absolute().resolve()
    manifest_path = output_dir / "manifest.json"
    manifest = _read_json_object(manifest_path)
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("artifact_type") != ARTIFACT_TYPE
        or manifest.get("study_id") != STUDY_ID
    ):
        raise ValueError("Panel manifest header differs")
    _verify_self_hash(manifest)
    _validate_inventory(output_dir, manifest)
    if manifest.get("implementations") != _implementation_identities():
        raise ValueError("Panel implementation identities differ")
    if manifest.get("tokenizer", {}).get("chat_template", {}).get("sha256") != EXPECTED_CHAT_TEMPLATE_SHA256:
        raise ValueError("Panel chat-template identity differs")

    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.replay-",
        dir=output_dir.parent,
    ) as temporary:
        replay = Path(temporary) / "artifact"
        replay.mkdir()
        replay_manifest = _build_staging(
            replay,
            input_dir=input_dir.expanduser().absolute(),
            tokenizer_path=tokenizer_path.expanduser().absolute().resolve(),
            chat_template_path=chat_template_path.expanduser().absolute().resolve(),
        )
        if replay_manifest != manifest:
            raise ValueError("Replayed panel manifest differs before byte comparison")
        _compare_trees(output_dir, replay)
    return manifest


def main() -> None:
    args = parse_args()
    tokenizer_path = args.tokenizer.expanduser().absolute().resolve()
    chat_template_path = (
        args.chat_template.expanduser().absolute().resolve()
        if args.chat_template is not None
        else tokenizer_path / "chat_template.jinja"
    )
    if args.command == "materialize":
        manifest = materialize(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            tokenizer_path=tokenizer_path,
            chat_template_path=chat_template_path,
        )
    else:
        manifest = validate(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            tokenizer_path=tokenizer_path,
            chat_template_path=chat_template_path,
        )
    print(
        json.dumps(
            {
                "command": args.command,
                "output_dir": str(args.output_dir.expanduser().absolute()),
                "manifest_content_sha256": manifest["payload_without_self_hash_sha256"],
                "bank_sequence_sha256": manifest["design"]["bank_sequence_sha256"],
                "cluster_cell": manifest["design"]["cluster_cell"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
