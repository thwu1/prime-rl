#!/usr/bin/env python3
"""Stdlib-only import-closure bootstrap for the private source-wheel proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import stat
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

APPROVED_BASE_RUNTIME_COMMIT = "ceb9356c98c72e51568e7bb4658a540cb1492254"
BOOTSTRAP_ATTESTATION_ENV = "SOURCE_WHEEL_PROOF_BOOTSTRAP_ATTESTATION_SHA256"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
CLEAN_TREE_SHA256 = hashlib.sha256(b"").hexdigest()
MAX_INSPECTION_RECEIPT_BYTES = 16 * 1024


class BindingError(RuntimeError):
    """A fail-closed binding error with an aggregate-safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_file_digest(path: Path, code: str, *, executable: bool = False) -> tuple[int, int, str]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise BindingError(code) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or (executable and before.st_mode & 0o111 == 0):
            raise BindingError(code)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise BindingError(code)
    return stat.S_IMODE(before.st_mode), before.st_size, digest.hexdigest()


def stable_file_payload(path: Path, code: str, *, max_bytes: int) -> tuple[int, bytes, str]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise BindingError(code) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > max_bytes:
            raise BindingError(code)
        payload = b""
        while chunk := os.read(descriptor, min(1024 * 1024, max_bytes + 1 - len(payload))):
            payload += chunk
            if len(payload) > max_bytes:
                raise BindingError(code)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise BindingError(code)
    return stat.S_IMODE(before.st_mode), payload, sha256_bytes(payload)


def canonical_tree_manifest_sha256(root: Path) -> str:
    """Hash a complete directory tree without following directory symlinks."""
    try:
        resolved_root = root.resolve(strict=True)
        root_status = resolved_root.lstat()
    except OSError as error:
        raise BindingError("runtime_manifest_invalid") from error
    if root != resolved_root or not stat.S_ISDIR(root_status.st_mode):
        raise BindingError("runtime_manifest_invalid")
    records: list[list[object]] = [["directory", ".", stat.S_IMODE(root_status.st_mode)]]

    def visit(directory: Path, relative: PurePosixPath) -> None:
        try:
            before = directory.lstat()
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            raise BindingError("runtime_manifest_invalid") from error
        names = [entry.name for entry in entries]
        for entry in entries:
            child = Path(entry.path)
            child_relative = relative / entry.name
            try:
                status = child.lstat()
            except OSError as error:
                raise BindingError("runtime_manifest_invalid") from error
            if stat.S_ISDIR(status.st_mode):
                records.append(["directory", child_relative.as_posix(), stat.S_IMODE(status.st_mode)])
                visit(child, child_relative)
                continue
            if stat.S_ISREG(status.st_mode):
                mode, size, digest = stable_file_digest(child, "runtime_manifest_invalid")
                records.append(["file", child_relative.as_posix(), mode, size, digest])
                continue
            if stat.S_ISLNK(status.st_mode):
                try:
                    target = os.readlink(child)
                    resolved_target = child.resolve(strict=True)
                except OSError as error:
                    raise BindingError("runtime_manifest_invalid") from error
                if not resolved_target.is_file():
                    raise BindingError("runtime_manifest_invalid")
                mode, size, digest = stable_file_digest(resolved_target, "runtime_manifest_invalid")
                records.append(
                    [
                        "symlink",
                        child_relative.as_posix(),
                        stat.S_IMODE(status.st_mode),
                        target,
                        str(resolved_target),
                        mode,
                        size,
                        digest,
                    ]
                )
                try:
                    after_link = child.lstat()
                    after_target = os.readlink(child)
                except OSError as error:
                    raise BindingError("runtime_manifest_invalid") from error
                if (
                    status.st_dev,
                    status.st_ino,
                    status.st_mode,
                    status.st_mtime_ns,
                    status.st_ctime_ns,
                    target,
                ) != (
                    after_link.st_dev,
                    after_link.st_ino,
                    after_link.st_mode,
                    after_link.st_mtime_ns,
                    after_link.st_ctime_ns,
                    after_target,
                ):
                    raise BindingError("runtime_manifest_changed")
                continue
            raise BindingError("runtime_manifest_invalid")
        try:
            after = directory.lstat()
            after_names = sorted(entry.name for entry in os.scandir(directory))
        except OSError as error:
            raise BindingError("runtime_manifest_invalid") from error
        if names != after_names or (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BindingError("runtime_manifest_changed")

    visit(resolved_root, PurePosixPath())
    return sha256_bytes(canonical_json({"schema_version": 1, "records": records}))


def python_sources_sha256(directory: Path) -> str:
    try:
        root = directory.resolve(strict=True)
        paths = sorted(
            (path for path in root.iterdir() if path.is_file() and path.suffix == ".py"),
            key=lambda path: path.name,
        )
    except OSError as error:
        raise BindingError("vmvm_runtime_source_invalid") from error
    if directory != root or not paths:
        raise BindingError("vmvm_runtime_source_invalid")
    records = []
    for path in paths:
        mode, size, digest = stable_file_digest(path, "vmvm_runtime_source_invalid")
        records.append([path.name, mode, size, digest])
    return sha256_bytes(canonical_json({"schema_version": 1, "files": records}))


def git_output(project_dir: Path, *arguments: str) -> str:
    environment = {
        "HOME": "/nonexistent",
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    }
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(project_dir), *arguments],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
    except OSError as error:
        raise BindingError("source_checkout_invalid") from error
    if result.returncode != 0:
        raise BindingError("source_checkout_invalid")
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise BindingError("source_checkout_invalid") from error


