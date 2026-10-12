from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

TAU2_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
TAU2_ARCHIVE_SHA256 = "7a227036d07fdeb088dbd0c99fdb40ee9b9e0ebc06aadbc4dec1217b3383e57e"
TAU2_ARCHIVE_URL = f"https://github.com/sierra-research/tau2-bench/archive/{TAU2_COMMIT}.tar.gz"
TAU2_ROOT = f"tau2-bench-{TAU2_COMMIT}"

_INCLUDED_TREES = (
    "src",
    "data/tau2/domains/banking_knowledge",
    "data/tau2/user_simulator",
)
_INCLUDED_FILES = {"pyproject.toml", "README.md", "LICENSE"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "tau3-banking-vmvm/0.1"})
    with urllib.request.urlopen(request, timeout=600) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _selected(relative_name: str) -> bool:
    if relative_name in _INCLUDED_FILES:
        return True
    return any(relative_name == tree or relative_name.startswith(f"{tree}/") for tree in _INCLUDED_TREES)


def _build_slim_archive(source: Path, destination: Path) -> None:
    with source.open("rb") as raw_source, tarfile.open(fileobj=raw_source, mode="r:gz") as archive:
        with destination.open("wb") as raw_destination:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_destination, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as output:
                    for member in archive:
                        prefix = f"{TAU2_ROOT}/"
                        if not member.name.startswith(prefix):
                            continue
                        relative_name = member.name.removeprefix(prefix).rstrip("/")
                        if not relative_name or not _selected(relative_name):
                            continue
                        copied = copy.copy(member)
                        copied.name = relative_name
                        copied.uid = 0
                        copied.gid = 0
                        copied.uname = ""
                        copied.gname = ""
                        source_file = archive.extractfile(member) if member.isfile() else None
                        output.addfile(copied, source_file)


def prepare_tau2_archive(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    full_archive = cache_dir / f"tau2-{TAU2_COMMIT}.tar.gz"
    slim_archive = cache_dir / f"tau2-{TAU2_COMMIT}-banking.tar.gz"
    manifest_path = slim_archive.with_suffix(slim_archive.suffix + ".json")

    if not full_archive.is_file() or sha256(full_archive) != TAU2_ARCHIVE_SHA256:
        descriptor, temporary_name = tempfile.mkstemp(prefix="tau2-download-", suffix=".tar.gz", dir=cache_dir)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            _download(TAU2_ARCHIVE_URL, temporary)
            actual = sha256(temporary)
            if actual != TAU2_ARCHIVE_SHA256:
                raise ValueError(f"Tau2 source archive checksum mismatch: expected {TAU2_ARCHIVE_SHA256}, got {actual}")
            os.replace(temporary, full_archive)
        finally:
            temporary.unlink(missing_ok=True)

    expected_manifest = {
        "source_commit": TAU2_COMMIT,
        "source_sha256": TAU2_ARCHIVE_SHA256,
    }
    if slim_archive.is_file() and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if all(manifest.get(key) == value for key, value in expected_manifest.items()) and manifest.get(
            "slim_sha256"
        ) == sha256(slim_archive):
            return slim_archive

    descriptor, temporary_name = tempfile.mkstemp(prefix="tau2-banking-", suffix=".tar.gz", dir=cache_dir)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _build_slim_archive(full_archive, temporary)
        os.replace(temporary, slim_archive)
    finally:
        temporary.unlink(missing_ok=True)
    manifest = expected_manifest | {
        "slim_sha256": sha256(slim_archive),
        "size_bytes": slim_archive.stat().st_size,
    }
    temporary_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_manifest, manifest_path)
    return slim_archive


def load_task_ids(archive_path: Path) -> list[str]:
    task_ids = []
    suffix = "/data/tau2/domains/banking_knowledge/tasks/"
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if suffix not in f"/{member.name}" or not member.name.endswith(".json"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            task_ids.append(str(json.load(extracted)["id"]))
    return sorted(task_ids)
