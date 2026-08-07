#!/usr/bin/env python3
"""Materialize and independently validate the known-cost neutral-tag bank."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k/train.jsonl")
DEFAULT_TOKENIZER = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/hf/hub/"
    "models--Interplay-LM-Reasoning--extrapolation_rl/snapshots/"
    "4861bd030e6fb92d94be3a1cecab89c2fac4b94a/id2-10_0.2easy_0.3medium_0.5hard/base"
)
SCHEMA_VERSION = 1
ALGORITHM_ID = "rsci-known-cost-neutral-tag-sha-rank"
ALGORITHM_VERSION = 1
RANK_DOMAIN = "rsci-known-cost-neutral-tag-rank-v1"
MIN_OPERATION = 10
MAX_OPERATION = 40
ROWS_PER_OPERATION = 1000
TAG_COUNT = 6
TAG_PREFIXES = tuple(f"<rsci_context_{index}>\n" for index in range(TAG_COUNT))
TEMPLATE_ORDER = (
    "crazy_zootopia",
    "movie_festival_awards",
    "teachers_in_school",
)
TEMPLATE_INDEX = {template: index for index, template in enumerate(TEMPLATE_ORDER)}
TOKENIZER_ARTIFACT_NAMES = (
    "added_tokens.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
    "vocab.json",
)
IMPLEMENTATION_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_tagged_bank.py"


@dataclass(frozen=True)
class SourceRow:
    raw: bytes
    value: dict[str, Any]
    sample_id: str
    operation: int
    template: str
    prompt: str
    line_number: int


@dataclass(frozen=True)
class MaterializationPlan:
    output_bytes: bytes
    manifest: dict[str, Any]
    manifest_bytes: bytes


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _read_json_object_bytes(content: bytes, *, description: str) -> dict[str, Any]:
    decoded = content.decode("utf-8")
    value = json.loads(decoded, object_pairs_hook=_object_without_duplicate_keys)
    if not isinstance(value, dict):
        raise ValueError(f"{description} is not a JSON object")
    return value


def _read_source(path: Path) -> tuple[bytes, list[SourceRow]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    content = path.read_bytes()
    if not content:
        raise ValueError(f"Source JSONL is empty: {path}")
    raw_lines = content.splitlines(keepends=True)
    if b"".join(raw_lines) != content:
        raise RuntimeError("Source JSONL line splitting did not preserve its bytes")

    rows: list[SourceRow] = []
    ids: set[str] = set()
    prompts: set[str] = set()
    operation_counts: Counter[int] = Counter()
    templates: set[str] = set()
    for line_number, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            raise ValueError(f"Blank JSONL record at {path}:{line_number}")
        value = _read_json_object_bytes(raw, description=f"Source record {path}:{line_number}")
        required = {"id", "op", "template", "prompt", "problem"}
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"Source record {path}:{line_number} is missing fields: {missing}")
        if "neutral_tag_index" in value:
            raise ValueError(f"Source record {path}:{line_number} already has neutral_tag_index")

        raw_id = value["id"]
        if not isinstance(raw_id, str) or not raw_id:
            raise ValueError(f"Source record {path}:{line_number} has an invalid id")
        operation = value["op"]
        if isinstance(operation, bool) or not isinstance(operation, int):
            raise ValueError(f"Source record {path}:{line_number} has a non-integer op")
        template = value["template"]
        if not isinstance(template, str) or template not in TEMPLATE_INDEX:
            raise ValueError(f"Source record {path}:{line_number} has an unknown template: {template!r}")
        prompt = value["prompt"]
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"Source record {path}:{line_number} has an invalid prompt")
        if not isinstance(value["problem"], str):
            raise ValueError(f"Source record {path}:{line_number} has a non-string problem")
        if raw_id in ids:
            raise ValueError(f"Source JSONL has a duplicate id: {raw_id}")
        if prompt in prompts:
            raise ValueError(f"Source JSONL has a duplicate prompt: {raw_id}")

        ids.add(raw_id)
        prompts.add(prompt)
        operation_counts[operation] += 1
        templates.add(template)
        rows.append(
            SourceRow(
                raw=raw,
                value=value,
                sample_id=raw_id,
                operation=operation,
                template=template,
                prompt=prompt,
                line_number=line_number,
            )
        )

    expected_operations = set(range(MIN_OPERATION, MAX_OPERATION + 1))
    if set(operation_counts) != expected_operations:
        raise ValueError(
            f"Expected exactly OP{MIN_OPERATION}-{MAX_OPERATION}, found {dict(sorted(operation_counts.items()))}"
        )
    invalid_counts = {operation: count for operation, count in operation_counts.items() if count != ROWS_PER_OPERATION}
    if invalid_counts:
        raise ValueError(
            f"Expected {ROWS_PER_OPERATION} rows per operation, found {dict(sorted(invalid_counts.items()))}"
        )
    if templates != set(TEMPLATE_ORDER):
        raise ValueError(f"Expected templates {list(TEMPLATE_ORDER)}, found {sorted(templates)}")
    return content, rows


def _rank_digest(block_seed: int, row: SourceRow) -> bytes:
    material = json.dumps(
        [RANK_DOMAIN, block_seed, row.operation, row.template, row.sample_id],
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).digest()


def _stratum_offset(block_seed: int, operation: int, template: str) -> int:
    return (operation - MIN_OPERATION + 2 * TEMPLATE_INDEX[template] + block_seed % TAG_COUNT) % TAG_COUNT


def assign_neutral_tags(
    rows: list[SourceRow], block_seed: int
) -> tuple[list[int], list[dict[str, Any]], dict[str, int]]:
    if isinstance(block_seed, bool) or not isinstance(block_seed, int) or block_seed < 0:
        raise ValueError("block_seed must be a non-negative integer")
    strata: dict[tuple[int, str], list[int]] = defaultdict(list)
    for row_index, row in enumerate(rows):
        strata[(row.operation, row.template)].append(row_index)

    assignments = [-1] * len(rows)
    stratum_records: list[dict[str, Any]] = []
    global_counts: Counter[int] = Counter()
    for (operation, template), row_indices in sorted(strata.items()):
        ranked = sorted(
            row_indices,
            key=lambda index: (
                _rank_digest(block_seed, rows[index]),
                rows[index].sample_id,
            ),
        )
        digests = [_rank_digest(block_seed, rows[index]) for index in ranked]
        if len(digests) != len(set(digests)):
            raise RuntimeError(f"SHA-256 rank collision in OP{operation}/{template}")
        offset = _stratum_offset(block_seed, operation, template)
        tag_counts: Counter[int] = Counter()
        for rank, row_index in enumerate(ranked):
            tag = (rank + offset) % TAG_COUNT
            assignments[row_index] = tag
            tag_counts[tag] += 1
            global_counts[tag] += 1
        counts = [tag_counts[index] for index in range(TAG_COUNT)]
        if max(counts) - min(counts) > 1:
            raise RuntimeError(f"Neutral-tag balance invariant failed in OP{operation}/{template}: {counts}")
        stratum_records.append(
            {
                "operation": operation,
                "template": template,
                "rows": len(ranked),
                "offset": offset,
                "tag_counts": {str(index): tag_counts[index] for index in range(TAG_COUNT)},
            }
        )
    if any(tag < 0 for tag in assignments):
        raise RuntimeError("At least one source row was not assigned a neutral tag")
    return assignments, stratum_records, {str(index): global_counts[index] for index in range(TAG_COUNT)}


def _inject_neutral_tag(raw: bytes, tag: int, *, line_number: int) -> bytes:
    if tag not in range(TAG_COUNT):
        raise ValueError(f"Invalid neutral tag at source line {line_number}: {tag}")
    closing_index = len(raw) - 1
    while closing_index >= 0 and raw[closing_index] in b" \t\r\n":
        closing_index -= 1
    if closing_index < 0 or raw[closing_index] != ord("}"):
        raise ValueError(f"Source line {line_number} does not end in a JSON object")
    addition = f',"neutral_tag_index":{tag}'.encode("ascii")
    return raw[:closing_index] + addition + raw[closing_index:]


def _file_identity_from_bytes(path: Path, content: bytes, rows: int) -> dict[str, Any]:
    return {
        "path": str(path.expanduser().resolve()),
        "sha256": bytes_sha256(content),
        "bytes": len(content),
        "rows": rows,
    }


def _tokenizer_file_identities(tokenizer_path: Path) -> list[dict[str, Any]]:
    identities = []
    for name in TOKENIZER_ARTIFACT_NAMES:
        path = tokenizer_path / name
        if not path.is_file():
            continue
        identities.append(
            {
                "name": name,
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    if not identities:
        raise ValueError(f"Pinned tokenizer directory has no recognized tokenizer artifacts: {tokenizer_path}")
    return identities


def tokenizer_facts(tokenizer_path: Path | None) -> dict[str, Any] | None:
    if tokenizer_path is None:
        return None
    from transformers import AutoTokenizer

    resolved = tokenizer_path.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    tokenizer = AutoTokenizer.from_pretrained(str(resolved), trust_remote_code=True)
    prefixes = []
    token_counts = []
    for index, prefix in enumerate(TAG_PREFIXES):
        token_ids = tokenizer.encode(prefix, add_special_tokens=False)
        if not all(isinstance(token_id, int) and not isinstance(token_id, bool) for token_id in token_ids):
            raise ValueError(f"Tokenizer returned invalid ids for neutral tag {index}")
        token_counts.append(len(token_ids))
        prefixes.append(
            {
                "index": index,
                "text": prefix,
                "utf8_sha256": bytes_sha256(prefix.encode("utf-8")),
                "token_ids": token_ids,
                "token_count": len(token_ids),
            }
        )
    if len(set(token_counts)) != 1:
        raise ValueError(f"Neutral-tag prefixes do not have equal token counts: {token_counts}")
    return {
        "path": str(resolved),
        "tokenizer_class": tokenizer.__class__.__name__,
        "vocab_size": int(tokenizer.vocab_size),
        "artifact_files": _tokenizer_file_identities(resolved),
        "prefixes": prefixes,
        "equal_token_counts": True,
        "common_token_count": token_counts[0],
    }


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_materialization_plan(
    *,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    block_seed: int,
    tokenizer_path: Path | None,
) -> MaterializationPlan:
    input_path = input_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    if len({input_path, output_path, manifest_path}) != 3:
        raise ValueError("input, output, and manifest paths must be distinct")

    input_bytes, rows = _read_source(input_path)
    assignments, strata, global_counts = assign_neutral_tags(rows, block_seed)
    output_lines = [
        _inject_neutral_tag(row.raw, tag, line_number=row.line_number)
        for row, tag in zip(rows, assignments, strict=True)
    ]
    output_bytes = b"".join(output_lines)
    if len(output_lines) != len(rows):
        raise RuntimeError("Output row count differs from the input row count")

    operation_counts = Counter(row.operation for row in rows)
    template_counts = Counter(row.template for row in rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "rsci_known_cost_neutral_tag_bank",
        "algorithm": {
            "id": ALGORITHM_ID,
            "version": ALGORITHM_VERSION,
            "rank_domain": RANK_DOMAIN,
            "rank_material": ["domain", "block_seed", "operation", "template", "sample_id"],
            "rank_tiebreaker": "sample_id",
            "tag_count": TAG_COUNT,
            "offset_formula": "(operation - 10 + 2 * template_index + block_seed % 6) % 6",
            "tag_formula": "(rank_within_stratum + offset) % 6",
            "template_order": list(TEMPLATE_ORDER),
            "output_transform": "insert integer neutral_tag_index immediately before each raw JSON object's closing brace",
        },
        "implementation": {
            "repository_path": IMPLEMENTATION_REPOSITORY_PATH,
            "sha256": bytes_sha256(Path(__file__).read_bytes()),
        },
        "block_seed": block_seed,
        "input": _file_identity_from_bytes(input_path, input_bytes, len(rows)),
        "output": _file_identity_from_bytes(output_path, output_bytes, len(rows)),
        "manifest_path": str(manifest_path),
        "source_contract": {
            "minimum_operation": MIN_OPERATION,
            "maximum_operation": MAX_OPERATION,
            "rows_per_operation": ROWS_PER_OPERATION,
            "operation_counts": {str(key): operation_counts[key] for key in sorted(operation_counts)},
            "template_counts": {key: template_counts[key] for key in TEMPLATE_ORDER},
            "unique_sample_ids": len({row.sample_id for row in rows}),
            "unique_prompts": len({row.prompt for row in rows}),
            "original_bytes_preserved_except_neutral_tag_insertion": True,
        },
        "assignment": {
            "global_tag_counts": global_counts,
            "strata": strata,
        },
        "tag_tokenization": tokenizer_facts(tokenizer_path),
    }
    return MaterializationPlan(
        output_bytes=output_bytes,
        manifest=manifest,
        manifest_bytes=_manifest_bytes(manifest),
    )


def _write_bytes_atomic(path: Path, content: bytes) -> None:
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


def _validate_manifest_header(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Tagged-bank manifest has the wrong schema version")
    if manifest.get("artifact_type") != "rsci_known_cost_neutral_tag_bank":
        raise ValueError("Tagged-bank manifest has the wrong artifact type")
    algorithm = manifest.get("algorithm")
    if not isinstance(algorithm, dict):
        raise ValueError("Tagged-bank manifest has no algorithm record")
    if algorithm.get("id") != ALGORITHM_ID or algorithm.get("version") != ALGORITHM_VERSION:
        raise ValueError("Tagged-bank manifest has the wrong algorithm identity")


def _bound_path(recorded: object, override: Path | None, *, name: str) -> Path:
    if not isinstance(recorded, str) or not recorded:
        raise ValueError(f"Tagged-bank manifest has no {name} path")
    bound = Path(recorded).expanduser().resolve()
    if override is not None and override.expanduser().resolve() != bound:
        raise ValueError(f"Requested {name} path differs from the manifest")
    return bound


def validate_tagged_bank(
    *,
    manifest_path: Path,
    input_path: Path | None = None,
    output_path: Path | None = None,
    tokenizer_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    raw_manifest = manifest_path.read_bytes()
    manifest = _read_json_object_bytes(raw_manifest, description=f"Manifest {manifest_path}")
    _validate_manifest_header(manifest)
    if _manifest_bytes(manifest) != raw_manifest:
        raise ValueError("Tagged-bank manifest is not in canonical JSON form")
    if manifest.get("manifest_path") != str(manifest_path):
        raise ValueError("Tagged-bank manifest is not at its recorded path")

    input_record = manifest.get("input")
    output_record = manifest.get("output")
    if not isinstance(input_record, dict) or not isinstance(output_record, dict):
        raise ValueError("Tagged-bank manifest has invalid input/output records")
    bound_input = _bound_path(input_record.get("path"), input_path, name="input")
    bound_output = _bound_path(output_record.get("path"), output_path, name="output")
    if not bound_output.is_file():
        raise FileNotFoundError(bound_output)

    recorded_tokenization = manifest.get("tag_tokenization")
    if recorded_tokenization is None:
        if tokenizer_path is not None:
            raise ValueError("A tokenizer override was supplied for a manifest without tokenizer facts")
        bound_tokenizer = None
    else:
        if not isinstance(recorded_tokenization, dict):
            raise ValueError("Tagged-bank manifest has an invalid tokenizer record")
        bound_tokenizer = _bound_path(recorded_tokenization.get("path"), tokenizer_path, name="tokenizer")

    block_seed = manifest.get("block_seed")
    if isinstance(block_seed, bool) or not isinstance(block_seed, int) or block_seed < 0:
        raise ValueError("Tagged-bank manifest has an invalid block seed")
    expected = build_materialization_plan(
        input_path=bound_input,
        output_path=bound_output,
        manifest_path=manifest_path,
        block_seed=block_seed,
        tokenizer_path=bound_tokenizer,
    )
    actual_output = bound_output.read_bytes()
    if actual_output != expected.output_bytes:
        raise ValueError("Tagged-bank output differs from the independently recomputed assignment")
    if manifest != expected.manifest:
        raise ValueError("Tagged-bank manifest differs from the independently recomputed contract")
    return {
        "manifest": manifest,
        "manifest_sha256": bytes_sha256(raw_manifest),
        "output_sha256": bytes_sha256(actual_output),
    }


def materialize_tagged_bank(
    *,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    block_seed: int,
    tokenizer_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = build_materialization_plan(
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest_path,
        block_seed=block_seed,
        tokenizer_path=tokenizer_path,
    )
    output_path = output_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    if dry_run:
        return {
            "dry_run": True,
            "already_materialized": False,
            "manifest": plan.manifest,
            "manifest_sha256": bytes_sha256(plan.manifest_bytes),
        }

    if output_path.exists() or manifest_path.exists():
        if not output_path.is_file() or not manifest_path.is_file():
            raise FileExistsError("Tagged-bank output and manifest must either both be absent or both be files")
        validated = validate_tagged_bank(
            manifest_path=manifest_path,
            input_path=input_path,
            output_path=output_path,
            tokenizer_path=tokenizer_path,
        )
        if validated["manifest"] != plan.manifest:
            raise ValueError("Existing tagged-bank artifact belongs to another materialization request")
        return {**validated, "dry_run": False, "already_materialized": True}

    _write_bytes_atomic(output_path, plan.output_bytes)
    _write_bytes_atomic(manifest_path, plan.manifest_bytes)
    validated = validate_tagged_bank(
        manifest_path=manifest_path,
        input_path=input_path,
        output_path=output_path,
        tokenizer_path=tokenizer_path,
    )
    return {**validated, "dry_run": False, "already_materialized": False}


def _default_manifest_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".manifest.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser("materialize", help="build a deterministic tagged bank")
    materialize.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--manifest", type=Path)
    materialize.add_argument("--block-seed", type=int, required=True)
    materialize.add_argument("--tokenizer", type=Path)
    materialize.add_argument("--dry-run", action="store_true")

    validate = subparsers.add_parser("validate", help="independently replay and validate a tagged bank")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--input", type=Path)
    validate.add_argument("--output", type=Path)
    validate.add_argument("--tokenizer", type=Path)
    validate.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _summary(result: dict[str, Any], *, command: str, dry_run: bool) -> dict[str, Any]:
    manifest = result["manifest"]
    return {
        "command": command,
        "dry_run": dry_run,
        "already_materialized": result.get("already_materialized"),
        "input": manifest["input"],
        "output": manifest["output"],
        "manifest_path": manifest["manifest_path"],
        "manifest_sha256": result["manifest_sha256"],
        "block_seed": manifest["block_seed"],
        "global_tag_counts": manifest["assignment"]["global_tag_counts"],
        "tag_tokenization": manifest["tag_tokenization"],
    }


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        manifest_path = args.manifest or _default_manifest_path(args.output)
        result = materialize_tagged_bank(
            input_path=args.input,
            output_path=args.output,
            manifest_path=manifest_path,
            block_seed=args.block_seed,
            tokenizer_path=args.tokenizer,
            dry_run=args.dry_run,
        )
    else:
        result = validate_tagged_bank(
            manifest_path=args.manifest,
            input_path=args.input,
            output_path=args.output,
            tokenizer_path=args.tokenizer,
        )
    print(json.dumps(_summary(result, command=args.command, dry_run=args.dry_run), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