def expected_import_roots(project_dir: Path, site_packages_path: Path) -> tuple[Path, ...]:
    return (
        project_dir / "user/tianhaowu/terminal_bench_vmvm",
        project_dir / "environments/vmvm_tb_v2",
        project_dir / "deps/verifiers",
        project_dir / "deps/renderers",
        project_dir / "deps/pydantic-config/src",
        site_packages_path,
    )


def _validate_bootstrap_flags() -> None:
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.no_user_site
        and sys.flags.safe_path
        and sys.dont_write_bytecode
    ):
        raise BindingError("python_bootstrap_flags_invalid")
    if "site" in sys.modules or "sitecustomize" in sys.modules or "usercustomize" in sys.modules:
        raise BindingError("python_bootstrap_site_loaded")


def _validate_stdlib_sys_path(python_stdlib_path: Path, paths: list[str]) -> tuple[str, ...]:
    try:
        stdlib = python_stdlib_path.resolve(strict=True)
    except OSError as error:
        raise BindingError("python_import_closure_invalid") from error
    if python_stdlib_path != stdlib or not stdlib.is_dir() or not paths or len(paths) != len(set(paths)):
        raise BindingError("python_import_closure_invalid")
    zip_path = stdlib.parent / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    for raw in paths:
        path = Path(raw)
        if not raw or not path.is_absolute():
            raise BindingError("python_import_closure_invalid")
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            if path != zip_path:
                raise BindingError("python_import_closure_invalid")
            continue
        except OSError as error:
            raise BindingError("python_import_closure_invalid") from error
        try:
            resolved.relative_to(stdlib)
        except ValueError as error:
            raise BindingError("python_import_closure_invalid") from error
    return tuple(paths)


def install_import_roots(project_dir: Path, site_packages_path: Path) -> tuple[Path, ...]:
    _validate_bootstrap_flags()
    initial = _validate_stdlib_sys_path(Path(sysconfig.get_path("stdlib")), list(sys.path))
    roots = expected_import_roots(project_dir, site_packages_path)
    resolved_roots: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve(strict=True)
        except OSError as error:
            raise BindingError("python_import_closure_invalid") from error
        if root != resolved or not resolved.is_dir():
            raise BindingError("python_import_closure_invalid")
        resolved_roots.append(resolved)
    sys.path[:] = [str(path) for path in resolved_roots] + list(initial)
    return tuple(resolved_roots)


def _expected_effective_sys_path(import_roots: tuple[Path, ...], python_stdlib_path: Path) -> tuple[str, ...]:
    prefix = tuple(str(path) for path in import_roots)
    observed = tuple(sys.path)
    if observed[: len(prefix)] != prefix:
        raise BindingError("python_import_closure_invalid")
    suffix = _validate_stdlib_sys_path(python_stdlib_path, list(observed[len(prefix) :]))
    if observed != prefix + suffix:
        raise BindingError("python_import_closure_invalid")
    return observed


