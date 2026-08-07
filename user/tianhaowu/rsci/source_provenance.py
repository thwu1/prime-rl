#!/usr/bin/env python3
"""Create and verify a commit-pinned RSCI runtime source snapshot."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

LIVE_REPO_ROOT = Path("/storage/home/tianhaowu/prime-rl")
SNAPSHOT_NAME = "source_snapshot"
MANIFEST_NAME = "source_provenance.json"
FREEZE_NAME = "source_environment.freeze.txt"
SCHEMA_VERSION = 1
RUNTIME_PATHS = (
    "user/tianhaowu/rsci/source_runtime",
    "src",
    "packages/prime-rl-configs/src",
    "deps/pydantic-config/src",
    "deps/renderers",
    "deps/verifiers",
    "user/tianhaowu/rsci",
)
REQUIRED_IMPORTS = {
    "prime_rl.orchestrator.types": "src/prime_rl/orchestrator/types.py",
    "prime_rl.configs": "packages/prime-rl-configs/src/prime_rl/configs/__init__.py",
    "pydantic_config": "deps/pydantic-config/src/pydantic_config/__init__.py",
    "renderers": "deps/renderers/renderers/__init__.py",
    "rsci_gsm_infinite": "user/tianhaowu/rsci/rsci_gsm_infinite.py",
    "verifiers": "deps/verifiers/verifiers/__init__.py",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40,64}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("run_dir", type=Path)
    create.add_argument("--commit", default="HEAD")
    create.add_argument("--shared-venv", type=Path)

    materialize = subparsers.add_parser("materialize-launch")
    materialize.add_argument("run_dir", type=Path)
    materialize.add_argument("configs", nargs="+", type=Path)

    seal = subparsers.add_parser("seal-launch")
    seal.add_argument("run_dir", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("run_dir", type=Path)
    verify.add_argument("--expected-source", type=Path)
    return parser.parse_args()


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=text,
        capture_output=True,
        check=True,
    )


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    result = _run(["git", "-C", str(repo), *args], cwd=repo, text=text)
    return result.stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_field(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def source_tree_sha256(root: Path) -> str:
    """Hash paths, types, modes, contents, and symlink targets without following links."""
    root = root.resolve()
    digest = hashlib.sha256(b"rsci-source-tree-v1\0")
    paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".venv":
            continue
        metadata = path.lstat()
        _digest_field(digest, relative.as_posix().encode())
        _digest_field(digest, f"{stat.S_IMODE(metadata.st_mode):04o}".encode())
        if path.is_symlink():
            _digest_field(digest, b"symlink")
            _digest_field(digest, os.readlink(path).encode())
        elif path.is_dir():
            _digest_field(digest, b"directory")
        elif path.is_file():
            _digest_field(digest, b"file")
            _digest_field(digest, str(metadata.st_size).encode())
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise ValueError(f"Unsupported source-tree entry: {path}")
    return digest.hexdigest()


def _gitlinks(repo: Path, commit: str) -> list[tuple[Path, str]]:
    raw = _git(repo, "ls-tree", "-r", "-z", commit, text=False)
    links = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        if not separator:
            raise ValueError(f"Malformed git ls-tree record in {repo}: {record!r}")
        mode, object_type, object_id = metadata.decode().split()
        if mode != "160000":
            continue
        if object_type != "commit":
            raise ValueError(f"Gitlink has unexpected object type in {repo}: {record!r}")
        path_value = raw_path.decode()
        pure_path = PurePosixPath(path_value)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ValueError(f"Unsafe gitlink path in {repo}: {path_value!r}")
        links.append((Path(*pure_path.parts), object_id))
    return links


def _extract_git_archive(repo: Path, commit: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    archive_fd, archive_name = tempfile.mkstemp(prefix=".source-archive.", suffix=".tar", dir=destination.parent)
    archive_path = Path(archive_name)
    try:
        with os.fdopen(archive_fd, "wb") as archive_handle:
            subprocess.run(
                ["git", "-C", str(repo), "archive", "--format=tar", commit],
                cwd=repo,
                stdout=archive_handle,
                check=True,
            )
        with tarfile.open(archive_path, mode="r:") as archive:
            archive.extractall(destination, filter="data")
    finally:
        archive_path.unlink(missing_ok=True)


def _materialize_submodules(
    repo: Path,
    commit: str,
    destination: Path,
    *,
    prefix: PurePosixPath = PurePosixPath(),
) -> list[dict[str, str]]:
    records = []
    for relative_path, object_id in _gitlinks(repo, commit):
        submodule_repo = repo / relative_path
        if not submodule_repo.is_dir():
            raise FileNotFoundError(f"Pinned submodule is not initialized: {submodule_repo}")
        _git(submodule_repo, "cat-file", "-e", f"{object_id}^{{commit}}")
        submodule_destination = destination / relative_path
        if submodule_destination.exists() and any(submodule_destination.iterdir()):
            raise FileExistsError(f"Submodule destination is not empty: {submodule_destination}")
        _extract_git_archive(submodule_repo, object_id, submodule_destination)
        manifest_path = prefix / PurePosixPath(relative_path.as_posix())
        records.append({"path": manifest_path.as_posix(), "commit_sha": object_id})
        records.extend(
            _materialize_submodules(
                submodule_repo,
                object_id,
                submodule_destination,
                prefix=manifest_path,
            )
        )
    return records


def _make_read_only(root: Path) -> None:
    paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        if path.is_symlink():
            continue
        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o222)
    root.chmod(stat.S_IMODE(root.stat().st_mode) & ~0o222)


def _verify_read_only(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink() or (relative.parts and relative.parts[0] == ".venv"):
            continue
        if stat.S_IMODE(path.stat().st_mode) & 0o222:
            raise ValueError(f"Source snapshot entry is writable: {path}")


def _normalized_pip_freeze(repo_root: Path, shared_venv: Path) -> str:
    python_path = shared_venv / "bin" / "python"
    if not python_path.is_file():
        raise FileNotFoundError(f"Shared environment Python does not exist: {python_path}")
    result = _run(
        ["uv", "pip", "freeze", "--python", str(python_path)],
        cwd=repo_root,
    )
    lines = sorted(line.rstrip() for line in result.stdout.splitlines() if line.strip())
    return "\n".join(lines) + "\n"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write_text_atomic(path: Path, value: str) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(value, encoding="utf-8")
    partial.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"Source provenance manifest does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Invalid source provenance schema: {path}")
    return payload


def _runtime_environment(snapshot: Path, source_repo: Path) -> dict[str, str]:
    environment = dict(os.environ)
    runtime_paths = [str(snapshot / path) for path in RUNTIME_PATHS]
    if existing := environment.get("PYTHONPATH"):
        runtime_paths.append(existing)
    environment.update(
        {
            "RSCI_SOURCE_SNAPSHOT": str(snapshot),
            "RSCI_LIVE_REPO_ROOT": str(source_repo),
            "UV_NO_SYNC": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join(runtime_paths),
        }
    )
    return environment


def _verify_runtime_imports(snapshot: Path, source_repo: Path) -> dict[str, str]:
    import_program = f"""
