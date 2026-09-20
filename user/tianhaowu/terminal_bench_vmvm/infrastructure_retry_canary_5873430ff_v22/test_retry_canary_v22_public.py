#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent
GENERATOR_PATH = ROOT / "build_infrastructure_retry_selection_v22.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if path == GENERATOR_PATH and module.SELF != GENERATOR_PATH:
        module.ARTIFACT_ROOT = ROOT
        module.SELF = GENERATOR_PATH
        module.PACKAGING_SNAPSHOT = ROOT / "packaging-26.3-py3-none-any.whl.snapshot.json"
    return module


def source_fixture(tmp_path: Path, generator, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    workflow = source / "workflow"
    vmvm = source / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    workflow.mkdir(parents=True)
    vmvm.mkdir(parents=True)
    pinned = workflow / "pinned.py"
    pinned.write_text("PINNED = True\n")
    initializer = vmvm / "__init__.py"
    backend = vmvm / "backend.py"
    initializer.write_bytes(b"")
    backend.write_text("VALUE = 1\n")
    for path in (pinned, initializer, backend):
        path.chmod(0o644)
    revisions = {
        "deps/verifiers": "3" * 40,
        "deps/renderers": "4" * 40,
        "deps/pydantic-config": "5" * 40,
    }
    for relative in revisions:
        (source / relative).mkdir(parents=True)
    namespace = SimpleNamespace(
        SOURCE_ROOT=source,
        SOURCE_REVISION="1" * 40,
        SOURCE_TREE="2" * 40,
        VERIFIERS_REVISION=revisions["deps/verifiers"],
        RENDERERS_REVISION=revisions["deps/renderers"],
        PYDANTIC_CONFIG_REVISION=revisions["deps/pydantic-config"],
        PINNED_SOURCE_FILES={pinned: sha256(pinned.read_bytes()).hexdigest()},
        VMVM_SHA256="",
    )

    def git_output(repository: Path, *arguments: str) -> str:
        if arguments in {
            ("rev-parse", "--verify", "HEAD"),
            ("rev-parse", "HEAD"),
        }:
            if repository == source:
                return f"{namespace.SOURCE_REVISION}\n"
            for relative, revision in revisions.items():
                if repository == source / relative:
                    return f"{revision}\n"
        if arguments == ("rev-parse", "HEAD^{tree}") and repository == source:
            return f"{namespace.SOURCE_TREE}\n"
        if (
            len(arguments) == 2
            and arguments[0] == "rev-parse"
            and arguments[1].startswith("HEAD:")
        ):
            return f"{revisions[arguments[1].removeprefix('HEAD:')]}\n"
        if arguments[0] in {"status", "ls-files"}:
            return ""
        raise AssertionError((repository, arguments))

    monkeypatch.setattr(generator, "git_output", git_output)
    monkeypatch.setattr(
        generator.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    def refresh_digest() -> None:
        files = sorted(vmvm.glob("*.py"))
        records = b"".join(
            f"{sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(source).as_posix()}\n".encode()
            for path in files
        )
        namespace.VMVM_SHA256 = sha256(records).hexdigest()

    refresh_digest()
    return namespace, vmvm, initializer, backend, refresh_digest


def production_shape_fixture():
    valid_rows = [
        {"slug": f"public-valid-{index:04d}", "valid": True, "reason": "ok"}
        for index in range(2488)
    ]
    invalid_rows = []
    for index in range(50):
        row = {
            "slug": f"public-invalid-{index:02d}",
            "valid": False,
            "reason": "error",
            "error": "ordinary verifier rejection",
        }
        if 15 <= index < 26:
            row["error"] = "operation timed out"
        elif 26 <= index < 29:
            row["error"] = "connection refused"
        elif index == 29:
            row["error"] = "image pull failed"
        invalid_rows.append(row)
    source_rows = [*valid_rows, *invalid_rows]
    repair_rows = [
        {
            "slug": row["slug"],
            "valid": index < 6,
            "reason": "ok" if index < 6 else "invalid",
        }
        for index, row in enumerate(invalid_rows)
    ]
    repair_rows.extend(
        {"slug": row["slug"], "valid": True, "reason": "ok"} for row in valid_rows[:20]
    )
    wheel_tasks = [row["slug"] for row in invalid_rows[6:15]]
    return source_rows, repair_rows, wheel_tasks


def snapshot_module_fixture(
    tmp_path: Path,
    generator,
    monkeypatch: pytest.MonkeyPatch,
):
    workflow = tmp_path / "workflow"
    package = workflow / "terminal_bench_vmvm"
    package.mkdir(parents=True)
    initializer = package / "__init__.py"
    source_wheels = package / "source_wheels.py"
    exported = workflow / "export_oracle_tasks.py"
    builder = workflow / "build_oracle_repair_canary.py"
    audit = workflow / "audit_oracle_repair_canary.py"
    initializer.write_text("raise AssertionError('package initializer executed')\n")
    source_wheels.write_text("VALUE = 7\n")
    exported.write_text(
        "from terminal_bench_vmvm.source_wheels import VALUE\nEXPORTED = VALUE\n"
    )
    builder.write_text(
        "import export_oracle_tasks as exported\n"
        "DEFAULT_SEED = str(exported.EXPORTED)\n"
    )
    audit.write_text(
        "import build_oracle_repair_canary as builder\n"
        "import export_oracle_tasks as exported\n"
        "OBSERVED = (builder.DEFAULT_SEED, exported.EXPORTED)\n"
    )
    for path in (initializer, source_wheels, exported, builder, audit):
        path.chmod(0o644)
    v1 = SimpleNamespace(
        WORKFLOW=workflow,
        PINNED_SOURCE_FILES={
            exported: sha256(exported.read_bytes()).hexdigest(),
            builder: sha256(builder.read_bytes()).hexdigest(),
            audit: sha256(audit.read_bytes()).hexdigest(),
        },
    )
    monkeypatch.setattr(
        generator,
        "SOURCE_WHEELS_SHA256",
        sha256(source_wheels.read_bytes()).hexdigest(),
    )
    return v1, source_wheels, audit


def test_v22_selection_roles_and_six_recovery_floor_are_exact() -> None:
    generator = load(GENERATOR_PATH, "retry_v22_generator_test")
    v1 = generator.load_v1()
    source_rows, repair_rows, wheel_tasks = production_shape_fixture()
    selected, metadata = v1.select_rows(source_rows, repair_rows, wheel_tasks)
    roles = generator.derive_roles(v1, source_rows, selected)

    assert len(selected) == 19
    assert len(roles["candidates"]) == 15
    assert len(roles["controls"]) == 4
    assert set(roles["candidates"]).isdisjoint(roles["controls"])
    assert set(roles["candidates"]) | set(roles["controls"]) == set(selected)
    assert metadata["category_counts"] == {"image": 1, "network": 3, "timeout": 11}
    assert list(roles["candidate_primary_category"].values()).count("timeout") == 11


def test_attempt_policy_does_not_claim_timeout_retries() -> None:
    generator = load(GENERATOR_PATH, "retry_v22_policy_test")
    assert generator.ATTEMPT_POLICY == {
        "sandbox_error": {
            "retry_scope": "exception_type_only",
            "infra_retries": 4,
            "maximum_attempts": 5,
        },
        "asyncio_timeout_error": {
            "retry_scope": "none",
            "infra_retries": 0,
            "maximum_attempts": 1,
        },
        "timeout_category_candidates": {
            "count": 11,
            "classification_only": True,
            "category_does_not_enable_retries": True,
        },
        "timeout_bounds_seconds": {"setup": 7200, "validate": 21600, "session": 43200},
        "broad_harness_error_retry": False,
    }


def test_packaging_snapshot_binds_exact_wheel_and_semantic_contract() -> None:
    generator = load(GENERATOR_PATH, "retry_v22_packaging_snapshot_test")
    raw, sources = generator.load_packaging_snapshot()
    assert sha256(raw).hexdigest() == generator.PACKAGING_SNAPSHOT_SHA256
    assert set(sources) == {
        generator._packaging_module_name(member)
        for member in generator.PACKAGING_MODULE_MEMBERS
    }
    assert generator.packaging_provenance() == {
        "name": "packaging",
        "version": "26.3",
        "wheel_sha256": (
            "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c"
        ),
        "wheel_size": 129_956,
        "member_count": 29,
        "member_manifest_sha256": (
            "d02fb4c0b14244ef8a78ef2b91c29d988754c230c977089eb0c65eb5152e6ea4"
        ),
        "snapshot": {
            "path": str(generator.PACKAGING_SNAPSHOT),
            "sha256": generator.PACKAGING_SNAPSHOT_SHA256,
            "mode": "0400",
            "uid": 656177,
            "nlink": 1,
        },
        "loader": "restricted_in_memory_exact_wheel_sources_v1",
        "site_imports": False,
        "pyc_reads": False,
    }


def test_oracle_locks_accept_distinct_public_and_private_modes(tmp_path: Path) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_lock_test")
    public = tmp_path / "public"
    private = tmp_path / "private"
    public.mkdir(mode=0o755)
    private.mkdir(mode=0o700)
    public.chmod(0o755)
    private.chmod(0o700)
    (public / ".writer.lock").touch(mode=0o644)
    (private / ".writer.lock").touch(mode=0o600)
    (public / ".writer.lock").chmod(0o644)
    (private / ".writer.lock").chmod(0o600)

    with generator.locked_oracle(public, directory_mode=0o755, lock_mode=0o644):
        pass
    with generator.locked_oracle(private, directory_mode=0o700, lock_mode=0o600):
        pass
    with (
        pytest.raises(generator.SelectionV22Error, match="oracle_lock_invalid"),
        generator.locked_oracle(public, directory_mode=0o755, lock_mode=0o600),
    ):
        pass


def test_public_source_modes_are_explicitly_bound_without_mutation() -> None:
    generator = load(GENERATOR_PATH, "retry_v22_public_modes_test")
    assert generator.SOURCE_ORACLE.stat().st_mode & 0o777 == 0o755
    assert (generator.SOURCE_ORACLE / ".writer.lock").stat().st_mode & 0o777 == 0o644
    assert generator.REPAIR_ORACLE.stat().st_mode & 0o777 == 0o700
    assert (generator.REPAIR_ORACLE / ".writer.lock").stat().st_mode & 0o777 == 0o600


def test_execution_source_accepts_only_the_exact_empty_initializer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_empty_initializer_test")
    v1, _vmvm, _initializer, _backend, _refresh = source_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    generator.validate_execution_source(v1)


@pytest.mark.parametrize(
    "mutation",
    (
        "initializer_nonempty",
        "alternate_empty",
        "symlink",
        "hardlink",
        "wrong_mode",
        "aggregate",
    ),
)
def test_execution_source_rejects_invalid_vmvm_file_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    generator = load(GENERATOR_PATH, f"retry_v22_vmvm_{mutation}_test")
    v1, vmvm, initializer, backend, refresh = source_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    if mutation == "initializer_nonempty":
        initializer.write_text("VALUE = 1\n")
        refresh()
    elif mutation == "alternate_empty":
        (vmvm / "alternate.py").write_bytes(b"")
        refresh()
    elif mutation == "symlink":
        backend.unlink()
        backend.symlink_to(initializer)
        refresh()
    elif mutation == "hardlink":
        os.link(backend, vmvm / "backend.alias")
    elif mutation == "wrong_mode":
        backend.chmod(0o600)
    else:
        v1.VMVM_SHA256 = "0" * 64
    with pytest.raises(generator.SelectionV22Error):
        generator.validate_execution_source(v1)


def test_execution_source_rejects_ignored_untracked_version_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_untracked_test")
    v1, _vmvm, _initializer, _backend, _refresh = source_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    original = generator.git_output

    def untracked(repository: Path, *arguments: str) -> str:
        if arguments and arguments[0] == "ls-files":
            return "ignored/_version.py\n"
        return original(repository, *arguments)

    monkeypatch.setattr(generator, "git_output", untracked)
    with pytest.raises(generator.SelectionV22Error, match="source_identity_invalid"):
        generator.validate_execution_source(v1)


def test_imported_v1_failures_are_translated_without_payload() -> None:
    generator = load(GENERATOR_PATH, "retry_v22_translation_test")

    def fail_with_private_payload() -> None:
        raise RuntimeError("private payload")

    with pytest.raises(generator.SelectionV22Error, match="^stable_boundary_failure$"):
        generator.call_v1("stable_boundary_failure", fail_with_private_payload)
    v1 = SimpleNamespace(validate_source_wheel_cardinality=fail_with_private_payload)
    with pytest.raises(
        generator.SelectionV22Error,
        match="^source_wheel_cardinality_invalid$",
    ):
        generator.validate_source_wheel_cardinality(v1)


def test_snapshot_module_scope_is_dependency_free_repeatable_and_transactional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_snapshot_scope_test")
    v1, _source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    original_meta_path = list(sys.meta_path)
    original_importer_cache = dict(sys.path_importer_cache)
    for _ in range(2):
        with generator.snapshot_module_scope(v1) as (audit, builder):
            assert audit.OBSERVED == ("7", 7)
            assert builder.DEFAULT_SEED == "7"
            assert sys.path == original_path
        assert sys.path == original_path
        assert sys.modules == original_modules
        assert sys.meta_path == original_meta_path
        assert sys.path_importer_cache == original_importer_cache


@pytest.mark.parametrize(
    "name",
    (
        "audit_oracle_repair_canary",
        "build_oracle_repair_canary",
        "export_oracle_tasks",
        "terminal_bench_vmvm",
        "terminal_bench_vmvm.source_wheels",
        "terminal_bench_vmvm.unexpected",
        "packaging",
        "packaging.requirements",
    ),
)
def test_snapshot_module_scope_rejects_preexisting_collisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    generator = load(GENERATOR_PATH, f"retry_v22_collision_{name}_test")
    v1, _source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    sentinel = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, sentinel)
    original_path = list(sys.path)
    with (
        pytest.raises(generator.SelectionV22Error, match="^snapshot_module_collision$"),
        generator.snapshot_module_scope(v1),
    ):
        pass
    assert sys.modules[name] is sentinel
    assert sys.path == original_path


def test_snapshot_module_scope_rejects_mutation_and_restores_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_snapshot_mutation_test")
    v1, source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    original_path = list(sys.path)
    with (
        pytest.raises(generator.SelectionV22Error, match="^snapshot_source_changed$"),
        generator.snapshot_module_scope(v1),
    ):
        source_wheels.write_text("VALUE = 8\n")
    assert sys.path == original_path
    assert not any(generator._snapshot_module_collision(name) for name in sys.modules)


def test_packaging_snapshot_mutation_after_load_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_packaging_mutation_test")
    v1, _source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    stable_file = generator.stable_file
    snapshot_reads = 0

    def mutate_after_load(path, *args, **kwargs):
        nonlocal snapshot_reads
        raw = stable_file(path, *args, **kwargs)
        if path == generator.PACKAGING_SNAPSHOT:
            snapshot_reads += 1
            if snapshot_reads > 1:
                return raw + b"mutation"
        return raw

    monkeypatch.setattr(generator, "stable_file", mutate_after_load)
    with (
        pytest.raises(
            generator.SelectionV22Error,
            match="^packaging_snapshot_changed$",
        ),
        generator.snapshot_module_scope(v1),
    ):
        pass
    assert snapshot_reads == 2


def test_packaging_loader_rejects_unmanifested_submodule_with_staged_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_packaging_unmanifested_test")
    v1, source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    source_wheels.write_text("import packaging.not_manifested\nVALUE = 7\n")
    generator.SOURCE_WHEELS_SHA256 = sha256(source_wheels.read_bytes()).hexdigest()
    with (
        pytest.raises(
            generator.SelectionV22Error,
            match="^snapshot_source_wheels_import_invalid$",
        ),
        generator.snapshot_module_scope(v1),
    ):
        pass


@pytest.mark.parametrize(
    ("relative", "code"),
    (
        (
            "terminal_bench_vmvm/source_wheels.py",
            "snapshot_source_wheels_import_invalid",
        ),
        ("export_oracle_tasks.py", "snapshot_export_import_invalid"),
        ("build_oracle_repair_canary.py", "snapshot_builder_import_invalid"),
        ("audit_oracle_repair_canary.py", "snapshot_auditor_import_invalid"),
    ),
)
def test_snapshot_import_failures_have_staged_aggregate_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    code: str,
) -> None:
    generator = load(GENERATOR_PATH, f"retry_v22_stage_{relative}_test")
    v1, source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    target = v1.WORKFLOW / relative
    target.write_text("raise RuntimeError('private payload')\n")
    if target == source_wheels:
        generator.SOURCE_WHEELS_SHA256 = sha256(target.read_bytes()).hexdigest()
    else:
        v1.PINNED_SOURCE_FILES[target] = sha256(target.read_bytes()).hexdigest()
    with (
        pytest.raises(generator.SelectionV22Error, match=f"^{code}$"),
        generator.snapshot_module_scope(v1),
    ):
        pass