def python_runtime_manifest_sha256(
    python_path: Path,
    python_stdlib_path: Path,
    import_roots: tuple[Path, ...],
    import_root_bindings: tuple[tuple[str, str], ...],
) -> str:
    try:
        executable = Path(sys.executable).resolve(strict=True)
        stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
        platstdlib = Path(sysconfig.get_path("platstdlib")).resolve(strict=True)
    except (OSError, TypeError) as error:
        raise BindingError("python_runtime_invalid") from error
    if executable != python_path or stdlib != python_stdlib_path or len(import_roots) != len(import_root_bindings):
        raise BindingError("python_runtime_invalid")
    _validate_bootstrap_flags()
    effective_sys_path = _expected_effective_sys_path(import_roots, python_stdlib_path)
    _, _, executable_sha256 = stable_file_digest(executable, "python_runtime_invalid", executable=True)
    path_records = []
    bindings = dict(import_root_bindings)
    if len(bindings) != len(import_roots):
        raise BindingError("python_import_closure_invalid")
    for raw in effective_sys_path:
        path = Path(raw)
        if path in import_roots:
            path_records.append([raw, "bound-import-root", bindings[raw]])
        elif path.exists():
            path_records.append([raw, "stdlib", str(path.resolve(strict=True))])
        else:
            path_records.append([raw, "missing-stdlib-zip", None])
    payload = {
        "schema_version": 2,
        "kind": "python-stdlib-runtime-and-import-closure-manifest",
        "executable": str(executable),
        "executable_sha256": executable_sha256,
        "stdlib": str(stdlib),
        "platstdlib": str(platstdlib),
        "stdlib_tree_sha256": canonical_tree_manifest_sha256(stdlib),
        "implementation": sys.implementation.name,
        "cache_tag": sys.implementation.cache_tag,
        "version": list(sys.version_info[:5]),
        "platform": sysconfig.get_platform(),
        "soabi": sysconfig.get_config_var("SOABI"),
        "multiarch": sysconfig.get_config_var("MULTIARCH"),
        "prefixes": [sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix],
        "effective_sys_path": path_records,
        "startup_flags": {
            "isolated": bool(sys.flags.isolated),
            "no_site": bool(sys.flags.no_site),
            "no_user_site": bool(sys.flags.no_user_site),
            "safe_path": bool(sys.flags.safe_path),
            "dont_write_bytecode": bool(sys.dont_write_bytecode),
        },
    }
    return sha256_bytes(canonical_json(payload))


@dataclass(frozen=True)
class ExecutionBindings:
    project_dir: Path
    inspection_receipt_path: Path
    clean_wrapper_path: Path
    canonical_launcher_path: Path
    executed_launcher_path: Path
    uv_path: Path
    python_path: Path
    python_stdlib_path: Path
    site_packages_path: Path
    vacli_path: Path
    inspection_receipt_sha256: str
    clean_wrapper_sha256: str
    launcher_sha256: str
    uv_sha256: str
    python_sha256: str
    python_runtime_manifest_sha256: str
    site_packages_manifest_sha256: str
    base_runtime_commit: str
    source_commit: str
    source_git_tree: str
    source_tree_sha256: str
    verifiers_commit: str
    renderers_commit: str
    pydantic_config_commit: str
    vmvm_tb_v2_sha256: str
    vacli_binary_sha256: str
    expected_host: str


def _resolved_bindings(bindings: ExecutionBindings) -> tuple[Path, ...]:
    try:
        project = bindings.project_dir.resolve(strict=True)
        inspection_receipt = bindings.inspection_receipt_path.resolve(strict=True)
        clean_wrapper = bindings.clean_wrapper_path.resolve(strict=True)
        canonical_launcher = bindings.canonical_launcher_path.resolve(strict=True)
        executed_launcher = bindings.executed_launcher_path.resolve(strict=True)
        uv_path = bindings.uv_path.resolve(strict=True)
        python_path = bindings.python_path.resolve(strict=True)
        python_stdlib = bindings.python_stdlib_path.resolve(strict=True)
        site_packages = bindings.site_packages_path.resolve(strict=True)
        vacli_path = bindings.vacli_path.resolve(strict=True)
    except OSError as error:
        raise BindingError("execution_binding_invalid") from error
    expected_wrapper = project / "user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof_clean_env.sbatch"
    expected_launcher = project / "user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof.sbatch"
    if (
        project != bindings.project_dir
        or inspection_receipt != bindings.inspection_receipt_path
        or clean_wrapper != bindings.clean_wrapper_path
        or clean_wrapper != expected_wrapper
        or canonical_launcher != bindings.canonical_launcher_path
        or canonical_launcher != expected_launcher
        or executed_launcher != canonical_launcher
        or executed_launcher != bindings.executed_launcher_path
        or uv_path != bindings.uv_path
        or python_path != bindings.python_path
        or python_stdlib != bindings.python_stdlib_path
        or site_packages != bindings.site_packages_path
        or vacli_path != bindings.vacli_path
    ):
        raise BindingError("execution_binding_invalid")
    return (
        project,
        inspection_receipt,
        clean_wrapper,
        canonical_launcher,
        uv_path,
        python_path,
        python_stdlib,
        site_packages,
        vacli_path,
    )


