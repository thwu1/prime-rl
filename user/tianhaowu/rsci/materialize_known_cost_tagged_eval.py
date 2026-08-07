#!/usr/bin/env python3
"""Clone strict GSM-Infinite held-out rows under every known-cost neutral tag."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import materialize_known_cost_tagged_bank as training_tags

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_paired_tagged_eval"
ALGORITHM_ID = "rsci-known-cost-paired-heldout-tags-v1"
SOURCE_ID_DOMAIN = "rsci-known-cost-paired-heldout-source-v1"
CLONE_ID_DOMAIN = "rsci-known-cost-paired-heldout-clone-v1"
IMPLEMENTATION_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_tagged_eval.py"
RUNTIME_REPOSITORY_PATH = "user/tianhaowu/rsci/rsci_gsm_infinite.py"
KNOWN_OPERATIONS = tuple(range(11, 46))
EXPECTED_TAG_COUNT = 6
EXPECTED_TAG_PREFIXES = tuple(f"<rsci_context_{index}>\n" for index in range(EXPECTED_TAG_COUNT))
EXPECTED_TEMPLATES = (
    "crazy_zootopia",
    "movie_festival_awards",
    "teachers_in_school",
)
REQUIRED_CONTENT_FIELDS = ("problem", "question", "solution")


@dataclass(frozen=True)
class SourceRow:
    value: dict[str, Any]
    sample_id: str
    raw_sample_id: str
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


def canonical_json_bytes(value: object, *, indent: int | None = None) -> bytes:
    options: dict[str, Any] = {
        "ensure_ascii": False,
        "allow_nan": False,
        "sort_keys": True,
    }
    if indent is None:
        options["separators"] = (",", ":")
    else:
        options["indent"] = indent
    return (json.dumps(value, **options) + "\n").encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    return bytes_sha256(canonical_json_bytes(value).rstrip(b"\n"))


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def _read_json_object(content: bytes, *, description: str) -> dict[str, Any]:
    value = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_object_without_duplicate_keys,
        parse_constant=_reject_nonfinite_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"{description} is not a JSON object")
    return value


def _validate_tag_contract() -> dict[str, Any]:
    observed = {
        "tag_count": training_tags.TAG_COUNT,
        "tag_prefixes": tuple(training_tags.TAG_PREFIXES),
        "template_order": tuple(training_tags.TEMPLATE_ORDER),
    }
    expected = {
        "tag_count": EXPECTED_TAG_COUNT,
        "tag_prefixes": EXPECTED_TAG_PREFIXES,
        "template_order": EXPECTED_TEMPLATES,
    }
    if observed != expected:
        raise ValueError(f"Training/evaluation neutral-tag constants diverged: {observed!r} != {expected!r}")
    return {
        "tag_count": EXPECTED_TAG_COUNT,
        "literal_prefixes": list(EXPECTED_TAG_PREFIXES),
        "template_order": list(EXPECTED_TEMPLATES),
        "training_materializer": _implementation_identity(
            Path(training_tags.__file__), training_tags.IMPLEMENTATION_REPOSITORY_PATH
        ),
    }


def _implementation_identity(path: Path, repository_path: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "repository_path": repository_path,
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def derive_runtime_prompt(problem: str, question: str) -> str:
    return f"<question> {str(problem).strip()} {str(question).strip()} </question> <solution>"


def derive_runtime_answer(solution: str) -> str:
    _, separator, suffix = str(solution).rpartition("Answer:")
    if not separator:
        raise ValueError("Gold solution has no Answer marker")
    lines = suffix.strip().splitlines()
    if not lines:
        raise ValueError("Gold solution has no content after its final Answer marker")
    return lines[0].strip().rstrip(".")


def canonical_source_id(
    operation: int,
    template: str,
    raw_sample_id: str,
    derived_prompt: str,
    solution: str,
) -> str:
    material = canonical_json_bytes(
        [SOURCE_ID_DOMAIN, operation, template, raw_sample_id, derived_prompt, solution]
    ).rstrip(b"\n")
    return f"known_cost_tagged_eval_source_{hashlib.sha256(material).hexdigest()}"


def _file_identity(path: Path, content: bytes, rows: int) -> dict[str, Any]:
    return {
        "path": str(path.expanduser().resolve()),
        "sha256": bytes_sha256(content),
        "size_bytes": len(content),
        "rows": rows,
    }


def _read_source(path: Path) -> tuple[bytes, list[SourceRow]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    content = path.read_bytes()
    if not content:
        raise ValueError(f"Held-out JSONL is empty: {path}")
    raw_lines = content.splitlines(keepends=True)
    if b"".join(raw_lines) != content:
        raise RuntimeError("Held-out JSONL line splitting did not preserve its bytes")

    rows: list[SourceRow] = []
    sample_ids: set[str] = set()
    prompts: set[str] = set()
    for line_number, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip():
            raise ValueError(f"Blank held-out JSONL record at {path}:{line_number}")
        value = _read_json_object(raw_line, description=f"Held-out record {path}:{line_number}")
        required = {"id", "op", "template", *REQUIRED_CONTENT_FIELDS}
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"Held-out record {path}:{line_number} is missing fields: {missing}")
        forbidden = {"source_sample_id", "source_raw_id", "neutral_tag_index"} & value.keys()
        if forbidden:
            raise ValueError(f"Held-out record {path}:{line_number} already has clone fields: {sorted(forbidden)}")

        raw_sample_id = value["id"]
        if not isinstance(raw_sample_id, str) or not raw_sample_id:
            raise ValueError(f"Held-out record {path}:{line_number} has an invalid id")
        operation = value["op"]
        if isinstance(operation, bool) or not isinstance(operation, int) or operation not in KNOWN_OPERATIONS:
            raise ValueError(f"Held-out record {path}:{line_number} has an unknown operation: {operation!r}")
        template = value["template"]
        if not isinstance(template, str) or template not in EXPECTED_TEMPLATES:
            raise ValueError(f"Held-out record {path}:{line_number} has an unknown template: {template!r}")
        for field in REQUIRED_CONTENT_FIELDS:
            if not isinstance(value[field], str):
                raise ValueError(f"Held-out record {path}:{line_number} has non-string {field}")
        prompt = derive_runtime_prompt(value["problem"], value["question"])
        if "prompt" in value and (not isinstance(value["prompt"], str) or value["prompt"] != prompt):
            raise ValueError(
                f"Held-out record {path}:{line_number} has an explicit prompt that differs from runtime derivation"
            )
        answer = derive_runtime_answer(value["solution"])
        if "answer" in value and (not isinstance(value["answer"], str) or value["answer"] != answer):
            raise ValueError(
                f"Held-out record {path}:{line_number} has an explicit answer that differs from runtime derivation"
            )
        sample_id = canonical_source_id(
            operation,
            template,
            raw_sample_id,
            prompt,
            value["solution"],
        )
        if sample_id in sample_ids:
            raise RuntimeError(f"Canonical source-id collision for held-out record {path}:{line_number}")
        if prompt in prompts:
            raise ValueError(f"Held-out JSONL has a duplicate source prompt at raw id {raw_sample_id!r}")
        sample_ids.add(sample_id)
        prompts.add(prompt)
        rows.append(SourceRow(value, sample_id, raw_sample_id, operation, template, prompt, line_number))
    return content, rows


def clone_id(source_sample_id: str, neutral_tag_index: int) -> str:
    if not isinstance(source_sample_id, str) or not source_sample_id:
        raise ValueError("source_sample_id must be a non-empty string")
    if (
        isinstance(neutral_tag_index, bool)
        or not isinstance(neutral_tag_index, int)
        or neutral_tag_index not in range(EXPECTED_TAG_COUNT)
    ):
        raise ValueError(f"neutral_tag_index must lie in [0, {EXPECTED_TAG_COUNT})")
    material = canonical_json_bytes([CLONE_ID_DOMAIN, source_sample_id, neutral_tag_index]).rstrip(b"\n")
    return f"known_cost_tagged_eval_{hashlib.sha256(material).hexdigest()}"


def _clone_rows(rows: list[SourceRow]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clones: list[dict[str, Any]] = []
    clone_ids: set[str] = set()
    effective_prompts: set[str] = set()
    stratum_counts: Counter[tuple[int, str, int]] = Counter()
    source_strata: Counter[tuple[int, str]] = Counter()
    for row in rows:
        source_strata[(row.operation, row.template)] += 1
        for tag_index, tag_prefix in enumerate(EXPECTED_TAG_PREFIXES):
            identifier = clone_id(row.sample_id, tag_index)
            if identifier in clone_ids:
                raise RuntimeError(f"Clone-id collision for source {row.sample_id!r}, tag {tag_index}")
            effective_prompt = f"{tag_prefix}{row.prompt}"
            if effective_prompt in effective_prompts:
                raise RuntimeError(f"Effective prompt collision for source {row.sample_id!r}, tag {tag_index}")
            clone = dict(row.value)
            clone.update(
                {
                    "id": identifier,
                    "source_sample_id": row.sample_id,
                    "source_raw_id": row.raw_sample_id,
                    "neutral_tag_index": tag_index,
                }
            )
            restored = dict(clone)
            restored["id"] = restored.pop("source_raw_id")
            restored.pop("source_sample_id")
            restored.pop("neutral_tag_index")
            if restored != row.value:
                raise RuntimeError(f"Clone content changed for source {row.sample_id!r}, tag {tag_index}")
            clone_ids.add(identifier)
            effective_prompts.add(effective_prompt)
            stratum_counts[(row.operation, row.template, tag_index)] += 1
            clones.append(clone)

    strata = []
    for operation, template in sorted(source_strata):
        source_count = source_strata[(operation, template)]
        tag_counts = {
            str(tag_index): stratum_counts[(operation, template, tag_index)] for tag_index in range(EXPECTED_TAG_COUNT)
        }
        if set(tag_counts.values()) != {source_count}:
            raise RuntimeError(f"Paired tag expansion failed for OP{operation}/{template}: {tag_counts}")
        strata.append(
            {
                "operation": operation,
                "template": template,
                "source_rows": source_count,
                "clone_rows": source_count * EXPECTED_TAG_COUNT,
                "tag_counts": tag_counts,
            }
        )
    if len(clones) != len(rows) * EXPECTED_TAG_COUNT:
        raise RuntimeError("Tagged held-out row count differs from six clones per source")
    return clones, strata


def _tokenizer_record(tokenizer_path: Path) -> dict[str, Any]:
    facts = training_tags.tokenizer_facts(tokenizer_path)
    if facts is None:
        raise RuntimeError("Known-cost tagged evaluation requires pinned tokenizer facts")
    record = dict(facts)
    record["artifact_inventory_sha256"] = canonical_json_sha256(record["artifact_files"])
    return record


def _counts(rows: list[SourceRow], clones: list[dict[str, Any]]) -> dict[str, Any]:
    source_by_operation = Counter(row.operation for row in rows)
    source_by_template = Counter(row.template for row in rows)
    clone_by_operation = Counter(int(row["op"]) for row in clones)
    clone_by_template = Counter(str(row["template"]) for row in clones)
    clone_by_tag = Counter(int(row["neutral_tag_index"]) for row in clones)
    source_raw_id_counts = Counter(row.raw_sample_id for row in rows)
    duplicate_source_raw_id_counts = {
        raw_sample_id: count for raw_sample_id, count in sorted(source_raw_id_counts.items()) if count > 1
    }
    return {
        "source_rows": len(rows),
        "clone_rows": len(clones),
        "unique_source_ids": len({row.sample_id for row in rows}),
        "unique_source_raw_ids": len(source_raw_id_counts),
        "duplicate_source_raw_id_rows": sum(count - 1 for count in source_raw_id_counts.values()),
        "duplicate_source_raw_id_counts": duplicate_source_raw_id_counts,
        "unique_source_prompts": len({row.prompt for row in rows}),
        "unique_clone_ids": len({str(row["id"]) for row in clones}),
        "unique_effective_prompts": len(
            {f"{tag_prefix}{row.prompt}" for row in rows for tag_prefix in EXPECTED_TAG_PREFIXES}
        ),
        "source_by_operation": {str(key): source_by_operation[key] for key in sorted(source_by_operation)},
        "clone_by_operation": {str(key): clone_by_operation[key] for key in sorted(clone_by_operation)},
        "source_by_template": {key: source_by_template[key] for key in EXPECTED_TEMPLATES},
        "clone_by_template": {key: clone_by_template[key] for key in EXPECTED_TEMPLATES},
        "clone_by_tag": {str(index): clone_by_tag[index] for index in range(EXPECTED_TAG_COUNT)},
    }


def build_materialization_plan(
    *,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    tokenizer_path: Path,
) -> MaterializationPlan:
    input_path = input_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    tokenizer_path = tokenizer_path.expanduser().resolve()
    if len({input_path, output_path, manifest_path}) != 3:
        raise ValueError("input, output, and manifest paths must be distinct")

    tag_contract = _validate_tag_contract()
    input_bytes, rows = _read_source(input_path)
    clones, strata = _clone_rows(rows)
    output_bytes = b"".join(canonical_json_bytes(row) for row in clones)
    tokenizer = _tokenizer_record(tokenizer_path)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "algorithm": {
            "id": ALGORITHM_ID,
            "source_id_domain": SOURCE_ID_DOMAIN,
            "source_id_rule": (
                "full SHA-256 of canonical [domain, op, template, raw id, derived base prompt, solution]"
            ),
            "clone_id_domain": CLONE_ID_DOMAIN,
            "clone_id_rule": "full SHA-256 of canonical [domain, source_sample_id, neutral_tag_index]",
            "ordering_rule": "source JSONL order, then neutral_tag_index 0 through 5",
            "serialization": "UTF-8 canonical JSON with sorted keys, compact separators, and one trailing newline",
            "prompt_transform": (
                "JSONL preserves source fields; runtime derives the base prompt when absent and prepends the "
                "literal prefix selected by neutral_tag_index"
            ),
        },
        "implementation": _implementation_identity(Path(__file__), IMPLEMENTATION_REPOSITORY_PATH),
        "runtime_compatibility": {
            "implementation": _implementation_identity(
                Path(__file__).with_name("rsci_gsm_infinite.py"), RUNTIME_REPOSITORY_PATH
            ),
            "prompt_derivation": ("<question> {str(problem).strip()} {str(question).strip()} </question> <solution>"),
            "answer_derivation": (
                "str(solution).rpartition('Answer:') suffix, stripped, first line, stripped, trailing periods removed"
            ),
            "explicit_field_policy": (
                "prompt and answer remain optional; when present, each must be a string exactly equal to its "
                "runtime-derived value"
            ),
        },
        "tag_contract": tag_contract,
        "input": _file_identity(input_path, input_bytes, len(rows)),
        "output": _file_identity(output_path, output_bytes, len(clones)),
        "manifest_path": str(manifest_path),
        "source_contract": {
            "known_operations": list(KNOWN_OPERATIONS),
            "known_templates": list(EXPECTED_TEMPLATES),
            "required_content_fields": list(REQUIRED_CONTENT_FIELDS),
            "optional_derived_fields": ["prompt", "answer"],
            "canonical_source_ids_required_unique": True,
            "unique_source_prompts_required": True,
            "duplicate_raw_ids_allowed_and_audited": True,
            "all_source_fields_preserved_except_id": True,
            "raw_id_copied_to": "source_raw_id",
            "canonical_source_id_copied_to": "source_sample_id",
        },
        "counts": _counts(rows, clones),
        "operation_template_tag_strata": strata,
        "tag_tokenization": tokenizer,
    }
    manifest_bytes = canonical_json_bytes(manifest, indent=2)
    return MaterializationPlan(output_bytes, manifest, manifest_bytes)


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
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Tagged-eval manifest has the wrong schema or artifact type")
    algorithm = manifest.get("algorithm")
    if not isinstance(algorithm, dict) or algorithm.get("id") != ALGORITHM_ID:
        raise ValueError("Tagged-eval manifest has the wrong algorithm identity")


def _bound_path(recorded: object, override: Path | None, *, label: str) -> Path:
    if not isinstance(recorded, str) or not recorded:
        raise ValueError(f"Tagged-eval manifest has no {label} path")
    path = Path(recorded).expanduser().resolve()
    if override is not None and override.expanduser().resolve() != path:
        raise ValueError(f"Requested {label} path differs from the manifest")
    return path


def validate_tagged_eval(
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
    manifest = _read_json_object(raw_manifest, description=f"Tagged-eval manifest {manifest_path}")
    _validate_manifest_header(manifest)
    if canonical_json_bytes(manifest, indent=2) != raw_manifest:
        raise ValueError("Tagged-eval manifest is not canonical JSON")
    if manifest.get("manifest_path") != str(manifest_path):
        raise ValueError("Tagged-eval manifest is not at its recorded path")

    input_record = manifest.get("input")
    output_record = manifest.get("output")
    tokenizer_record = manifest.get("tag_tokenization")
    if not isinstance(input_record, dict) or not isinstance(output_record, dict):
        raise ValueError("Tagged-eval manifest has invalid input/output identities")
    if not isinstance(tokenizer_record, dict):
        raise ValueError("Tagged-eval manifest has no tokenizer identity")
    bound_input = _bound_path(input_record.get("path"), input_path, label="input")
    bound_output = _bound_path(output_record.get("path"), output_path, label="output")
    bound_tokenizer = _bound_path(tokenizer_record.get("path"), tokenizer_path, label="tokenizer")
    if not bound_output.is_file():
        raise FileNotFoundError(bound_output)

    expected = build_materialization_plan(
        input_path=bound_input,
        output_path=bound_output,
        manifest_path=manifest_path,
        tokenizer_path=bound_tokenizer,
    )
    actual_output = bound_output.read_bytes()
    if actual_output != expected.output_bytes:
        raise ValueError("Tagged-eval output differs from the independently replayed expansion")
    if manifest != expected.manifest:
        raise ValueError("Tagged-eval manifest differs from the independently replayed contract")
    return {
        "manifest": manifest,
        "manifest_sha256": bytes_sha256(raw_manifest),
        "output_sha256": bytes_sha256(actual_output),
    }


def materialize_tagged_eval(
    *,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    tokenizer_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = build_materialization_plan(
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest_path,
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
            "output_sha256": bytes_sha256(plan.output_bytes),
        }
    if output_path.exists() or manifest_path.exists():
        if not output_path.is_file() or not manifest_path.is_file():
            raise FileExistsError("Tagged-eval output and manifest must both exist or both be absent")
        validated = validate_tagged_eval(
            manifest_path=manifest_path,
            input_path=input_path,
            output_path=output_path,
            tokenizer_path=tokenizer_path,
        )
        if validated["manifest"] != plan.manifest:
            raise ValueError("Existing tagged-eval artifact belongs to another request")
        return {**validated, "dry_run": False, "already_materialized": True}

    _write_bytes_atomic(output_path, plan.output_bytes)
    _write_bytes_atomic(manifest_path, plan.manifest_bytes)
    validated = validate_tagged_eval(
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
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--input", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--manifest", type=Path)
    materialize.add_argument("--tokenizer", type=Path, default=training_tags.DEFAULT_TOKENIZER)
    materialize.add_argument("--dry-run", action="store_true")
    validate = subparsers.add_parser("validate")
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
        "counts": manifest["counts"],
        "tag_tokenization": manifest["tag_tokenization"],
    }


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        result = materialize_tagged_eval(
            input_path=args.input,
            output_path=args.output,
            manifest_path=args.manifest or _default_manifest_path(args.output),
            tokenizer_path=args.tokenizer,
            dry_run=args.dry_run,
        )
    else:
        result = validate_tagged_eval(
            manifest_path=args.manifest,
            input_path=args.input,
            output_path=args.output,
            tokenizer_path=args.tokenizer,
        )
    print(json.dumps(_summary(result, command=args.command, dry_run=args.dry_run), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
