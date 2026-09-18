#!/usr/bin/env python3
"""Emit aggregate hashes for independent source-wheel proof approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from terminal_bench_vmvm.source_wheel_proof import (
    _python_sources_sha256,
    _stable_file_digest,
    canonical_tree_manifest_sha256,
    python_runtime_manifest_sha256,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--python-stdlib", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--vacli", type=Path, required=True)
    parser.add_argument("--vmvm-source", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        launcher = args.launcher.resolve(strict=True)
        uv_path = args.uv.resolve(strict=True)
        python_path = args.python.resolve(strict=True)
        python_stdlib = args.python_stdlib.resolve(strict=True)
        site_packages = args.site_packages.resolve(strict=True)
        vacli_path = args.vacli.resolve(strict=True)
        vmvm_source = args.vmvm_source.resolve(strict=True)
        result = {
            "launcher_sha256": _stable_file_digest(launcher, "binding_invalid")[2],
            "uv_sha256": _stable_file_digest(uv_path, "binding_invalid", executable=True)[2],
            "python_sha256": _stable_file_digest(python_path, "binding_invalid", executable=True)[2],
            "python_runtime_manifest_sha256": python_runtime_manifest_sha256(
                python_path,
                python_stdlib,
            ),
            "site_packages_manifest_sha256": canonical_tree_manifest_sha256(site_packages),
            "vacli_binary_sha256": _stable_file_digest(
                vacli_path,
                "binding_invalid",
                executable=True,
            )[2],
            "vmvm_tb_v2_sha256": _python_sources_sha256(vmvm_source),
        }
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "binding_inspection_failed"}, sort_keys=True))
        return 1
    print(json.dumps({"status": "complete", "hashes": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