def test_packaging_module_origin_is_exact_and_transactional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_packaging_origin_test")
    v1, _source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    snapshot_raw, sources = generator.load_packaging_snapshot()
    origin, package_raw = sources["packaging"]
    sources["packaging"] = (origin, package_raw + b"\n__file__ = '/wrong'\n")
    monkeypatch.setattr(
        generator,
        "load_packaging_snapshot",
        lambda: (snapshot_raw, sources),
    )
    with (
        pytest.raises(
            generator.SelectionV22Error,
            match="^snapshot_packaging_origin_invalid$",
        ),
        generator.snapshot_module_scope(v1),
    ):
        pass


def test_packaging_import_failure_has_stable_stage_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_packaging_stage_test")
    v1, _source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    snapshot_raw, sources = generator.load_packaging_snapshot()
    origin, _raw = sources["packaging.markers"]
    sources["packaging.markers"] = (
        origin,
        b"raise RuntimeError('private payload')\n",
    )
    monkeypatch.setattr(
        generator,
        "load_packaging_snapshot",
        lambda: (snapshot_raw, sources),
    )
    with (
        pytest.raises(
            generator.SelectionV22Error,
            match="^snapshot_packaging_import_invalid$",
        ),
        generator.snapshot_module_scope(v1),
    ):
        pass


