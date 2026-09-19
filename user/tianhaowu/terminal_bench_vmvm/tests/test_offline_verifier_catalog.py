from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from zipfile import ZipFile

import pytest
import terminal_bench_vmvm.offline_verifier_catalog as catalog_module
from terminal_bench_vmvm.offline_verifier_catalog import (
    CLOSURE_PROBE_CODE,
    RUNTIME_STAGING_ROOT,
    AggregateCatalogReceipt,
    CatalogIdentity,
    ExpectedTaskBinding,
    OfflineCatalogError,
    OfflineVerifierCatalog,
    RuntimeFingerprint,
    _verified_source_digest,
    binding_plan_sha256,
    catalog_consumer_code_sha256,
    closure_probe_argv,
    closure_sha256,
    offline_install_argv,
    offline_install_environment,
    ordered_requirements_sha256,
    validate_runtime_staging_paths,
)
from terminal_bench_vmvm.source_wheels import canonical_json, inspect_wheelhouse, pack_wheelhouse


def _digest(value: str | bytes) -> str:
    payload = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _allowlist_digest(kind: str, values: list[str]) -> str:
    return _digest(canonical_json({"schema_version": 1, "kind": kind, "values": values}))


def _wheel(distribution: str, version: str, *requirements: str) -> bytes:
    filename_distribution = distribution.replace("-", "_")
    output = io.BytesIO()
    with ZipFile(output, mode="w") as wheel:
        metadata_dir = f"{filename_distribution}-{version}.dist-info"
        metadata = ["Metadata-Version: 2.1", f"Name: {distribution}", f"Version: {version}"]
        metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
        wheel.writestr(f"{metadata_dir}/METADATA", "\n".join(metadata) + "\n")
        wheel.writestr(
            f"{metadata_dir}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: catalog-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return output.getvalue()


def _nondeterministic_archive(wheels: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for filename in sorted(wheels):
            payload = wheels[filename]
            member = tarfile.TarInfo(filename)
            member.size = len(payload)
            member.mode = 0o444
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.mtime = 1
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def _write_private(root: Path, relative: Path, payload: bytes) -> Path:
    path = root / relative
    current = root
    for part in relative.parts[:-1]:
        current /= part
        current.mkdir(exist_ok=True)
        current.chmod(0o700)
    path.write_bytes(payload)
    path.chmod(0o400)
    return path


def _fingerprint(marker_environment: dict[str, str], supported_tags: list[str]) -> RuntimeFingerprint:
    return RuntimeFingerprint(
        implementation="cpython",
        python_full_version="3.12.8",
        abi="cpython-312-x86_64-linux-gnu",
        platform="linux-x86_64",
        machine="x86_64",
        libc="glibc-2.36",
        pip_version="24.3.1",
        marker_environment_sha256=_digest(canonical_json(marker_environment)),
        supported_tags_sha256=_digest(canonical_json(supported_tags)),
    )


def _closure_record(distributions: list[list[str]]) -> dict[str, object]:
    return {"distributions": distributions, "sha256": closure_sha256(distributions)}


def _artifact_path(kind: str, digest: str, suffix: str) -> Path:
    return Path(kind) / "sha256" / digest[:2] / f"{digest}{suffix}"


def _fixture(
    tmp_path: Path,
    *,
    source_origin: bool = False,
    deterministic_archive: bool = True,
    approve_binary: bool = True,
    empty_inventory_requirements: bool = False,
    nonempty_empty_inventory_closure: bool = False,
) -> tuple[
    Path,
    CatalogIdentity,
    Path,
    Path,
    tuple[ExpectedTaskBinding, ...],
    RuntimeFingerprint,
]:
    project = tmp_path / "project"
    dataset = tmp_path / "dataset"
    root = tmp_path / "private-catalog"
    project.mkdir()
    dataset.mkdir()
    root.mkdir(mode=0o700)
    root.chmod(0o700)

    marker_environment = {"python_version": "3.12", "sys_platform": "linux"}
    supported_tags = ["py3-none-any"]
    fingerprint = _fingerprint(marker_environment, supported_tags)

    source_attestation = _digest("approved-source-attestation")
    approved_sources: list[str] = []
    wheel_requirements = ("root-pkg==1.0.0",)
    inventory_requirements = () if empty_inventory_requirements else ("installed-pkg==3.0.0",)
    inventory_image = f"registry.invalid/image-a@sha256:{'a' * 64}"
    wheel_image = f"registry.invalid/image-b@sha256:{'b' * 64}"
    tasks = (
        ExpectedTaskBinding("synthetic-image-task", "shared-agent", inventory_image, inventory_requirements),
        ExpectedTaskBinding("synthetic-wheel-task", "separate-verifier", wheel_image, wheel_requirements),
    )
    wheels = {
        "helper_pkg-2.0.0-py3-none-any.whl": _wheel("helper-pkg", "2.0.0"),
        "root_pkg-1.0.0-py3-none-any.whl": _wheel("root-pkg", "1.0.0", "helper-pkg==2.0.0"),
    }
    archive = pack_wheelhouse(wheels) if deterministic_archive else _nondeterministic_archive(wheels)
    evidence = inspect_wheelhouse(archive)
    binary_policies = {
        item.filename: {
            "schema_version": 1,
            "distribution": item.distribution,
            "version": item.version,
            "filename": item.filename,
            "size": item.size,
            "sha256": item.sha256,
            "source_url_sha256": _digest(f"source-url:{item.filename}"),
            "source_snapshot_sha256": _digest("index-snapshot"),
        }
        for item in evidence
        if not (source_origin and item.distribution == "root-pkg")
    }
    approved_binaries = (
        sorted(_digest(canonical_json(policy)) for policy in binary_policies.values()) if approve_binary else []
    )
    toolchain_record = {
        "schema_version": 1,
        "python_version": "3.12.8",
        "pip_version": "24.3.1",
        "resolver": "pip",
        "resolver_version": "24.3.1",
        "builder_code_sha256": _digest("builder-code"),
        "build_environment_sha256": _digest("builder-environment"),
    }
    toolchain_sha256 = _digest(canonical_json(toolchain_record))
    approved_toolchains = [toolchain_sha256]
    identity = CatalogIdentity(
        dataset_revision="1" * 40,
        task_selection_sha256=_digest("selection"),
        expected_task_count=len(tasks),
        binding_plan_sha256=binding_plan_sha256(tasks),
        catalog_consumer_code_sha256=catalog_consumer_code_sha256(),
        image_manifest_sha256=_digest("images"),
        requirements_extractor_sha256=_digest("extractor"),
        inventory_probe_code_sha256=_digest("inventory-probe"),
        inventory_probe_environment_sha256=_digest("inventory-environment"),
        inventory_probe_approval_sha256=_digest("inventory-approval"),
        source_policy_sha256=_digest("source-policy"),
        source_policy_approval_sha256=_digest("source-policy-approval"),
        approved_binary_artifacts_sha256=_allowlist_digest("binary-artifacts", approved_binaries),
        approved_source_attestations_sha256=_allowlist_digest("source-attestations", approved_sources),
        approved_toolchains_sha256=_allowlist_digest("toolchains", approved_toolchains),
    )
    wheel_requirements_sha256 = ordered_requirements_sha256(wheel_requirements)
    archive_sha256 = _digest(archive)
    _write_private(root, _artifact_path("archives", archive_sha256, ".tar"), archive)
    closure = sorted([[item.distribution, item.version] for item in evidence])
    wheel_records = []
    for item in evidence:
        origin = "source-build" if source_origin and item.distribution == "root-pkg" else "binary"
        binary_policy = binary_policies.get(item.filename)
        wheel_records.append(
            {
                "distribution": item.distribution,
                "version": item.version,
                "filename": item.filename,
                "size": item.size,
                "sha256": item.sha256,
                "universal": item.universal,
                "origin": origin,
                "binary_artifact_policy": binary_policy,
                "binary_artifact_policy_sha256": (
                    _digest(canonical_json(binary_policy)) if binary_policy is not None else None
                ),
                "source_attestation_sha256": source_attestation if origin == "source-build" else None,
            }
        )
    wheelhouse_manifest = {
        "schema_version": 1,
        "requirements": list(wheel_requirements),
        "requirements_sha256": wheel_requirements_sha256,
        "archive": {"sha256": archive_sha256, "size": len(archive)},
        "closure": _closure_record(closure),
        "compatibility": {
            "scope": "universal",
            "image": None,
            "runtime_fingerprint": fingerprint.record(),
            "runtime_fingerprint_sha256": fingerprint.sha256,
            "marker_environment": marker_environment,
            "supported_tags": supported_tags,
        },
        "toolchain": {"record": toolchain_record, "sha256": toolchain_sha256},
        "source_policy": {
            "policy_sha256": identity.source_policy_sha256,
            "approval_sha256": identity.source_policy_approval_sha256,
        },
        "wheels": wheel_records,
    }
    wheelhouse_payload = canonical_json(wheelhouse_manifest)
    wheelhouse_manifest_sha256 = _digest(wheelhouse_payload)
    _write_private(
        root,
        _artifact_path("manifests", wheelhouse_manifest_sha256, ".json"),
        wheelhouse_payload,
    )

    inventory_requirements_sha256 = ordered_requirements_sha256(inventory_requirements)
    inventory = [["ambient-pkg", "9.0.0"]]
    if inventory_requirements:
        inventory.append(["installed-pkg", "3.0.0"])
    inventory_closure = (
        [["ambient-pkg", "9.0.0"]]
        if nonempty_empty_inventory_closure
        else ([["installed-pkg", "3.0.0"]] if inventory_requirements else [])
    )
    inventory_manifest = {
        "schema_version": 1,
        "image": inventory_image,
        "requirements": list(inventory_requirements),
        "requirements_sha256": inventory_requirements_sha256,
        "runtime_fingerprint": fingerprint.record(),
        "runtime_fingerprint_sha256": fingerprint.sha256,
        "installed_inventory": inventory,
        "installed_inventory_sha256": closure_sha256(inventory),
        "closure": _closure_record(inventory_closure),
        "probe": {
            "code_sha256": identity.inventory_probe_code_sha256,
            "environment_sha256": identity.inventory_probe_environment_sha256,
            "approval_sha256": identity.inventory_probe_approval_sha256,
        },
    }
    inventory_payload = canonical_json(inventory_manifest)
    inventory_manifest_sha256 = _digest(inventory_payload)
    _write_private(
        root,
        _artifact_path("inventories", inventory_manifest_sha256, ".json"),
        inventory_payload,
    )

    wheel_coverage_core = {
        "requirements_sha256": wheel_requirements_sha256,
        "runtime_fingerprint": fingerprint.record(),
        "runtime_fingerprint_sha256": fingerprint.sha256,
        "scope": "universal",
        "image": None,
        "mode": "wheelhouse",
        "artifact_sha256": wheelhouse_manifest_sha256,
    }
    wheel_coverage_sha256 = _digest(canonical_json(wheel_coverage_core))
    image_coverage_core = {
        "requirements_sha256": inventory_requirements_sha256,
        "runtime_fingerprint": fingerprint.record(),
        "runtime_fingerprint_sha256": fingerprint.sha256,
        "scope": "image",
        "image": inventory_image,
        "mode": "image-inventory",
        "artifact_sha256": inventory_manifest_sha256,
    }
    image_coverage_sha256 = _digest(canonical_json(image_coverage_core))
    coverages = [
        {"coverage_sha256": wheel_coverage_sha256, **wheel_coverage_core},
        {"coverage_sha256": image_coverage_sha256, **image_coverage_core},
    ]
    coverages.sort(key=lambda item: item["coverage_sha256"])

    binding_inputs = [
        (
            "synthetic-image-task",
            "shared-agent",
            inventory_image,
            inventory_requirements_sha256,
            image_coverage_sha256,
        ),
        (
            "synthetic-wheel-task",
            "separate-verifier",
            wheel_image,
            wheel_requirements_sha256,
            wheel_coverage_sha256,
        ),
    ]
    task_bindings = []
    for task_key, runtime_role, image, requirement_digest, coverage_digest in binding_inputs:
        core = {
            "task_key": task_key,
            "runtime_role": runtime_role,
            "image": image,
            "requirements_sha256": requirement_digest,
            "coverage_sha256": coverage_digest,
        }
        task_bindings.append({**core, "binding_sha256": _digest(canonical_json(core))})
    task_bindings.sort(key=lambda item: item["task_key"])
    requirement_sets = [
        {"requirements": list(wheel_requirements), "requirements_sha256": wheel_requirements_sha256},
        {"requirements": list(inventory_requirements), "requirements_sha256": inventory_requirements_sha256},
    ]
    requirement_sets.sort(key=lambda item: item["requirements_sha256"])
    catalog = {
        "schema_version": 1,
        "identity": identity.record(),
        "identity_sha256": identity.sha256,
        "policy": {
            "source_policy_sha256": identity.source_policy_sha256,
            "source_policy_approval_sha256": identity.source_policy_approval_sha256,
            "approved_binary_artifacts": approved_binaries,
            "approved_binary_artifacts_sha256": identity.approved_binary_artifacts_sha256,
            "approved_source_attestations": approved_sources,
            "approved_source_attestations_sha256": identity.approved_source_attestations_sha256,
            "approved_toolchains": approved_toolchains,
            "approved_toolchains_sha256": identity.approved_toolchains_sha256,
        },
        "requirement_sets": requirement_sets,
        "coverages": coverages,
        "task_bindings": task_bindings,
    }
    catalog_payload = canonical_json(catalog)
    catalog_path = _write_private(root, Path("catalog.json"), catalog_payload)
    return catalog_path, identity, project, dataset, tasks, fingerprint


def _load(
    catalog_path: Path,
    identity: CatalogIdentity,
    project: Path,
    dataset: Path,
) -> OfflineVerifierCatalog:
    return OfflineVerifierCatalog.load(
        catalog_path,
        _digest(catalog_path.read_bytes()),
        identity,
        project_root=project,
        dataset_root=dataset,
    )


def test_catalog_preflight_resolves_both_static_coverage_classes(tmp_path: Path) -> None:
    catalog_path, identity, project, dataset, tasks, fingerprint = _fixture(tmp_path)
    catalog = _load(catalog_path, identity, project, dataset)
    receipt = catalog.preflight(tasks, expected_task_count=2)

    assert receipt == AggregateCatalogReceipt(
        tasks=2,
        images=2,
        requirement_sets=2,
        coverage_records=2,
        image_inventory_tasks=1,
        wheelhouse_tasks=1,
        image_inventories=1,
        wheelhouses=1,
        wheels=2,
        source_built_wheels=0,
        shared_agent_tasks=1,
        separate_verifier_tasks=1,
    )
    public = receipt.to_public_dict()
    assert set(public) == {"contract_version", "status", "counts"}
    assert not any(_digest(label) in json.dumps(public) for label in ("selection", "images", "extractor"))
    assert "synthetic" not in json.dumps(public)
    assert "/" not in json.dumps(public)

    image_plan = catalog.resolve(
        tasks[0].task_key,
        tasks[0].runtime_role,
        tasks[0].image,
        tasks[0].requirements,
        fingerprint,
    )
    assert image_plan.guarantee == "image-inventory"
    image_control = json.loads(image_plan.probe_control_payload(None))
    assert image_control["inventory"] != image_control["closure"]

    wheel_plan = catalog.resolve(
        tasks[1].task_key,
        tasks[1].runtime_role,
        tasks[1].image,
        tasks[1].requirements,
        fingerprint,
    )
    assert wheel_plan.guarantee == "wheelhouse"
    assert wheel_plan.read_verified_archive()
    with pytest.raises(OfflineCatalogError, match="probe_path_invalid"):
        wheel_plan.probe_control_payload(None)
    request = wheel_plan.install_request_payload(f"{RUNTIME_STAGING_ROOT}/run/wheels")
    assert request.count(b".whl --hash=sha256:") == 2
    argv = offline_install_argv(
        f"{RUNTIME_STAGING_ROOT}/run/site",
        f"{RUNTIME_STAGING_ROOT}/run/install-request.txt",
    )
    assert "--no-index" in argv and "--no-deps" in argv and "--require-hashes" in argv
    assert not any("root-pkg" in argument or "helper-pkg" in argument for argument in argv)
    assert offline_install_environment()["PIP_NO_INDEX"] == "1"


def test_catalog_rejects_nonempty_inventory_closure_for_empty_requirements(tmp_path: Path) -> None:
    catalog_path, identity, project, dataset, tasks, _ = _fixture(
        tmp_path,
        empty_inventory_requirements=True,
        nonempty_empty_inventory_closure=True,
    )
    catalog = _load(catalog_path, identity, project, dataset)
    with pytest.raises(OfflineCatalogError, match="inventory_invalid"):
        catalog.preflight(tasks, expected_task_count=2)


def test_closure_probe_accepts_exact_overlay_and_emits_aggregate_only(tmp_path: Path) -> None:
    catalog_path, identity, project, dataset, tasks, fingerprint = _fixture(tmp_path)
    catalog = _load(catalog_path, identity, project, dataset)
    catalog.preflight(tasks, expected_task_count=2)
    plan = catalog.resolve(
        tasks[1].task_key,
        tasks[1].runtime_role,
        tasks[1].image,
        tasks[1].requirements,
        fingerprint,
    )
    runtime_root = Path(RUNTIME_STAGING_ROOT)
    runtime_root.mkdir(mode=0o700, exist_ok=True)
    runtime_root.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="catalog-test-", dir=runtime_root) as directory:
        run_root = Path(directory)
        site = run_root / "site"
        site.mkdir()
        for distribution, version, requirement in (
            ("root-pkg", "1.0.0", "Requires-Dist: helper-pkg==2.0.0\n"),
            ("helper-pkg", "2.0.0", ""),
        ):
            metadata = site / f"{distribution.replace('-', '_')}-{version}.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n{requirement}"
            )
        control = run_root / "control.json"
        control_payload = plan.probe_control_payload(str(site))
        control.write_bytes(control_payload)
        script = run_root / "probe.py"
        script.write_text(CLOSURE_PROBE_CODE)
        argv = closure_probe_argv(str(script), str(control), _digest(control_payload))
        completed = subprocess.run(
            [sys.executable, *argv[1:]],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {"count": 2, "status": "ok"}
        assert "root-pkg" not in completed.stdout
        control.write_bytes(control_payload + b" ")
        rejected = subprocess.run(
            [sys.executable, *argv[1:]],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert rejected.returncode == 1
        assert json.loads(rejected.stdout) == {"status": "failed"}


@pytest.mark.parametrize(
    "site,request_path",
    [
        ("/", f"{RUNTIME_STAGING_ROOT}/run/request"),
        ("/usr", f"{RUNTIME_STAGING_ROOT}/run/request"),
        (f"{RUNTIME_STAGING_ROOT}/run/../site", f"{RUNTIME_STAGING_ROOT}/run/request"),
        (f"{RUNTIME_STAGING_ROOT}//run/site", f"{RUNTIME_STAGING_ROOT}/run/request"),
        (f"{RUNTIME_STAGING_ROOT}/run/site\n", f"{RUNTIME_STAGING_ROOT}/run/request"),
        (f"{RUNTIME_STAGING_ROOT}/run", f"{RUNTIME_STAGING_ROOT}/run/request"),
        (f"{RUNTIME_STAGING_ROOT}/run/site", f"{RUNTIME_STAGING_ROOT}/run/site"),
    ],
)
def test_runtime_paths_are_confined_and_distinct(site: str, request_path: str) -> None:
    with pytest.raises(OfflineCatalogError, match="install_path_invalid"):
        offline_install_argv(site, request_path)


def test_probe_paths_are_confined_and_non_aliasing() -> None:
    digest = "1" * 64
    with pytest.raises(OfflineCatalogError, match="probe_path_invalid"):
        closure_probe_argv("/usr/probe.py", f"{RUNTIME_STAGING_ROOT}/run/control.json", digest)
    with pytest.raises(OfflineCatalogError, match="probe_path_invalid"):
        closure_probe_argv(
            f"{RUNTIME_STAGING_ROOT}/run",
            f"{RUNTIME_STAGING_ROOT}/run/control.json",
            digest,
        )
    with pytest.raises(OfflineCatalogError, match="probe_control_digest_invalid"):
        closure_probe_argv(
            f"{RUNTIME_STAGING_ROOT}/run/probe.py",
            f"{RUNTIME_STAGING_ROOT}/run/control.json",
            "not-a-digest",
        )


def test_complete_runtime_path_set_rejects_cross_phase_aliases() -> None:
    root = f"{RUNTIME_STAGING_ROOT}/run"
    with pytest.raises(OfflineCatalogError, match="runtime_paths_invalid"):
        validate_runtime_staging_paths(
            (
                f"{root}/archive.tar",
                f"{root}/wheels",
                f"{root}/site",
                f"{root}/site/request.txt",
                f"{root}/probe.py",
                f"{root}/control.json",
            )
        )


@pytest.mark.parametrize("control", ["\t", "\x1b", "\b", "\f", "\x7f"])
@pytest.mark.parametrize("path_index", range(6))
def test_runtime_paths_reject_all_c0_controls_and_delete(control: str, path_index: int) -> None:
    root = f"{RUNTIME_STAGING_ROOT}/run"
    paths = [
        f"{root}/archive.tar",
        f"{root}/wheels",
        f"{root}/site",
        f"{root}/request.txt",
        f"{root}/probe.py",
        f"{root}/control.json",
    ]
    paths[path_index] += control
    with pytest.raises(OfflineCatalogError, match="runtime_paths_invalid"):
        validate_runtime_staging_paths(paths)


def test_preflight_failure_is_aggregate_safe_and_requires_exact_exhaustion(tmp_path: Path) -> None:
    catalog_path, identity, project, dataset, tasks, fingerprint = _fixture(tmp_path)
    catalog = _load(catalog_path, identity, project, dataset)
    private_key = "private-missing-member"
    with pytest.raises(OfflineCatalogError) as raised:
        catalog.preflight(
            (
                ExpectedTaskBinding(private_key, tasks[0].runtime_role, tasks[0].image, tasks[0].requirements),
                tasks[1],
            ),
            expected_task_count=2,
        )
    assert raised.value.code == "catalog_coverage_incomplete"
    assert private_key not in str(raised.value)
    with pytest.raises(OfflineCatalogError, match="expected_task_count_invalid"):
        catalog.preflight(tasks[:1], expected_task_count=1)
    with pytest.raises(OfflineCatalogError, match="catalog_preflight_required"):
        catalog.resolve(
            tasks[0].task_key,
            tasks[0].runtime_role,
            tasks[0].image,
            tasks[0].requirements,
            fingerprint,
        )


def test_catalog_rejects_unapproved_source_and_nondeterministic_archive(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    catalog_path, identity, project, dataset, tasks, _ = _fixture(source, source_origin=True)
    catalog = _load(catalog_path, identity, project, dataset)
    with pytest.raises(OfflineCatalogError, match="source_input_unapproved"):
        catalog.preflight(tasks, expected_task_count=2)

    binary = tmp_path / "binary"
    binary.mkdir()
    catalog_path, identity, project, dataset, tasks, _ = _fixture(binary, approve_binary=False)
    catalog = _load(catalog_path, identity, project, dataset)
    with pytest.raises(OfflineCatalogError, match="binary_input_unapproved"):
        catalog.preflight(tasks, expected_task_count=2)

    nondeterministic = tmp_path / "nondeterministic"
    nondeterministic.mkdir()
    catalog_path, identity, project, dataset, tasks, _ = _fixture(
        nondeterministic,
        deterministic_archive=False,
    )
    catalog = _load(catalog_path, identity, project, dataset)
    with pytest.raises(OfflineCatalogError, match="wheelhouse_nondeterministic"):
        catalog.preflight(tasks, expected_task_count=2)


def test_catalog_rejects_path_alias_overlap_and_post_preflight_mutation(tmp_path: Path) -> None:
    catalog_path, identity, project, dataset, tasks, fingerprint = _fixture(tmp_path)
    with pytest.raises(OfflineCatalogError, match="catalog_root_overlap"):
        OfflineVerifierCatalog.load(
            catalog_path,
            _digest(catalog_path.read_bytes()),
            identity,
            project_root=catalog_path.parent,
            dataset_root=dataset,
        )

    alias_root = tmp_path / "alias-root"
    alias_root.mkdir(mode=0o700)
    alias_root.chmod(0o700)
    alias = alias_root / "catalog-alias.json"
    alias.symlink_to(catalog_path)
    with pytest.raises(OfflineCatalogError, match="catalog_root_invalid|catalog_invalid"):
        OfflineVerifierCatalog.load(
            alias,
            _digest(catalog_path.read_bytes()),
            identity,
            project_root=project,
            dataset_root=dataset,
        )

    catalog = _load(catalog_path, identity, project, dataset)
    catalog.preflight(tasks, expected_task_count=2)
    plan = catalog.resolve(
        tasks[1].task_key,
        tasks[1].runtime_role,
        tasks[1].image,
        tasks[1].requirements,
        fingerprint,
    )
    archive_paths = list((catalog_path.parent / "archives").glob("sha256/*/*.tar"))
    assert len(archive_paths) == 1
    archive_path = archive_paths[0]
    archive_path.chmod(0o600)
    archive_path.write_bytes(archive_path.read_bytes() + b"changed")
    archive_path.chmod(0o400)
    with pytest.raises(OfflineCatalogError, match="wheelhouse_archive_changed"):
        plan.read_verified_archive()


def test_catalog_root_and_files_must_be_private(tmp_path: Path) -> None:
    catalog_path, identity, project, dataset, _, _ = _fixture(tmp_path)
    catalog_path.parent.chmod(0o755)
    with pytest.raises(OfflineCatalogError, match="catalog_root_invalid"):
        _load(catalog_path, identity, project, dataset)
    catalog_path.parent.chmod(0o700)
    catalog_path.chmod(0o644)
    with pytest.raises(OfflineCatalogError, match="catalog_invalid"):
        _load(catalog_path, identity, project, dataset)


def test_catalog_rejects_boolean_schema_version(tmp_path: Path) -> None:
    catalog_path, identity, project, dataset, _, _ = _fixture(tmp_path)
    raw = json.loads(catalog_path.read_bytes())
    raw["schema_version"] = True
    payload = canonical_json(raw)
    catalog_path.chmod(0o600)
    catalog_path.write_bytes(payload)
    catalog_path.chmod(0o400)
    with pytest.raises(OfflineCatalogError, match="catalog_identity_mismatch"):
        OfflineVerifierCatalog.load(
            catalog_path,
            _digest(payload),
            identity,
            project_root=project,
            dataset_root=dataset,
        )


def test_verified_source_digest_rejects_ignored_bytecode(tmp_path: Path) -> None:
    source = tmp_path / "controller.py"
    source.write_text("VALUE = 1\n")
    (tmp_path / "__pycache__").mkdir()
    with pytest.raises(OfflineCatalogError, match="python_bytecode_present"):
        _verified_source_digest((("controller", source),))


def test_verified_source_digest_rejects_final_path_inode_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "controller.py"
    source.write_text("VALUE = 1\n")
    replacement = tmp_path / "replacement.py"
    replacement.write_text("VALUE = 2\n")
    original_open = catalog_module._source_path_descriptors
    opens = 0

    def swap_before_revalidation(path: Path) -> list[int]:
        nonlocal opens
        opens += 1
        if opens == 2:
            replacement.replace(source)
        return original_open(path)

    monkeypatch.setattr(catalog_module, "_source_path_descriptors", swap_before_revalidation)
    with pytest.raises(OfflineCatalogError, match="verified_source_invalid"):
        _verified_source_digest((("controller", source),))


def test_verified_source_digest_rejects_parent_directory_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_parent = tmp_path / "source"
    source_parent.mkdir()
    source = source_parent / "controller.py"
    source.write_text("VALUE = 1\n")
    replacement_parent = tmp_path / "replacement"
    replacement_parent.mkdir()
    (replacement_parent / source.name).write_text("VALUE = 2\n")
    displaced_parent = tmp_path / "source-original"
    original_open = catalog_module._source_path_descriptors
    opens = 0

    def swap_parent_before_revalidation(path: Path) -> list[int]:
        nonlocal opens
        opens += 1
        if opens == 2:
            source_parent.rename(displaced_parent)
            replacement_parent.rename(source_parent)
        return original_open(path)

    monkeypatch.setattr(catalog_module, "_source_path_descriptors", swap_parent_before_revalidation)
    with pytest.raises(OfflineCatalogError, match="verified_source_invalid"):
        _verified_source_digest((("controller", source),))


def test_verified_source_digest_rechecks_bytecode_cache_after_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "controller.py"
    source.write_text("VALUE = 1\n")
    real_read = catalog_module.os.read
    cache_created = False

    def create_cache_after_first_read(descriptor: int, size: int) -> bytes:
        nonlocal cache_created
        payload = real_read(descriptor, size)
        if payload and not cache_created:
            (tmp_path / "__pycache__").mkdir()
            cache_created = True
        return payload

    monkeypatch.setattr(catalog_module.os, "read", create_cache_after_first_read)
    with pytest.raises(OfflineCatalogError, match="python_bytecode_present"):
        _verified_source_digest((("controller", source),))