def _validate_environment() -> None:
    expected_python_environment = {
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONSAFEPATH": "1",
    }
    observed_python_environment = {name: value for name, value in os.environ.items() if name.startswith("PYTHON")}
    forbidden = (
        "BASH_ENV",
        "ENV",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    )
    if (
        os.environ.get("PATH") != "/usr/bin:/bin"
        or observed_python_environment != expected_python_environment
        or any(name in os.environ for name in forbidden)
        or any(name.startswith("LD_") for name in os.environ)
        or any(name.startswith("BASH_FUNC_") for name in os.environ)
    ):
        raise BindingError("execution_environment_not_sanitized")


def _import_root_bindings(bindings: ExecutionBindings, import_roots: tuple[Path, ...]) -> tuple[tuple[str, str], ...]:
    values = (
        f"source-git-tree:{bindings.source_git_tree}",
        f"source-git-tree:{bindings.source_git_tree};vmvm:{bindings.vmvm_tb_v2_sha256}",
        f"gitlink:{bindings.verifiers_commit}",
        f"gitlink:{bindings.renderers_commit}",
        f"gitlink:{bindings.pydantic_config_commit}",
        f"tree-sha256:{bindings.site_packages_manifest_sha256}",
    )
    return tuple(
        (
            str(path),
            f"{value};effective-root-tree-sha256:{canonical_tree_manifest_sha256(path)}",
        )
        for path, value in zip(import_roots[:-1], values[:-1], strict=True)
    ) + ((str(import_roots[-1]), values[-1]),)


def inspection_receipt(hashes: dict[str, object], host: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "source-wheel-proof-environment-inspection",
        "status": "complete",
        "invocation_host": host,
        "hashes": hashes,
    }


def _expected_inspection_hashes(bindings: ExecutionBindings) -> dict[str, object]:
    return {
        "clean_wrapper_sha256": bindings.clean_wrapper_sha256,
        "launcher_sha256": bindings.launcher_sha256,
        "python_runtime_manifest_sha256": bindings.python_runtime_manifest_sha256,
        "python_sha256": bindings.python_sha256,
        "site_packages_manifest_sha256": bindings.site_packages_manifest_sha256,
        "uv_sha256": bindings.uv_sha256,
        "vacli_binary_sha256": bindings.vacli_binary_sha256,
        "vmvm_tb_v2_sha256": bindings.vmvm_tb_v2_sha256,
    }


def _validate_inspection_receipt(bindings: ExecutionBindings, path: Path) -> None:
    mode, payload, digest = stable_file_payload(
        path,
        "inspection_receipt_invalid",
        max_bytes=MAX_INSPECTION_RECEIPT_BYTES,
    )
    expected = canonical_json(inspection_receipt(_expected_inspection_hashes(bindings), bindings.expected_host)) + b"\n"
    if mode & 0o077 or digest != bindings.inspection_receipt_sha256 or payload != expected:
        raise BindingError("inspection_receipt_invalid")


