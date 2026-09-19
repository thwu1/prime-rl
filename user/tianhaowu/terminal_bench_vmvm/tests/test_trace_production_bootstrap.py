from __future__ import annotations

import hashlib
import importlib
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import trace_production_bootstrap as bootstrap


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("mutation", ("mode", "symlink", "hardlink", "hash"))
def test_stable_bytes_rejects_identity_and_content_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n")
    source.chmod(0o600)
    expected = _digest(source)
    candidate = source
    if mutation == "mode":
        source.chmod(0o644)
    elif mutation == "symlink":
        candidate = tmp_path / "alias.py"
        candidate.symlink_to(source)
    elif mutation == "hardlink":
        os.link(source, tmp_path / "second.py")
    else:
        source.write_text("VALUE = 2\n")

    with pytest.raises(bootstrap.BootstrapError, match="^stable_invalid$"):
        bootstrap.stable_bytes(
            candidate,
            code="stable_invalid",
            maximum=1024,
            expected_sha256=expected,
            expected_mode=0o600,
            expected_uid=os.getuid(),
        )


def test_tree_manifest_rejects_customization_module(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir(mode=0o755)
    customization = root / "sitecustomize.py"
    customization.write_text("raise RuntimeError\n")
    customization.chmod(0o644)
    with pytest.raises(
        bootstrap.BootstrapError,
        match="^runtime_customization_forbidden$",
    ):
        bootstrap.tree_manifest_sha256(
            root,
            code="site_invalid",
            expected_uid=os.getuid(),
            forbid_customization=True,
        )


def test_site_manifest_rejects_precompiled_bytecode(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir(mode=0o755)
    cache = root / "module.pyc"
    cache.write_bytes(b"synthetic bytecode")
    cache.chmod(0o644)
    with pytest.raises(
        bootstrap.BootstrapError,
        match="^runtime_bytecode_forbidden$",
    ):
        bootstrap.tree_manifest_sha256(
            root,
            code="site_invalid",
            expected_uid=os.getuid(),
            forbid_customization=True,
        )


def test_site_manifest_rejects_symlinks_unless_explicitly_trusted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "site"
    root.mkdir(mode=0o755)
    target = root / "module.py"
    target.write_text("VALUE = 1\n")
    target.chmod(0o644)
    (root / "alias.py").symlink_to(target.name)

    with pytest.raises(bootstrap.BootstrapError, match="^site_invalid$"):
        bootstrap.tree_manifest_sha256(
            root,
            code="site_invalid",
            expected_uid=os.getuid(),
            forbid_customization=True,
        )

    digest = bootstrap.tree_manifest_sha256(
        root,
        code="stdlib_invalid",
        expected_uid=os.getuid(),
        forbid_customization=False,
        allow_symlinks=True,
    )
    assert len(digest) == 64


def test_source_manifest_rejects_tracked_bytecode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "cache.pyc"
    cache.write_bytes(b"not bytecode")
    cache.chmod(0o644)
    blob = bootstrap._git_blob_sha1(cache.read_bytes())
    tree = f"100644 blob {blob}\tcache.pyc\0".encode()
    monkeypatch.setattr(bootstrap, "_git", lambda *_args: tree)
    with pytest.raises(
        bootstrap.BootstrapError,
        match="^source_import_artifact_forbidden$",
    ):
        bootstrap._validate_importable_git_tree(tmp_path, "1" * 40)


def test_ignored_importable_scan_covers_source_cache_and_customization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_git",
        lambda *_args: (
            b"ignored/module.py\0ignored/__pycache__/module.pyc\0"
            b"ignored/native.so\0ignored/sitecustomize.py\0ignored/data.txt\0"
        ),
    )
    assert bootstrap._ignored_importables(tmp_path) == (
        "ignored/__pycache__/module.pyc",
        "ignored/module.py",
        "ignored/native.so",
        "ignored/sitecustomize.py",
    )


def test_verified_source_loader_executes_captured_hash_and_rejects_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "verified.py"
    source.write_text("VALUE = 7\n")
    source.chmod(0o644)
    loader = bootstrap._VerifiedSourceLoader(source, _digest(source))
    module = ModuleType("verified")
    module.__file__ = str(source)
    loader.exec_module(module)
    assert module.VALUE == 7

    source.write_text("VALUE = 8\n")
    with pytest.raises(bootstrap.BootstrapError, match="^verified_import_changed$"):
        loader.exec_module(ModuleType("changed"))


def test_verified_finder_rejects_unmanifested_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shadow = tmp_path / "shadowed.py"
    shadow.write_text("VALUE = 1\n")
    shadow.chmod(0o644)
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    finder = bootstrap._VerifiedImportFinder((tmp_path,), {})
    try:
        with pytest.raises(
            bootstrap.BootstrapError,
            match="^unmanifested_import_forbidden$",
        ):
            finder.find_spec("shadowed")
    finally:
        finder.close()


def test_verified_finder_rejects_final_symlink_without_executing_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = tmp_path / "protected"
    protected.mkdir()
    marker = tmp_path / "executed"
    outside = tmp_path / "outside.py"
    outside.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    module_name = "trace_v8_final_symlink"
    (protected / f"{module_name}.py").symlink_to(outside)
    finder = bootstrap._VerifiedImportFinder((protected,), {})
    monkeypatch.setattr(sys, "path", [str(protected), *sys.path])
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    try:
        with pytest.raises(
            bootstrap.BootstrapError,
            match="^verified_import_origin_invalid$",
        ):
            importlib.import_module(module_name)
        assert not marker.exists()
    finally:
        sys.modules.pop(module_name, None)
        finder.close()


def test_verified_finder_rejects_replaced_root_without_executing_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = tmp_path / "protected"
    protected.mkdir()
    marker = tmp_path / "executed"
    module_name = "trace_v8_replaced_root"
    source = protected / f"{module_name}.py"
    body = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    source.write_text(body)
    finder = bootstrap._VerifiedImportFinder((protected,), {source: _digest(source)})
    monkeypatch.setattr(sys, "path", [str(protected), *sys.path])
    try:
        spec = finder.find_spec(module_name)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        protected.rename(tmp_path / "displaced")
        protected.mkdir()
        (protected / source.name).write_text(body)
        with pytest.raises(
            bootstrap.BootstrapError,
            match="^verified_import_origin_invalid$",
        ):
            spec.loader.exec_module(module)
        assert not marker.exists()
    finally:
        finder.close()


def test_verified_finder_rejects_escaped_namespace_without_executing_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = tmp_path / "protected"
    protected.mkdir()
    module_name = "trace_v8_namespace"
    outside_namespace = tmp_path / "outside" / module_name
    outside_namespace.mkdir(parents=True)
    marker = tmp_path / "executed"
    (outside_namespace / "payload.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    (protected / module_name).symlink_to(outside_namespace, target_is_directory=True)
    finder = bootstrap._VerifiedImportFinder((protected,), {})
    monkeypatch.setattr(sys, "path", [str(protected), *sys.path])
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    try:
        with pytest.raises(
            bootstrap.BootstrapError,
            match="^verified_import_origin_invalid$",
        ):
            importlib.import_module(f"{module_name}.payload")
        assert not marker.exists()
    finally:
        sys.modules.pop(f"{module_name}.payload", None)
        sys.modules.pop(module_name, None)
        finder.close()


def test_native_extension_capture_is_sealed_before_delegate_execution(
    tmp_path: Path,
) -> None:
    original = tmp_path / "native.so"
    original.write_bytes(b"trusted-native-bytes")
    original.chmod(0o644)
    body = original.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    descriptor = bootstrap._sealed_memfd(body, "native-test")
    sealed_path = f"/proc/self/fd/{descriptor}"
    observed: list[bytes] = []

    class Delegate:
        def create_module(self, spec: object) -> ModuleType:
            observed.append(Path(spec.origin).read_bytes())  # type: ignore[attr-defined]
            return ModuleType("native")

        def exec_module(self, _module: object) -> None:
            observed.append(Path(sealed_path).read_bytes())

    loader = bootstrap._VerifiedExtensionLoader(
        "native",
        original,
        digest,
        descriptor,
        Delegate(),  # type: ignore[arg-type]
    )
    spec = SimpleNamespace(origin=sealed_path)
    try:
        original.write_bytes(b"attacker-replacement")
        module = loader.create_module(spec)
        loader.exec_module(module)
        assert observed == [body, body]
        with pytest.raises(PermissionError):
            os.pwrite(descriptor, b"x", 0)
    finally:
        os.close(descriptor)


def test_runtime_tool_contract_is_exact_and_root_owned() -> None:
    assert bootstrap.RUNTIME_TOOL_PATHS == {
        "bash": "/usr/bin/bash",
        "chmod": "/usr/bin/chmod",
        "env": "/usr/bin/env",
        "git": "/usr/bin/git",
        "id": "/usr/bin/id",
        "mktemp": "/usr/bin/mktemp",
        "realpath": "/usr/bin/realpath",
        "rmdir": "/usr/bin/rmdir",
        "sacct": "/usr/bin/sacct",
        "sbatch": "/usr/bin/sbatch",
        "scancel": "/usr/bin/scancel",
        "scontrol": "/usr/bin/scontrol",
        "sha256sum": "/usr/bin/sha256sum",
        "sleep": "/usr/bin/sleep",
        "squeue": "/usr/bin/squeue",
        "stat": "/usr/bin/stat",
    }
    for path in bootstrap.RUNTIME_TOOL_PATHS.values():
        metadata = Path(path).stat(follow_symlinks=False)
        assert stat.S_ISREG(metadata.st_mode)
        assert stat.S_IMODE(metadata.st_mode) == 0o755
        assert metadata.st_uid == 0 and metadata.st_nlink == 1


def test_wrapper_bootstrap_contract_forbids_ambient_import_paths() -> None:
    wrapper = (
        Path(bootstrap.__file__)
        .with_name("run_trace_production_audit.sbatch")
        .read_text()
    )
    submitter = (
        Path(bootstrap.__file__)
        .with_name("submit_trace_production_audit.sh")
        .read_text()
    )
    submission_controller = (
        Path(bootstrap.__file__)
        .with_name("trace_production_submit_control.py")
        .read_text()
    )
    assert '"--export=NONE"' in submission_controller
    assert '"-",' in submission_controller
    assert "TRACE_SUBMITTER_SEALED_FD" in submitter
    assert '"$python_path" -I -S -B -c "$loader"' in wrapper
    assert 'PYTHONPYCACHEPREFIX="$pycache_prefix"' in wrapper
    assert "if (( $# != 20 ))" in wrapper
    assert '"$reservation_device" "$reservation_inode"' in wrapper
    assert '"$reservation_parent_device" "$reservation_parent_inode"' in wrapper
    assert "PYTHONPATH=" not in wrapper
    assert "PYTHONHOME" in wrapper and "sitecustomize.py" in wrapper
    assert "BASH_ENV" in wrapper and "BASH_FUNC_" in wrapper
    for script in (wrapper, submitter):
        assert "GIT_NO_REPLACE_OBJECTS=1" in script
        assert "GIT_ATTR_NOSYSTEM=1" in script
        assert "GIT_CONFIG_GLOBAL=/dev/null" in script
        assert "GIT_CONFIG_NOSYSTEM=1" in script
    assert "digest_file /proc/self/fd/8" in wrapper
    assert "digest_file /proc/self/fd/9" in wrapper


def test_exact_isolated_bootstrap_environment_is_accepted(tmp_path: Path) -> None:
    prefix = tmp_path / "sealed-cache"
    prefix.mkdir(mode=0o500)
    prefix.chmod(0o500)
    source = Path(bootstrap.__file__)
    program = (
        "import pathlib;"
        f"p=pathlib.Path({str(source)!r});"
        "g={'__builtins__':__builtins__,'__file__':str(p),'__name__':'bootstrap_probe'};"
        "exec(compile(p.read_bytes(),str(p),'exec'),g);"
        f"g['_validate_environment'](pathlib.Path({str(prefix)!r}));"
        f"g['_validate_pycache_prefix'](pathlib.Path({str(prefix)!r}))"
    )
    result = subprocess.run(
        ["/usr/bin/python3.12", "-I", "-S", "-B", "-c", program],
        check=False,
        capture_output=True,
        env={
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPYCACHEPREFIX": str(prefix),
            "PYTHONSAFEPATH": "1",
            "THRIFT_TLS_CL_CERT_PATH": "/synthetic/client.crt",
            "THRIFT_TLS_CL_KEY_PATH": "/synthetic/client.key",
        },
        timeout=20,
    )
    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
    assert list(prefix.iterdir()) == []


def test_submitter_rejects_before_scheduler_with_empty_arguments() -> None:
    submitter = Path(bootstrap.__file__).with_name("submit_trace_production_audit.sh")
    result = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc", str(submitter)],
        check=False,
        capture_output=True,
        env={
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        },
        timeout=20,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b'{"code":"arguments_invalid","status":"error"}\n'


def _phase(*, state: str, timeout: int) -> dict[str, object]:
    return {
        "converged": True,
        "elapsed_milliseconds": 2_000,
        "explicit_conflict_fields": [],
        "final_mismatch_fields": [],
        "mismatch_fields": [],
        "mismatch_occurrences": {},
        "polls": 2,
        "required_consecutive": 2,
        "state": state,
        "timeout_seconds": timeout,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeout_seconds", 780),
        ("required_consecutive", 1),
        ("explicit_conflict_fields", ["JobName"]),
        ("final_mismatch_fields", ["held_state"]),
        ("state", "RUNNING"),
    ],
)
def test_phase_certificate_rejects_resealed_semantic_mutation(
    field: str,
    value: object,
) -> None:
    phase = _phase(state="PENDING", timeout=bootstrap.HELD_TIMEOUT_SECONDS)
    phase[field] = value
    with pytest.raises(
        bootstrap.BootstrapError, match="^submission_admission_invalid$"
    ):
        bootstrap._validate_phase_certificate(
            phase,
            timeout_seconds=bootstrap.HELD_TIMEOUT_SECONDS,
            allowed_states=frozenset({"PENDING"}),
        )
