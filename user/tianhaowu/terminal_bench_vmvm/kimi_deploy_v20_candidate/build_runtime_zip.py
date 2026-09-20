#!/usr/bin/python3.12
"""Build the deterministic, pure-Python deploy-controller import closure."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

SOURCE_BOUND = True
SOURCE_PACKAGE = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/sources/ram-common-468a6e5/vllm_tools/serve_api_v2/src"
)
DEPENDENCIES = Path(
    "/checkpoint/ram/tianhaowu/terminal_bench_vmvm/dependencies/k3_deploy_control_arm64_py313_4ec7114_v1"
)
OUTPUT = Path(__file__).resolve(strict=True).with_name("runtime.zip")
SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".a", ".o"}
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def collect(root: Path, prefix: str) -> list[tuple[str, bytes]]:
    if root.resolve(strict=True) != root or root.is_symlink():
        raise RuntimeError("noncanonical root")
    result: list[tuple[str, bytes]] = []
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in SKIP_NAMES)
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            status = path.stat(follow_symlinks=False)
            if path.is_symlink() or not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
                raise RuntimeError(f"unsupported entry: {prefix}/{relative}")
            if path.suffix.lower() in SKIP_SUFFIXES or path.name.endswith(".pth"):
                continue
            result.append((f"{prefix}{relative}", path.read_bytes()))
    return result


def main() -> int:
    if len(sys.argv) != 1:
        raise SystemExit("no arguments accepted")
    if not SOURCE_BOUND:
        raise RuntimeError("source unbound")
    records = collect(SOURCE_PACKAGE, "") + collect(DEPENDENCIES, "")
    by_name: dict[str, bytes] = {}
    for name, raw in records:
        prior = by_name.setdefault(name, raw)
        if prior != raw:
            raise RuntimeError(f"conflicting archive entry: {name}")
    manifest = {
        "schema_version": 1,
        "kind": "k3-redeploy-pure-python-runtime",
        "files": [[name, len(raw), hashlib.sha256(raw).hexdigest()] for name, raw in sorted(by_name.items())],
    }
    by_name["REDEPLOY_RUNTIME_MANIFEST.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    temporary = OUTPUT.with_name(f".{OUTPUT.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            with zipfile.ZipFile(
                target,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
                strict_timestamps=True,
            ) as archive:
                for name, raw in sorted(by_name.items()):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (stat.S_IFREG | 0o400) << 16
                    info.create_system = 3
                    archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, OUTPUT, follow_symlinks=False)
        os.unlink(temporary)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