def validate_pre_import_bindings(bindings: ExecutionBindings) -> tuple[Path, ...]:
    _validate_bootstrap_flags()
    _validate_environment()
    if HOST_RE.fullmatch(bindings.expected_host) is None or os.uname().nodename != bindings.expected_host:
        raise BindingError("execution_host_mismatch")
    (
        project,
        inspection_receipt_path,
        clean_wrapper,
        canonical_launcher,
        uv_path,
        python_path,
        python_stdlib,
        site_packages,
        vacli_path,
    ) = _resolved_bindings(bindings)
    digests = (
        bindings.inspection_receipt_sha256,
        bindings.clean_wrapper_sha256,
        bindings.launcher_sha256,
        bindings.uv_sha256,
        bindings.python_sha256,
        bindings.python_runtime_manifest_sha256,
        bindings.site_packages_manifest_sha256,
        bindings.vmvm_tb_v2_sha256,
        bindings.vacli_binary_sha256,
    )
    revisions = (
        bindings.base_runtime_commit,
        bindings.source_commit,
        bindings.source_git_tree,
        bindings.verifiers_commit,
        bindings.renderers_commit,
        bindings.pydantic_config_commit,
    )
    if any(SHA256_RE.fullmatch(value) is None for value in digests) or any(
        REVISION_RE.fullmatch(value) is None for value in revisions
    ):
        raise BindingError("execution_binding_invalid")
    if bindings.base_runtime_commit != APPROVED_BASE_RUNTIME_COMMIT or bindings.source_tree_sha256 != CLEAN_TREE_SHA256:
        raise BindingError("source_base_invalid")
    _validate_inspection_receipt(bindings, inspection_receipt_path)
    file_bindings = (
        (clean_wrapper, bindings.clean_wrapper_sha256, False),
        (canonical_launcher, bindings.launcher_sha256, False),
        (uv_path, bindings.uv_sha256, True),
        (python_path, bindings.python_sha256, True),
        (vacli_path, bindings.vacli_binary_sha256, True),
    )
    for path, expected_sha256, executable in file_bindings:
        if stable_file_digest(path, "execution_tool_invalid", executable=executable)[2] != expected_sha256:
            raise BindingError("execution_tool_sha256_mismatch")
    if os.environ.get("VACLI_BIN") != str(vacli_path):
        raise BindingError("execution_environment_not_sanitized")
    if canonical_tree_manifest_sha256(site_packages) != bindings.site_packages_manifest_sha256:
        raise BindingError("site_packages_manifest_mismatch")
    vmvm_source = project / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    if python_sources_sha256(vmvm_source) != bindings.vmvm_tb_v2_sha256:
        raise BindingError("vmvm_runtime_source_mismatch")
    if git_output(project, "rev-parse", "--verify", "HEAD") != bindings.source_commit:
        raise BindingError("source_checkout_mismatch")
    if git_output(project, "rev-parse", "--verify", "HEAD^{tree}") != bindings.source_git_tree:
        raise BindingError("source_checkout_mismatch")
    if git_output(project, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"):
        raise BindingError("source_checkout_not_clean")
    if (
        git_output(project, "merge-base", bindings.base_runtime_commit, bindings.source_commit)
        != bindings.base_runtime_commit
    ):
        raise BindingError("source_base_invalid")
    dependencies = {
        "deps/verifiers": bindings.verifiers_commit,
        "deps/renderers": bindings.renderers_commit,
        "deps/pydantic-config": bindings.pydantic_config_commit,
    }
    for relative, expected_commit in dependencies.items():
        dependency = project / relative
        if not (dependency / ".git").is_file():
            raise BindingError("source_dependency_invalid")
        tree_record = git_output(project, "ls-tree", "HEAD", relative).split()
        if len(tree_record) != 4 or tree_record[:2] != ["160000", "commit"] or tree_record[2] != expected_commit:
            raise BindingError("source_dependency_invalid")
        if git_output(dependency, "rev-parse", "--verify", "HEAD") != expected_commit:
            raise BindingError("source_dependency_invalid")
        if git_output(dependency, "status", "--porcelain=v1", "--untracked-files=all"):
            raise BindingError("source_dependency_invalid")
    return expected_import_roots(project, site_packages)


def bootstrap_attestation_sha256(bindings: ExecutionBindings, runtime_manifest_sha256: str) -> str:
    payload = {
        "schema_version": 2,
        "kind": "source-wheel-proof-bootstrap-attestation",
        "runtime_manifest_sha256": runtime_manifest_sha256,
        "source": {
            "base": bindings.base_runtime_commit,
            "commit": bindings.source_commit,
            "tree": bindings.source_git_tree,
            "verifiers": bindings.verifiers_commit,
            "renderers": bindings.renderers_commit,
            "pydantic_config": bindings.pydantic_config_commit,
            "vmvm": bindings.vmvm_tb_v2_sha256,
        },
        "execution": {
            "inspection_host": bindings.expected_host,
            "inspection_receipt": bindings.inspection_receipt_sha256,
            "clean_wrapper": bindings.clean_wrapper_sha256,
            "launcher": bindings.launcher_sha256,
            "uv": bindings.uv_sha256,
            "python": bindings.python_sha256,
            "site_packages": bindings.site_packages_manifest_sha256,
            "vacli": bindings.vacli_binary_sha256,
        },
    }
    return sha256_bytes(canonical_json(payload))


def _validate_runtime_closure(
    bindings: ExecutionBindings,
    import_roots: tuple[Path, ...],
    *,
    require_attestation: bool,
) -> str:
    expected_roots = tuple(str(path) for path in import_roots)
    if tuple(sys.path[: len(expected_roots)]) != expected_roots:
        raise BindingError("python_import_closure_invalid")
    runtime_manifest = python_runtime_manifest_sha256(
        bindings.python_path,
        bindings.python_stdlib_path,
        import_roots,
        _import_root_bindings(bindings, import_roots),
    )
    if runtime_manifest != bindings.python_runtime_manifest_sha256:
        raise BindingError("python_runtime_manifest_mismatch")
    attestation = bootstrap_attestation_sha256(bindings, runtime_manifest)
    if require_attestation and os.environ.get(BOOTSTRAP_ATTESTATION_ENV) != attestation:
        raise BindingError("python_bootstrap_attestation_mismatch")
    return attestation


def validate_execution_bindings(bindings: ExecutionBindings, *, require_attestation: bool) -> str:
    import_roots = tuple(validate_pre_import_bindings(bindings))
    return _validate_runtime_closure(
        bindings,
        import_roots,
        require_attestation=require_attestation,
    )


def _add_binding_arguments(parser: argparse.ArgumentParser) -> None:
    for name in (
        "project-dir",
        "inspection-receipt-path",
        "clean-wrapper-path",
        "canonical-launcher-path",
        "executed-launcher-path",
        "uv-path",
        "python-path",
        "python-stdlib-path",
        "site-packages-path",
        "vacli-path",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in (
        "inspection-receipt-sha256",
        "clean-wrapper-sha256",
        "launcher-sha256",
        "uv-sha256",
        "python-sha256",
        "python-runtime-manifest-sha256",
        "site-packages-manifest-sha256",
        "base-runtime-commit",
        "source-commit",
        "source-git-tree",
        "source-tree-sha256",
        "verifiers-commit",
        "renderers-commit",
        "pydantic-config-commit",
        "vmvm-tb-v2-sha256",
        "vacli-binary-sha256",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--expected-host", required=True)


def _bindings_from_args(args: argparse.Namespace) -> ExecutionBindings:
    return ExecutionBindings(**{field: getattr(args, field) for field in ExecutionBindings.__dataclass_fields__})


def _inspect(args: argparse.Namespace) -> dict[str, object]:
    _validate_bootstrap_flags()
    project = args.project_dir.resolve(strict=True)
    clean_wrapper = args.clean_wrapper.resolve(strict=True)
    launcher = args.launcher.resolve(strict=True)
    uv_path = args.uv.resolve(strict=True)
    python_path = args.python.resolve(strict=True)
    python_stdlib = args.python_stdlib.resolve(strict=True)
    site_packages = args.site_packages.resolve(strict=True)
    vacli_path = args.vacli.resolve(strict=True)
    vmvm_source = args.vmvm_source.resolve(strict=True)
    expected_wrapper = project / "user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof_clean_env.sbatch"
    expected_launcher = project / "user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof.sbatch"
    expected_vmvm_source = project / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    if (
        project != args.project_dir
        or clean_wrapper != args.clean_wrapper
        or clean_wrapper != expected_wrapper
        or launcher != args.launcher
        or launcher != expected_launcher
        or uv_path != args.uv
        or python_path != args.python
        or python_path != Path(sys.executable).resolve(strict=True)
        or python_stdlib != args.python_stdlib
        or python_stdlib != Path(sysconfig.get_path("stdlib")).resolve(strict=True)
        or site_packages != args.site_packages
        or vacli_path != args.vacli
        or vmvm_source != args.vmvm_source
        or vmvm_source != expected_vmvm_source
        or git_output(project, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
    ):
        raise BindingError("binding_inspection_invalid")
    source_git_tree = git_output(project, "rev-parse", "--verify", "HEAD^{tree}")
    dependency_commits = []
    for relative in ("deps/verifiers", "deps/renderers", "deps/pydantic-config"):
        dependency = project / relative
        tree_record = git_output(project, "ls-tree", "HEAD", relative).split()
        observed_commit = git_output(dependency, "rev-parse", "--verify", "HEAD")
        if (
            not (dependency / ".git").is_file()
            or len(tree_record) != 4
            or tree_record[:2] != ["160000", "commit"]
            or tree_record[2] != observed_commit
            or git_output(dependency, "status", "--porcelain=v1", "--untracked-files=all")
        ):
            raise BindingError("binding_inspection_invalid")
        dependency_commits.append(observed_commit)
    verifiers_commit, renderers_commit, pydantic_config_commit = dependency_commits
    site_manifest = canonical_tree_manifest_sha256(site_packages)
    vmvm_sha256 = python_sources_sha256(vmvm_source)
    roots = install_import_roots(project, site_packages)
    root_values = (
        f"source-git-tree:{source_git_tree}",
        f"source-git-tree:{source_git_tree};vmvm:{vmvm_sha256}",
        f"gitlink:{verifiers_commit}",
        f"gitlink:{renderers_commit}",
        f"gitlink:{pydantic_config_commit}",
    )
    root_bindings = tuple(
        (
            str(path),
            f"{value};effective-root-tree-sha256:{canonical_tree_manifest_sha256(path)}",
        )
        for path, value in zip(roots[:-1], root_values, strict=True)
    ) + ((str(roots[-1]), f"tree-sha256:{site_manifest}"),)
    return {
        "clean_wrapper_sha256": stable_file_digest(clean_wrapper, "binding_invalid")[2],
        "launcher_sha256": stable_file_digest(launcher, "binding_invalid")[2],
        "uv_sha256": stable_file_digest(uv_path, "binding_invalid", executable=True)[2],
        "python_sha256": stable_file_digest(python_path, "binding_invalid", executable=True)[2],
        "python_runtime_manifest_sha256": python_runtime_manifest_sha256(
            python_path,
            python_stdlib,
            roots,
            root_bindings,
        ),
        "site_packages_manifest_sha256": site_manifest,
        "vacli_binary_sha256": stable_file_digest(vacli_path, "binding_invalid", executable=True)[2],
        "vmvm_tb_v2_sha256": vmvm_sha256,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--project-dir", type=Path, required=True)
    inspect_parser.add_argument("--clean-wrapper", type=Path, required=True)
    inspect_parser.add_argument("--launcher", type=Path, required=True)
    inspect_parser.add_argument("--uv", type=Path, required=True)
    inspect_parser.add_argument("--python", type=Path, required=True)
    inspect_parser.add_argument("--python-stdlib", type=Path, required=True)
    inspect_parser.add_argument("--site-packages", type=Path, required=True)
    inspect_parser.add_argument("--vacli", type=Path, required=True)
    inspect_parser.add_argument("--vmvm-source", type=Path, required=True)
    run_parser = subparsers.add_parser("run")
    _add_binding_arguments(run_parser)
    run_parser.add_argument("--main-script", type=Path, required=True)
    run_parser.add_argument("main_args", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    try:
        args = _parse_args()
        if args.command == "inspect":
            result = _inspect(args)
            print(canonical_json(inspection_receipt(result, os.uname().nodename)).decode())
            return 0
        bindings = _bindings_from_args(args)
        _validate_stdlib_sys_path(bindings.python_stdlib_path, list(sys.path))
        roots = tuple(validate_pre_import_bindings(bindings))
        install_import_roots(bindings.project_dir, bindings.site_packages_path)
        attestation = _validate_runtime_closure(bindings, roots, require_attestation=False)
        os.environ[BOOTSTRAP_ATTESTATION_ENV] = attestation
        main_script = args.main_script.resolve(strict=True)
        expected_main = roots[0] / "prove_source_wheel_policy.py"
        if main_script != expected_main or args.main_script != main_script or not main_script.is_file():
            raise BindingError("proof_main_script_invalid")
        main_args = args.main_args
        if main_args[:1] == ["--"]:
            main_args = main_args[1:]
        sys.argv = [str(main_script), *main_args]
        try:
            runpy.run_path(str(main_script), run_name="__main__")
        except SystemExit as error:
            if error.code is None:
                return 0
            if isinstance(error.code, int):
                return error.code
            return 1
        return 0
    except BindingError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, sort_keys=True), flush=True)
        return 1
    except BaseException:
        print(
            json.dumps({"status": "failed", "error_code": "bootstrap_unexpected_failure"}, sort_keys=True), flush=True
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
