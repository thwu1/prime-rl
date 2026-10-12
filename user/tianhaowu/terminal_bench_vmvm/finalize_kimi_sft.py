#!/usr/bin/env python3
"""Export and render-preflight terminal Kimi pass-only traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

import export_sft
import kimi_sandoq_production as production
from direct_qwen_union_contract import canonical_json, read_regular

KIND = "kimi-k3-max-sandoq-pass-only-sft"
SCHEMA_VERSION = 1


class KimiSFTError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _private_directory(path: Path, code: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as error:
        raise KimiSFTError(code) from error
    if (
        not path.is_absolute()
        or path != Path(os.path.normpath(path))
        or path != resolved
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise KimiSFTError(code)
    return resolved


def _artifact(path: Path, code: str, *, private: bool = True) -> dict[str, int | str]:
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
        body = read_regular(path, max_bytes=64 * 1024 * 1024)
    except (OSError, ValueError) as error:
        raise KimiSFTError(code) from error
    if (
        path != resolved
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or (private and stat.S_IMODE(metadata.st_mode) != 0o600)
    ):
        raise KimiSFTError(code)
    return {"bytes": len(body), "path": str(path), "sha256": hashlib.sha256(body).hexdigest()}


def _publish(path: Path, value: dict[str, Any]) -> str:
    body = canonical_json(value)
    try:
        root = _private_directory(path.parent, "receipt_parent_invalid")
        if path.parent != root or os.path.lexists(path):
            raise KimiSFTError("receipt_path_invalid")
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
    except OSError as error:
        raise KimiSFTError("receipt_publish_failed") from error
    return hashlib.sha256(body).hexdigest()


def export_pass_only(
    *,
    project_root: Path,
    expected_revision: str,
    trace_certificate: Path,
    trace_certificate_sha256: str,
    output_root: Path,
    output_dir: Path,
    validation_permyriad: int,
    split_salt: str,
    receipt: Path,
) -> dict[str, Any]:
    source = production._source_binding(project_root, expected_revision)
    root = _private_directory(output_root, "output_root_invalid")
    if (
        output_dir.parent != root
        or output_dir.name in {"", ".", ".."}
        or os.path.lexists(output_dir)
        or receipt.parent != root
        or receipt == output_dir
        or os.path.lexists(receipt)
        or isinstance(validation_permyriad, bool)
        or not isinstance(validation_permyriad, int)
        or not 0 <= validation_permyriad < 10_000
        or not split_salt
        or "\x00" in split_salt
    ):
        raise KimiSFTError("export_arguments_invalid")
    try:
        validated = production.validate_trace_certificate(
            trace_certificate,
            trace_certificate_sha256,
        )
        summary = export_sft.export_sft(
            export_sft.ExportOptions(
                results=Path(validated["results"]),
                output_dir=output_dir,
                selection="pass-only",
                expected_count=production.EXPECTED_TASK_COUNT,
                validation_permyriad=validation_permyriad,
                split_salt=split_salt,
                max_sequence_tokens=production.MAX_SEQUENCE_TOKENS,
                require_exact_provider_json=True,
            )
        )
    except production.KimiProductionError as error:
        raise KimiSFTError("trace_certificate_invalid") from error
    except export_sft.ExportError as error:
        raise KimiSFTError("sft_export_failed") from error
    certificate = validated["value"]
    if (
        summary.get("status") != "exported"
        or summary.get("selection") != "pass-only"
        or summary.get("input_traces") != production.EXPECTED_TASK_COUNT
        or summary.get("approved_tasks") != production.EXPECTED_TASK_COUNT
        or summary.get("selected_traces") != validated["selected_traces"]
        or summary.get("selected_traces") != certificate["sft"]["expected_selected_traces"]
        or not isinstance(summary.get("rows"), dict)
        or not isinstance(summary.get("output_sha256"), dict)
    ):
        raise KimiSFTError("sft_export_contract_invalid")
    manifest = _artifact(output_dir / "manifest.json", "sft_manifest_invalid", private=False)
    if manifest["sha256"] != summary["output_sha256"].get("manifest"):
        raise KimiSFTError("sft_manifest_invalid")
    value = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "exported",
        "source": source,
        "trace_certificate": _artifact(trace_certificate, "trace_certificate_invalid"),
        "export": {
            "root": str(output_dir),
            "manifest": manifest,
            "selection": "pass-only",
            "input_traces": summary["input_traces"],
            "selected_traces": summary["selected_traces"],
            "rows": summary["rows"],
            "validation_permyriad": validation_permyriad,
            "split_salt_sha256": hashlib.sha256(split_salt.encode("utf-8")).hexdigest(),
            "require_exact_provider_json": True,
        },
        "preflight": {"required": True, "state": "pending"},
    }
    receipt_sha256 = _publish(receipt, value)
    return {
        "state": "exported",
        "input_traces": summary["input_traces"],
        "selected_traces": summary["selected_traces"],
        "rows": summary["rows"]["total"],
        "manifest_sha256": manifest["sha256"],
        "receipt_sha256": receipt_sha256,
    }


def _load_export_receipt(path: Path, expected_sha256: str) -> dict[str, Any]:
    artifact = _artifact(path, "export_receipt_invalid")
    try:
        body = read_regular(path)
        value = json.loads(body)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise KimiSFTError("export_receipt_invalid") from error
    export = value.get("export") if isinstance(value, dict) else None
    if (
        artifact["sha256"] != expected_sha256
        or not isinstance(value, dict)
        or canonical_json(value) != body
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != KIND
        or value.get("state") != "exported"
        or not isinstance(export, dict)
        or export.get("selection") != "pass-only"
        or export.get("require_exact_provider_json") is not True
        or export.get("input_traces") != production.EXPECTED_TASK_COUNT
        or not isinstance(export.get("selected_traces"), int)
        or export["selected_traces"] < 1
        or value.get("preflight") != {"required": True, "state": "pending"}
    ):
        raise KimiSFTError("export_receipt_invalid")
    return value


def preflight_export(
    *,
    project_root: Path,
    expected_revision: str,
    export_receipt: Path,
    export_receipt_sha256: str,
    tokenizer_snapshot_path: Path | None,
    tokenizer_snapshot_sha256: str | None,
    output: Path,
) -> dict[str, Any]:
    production._source_binding(project_root, expected_revision)
    value = _load_export_receipt(export_receipt, export_receipt_sha256)
    export = value["export"]
    root = Path(export["root"])
    manifest = export["manifest"]
    if _artifact(root / "manifest.json", "sft_manifest_invalid", private=False) != manifest:
        raise KimiSFTError("sft_manifest_invalid")
    try:
        from prime_rl.trainer.sft.export_preflight import (
            SFTPreflightError,
            create_sft_preflight_attestation,
        )
    except ImportError as error:
        raise KimiSFTError("sft_preflight_failed") from error
    try:
        summary = create_sft_preflight_attestation(
            export_root=root,
            expected_manifest_sha256=str(manifest["sha256"]),
            project_dir=project_root,
            expected_project_revision=expected_revision,
            expected_require_exact_provider_json=True,
            output=output,
            tokenizer_snapshot_path=tokenizer_snapshot_path,
            expected_tokenizer_snapshot_sha256=tokenizer_snapshot_sha256,
        )
    except SFTPreflightError as error:
        raise KimiSFTError("sft_preflight_failed") from error
    return {
        "state": "attested",
        "attestation_sha256": summary["attestation_sha256"],
        "rendered_rows": summary["rendering"]["rows"],
        "selected_traces": export["selected_traces"],
    }


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise KimiSFTError("arguments_invalid")


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export")
    exporter.add_argument("--project-root", type=Path, required=True)
    exporter.add_argument("--expected-revision", required=True)
    exporter.add_argument("--trace-certificate", type=Path, required=True)
    exporter.add_argument("--trace-certificate-sha256", required=True)
    exporter.add_argument("--output-root", type=Path, required=True)
    exporter.add_argument("--output-dir", type=Path, required=True)
    exporter.add_argument("--validation-permyriad", type=int, default=500)
    exporter.add_argument("--split-salt", required=True)
    exporter.add_argument("--receipt", type=Path, required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--project-root", type=Path, required=True)
    preflight.add_argument("--expected-revision", required=True)
    preflight.add_argument("--export-receipt", type=Path, required=True)
    preflight.add_argument("--export-receipt-sha256", required=True)
    preflight.add_argument("--tokenizer-snapshot-path", type=Path)
    preflight.add_argument("--tokenizer-snapshot-sha256")
    preflight.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "export":
            summary = export_pass_only(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                trace_certificate=args.trace_certificate,
                trace_certificate_sha256=args.trace_certificate_sha256,
                output_root=args.output_root,
                output_dir=args.output_dir,
                validation_permyriad=args.validation_permyriad,
                split_salt=args.split_salt,
                receipt=args.receipt,
            )
        else:
            if (args.tokenizer_snapshot_path is None) != (args.tokenizer_snapshot_sha256 is None):
                raise KimiSFTError("arguments_invalid")
            summary = preflight_export(
                project_root=args.project_root,
                expected_revision=args.expected_revision,
                export_receipt=args.export_receipt,
                export_receipt_sha256=args.export_receipt_sha256,
                tokenizer_snapshot_path=args.tokenizer_snapshot_path,
                tokenizer_snapshot_sha256=args.tokenizer_snapshot_sha256,
                output=args.output,
            )
    except KimiSFTError as error:
        print(json.dumps({"code": error.code, "state": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print('{"code":"internal_error","state":"blocked"}', file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