import importlib
import json
import sys
from pathlib import Path

snapshot = Path({str(snapshot)!r}).resolve()
live_repo = Path({str(source_repo)!r}).resolve()
expected = {REQUIRED_IMPORTS!r}
resolved = {{}}
for name, relative in expected.items():
    module = importlib.import_module(name)
    module_path = Path(module.__file__).resolve()
    expected_path = (snapshot / relative).resolve()
    if module_path != expected_path:
        raise RuntimeError(f"{{name}} resolved to {{module_path}}, expected {{expected_path}}")
    resolved[name] = str(module_path)
offenders = []
for entry in sys.path:
    if not entry:
        continue
    path = Path(entry).resolve()
    if (path == live_repo or live_repo in path.parents) and not (path == snapshot or snapshot in path.parents):
        offenders.append(str(path))
if offenders:
    raise RuntimeError(f"mutable checkout paths remain on sys.path: {{offenders}}")
print("RSCI_IMPORTS=" + json.dumps(resolved, sort_keys=True))
"""
    result = _run(
        ["uv", "run", "--no-sync", "python", "-c", import_program],
        cwd=snapshot,
        env=_runtime_environment(snapshot, source_repo),
    )
    marker = next((line for line in result.stdout.splitlines() if line.startswith("RSCI_IMPORTS=")), None)
    if marker is None:
        raise RuntimeError(f"Runtime import verification emitted no result: {result.stdout!r}")
    resolved = json.loads(marker.removeprefix("RSCI_IMPORTS="))
    if not isinstance(resolved, dict):
        raise ValueError("Runtime import verification result is not an object")
    return resolved


def _snapshot_config_paths(snapshot: Path, config_paths: list[Path]) -> list[str]:
    normalized = []
    for config_path in config_paths:
        raw_path = config_path.as_posix()
        pure_path = PurePosixPath(raw_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ValueError(f"Launch configs must be repository-relative paths: {raw_path}")
        resolved = (snapshot / Path(*pure_path.parts)).resolve()
        if snapshot != resolved and snapshot not in resolved.parents:
            raise ValueError(f"Launch config escapes the source snapshot: {raw_path}")
        if not resolved.is_file():
            raise FileNotFoundError(f"Pinned launch config does not exist: {resolved}")
        if resolved.suffix != ".toml":
            raise ValueError(f"Pinned launch config is not TOML: {resolved}")
        normalized.append(resolved.relative_to(snapshot).as_posix())
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"Pinned launch config list contains duplicates: {normalized}")
    return normalized


def _materialize_command(config_paths: list[str]) -> list[str]:
    command = ["uv", "run", "--no-sync", "rl"]
    for config_path in config_paths:
        command.extend(("@", config_path))
    command.append("--dry-run")
    return command


def _launch_artifact_hashes(run_dir: Path, snapshot: Path) -> dict[str, str]:
    config_dir = run_dir / "configs"
    config_paths = sorted(config_dir.glob("*.toml"))
    required_configs = {"inference.toml", "orchestrator.toml", "trainer.toml"}
    config_names = {path.name for path in config_paths}
    missing_configs = sorted(required_configs - config_names)
    if missing_configs:
        raise FileNotFoundError(f"Resolved launch configs are missing under {config_dir}: {missing_configs}")
    unexpected_configs = sorted(config_names - required_configs)
    if unexpected_configs:
        raise ValueError(f"Unexpected resolved launch configs under {config_dir}: {unexpected_configs}")
    sbatch_path = run_dir / "rl.sbatch"
    if not sbatch_path.is_file():
        raise FileNotFoundError(f"Generated RL script does not exist: {sbatch_path}")

    sbatch = sbatch_path.read_text(encoding="utf-8")
    project_assignments = {
        f"export PROJECT_DIR={snapshot}",
        f'export PROJECT_DIR="{snapshot}"',
    }
    if not project_assignments.intersection(sbatch.splitlines()):
        raise ValueError(f"Generated RL script does not pin PROJECT_DIR to {snapshot}")
    output_assignments = {
        f"export OUTPUT_DIR={run_dir}",
        f'export OUTPUT_DIR="{run_dir}"',
    }
    if not output_assignments.intersection(sbatch.splitlines()):
        raise ValueError(f"Generated RL script does not pin OUTPUT_DIR to {run_dir}")
    activation = 'source user/tianhaowu/rsci/scripts/activate_source_snapshot.sh "$OUTPUT_DIR"'
    activation_index = sbatch.find(activation)
    if activation_index < 0:
        raise ValueError("Generated RL script does not source the RSCI snapshot activation guard")
    project_import_index = sbatch.find("uv run ")
    if project_import_index >= 0 and activation_index > project_import_index:
        raise ValueError("Generated RL script imports project code before the snapshot activation guard")

    artifacts = [sbatch_path, *config_paths]
    return {str(path.relative_to(run_dir)): sha256_file(path) for path in artifacts}


def _valid_artifact_hashes(value: object) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(path, str) and isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None
            for path, digest in value.items()
        )
    )


def _verify_launch_materialization(
    run_dir: Path,
    snapshot: Path,
    manifest: dict[str, Any],
    *,
    required: bool,
) -> dict[str, Any]:
    materialization = manifest.get("launch_materialization")
    if materialization is None and not required:
        return {}
    if not isinstance(materialization, dict):
        raise ValueError("Launch was not materialized by the pinned source snapshot")
    config_paths = materialization.get("config_paths")
    if (
        not isinstance(config_paths, list)
        or not config_paths
        or not all(isinstance(path, str) for path in config_paths)
    ):
        raise ValueError("Launch materialization has invalid pinned config paths")
    normalized_paths = _snapshot_config_paths(snapshot, [Path(path) for path in config_paths])
    if normalized_paths != config_paths:
        raise ValueError("Launch materialization config paths are not canonical")
    expected_command = _materialize_command(config_paths)
    if materialization.get("command") != expected_command:
        raise ValueError("Launch materialization command does not match its pinned config paths")
    if materialization.get("parent_commit_sha") != manifest.get("parent_commit_sha"):
        raise ValueError("Launch materialization does not match the pinned parent commit")
    if materialization.get("source_tree_sha256") != manifest.get("source_tree_sha256"):
        raise ValueError("Launch materialization does not match the pinned source tree")
    recorded_hashes = materialization.get("artifact_sha256")
    if not _valid_artifact_hashes(recorded_hashes):
        raise ValueError("Launch materialization has invalid artifact hashes")
    current_hashes = _launch_artifact_hashes(run_dir, snapshot)
    if current_hashes != recorded_hashes:
        raise ValueError("Launch artifacts changed after pinned materialization")
    return materialization


def _verify_launch_artifacts(
    run_dir: Path,
    snapshot: Path,
    manifest: dict[str, Any],
    *,
    required: bool,
) -> dict[str, str]:
    recorded = manifest.get("launch_artifacts_sha256")
    if recorded is None and not required:
        return {}
    if not _valid_artifact_hashes(recorded):
        raise ValueError("Source provenance is not sealed to resolved configs and rl.sbatch")
    current = _launch_artifact_hashes(run_dir, snapshot)
    if current != recorded:
        raise ValueError("Resolved configs or rl.sbatch changed after source provenance was sealed")
    return current


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"TOML root is not an object: {path}")
    return payload


def _file_identity(path: Path) -> dict[str, Any]:
    if not path.is_absolute():
        raise ValueError(f"Launch input path must be absolute: {path}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Launch input file does not exist: {resolved}")
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _directory_identity(path: Path) -> dict[str, Any]:
    if not path.is_absolute():
        raise ValueError(f"Launch input path must be absolute: {path}")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"Launch input directory does not exist: {resolved}")

    digest = hashlib.sha256(b"rsci-input-directory-v1\0")
    file_count = 0
    size_bytes = 0
    for entry in sorted(resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix()):
        relative = entry.relative_to(resolved).as_posix()
        if entry.is_symlink():
            target = entry.resolve()
            if not target.is_file():
                raise ValueError(f"Launch input directory contains a non-file symlink: {entry}")
        elif entry.is_dir():
            continue
        elif entry.is_file():
            target = entry
        else:
            raise ValueError(f"Unsupported launch input directory entry: {entry}")
        content_digest = sha256_file(target)
        size = target.stat().st_size
        _digest_field(digest, relative.encode())
        _digest_field(digest, str(size).encode())
        _digest_field(digest, content_digest.encode())
        file_count += 1
        size_bytes += size
    if file_count == 0:
        raise ValueError(f"Launch input directory contains no files: {resolved}")
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "file_count": file_count,
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
    }


def _dataset_manifest_identity(dataset: dict[str, Any]) -> dict[str, Any] | None:
    dataset_path = Path(dataset["path"])
    resolved_dataset = Path(dataset["resolved_path"])
    for parent in (dataset_path.parent, dataset_path.parent.parent):
        manifest_path = parent / "dataset_manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, dict):
            raise ValueError(f"Dataset manifest has no files object: {manifest_path}")
        for record in files.values():
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                continue
            if Path(record["path"]).expanduser().resolve() != resolved_dataset:
                continue
            declared_digest = record.get("sha256")
            if declared_digest != dataset["sha256"]:
                raise ValueError(
                    f"Dataset bytes do not match {manifest_path}: "
                    f"declared={declared_digest}, actual={dataset['sha256']}"
                )
            identity = _file_identity(manifest_path.resolve())
            identity["declared_dataset_sha256"] = declared_digest
            return identity
    return None


def _nested_string(payload: dict[str, Any], keys: tuple[str, ...], source: Path) -> str:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"Resolved config {source} has no {'.'.join(keys)}")
        value = value[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Resolved config {source} has invalid {'.'.join(keys)}")
    return value


def _launch_input_identities(run_dir: Path) -> dict[str, Any]:
    config_dir = run_dir / "configs"
    trainer_path = config_dir / "trainer.toml"
    orchestrator_path = config_dir / "orchestrator.toml"
    inference_path = config_dir / "inference.toml"
    trainer = _load_toml(trainer_path)
    orchestrator = _load_toml(orchestrator_path)
    inference = _load_toml(inference_path)

    model_references = {
        "trainer.model.name": _nested_string(trainer, ("model", "name"), trainer_path),
        "orchestrator.student.model.name": _nested_string(
            orchestrator,
            ("student", "model", "name"),
            orchestrator_path,
        ),
        "inference.model.name": _nested_string(inference, ("model", "name"), inference_path),
    }
    resolved_models = {str(Path(value).expanduser().resolve()) for value in model_references.values()}
    if len(resolved_models) != 1:
        raise ValueError(f"Resolved launch configs disagree on the base model: {model_references}")
    configured_model_path = Path(model_references["trainer.model.name"]).expanduser()
    base_model = _directory_identity(configured_model_path)
    base_model["config_references"] = model_references

    tokenizer_references = {
        "trainer.tokenizer.name": _nested_string(trainer, ("tokenizer", "name"), trainer_path),
        "orchestrator.tokenizer.name": _nested_string(
            orchestrator,
            ("tokenizer", "name"),
            orchestrator_path,
        ),
    }
    resolved_tokenizers = {str(Path(value).expanduser().resolve()) for value in tokenizer_references.values()}
    if len(resolved_tokenizers) != 1:
        raise ValueError(f"Resolved launch configs disagree on the tokenizer: {tokenizer_references}")
    configured_tokenizer_path = Path(tokenizer_references["trainer.tokenizer.name"]).expanduser()
    if configured_tokenizer_path.resolve() == configured_model_path.resolve():
        tokenizer = {key: base_model[key] for key in ("path", "resolved_path", "file_count", "size_bytes", "sha256")}
        tokenizer["path"] = str(configured_tokenizer_path)
    else:
        tokenizer = _directory_identity(configured_tokenizer_path)
    tokenizer["config_references"] = tokenizer_references

    chat_template_references = {
        "trainer.tokenizer.chat_template": _nested_string(
            trainer,
            ("tokenizer", "chat_template"),
            trainer_path,
        ),
        "orchestrator.tokenizer.chat_template": _nested_string(
            orchestrator,
            ("tokenizer", "chat_template"),
            orchestrator_path,
        ),
        "inference.model.chat_template": _nested_string(
            inference,
            ("model", "chat_template"),
            inference_path,
        ),
    }
    resolved_templates = {str(Path(value).expanduser().resolve()) for value in chat_template_references.values()}
    if len(resolved_templates) != 1:
        raise ValueError(f"Resolved launch configs disagree on the chat template: {chat_template_references}")
    chat_template = _file_identity(Path(chat_template_references["trainer.tokenizer.chat_template"]).expanduser())
    chat_template["config_references"] = chat_template_references

    datasets_by_path: dict[str, dict[str, Any]] = {}
    for phase in ("train", "eval"):
        section = orchestrator.get(phase)
        environments = section.get("env") if isinstance(section, dict) else None
        if not isinstance(environments, list) or not environments:
            raise ValueError(f"Resolved orchestrator config has no {phase} environments: {orchestrator_path}")
        for index, environment in enumerate(environments):
            if not isinstance(environment, dict):
                raise ValueError(f"Resolved {phase} environment {index} is not an object: {orchestrator_path}")
            args = environment.get("args")
            dataset_path = args.get("dataset_path") if isinstance(args, dict) else None
            if not isinstance(dataset_path, str) or not dataset_path:
                raise ValueError(f"Resolved {phase} environment {index} has no args.dataset_path: {orchestrator_path}")
            if dataset_path not in datasets_by_path:
                identity = _file_identity(Path(dataset_path).expanduser())
                if dataset_manifest := _dataset_manifest_identity(identity):
                    identity["dataset_manifest"] = dataset_manifest
                datasets_by_path[dataset_path] = identity
            datasets_by_path[dataset_path].setdefault("environments", []).append(
                {
                    "phase": phase,
                    "index": index,
                    "id": environment.get("id"),
                    "name": environment.get("name"),
                }
            )
    return {
        "datasets": [datasets_by_path[path] for path in sorted(datasets_by_path)],
        "base_model": base_model,
        "tokenizer": tokenizer,
        "chat_template": chat_template,
    }


def _verify_launch_inputs(
    run_dir: Path,
    manifest: dict[str, Any],
    *,
    required: bool,
) -> dict[str, Any]:
    recorded = manifest.get("launch_inputs")
    if recorded is None and not required:
        return {}
    if not isinstance(recorded, dict):
        raise ValueError("Source provenance is not sealed to datasets, model, tokenizer, and chat template inputs")
    current = _launch_input_identities(run_dir)
    if current != recorded:
        raise ValueError("Dataset, model, tokenizer, or chat template changed after launch sealing")
    return current


def verify_snapshot(
    run_dir: Path,
    expected_source: Path | None = None,
    *,
    verify_imports: bool = True,
    require_launch: bool = True,
) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    manifest = _load_manifest(run_dir)
    snapshot = Path(manifest.get("snapshot_path", "")).resolve()
    expected_snapshot = (expected_source or run_dir / SNAPSHOT_NAME).expanduser().resolve()
    if snapshot != expected_snapshot or snapshot != (run_dir / SNAPSHOT_NAME).resolve():
        raise ValueError(f"Source snapshot identity mismatch: manifest={snapshot}, expected={expected_snapshot}")
    if not snapshot.is_dir():
        raise FileNotFoundError(f"Source snapshot does not exist: {snapshot}")
    source_repo = Path(manifest.get("source_repo", "")).resolve()
    if source_repo != LIVE_REPO_ROOT.resolve():
        raise ValueError(f"Unexpected source repository in provenance: {source_repo}")

    parent_commit = manifest.get("parent_commit_sha")
    tree_digest = manifest.get("source_tree_sha256")
    lock_digest = manifest.get("uv_lock_sha256")
    freeze_digest = manifest.get("pip_freeze_sha256")
    for name, value in (
        ("parent_commit_sha", parent_commit),
        ("source_tree_sha256", tree_digest),
        ("uv_lock_sha256", lock_digest),
        ("pip_freeze_sha256", freeze_digest),
    ):
        if not isinstance(value, str):
            raise ValueError(f"Invalid {name} in source provenance")
        pattern = GIT_SHA_RE if name == "parent_commit_sha" else SHA256_RE
        if pattern.fullmatch(value) is None:
            raise ValueError(f"Invalid {name} in source provenance")
    submodules = manifest.get("submodules")
    if not isinstance(submodules, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("path"), str)
        or not isinstance(item.get("commit_sha"), str)
        or GIT_SHA_RE.fullmatch(item["commit_sha"]) is None
        for item in submodules
    ):
        raise ValueError("Source provenance has invalid submodule commit records")

    if source_tree_sha256(snapshot) != tree_digest:
        raise ValueError("Source snapshot content digest does not match source_provenance.json")
    _verify_read_only(snapshot)
    lock_path = snapshot / "uv.lock"
    if not lock_path.is_file() or sha256_file(lock_path) != lock_digest:
        raise ValueError("Snapshot uv.lock hash does not match source_provenance.json")

    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("Source provenance has no environment object")
    shared_venv = Path(environment.get("shared_venv", "")).resolve()
    venv_link = snapshot / ".venv"
    if not venv_link.is_symlink() or venv_link.resolve() != shared_venv:
        raise ValueError(f"Snapshot .venv does not resolve to the recorded shared environment: {shared_venv}")
    freeze_path = run_dir / FREEZE_NAME
    if not freeze_path.is_file() or sha256_file(freeze_path) != freeze_digest:
        raise ValueError("Persisted pip freeze hash does not match source_provenance.json")
    current_freeze = _normalized_pip_freeze(snapshot, shared_venv)
    if _sha256_text(current_freeze) != freeze_digest:
        raise ValueError("Shared environment pip freeze changed after source snapshot creation")

    materialization = _verify_launch_materialization(
        run_dir,
        snapshot,
        manifest,
        required=require_launch,
    )
    launch_artifacts = _verify_launch_artifacts(
        run_dir,
        snapshot,
        manifest,
        required=require_launch,
    )
    launch_inputs = _verify_launch_inputs(run_dir, manifest, required=require_launch)
    imports = _verify_runtime_imports(snapshot, source_repo) if verify_imports else {}
    return {
        "manifest_path": str(run_dir / MANIFEST_NAME),
        "snapshot_path": str(snapshot),
        "parent_commit_sha": parent_commit,
        "source_tree_sha256": tree_digest,
        "launch_materialization": materialization,
        "launch_artifacts_sha256": launch_artifacts,
        "launch_inputs": launch_inputs,
        "runtime_imports": imports,
    }


def materialize_launch(run_dir: Path, config_paths: list[Path]) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    lock_path = run_dir / "source_provenance.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        source_state = verify_snapshot(run_dir, require_launch=False)
        snapshot = Path(source_state["snapshot_path"])
        manifest = _load_manifest(run_dir)
        if manifest.get("launch_artifacts_sha256") is not None:
            raise ValueError("Refusing to rematerialize an already sealed launch")
        normalized_paths = _snapshot_config_paths(snapshot, config_paths)
        command = _materialize_command(normalized_paths)
        environment = _runtime_environment(snapshot, Path(manifest["source_repo"]))
        environment["NEVER_CLEAN_OUTPUT_DIR"] = "1"
        _run(command, cwd=snapshot, env=environment)
        artifact_hashes = _launch_artifact_hashes(run_dir, snapshot)
        materialization = {
            "materialized_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "parent_commit_sha": manifest["parent_commit_sha"],
            "source_tree_sha256": manifest["source_tree_sha256"],
            "config_paths": normalized_paths,
            "command": command,
            "artifact_sha256": artifact_hashes,
        }
        manifest["launch_materialization"] = materialization
        _write_json_atomic(run_dir / MANIFEST_NAME, manifest)
    _verify_launch_materialization(run_dir, snapshot, _load_manifest(run_dir), required=True)
    return {
        "manifest_path": str(run_dir / MANIFEST_NAME),
        "snapshot_path": str(snapshot),
        "launch_materialization": materialization,
    }


def seal_launch(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    lock_path = run_dir / "source_provenance.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        source_state = verify_snapshot(run_dir, require_launch=False)
        snapshot = Path(source_state["snapshot_path"])
        manifest = _load_manifest(run_dir)
        materialization = _verify_launch_materialization(
            run_dir,
            snapshot,
            manifest,
            required=True,
        )
        current = dict(materialization["artifact_sha256"])
        launch_inputs = _launch_input_identities(run_dir)
        recorded = manifest.get("launch_artifacts_sha256")
        if recorded is not None and recorded != current:
            raise ValueError("Refusing to replace a launch seal with different artifact hashes")
        recorded_inputs = manifest.get("launch_inputs")
        if recorded_inputs is not None and recorded_inputs != launch_inputs:
            raise ValueError("Refusing to replace a launch seal with different external inputs")
        manifest["launch_artifacts_sha256"] = current
        manifest["launch_inputs"] = launch_inputs
        manifest["launch_sealed_at"] = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        _write_json_atomic(run_dir / MANIFEST_NAME, manifest)
    return verify_snapshot(run_dir)


def create_snapshot(
    run_dir: Path,
    *,
    commit: str = "HEAD",
    repo_root: Path = LIVE_REPO_ROOT,
    shared_venv: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    if repo_root != LIVE_REPO_ROOT.resolve():
        raise ValueError(f"RSCI source snapshots must come from {LIVE_REPO_ROOT}, got {repo_root}")
    run_dir = run_dir.expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    resolved_commit = str(_git(repo_root, "rev-parse", f"{commit}^{{commit}}")).strip()
    shared_venv = (shared_venv or repo_root / ".venv").expanduser().resolve()
    if not shared_venv.is_dir():
        raise FileNotFoundError(f"Shared environment does not exist: {shared_venv}")

    lock_path = run_dir / "source_provenance.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        snapshot = run_dir / SNAPSHOT_NAME
        manifest_path = run_dir / MANIFEST_NAME
        if snapshot.exists() or manifest_path.exists():
            verified = verify_snapshot(run_dir, snapshot, require_launch=False)
            if verified["parent_commit_sha"] != resolved_commit:
                raise ValueError(
                    f"Existing source snapshot pins {verified['parent_commit_sha']}, requested {resolved_commit}"
                )
            return verified

        temporary = Path(tempfile.mkdtemp(prefix=".source_snapshot.", dir=run_dir))
        try:
            _extract_git_archive(repo_root, resolved_commit, temporary)
            submodules = _materialize_submodules(repo_root, resolved_commit, temporary)
            (temporary / ".venv").symlink_to(shared_venv, target_is_directory=True)
            _make_read_only(temporary)
            tree_digest = source_tree_sha256(temporary)
            uv_lock = temporary / "uv.lock"
            if not uv_lock.is_file():
                raise FileNotFoundError(f"Pinned source has no uv.lock: {uv_lock}")
            freeze = _normalized_pip_freeze(repo_root, shared_venv)
            freeze_digest = _sha256_text(freeze)
            _write_text_atomic(run_dir / FREEZE_NAME, freeze)
            temporary.replace(snapshot)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "source_repo": str(repo_root),
                "parent_commit_sha": resolved_commit,
                "submodules": sorted(submodules, key=lambda item: item["path"]),
                "snapshot_path": str(snapshot),
                "source_tree_sha256": tree_digest,
                "uv_lock_sha256": sha256_file(snapshot / "uv.lock"),
                "pip_freeze_sha256": freeze_digest,
                "pip_freeze_path": str(run_dir / FREEZE_NAME),
                "runtime_python_paths": list(RUNTIME_PATHS),
                "required_imports": REQUIRED_IMPORTS,
                "environment": {
                    "shared_venv": str(shared_venv),
                    "python": str(shared_venv / "bin" / "python"),
                    "uv_version": _run(["uv", "--version"], cwd=repo_root).stdout.strip(),
                },
            }
            _write_json_atomic(manifest_path, manifest)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    return verify_snapshot(run_dir, snapshot, require_launch=False)


def main() -> None:
    args = parse_args()
    if args.command == "create":
        result = create_snapshot(
            args.run_dir,
            commit=args.commit,
            shared_venv=args.shared_venv,
        )
    elif args.command == "materialize-launch":
        result = materialize_launch(args.run_dir, args.configs)
    elif args.command == "seal-launch":
        result = seal_launch(args.run_dir)
    elif args.command == "verify":
        result = verify_snapshot(args.run_dir, args.expected_source)
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