@pytest.mark.parametrize("mutation", ("wrong_mode", "hardlink", "hash"))
def test_snapshot_module_scope_binds_source_wheels_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    generator = load(GENERATOR_PATH, f"retry_v22_source_wheels_{mutation}_test")
    v1, source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    if mutation == "wrong_mode":
        source_wheels.chmod(0o600)
    elif mutation == "hardlink":
        os.link(source_wheels, tmp_path / "source_wheels.alias")
    else:
        source_wheels.write_text("VALUE = 8\n")
    with (
        pytest.raises(
            generator.SelectionV22Error,
            match="^snapshot_source_binding_invalid$",
        ),
        generator.snapshot_module_scope(v1),
    ):
        pass


def test_snapshot_module_scope_rejects_wrong_origin_and_restores_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_snapshot_origin_test")
    v1, _source_wheels, audit = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    audit.write_text("__file__ = '/wrong/origin.py'\n")
    v1.PINNED_SOURCE_FILES[audit] = sha256(audit.read_bytes()).hexdigest()
    original_path = list(sys.path)
    with (
        pytest.raises(
            generator.SelectionV22Error,
            match="^snapshot_module_origin_invalid$",
        ),
        generator.snapshot_module_scope(v1),
    ):
        pass
    assert sys.path == original_path
    assert not any(generator._snapshot_module_collision(name) for name in sys.modules)


