#!/usr/bin/env python3
"""Render and attest every row in a format-v3 Terminal-Bench SFT export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from prime_rl.trainer.sft.export_preflight import (
    MAX_RENDER_WORKERS,
    SFTPreflightError,
    create_sft_preflight_attestation,
)


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SFTPreflightError("arguments_invalid")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    parser.add_argument(
        "--expected-require-exact-provider-json",
        action=argparse.BooleanOptionalAction,
        required=True,
    )
    parser.add_argument("--tokenizer-snapshot-path", type=Path)
    parser.add_argument("--expected-tokenizer-snapshot-sha256")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.tokenizer_snapshot_path is None) != (
        args.expected_tokenizer_snapshot_sha256 is None
    ) or not 1 <= args.workers <= MAX_RENDER_WORKERS:
        raise SFTPreflightError("arguments_invalid")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = create_sft_preflight_attestation(
            export_root=args.export_root,
            expected_manifest_sha256=args.expected_manifest_sha256,
            project_dir=args.project_dir,
            expected_project_revision=args.expected_project_revision,
            expected_require_exact_provider_json=args.expected_require_exact_provider_json,
            output=args.output,
            tokenizer_snapshot_path=args.tokenizer_snapshot_path,
            expected_tokenizer_snapshot_sha256=args.expected_tokenizer_snapshot_sha256,
            workers=args.workers,
        )
    except SFTPreflightError as error:
        print(json.dumps({"error": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"error": "preflight_failed", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