def test_snapshot_module_scope_loads_twice_in_dependency_free_python() -> None:
    program = f"""
import importlib.util
import pathlib
import sys
spec = importlib.util.spec_from_file_location('retry_v22_isolated', {str(GENERATOR_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ARTIFACT_ROOT = pathlib.Path({str(ROOT)!r})
module.SELF = pathlib.Path({str(GENERATOR_PATH)!r})
module.PACKAGING_SNAPSHOT = module.ARTIFACT_ROOT / 'packaging-26.3-py3-none-any.whl.snapshot.json'
original_source_root = module.SOURCE_ROOT
module.SOURCE_ROOT = module.ARTIFACT_ROOT.parents[3]
module.WORKFLOW = module.SOURCE_ROOT / 'user/tianhaowu/terminal_bench_vmvm'
module.PINNED_SOURCE_FILES = {{
    module.SOURCE_ROOT / path.relative_to(original_source_root): digest
    for path, digest in module.PINNED_SOURCE_FILES.items()
}}
v1 = module.load_v1()
source_root = str(v1.SOURCE_ROOT)
snapshot_path = str(module.PACKAGING_SNAPSHOT)
opened = []
def audit_hook(event, args):
    if event == 'open' and args and isinstance(args[0], str):
        opened.append(args[0])
sys.addaudithook(audit_hook)
original_path = list(sys.path)
original_modules = dict(sys.modules)
original_meta_path = list(sys.meta_path)
original_importer_cache = dict(sys.path_importer_cache)
for _ in range(2):
    with module.snapshot_module_scope(v1) as (audit, builder):
        assert audit.__file__
        assert builder.__file__
        requirement = sys.modules['packaging.requirements'].Requirement(
            "example_pkg>=1; python_version >= '3.8'"
        )
        marker = sys.modules['packaging.markers'].Marker("python_version >= '3.8'")
        assert requirement.name == 'example_pkg'
        assert str(marker) == 'python_version >= "3.8"'
    assert sys.path == original_path
    assert sys.modules == original_modules
    assert sys.meta_path == original_meta_path
    assert sys.path_importer_cache == original_importer_cache
assert not [path for path in opened if path.startswith(source_root) and path.endswith('.pyc')]
assert not [path for path in opened if path.startswith(snapshot_path) and path.endswith('.pyc')]
"""
    result = subprocess.run(
        [
            str(load(GENERATOR_PATH, "retry_v22_python_path_test").PYTHON_REAL),
            "-I",
            "-S",
            "-B",
            "-c",
            program,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={
            "HOME": "/storage/home/tianhaowu",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_snapshot_module_scope_cannot_import_workflow_stdlib_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_snapshot_shadow_test")
    v1, source_wheels, _audit_path = snapshot_module_fixture(
        tmp_path,
        generator,
        monkeypatch,
    )
    shadow = v1.WORKFLOW / "colorsys.py"
    shadow.write_text("raise AssertionError('workflow shadow executed')\n")
    source_wheels.write_text("import colorsys\nVALUE = 7\n")
    generator.SOURCE_WHEELS_SHA256 = sha256(source_wheels.read_bytes()).hexdigest()
    monkeypatch.delitem(sys.modules, "colorsys", raising=False)
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    with generator.snapshot_module_scope(v1) as (audit, builder):
        assert audit.OBSERVED == ("7", 7)
        assert builder.DEFAULT_SEED == "7"
        package = sys.modules["terminal_bench_vmvm"]
        assert package.__path__ == []
        assert Path(sys.modules["colorsys"].__file__).resolve() != shadow
        assert sys.path == original_path
    assert sys.path == original_path
    assert sys.modules == original_modules


def test_validate_inputs_only_derives_everything_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = load(GENERATOR_PATH, "retry_v22_validate_only_test")
    selected = [f"opaque-{index:02d}" for index in range(19)]
    events: list[str] = []

    def receipt_body(_selected, _metadata, digest):
        events.append("receipt_body")
        return {
            "schema_version": 1,
            "artifact_type": "placeholder",
            "state": "prepared",
            "generator": {"path": str(generator.SELF), "sha256": digest},
            "selection": {},
            "final_union": {"projected_minimum_valid": 2500},
        }

    def receipt_envelope(body):
        events.append("receipt_envelope")
        assert body["module_import_closure"] == {
            "packaging": generator.packaging_provenance(),
        }
        return (
            generator.canonical_json(
                {
                    **body,
                    "selection_receipt_sha256": generator.sha256_bytes(
                        generator.canonical_json(body)
                    ),
                }
            )
            + b"\n"
        )

    v1 = SimpleNamespace(
        CANONICAL_SELF=None,
        OUTPUT_ROOT=None,
        TASK_FILE=None,
        RECEIPT=None,
        EXPECTED_CANDIDATES=15,
        CONTROL_COUNT=4,
        select_rows=lambda *_args: events.append("select") or (selected, {}),
        receipt_body=receipt_body,
        receipt_envelope=receipt_envelope,
        write_private_at=lambda *_args: pytest.fail("unexpected write"),
    )
    output = tmp_path / "selection"
    self_path = tmp_path / "generator.py"
    self_path.write_text("synthetic generator\n")
    self_path.chmod(0o500)
    digest = sha256(self_path.read_bytes()).hexdigest()
    monkeypatch.setattr(generator, "OUTPUT_ROOT", output)
    monkeypatch.setattr(generator, "TASK_FILE", output / "retry.tasks.txt")
    monkeypatch.setattr(generator, "ROLE_FILE", output / "selection_roles.private.json")
    monkeypatch.setattr(generator, "RECEIPT", output / "selection_receipt.json")
    monkeypatch.setattr(generator, "SELF", self_path)
    monkeypatch.setattr(generator, "validate_artifact_root_inventory", lambda: None)
    monkeypatch.setattr(generator, "load_v1", lambda: v1)
    monkeypatch.setattr(
        generator,
        "validate_execution_source",
        lambda _v1: events.append("source"),
    )

    @contextmanager
    def locked(*_args, **_kwargs):
        events.append("lock")
        yield

    monkeypatch.setattr(generator, "locked_oracle", locked)
    monkeypatch.setattr(
        generator,
        "validate_inputs",
        lambda _v1: events.append("inputs") or {},
    )
    monkeypatch.setattr(
        generator,
        "load_snapshots",
        lambda *_args: (
            events.append("snapshots")
            or (
                SimpleNamespace(results=[]),
                SimpleNamespace(results=[]),
                [],
            )
        ),
    )
    monkeypatch.setattr(
        generator,
        "derive_roles",
        lambda *_args: (
            events.append("roles")
            or {
                "schema_version": 1,
                "kind": "terminal_bench_vmvm_infrastructure_retry_roles",
                "candidates": selected[:15],
                "candidate_categories": {slug: ["timeout"] for slug in selected[:15]},
                "candidate_primary_category": {
                    slug: "timeout" for slug in selected[:15]
                },
                "controls": selected[15:],
            }
        ),
    )
    monkeypatch.setattr(
        generator,
        "validate_source_wheel_cardinality",
        lambda _v1: events.append("cardinality"),
    )

    result = generator.prepare(
        digest,
        verify_only=False,
        validate_inputs_only=True,
    )

    assert result["state"] == "validated_inputs"
    assert result["selected"] == 19
    assert result["retry_candidates"] == 15
    assert result["controls"] == 4
    assert not output.exists()
    assert events == [
        "source",
        "lock",
        "lock",
        "inputs",
        "snapshots",
        "select",
        "roles",
        "receipt_body",
        "receipt_envelope",
        "source",
        "cardinality",
    ]


@pytest.mark.skipif(
    os.environ.get("RUN_V22_REAL_INPUT_REGRESSION") != "1",
    reason="requires separate review and the canonical one-shot tmux pane",
)
def test_exact_real_validate_inputs_entrypoint_is_dependency_free_and_no_write() -> None:
    generator = load(GENERATOR_PATH, "retry_v22_real_entrypoint_test")
    tmux = os.environ.get("TMUX")
    pane = os.environ.get("TMUX_PANE")
    assert tmux and pane
    runtime_paths = (
        generator.OUTPUT_ROOT,
        Path(str(generator.OUTPUT_ROOT).replace("selection_", "run_")),
        Path(str(generator.OUTPUT_ROOT).replace("selection_", "run_") + ".launch-reservation"),
        generator.BASE / "logs/mobius_infrastructure_retry_run_5873430ff_v22",
        generator.BASE / "oracle/mobius_infrastructure_retry_audit_5873430ff_v22",
    )
    assert all(not os.path.lexists(path) for path in runtime_paths)
    digest = sha256(GENERATOR_PATH.read_bytes()).hexdigest()
    result = subprocess.run(
        [
            str(generator.PYTHON_REAL),
            "-I",
            "-S",
            "-B",
            str(GENERATOR_PATH),
            "--validate-inputs-only",
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={
            "APPROVED_RETRY_GENERATOR_SHA256": digest,
            "HOME": "/storage/home/tianhaowu",
            "LANG": "C",
            "LC_ALL": "C",
            "LOGNAME": "tianhaowu",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMUX": tmux,
            "TMUX_PANE": pane,
            "USER": "tianhaowu",
        },
        cwd="/storage/home/tianhaowu",
        timeout=120,
    )
    assert result.returncode == 0 and result.stderr == b""
    output = json.loads(result.stdout)
    assert output == {
        "state": "validated_inputs",
        "selected": 19,
        "retry_candidates": 15,
        "controls": 4,
        "task_file_sha256": output["task_file_sha256"],
        "role_file_sha256": output["role_file_sha256"],
        "selection_receipt_file_sha256": output[
            "selection_receipt_file_sha256"
        ],
        "selection_receipt_sha256": output["selection_receipt_sha256"],
        "projected_minimum_valid": 2500,
    }
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", output[field])
        for field in (
            "task_file_sha256",
            "role_file_sha256",
            "selection_receipt_file_sha256",
            "selection_receipt_sha256",
        )
    )
    assert all(not os.path.lexists(path) for path in runtime_paths)


def test_all_three_source_validation_callsites_use_v22_validator() -> None:
    generator_source = GENERATOR_PATH.read_text()
    launcher_source = (ROOT / "launch_infrastructure_retry_canary_v22.py").read_text()
    assert (
        len(
            re.findall(
                r"^\s+validate_execution_source\(v1\)$", generator_source, re.MULTILINE
            )
        )
        == 2
    )
    assert (
        len(
            re.findall(
                r"^\s+generator\.validate_execution_source\(v1\)$",
                launcher_source,
                re.MULTILINE,
            )
        )
        == 1
    )
    assert ".load_v1().validate_execution_source()" not in launcher_source
