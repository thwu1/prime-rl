from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import sysconfig
import tarfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
import source_wheel_proof_bootstrap as proof_bootstrap
import terminal_bench_vmvm.source_wheel_proof as source_wheel_proof
from terminal_bench_vmvm.source_wheel_proof import (
    APPROVED_BASE_RUNTIME_COMMIT,
    BINARY_DIR,
    CLEAN_TREE_SHA256,
    DISCOVERY_DOWNLOAD_CODE,
    FINGERPRINT_PROBE,
    INPUT_DIR,
    PIP_REPORT_PATH,
    RESOLVER_DIR,
    TARGET_SITE_DIR,
    WHEEL_DIR,
    WHEEL_DIRECTORY_PROBE,
    BuildResult,
    ProofStore,
    SourceWheelProofConfig,
    SourceWheelProofError,
    SourceWheelProofRunner,
    aggregate_failure,
    classify_source_build_failure,
    compare_build_payloads,
    load_private_discovery_input,
    run_source_wheel_proof,
    validate_execution_environment,
    validate_vacli_environment,
)
from terminal_bench_vmvm.source_wheels import (
    canonical_json,
    inspect_wheel,
    pack_wheelhouse,
    sha256_bytes,
)
from terminal_bench_vmvm.taskset import _SOURCE_WHEEL_CLOSURE_CODE, _SOURCE_WHEEL_DOWNLOAD_CODE
from verifiers.v1.runtimes import ProgramResult, VMVMConfig
from vmvm_tb_v2._vacli.backend import (
    BackendInitError,
    VacliVMVMBackend,
    _extract_vacli_lease_response,
    _vacli_lease_identity_sha256,
)

BUILD_TOOLS = {"pip": "24.3.1", "setuptools": "75.6.0", "wheel": "0.45.1"}


def _wheel_file(distribution: str, version: str, *requirements: str) -> bytes:
    wheel_distribution = distribution.replace("-", "_")
    output = io.BytesIO()
    with ZipFile(output, mode="w") as wheel:
        metadata_dir = f"{wheel_distribution}-{version}.dist-info"
        metadata = ["Metadata-Version: 2.1", f"Name: {distribution}", f"Version: {version}"]
        metadata.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
        wheel.writestr(f"{metadata_dir}/METADATA", "\n".join(metadata) + "\n")
        wheel.writestr(
            f"{metadata_dir}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: proof-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return output.getvalue()


def _source_file(distribution: str) -> bytes:
    source_distribution = distribution.replace("-", "_")
    metadata = f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n".encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo(f"{source_distribution}-1.0/PKG-INFO")
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))
    return output.getvalue()


@dataclass(frozen=True)
class FakeArtifacts:
    source_distribution: str
    source_filename: str
    source: bytes
    source_wheel_filename: str
    source_wheel: bytes
    binary_distribution: str
    binary_filename: str
    binary_url: str
    binary_wheel: bytes

    @property
    def closure(self) -> list[list[str]]:
        return sorted([[self.source_distribution, "1.0"], [self.binary_distribution, "2.0"]])


def _discovery_payload(entry_count: int) -> tuple[bytes, dict[str, FakeArtifacts]]:
    entries = []
    artifacts = {}
    for index in range(entry_count):
        source_distribution = f"proof-package-{index}"
        binary_distribution = f"proof-helper-{index}"
        source_stem = source_distribution.replace("-", "_")
        binary_stem = binary_distribution.replace("-", "_")
        source = _source_file(source_distribution)
        source_wheel = _wheel_file(source_distribution, "1.0")
        source_is_transitive = index % 3 == 0
        binary_wheel = _wheel_file(
            binary_distribution,
            "2.0",
            *([f"{source_distribution}>=1.0"] if source_is_transitive else []),
        )
        source_filename = f"{source_stem}-1.0.tar.gz"
        source_wheel_filename = f"{source_stem}-1.0-py3-none-any.whl"
        binary_filename = f"{binary_stem}-2.0-py3-none-any.whl"
        binary_url = f"https://files.example.invalid/{binary_filename}"
        image_digest = hashlib.sha256(f"image-{index}".encode()).hexdigest()
        image = f"registry.example.invalid/proof@sha256:{image_digest}"
        source_record = {
            "distribution": source_distribution,
            "version": "1.0",
            "filename": source_filename,
            "url": f"https://files.example.invalid/{source_filename}",
            "size": len(source),
            "sha256": sha256_bytes(source),
            "source_spec": (f"{source_distribution}>=1.0" if source_is_transitive else f"{source_distribution}==1.0"),
            "source_spec_exact": not source_is_transitive,
            "version_selection": "exact",
            "pkg_info_records": 1,
            "pkg_info_identity_agreement": True,
        }
        identity = sha256_bytes(canonical_json([index, image, source_record]))
        entries.append(
            {
                "task": f"private-task-{index}",
                "entry_identity_sha256": identity,
                "requirements": (
                    [f"{binary_distribution}==2.0"]
                    if source_is_transitive
                    else [f"{source_distribution}==1.0", f"{binary_distribution}==2.0"]
                ),
                "image": image,
                "source": source_record,
                "build_tools": None,
                "built_source_wheel": None,
                "binary_wheels": None,
                "reproducibility": None,
                "ready_for_policy": False,
            }
        )
        artifacts[image] = FakeArtifacts(
            source_distribution=source_distribution,
            source_filename=source_filename,
            source=source,
            source_wheel_filename=source_wheel_filename,
            source_wheel=source_wheel,
            binary_distribution=binary_distribution,
            binary_filename=binary_filename,
            binary_url=binary_url,
            binary_wheel=binary_wheel,
        )
    discovery = {
        "schema_version": 1,
        "kind": "source-wheel-policy-probe-input",
        "complete": False,
        "missing_required_evidence": ["runtime", "toolchain", "wheel", "closure"],
        "provenance": {
            "dataset_revision": "d" * 40,
            "image_manifest_sha256": "e" * 64,
            "oracle_results_sha256": "f" * 64,
        },
        "allowed_hosts": ["files.example.invalid"],
        "entries": entries,
    }
    return canonical_json(discovery) + b"\n", artifacts


def _write_discovery(
    tmp_path: Path,
    entry_count: int,
) -> tuple[Path, dict[str, FakeArtifacts]]:
    private = tmp_path / "private"
    private.mkdir(mode=0o700, parents=True)
    private.chmod(0o700)
    payload, artifacts = _discovery_payload(entry_count)
    path = private / "discovery.json"
    path.write_bytes(payload)
    path.chmod(0o600)
    return path, artifacts


def _config(discovery: Path, output: Path, **changes: object) -> SourceWheelProofConfig:
    missing = json.loads(discovery.read_bytes())["missing_required_evidence"]
    project = Path.cwd().resolve()
    config = SourceWheelProofConfig(
        input_path=discovery,
        input_sha256=sha256_bytes(discovery.read_bytes()),
        output_dir=output,
        expected_entry_count=9,
        expected_missing_evidence_sha256=sha256_bytes(canonical_json(missing)),
        project_dir=project,
        canonical_launcher_path=project / "unused-launcher",
        executed_launcher_path=project / "unused-launcher",
        uv_path=project / "unused-uv",
        python_path=Path(sys.executable).resolve(),
        python_stdlib_path=Path(sysconfig.get_path("stdlib")).resolve(),
        site_packages_path=project / "unused-site-packages",
        vacli_path=project / "unused-vacli",
        launcher_sha256="6" * 64,
        uv_sha256="7" * 64,
        python_sha256="8" * 64,
        python_runtime_manifest_sha256="9" * 64,
        site_packages_manifest_sha256="0" * 64,
        base_runtime_commit=APPROVED_BASE_RUNTIME_COMMIT,
        source_commit="a" * 40,
        source_git_tree="1" * 40,
        source_tree_sha256=CLEAN_TREE_SHA256,
        verifiers_commit="b" * 40,
        renderers_commit="c" * 40,
        pydantic_config_commit="d" * 40,
        vmvm_tb_v2_sha256="e" * 64,
        vacli_binary_sha256="f" * 64,
        invocation_host="worker.example.invalid",
        slurm_job_id="12345",
    )
    return replace(config, **changes)


def _fingerprint_payload() -> str:
    return json.dumps(
        {
            "marker_environment": {
                "implementation_name": "cpython",
                "implementation_version": "3.12.0",
                "os_name": "posix",
                "platform_machine": "x86_64",
                "platform_release": "6.8.0",
                "platform_system": "Linux",
                "platform_version": "proof-runtime",
                "python_full_version": "3.12.0",
                "platform_python_implementation": "CPython",
                "python_version": "3.12",
                "sys_platform": "linux",
            },
            "pip_version": BUILD_TOOLS["pip"],
            "wheel_compatibility": [
                "cpython",
                [3, 12],
                "cpython-312-x86_64-linux-gnu",
                "linux-x86_64",
                "x86_64",
            ],
            "build_tools": BUILD_TOOLS,
        },
        sort_keys=True,
    )


class FakeFleet:
    def __init__(
        self,
        artifacts: dict[str, FakeArtifacts],
        *,
        block_builds: bool = False,
        block_starts: bool = False,
        duplicate_descriptors: bool = False,
        source_build_stderr: str | None = None,
        source_build_stderr_by_image: dict[str, str] | None = None,
        fingerprint_failure: bool = False,
    ) -> None:
        self.artifacts = artifacts
        self.block_builds = block_builds
        self.block_starts = block_starts
        self.duplicate_descriptors = duplicate_descriptors
        self.source_build_stderr = source_build_stderr
        self.source_build_stderr_by_image = source_build_stderr_by_image or {}
        self.fingerprint_failure = fingerprint_failure
        self.release_builds = asyncio.Event()
        self.release_starts = asyncio.Event()
        self.two_builds_entered = asyncio.Event()
        self.all_starts_entered = asyncio.Event()
        self.builds_entered = 0
        self.starts_entered = 0
        self.runtimes: list[FakeRuntime] = []
        self.start_count = 0
        self.source_download_count = 0
        self.binary_download_count = 0
        self.resolution_count = 0
        self.live = 0
        self.peak_live = 0

    def factory(self, config: VMVMConfig, name: str) -> FakeRuntime:
        runtime = FakeRuntime(self, config, name)
        self.runtimes.append(runtime)
        return runtime


class FakeRuntime:
    def __init__(self, fleet: FakeFleet, config: VMVMConfig, name: str) -> None:
        self.fleet = fleet
        self.config = config
        self.name = name
        raw_identity = "duplicate-lease" if fleet.duplicate_descriptors else f"lease-{name}"
        self.descriptor = "container-id-must-not-be-used"
        self.backend = SimpleNamespace(
            lease_identity_sha256=sha256_bytes(canonical_json(["vacli-session-identity-v1", raw_identity]))
        )
        self.files: dict[str, bytes] = {}
        self.started = False
        self.stopped = False
        self.network_mode: str | None = None
        self.network_active = False
        self.build_count = 0

    @property
    def artifact(self) -> FakeArtifacts:
        return self.fleet.artifacts[self.config.image]

    async def start(self) -> None:
        self.fleet.starts_entered += 1
        if self.fleet.starts_entered >= 3:
            self.fleet.all_starts_entered.set()
        if self.fleet.block_starts:
            await self.fleet.release_starts.wait()
        self.started = True
        self.fleet.start_count += 1
        self.fleet.live += 1
        self.fleet.peak_live = max(self.fleet.peak_live, self.fleet.live)
        await asyncio.sleep(0)

    async def stop(self) -> None:
        if self.started and not self.stopped:
            self.stopped = True
            self.fleet.live -= 1
        await asyncio.sleep(0)

    async def configure_network_policy(self, mode: str) -> None:
        assert mode == "no-network"
        self.network_mode = mode

    async def activate_network_policy(self) -> None:
        assert self.network_mode == "no-network"
        self.network_active = True

    async def run(self, argv: list[str], env: dict[str, str]) -> ProgramResult:
        assert self.started and not self.stopped
        assert env == {}
        if argv[:4] == ["python3", "-I", "-c", _SOURCE_WHEEL_DOWNLOAD_CODE]:
            assert not self.network_active
            self.fleet.source_download_count += 1
            self.files[argv[5]] = self.artifact.source
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv[:4] == ["python3", "-I", "-c", DISCOVERY_DOWNLOAD_CODE]:
            assert not self.network_active
            self.fleet.binary_download_count += 1
            self.files[argv[5]] = self.artifact.binary_wheel
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv == ["python3", "-I", "-c", FINGERPRINT_PROBE]:
            assert self.network_active
            if self.fleet.fingerprint_failure:
                return ProgramResult(exit_code=1, stdout="", stderr="private-marker")
            return ProgramResult(exit_code=0, stdout=_fingerprint_payload(), stderr="")
        if argv[:5] == ["python3", "-I", "-m", "pip", "wheel"]:
            assert self.network_active
            assert "--no-index" in argv and "--no-deps" in argv and "--no-build-isolation" in argv
            self.build_count += 1
            self.fleet.builds_entered += 1
            if self.fleet.builds_entered >= 2:
                self.fleet.two_builds_entered.set()
            if self.fleet.block_builds and self.fleet.builds_entered >= 2:
                await self.fleet.release_builds.wait()
            source_build_stderr = self.fleet.source_build_stderr_by_image.get(
                self.config.image,
                self.fleet.source_build_stderr,
            )
            if source_build_stderr is not None:
                return ProgramResult(exit_code=1, stdout="", stderr=source_build_stderr)
            self.files[f"{WHEEL_DIR}/{self.artifact.source_wheel_filename}"] = self.artifact.source_wheel
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv[:5] == ["python3", "-I", "-m", "pip", "install"] and "--dry-run" in argv:
            assert not self.network_active
            self.fleet.resolution_count += 1
            report = {
                "version": "1",
                "install": [
                    {
                        "download_info": {
                            "url": f"file://{RESOLVER_DIR}/{self.artifact.source_wheel_filename}",
                            "archive_info": {"hashes": {"sha256": sha256_bytes(self.artifact.source_wheel)}},
                        },
                        "metadata": {"name": self.artifact.source_distribution, "version": "1.0"},
                    },
                    {
                        "download_info": {
                            "url": self.artifact.binary_url,
                            "archive_info": {"hashes": {"sha256": sha256_bytes(self.artifact.binary_wheel)}},
                        },
                        "metadata": {"name": self.artifact.binary_distribution, "version": "2.0"},
                    },
                ],
            }
            self.files[PIP_REPORT_PATH] = canonical_json(report)
            return ProgramResult(exit_code=0, stdout="", stderr="")
        if argv[:4] == ["python3", "-I", "-c", WHEEL_DIRECTORY_PROBE]:
            prefix = f"{WHEEL_DIR}/"
            records = [
                {"filename": path.removeprefix(prefix), "size": len(payload), "sha256": sha256_bytes(payload)}
                for path, payload in sorted(self.files.items())
                if path.startswith(prefix)
            ]
            return ProgramResult(exit_code=0, stdout=json.dumps(records), stderr="")
        if argv[:4] == ["python3", "-I", "-c", _SOURCE_WHEEL_CLOSURE_CODE]:
            assert self.network_active
            return ProgramResult(exit_code=0, stdout=json.dumps(self.artifact.closure), stderr="")
        if argv[:2] == ["sh", "-c"]:
            command = argv[2]
            if command.startswith(f"rm -rf {INPUT_DIR} {BINARY_DIR} {WHEEL_DIR}"):
                if "mkdir -p" not in command:
                    self.files.clear()
                return ProgramResult(exit_code=0, stdout="", stderr="")
            if "PIP_NO_INDEX=1" in command:
                assert self.network_active
                return ProgramResult(exit_code=0, stdout="", stderr="")
            if TARGET_SITE_DIR in command:
                assert self.network_active
                return ProgramResult(exit_code=0, stdout="", stderr="")
        raise AssertionError("unexpected fake-runtime command")

    async def read(self, path: str) -> bytes:
        return self.files[path]

    async def write(self, path: str, data: bytes) -> None:
        self.files[path] = data


def test_nine_entry_discovery_emits_policy_with_exactly_twenty_seven_starts(
    tmp_path: Path,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(artifacts)

    result = asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=fleet.factory))

    assert result["entries"] == 9
    assert result["runtime_starts"] == 27
    assert result["peak_live_runtimes"] == 6
    assert result["peak_concurrent_entries"] == 2
    assert fleet.start_count == 27
    assert fleet.peak_live == 6
    assert fleet.live == 0
    assert len(fleet.runtimes) == 27
    assert all(runtime.stopped and runtime.network_active for runtime in fleet.runtimes)
    assert sum(runtime.build_count for runtime in fleet.runtimes) == 18
    assert fleet.source_download_count == 18
    assert fleet.binary_download_count == 9
    assert fleet.resolution_count == 9
    assert all(runtime.build_count == 0 for runtime in fleet.runtimes if runtime.name.endswith("-target"))
    assert all(runtime.build_count == 1 for runtime in fleet.runtimes if "-builder-" in runtime.name)

    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    expected_modes = {
        ".writer.lock": 0o600,
        "attempt_journal": 0o700,
        "finalization.json": 0o400,
        "post_run_validation.json": 0o400,
        "proof_state.json": 0o600,
        "run_identity.json": 0o400,
        "source_wheel_candidate.json": 0o400,
        "source_wheel_policy.json": 0o400,
        "source_wheel_proof.json": 0o400,
    }
    assert {path.name for path in output.iterdir()} == set(expected_modes)
    assert {path.name: stat.S_IMODE(path.stat().st_mode) for path in output.iterdir()} == expected_modes
    candidate = json.loads((output / "source_wheel_candidate.json").read_bytes())
    identity_payload = (output / "run_identity.json").read_bytes()
    identity = json.loads(identity_payload)
    proof = json.loads((output / "source_wheel_proof.json").read_bytes())
    policy = json.loads((output / "source_wheel_policy.json").read_bytes())
    state = json.loads((output / "proof_state.json").read_bytes())
    assert candidate["runnable"] is False
    assert candidate["required_runtime_starts"] == 27
    assert proof["proof_runtime_starts"] == 27
    assert state["telemetry"]["attested_runtime_starts"] == 27
    assert state["attempt_journal"]["start_intents"] == 27
    assert state["attempt_journal"]["successful_starts"] == 27
    assert state["attempt_journal"]["record_count"] == 81
    journal_files = sorted((output / "attempt_journal").iterdir())
    assert len(journal_files) == 81
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o400 for path in journal_files)
    assert proof["source"]["approved_base_runtime_commit"] == APPROVED_BASE_RUNTIME_COMMIT
    assert proof["source"]["commit"] == "a" * 40
    assert proof["source"]["git_tree"] == "1" * 40
    assert proof["source"] == identity["source"]
    assert proof["run_identity_sha256"] == sha256_bytes(identity_payload)
    assert proof["discovery_input_sha256"] == sha256_bytes(discovery.read_bytes())
    assert proof["source"]["verifiers_commit"] == "b" * 40
    assert proof["source"]["renderers_commit"] == "c" * 40
    assert proof["source"]["pydantic_config_commit"] == "d" * 40
    assert proof["source"]["vmvm_tb_v2_sha256"] == "e" * 64
    assert proof["execution"]["vacli_binary_sha256"] == "f" * 64
    assert proof["execution"] == identity["execution"]
    assert proof["source_wheel_policy_sha256"] == sha256_bytes((output / "source_wheel_policy.json").read_bytes())
    finalization_payload = (output / "finalization.json").read_bytes()
    finalization = json.loads(finalization_payload)
    post_validation_payload = (output / "post_run_validation.json").read_bytes()
    post_validation = json.loads(post_validation_payload)
    assert result["finalization_sha256"] == sha256_bytes(finalization_payload)
    assert finalization["proof_file_sha256"] == sha256_bytes((output / "source_wheel_proof.json").read_bytes())
    assert finalization["source_wheel_policy_sha256"] == proof["source_wheel_policy_sha256"]
    assert finalization["post_run_validation"] == state["post_run_validation"]
    assert proof["post_run_validation"] == state["post_run_validation"]
    assert state["post_run_validation"]["record_sha256"] == sha256_bytes(post_validation_payload)
    assert post_validation["validation_id_sha256"] == state["post_run_validation"]["validation_id_sha256"]
    prevalidation_state = dict(state)
    prevalidation_state["post_run_validation"] = None
    assert post_validation["prevalidation_state_sha256"] == sha256_bytes(canonical_json(prevalidation_state) + b"\n")
    assert post_validation["attempt_journal"] == state["attempt_journal"]
    assert len(policy["entries"]) == 9
    assert all(entry["build_tools"] == BUILD_TOOLS for entry in policy["entries"])
    assert all(len(entry["binary_wheels"]) == 1 for entry in policy["entries"])
    assert all(entry["cross_builder"]["wheel_bytes_equal"] for entry in proof["entries"])
    assert all(len(set(entry["lease_identity_sha256s"].values())) == 3 for entry in proof["entries"])
    assert len({digest for entry in proof["entries"] for digest in entry["lease_identity_sha256s"].values()}) == 27
    assert b"lease-source-proof" not in (output / "source_wheel_proof.json").read_bytes()
    assert b"lease-source-proof" not in b"".join(path.read_bytes() for path in journal_files)
    assert b"container-id-must-not-be-used" not in (output / "source_wheel_proof.json").read_bytes()

    state_sha256 = sha256_bytes((output / "proof_state.json").read_bytes())
    resumed_fleet = FakeFleet(artifacts)
    resumed = _config(
        discovery,
        output,
        resume_state_sha256=state_sha256,
        slurm_job_id="12346",
    )
    assert asyncio.run(run_source_wheel_proof(resumed, runtime_factory=resumed_fleet.factory)) == result
    assert resumed_fleet.start_count == 0

    aggregate = json.dumps(aggregate_failure(output, "synthetic_failure"), sort_keys=True)
    assert "private-task" not in aggregate
    assert "https://" not in aggregate
    aggregate_attempts = json.loads(aggregate)["attempt_journal"]
    assert aggregate_attempts == {
        "status": "valid",
        "record_count": 81,
        "distinct_entries": 9,
        "distinct_attempts": 27,
        "start_intents": 27,
        "successful_starts": 27,
        "failed_starts": 0,
        "indeterminate_starts": 0,
        "successful_stops": 27,
        "failed_stops": 0,
    }


@pytest.mark.parametrize(
    "retained",
    [
        frozenset(),
        frozenset({"source_wheel_proof.json"}),
        frozenset({"source_wheel_policy.json"}),
    ],
)
def test_finalization_record_reconciles_every_partial_publication(
    tmp_path: Path,
    retained: frozenset[str],
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    original = asyncio.run(
        run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory)
    )
    for name in {"source_wheel_proof.json", "source_wheel_policy.json"} - retained:
        (output / name).unlink()
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)

    result = asyncio.run(
        run_source_wheel_proof(
            _config(
                discovery,
                output,
                resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                slurm_job_id="12346",
            ),
            runtime_factory=resumed_fleet.factory,
        )
    )

    assert result == original
    assert resumed_fleet.start_count == 0
    assert (output / "finalization.json").is_file()
    assert (output / "source_wheel_proof.json").is_file()
    assert (output / "source_wheel_policy.json").is_file()


def test_final_artifacts_without_finalization_record_fail_closed(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory))
    (output / "finalization.json").unlink()
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)

    with pytest.raises(SourceWheelProofError, match="^finalization_record_missing$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                    slurm_job_id="12346",
                ),
                runtime_factory=resumed_fleet.factory,
            )
        )
    assert resumed_fleet.start_count == 0


def test_completed_state_without_post_validation_cannot_launder_zero_start_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    initial_fleet = FakeFleet(artifacts)
    initial_factory = initial_fleet.factory
    validation_calls = 0

    def fail_post_validation(_: SourceWheelProofConfig) -> None:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            raise SourceWheelProofError("synthetic_post_validation_failure")

    monkeypatch.setattr(source_wheel_proof, "_runtime_factory", initial_factory)
    monkeypatch.setattr(source_wheel_proof, "validate_execution_environment", fail_post_validation)
    monkeypatch.setattr(source_wheel_proof, "validate_vacli_environment", lambda _: None)
    with pytest.raises(SourceWheelProofError, match="^synthetic_post_validation_failure$"):
        asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=initial_factory))

    assert initial_fleet.start_count == 27
    assert validation_calls == 2
    assert not (output / "post_run_validation.json").exists()
    state_path = output / "proof_state.json"
    state = json.loads(state_path.read_bytes())
    assert state["post_run_validation"] is None
    assert len(state["completed"]) == 9
    resumed_fleet = FakeFleet(artifacts)
    resumed_factory = resumed_fleet.factory
    monkeypatch.setattr(source_wheel_proof, "_runtime_factory", resumed_factory)
    monkeypatch.setattr(source_wheel_proof, "validate_execution_environment", lambda _: None)

    with pytest.raises(SourceWheelProofError, match="^completed_state_not_post_validated$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                    slurm_job_id="12346",
                ),
                runtime_factory=resumed_factory,
            )
        )
    assert resumed_fleet.start_count == 0
    assert not (output / "finalization.json").exists()
    assert not (output / "source_wheel_policy.json").exists()


def test_post_validation_record_reconciles_state_update_crash(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    original = asyncio.run(
        run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory)
    )
    for name in ("finalization.json", "source_wheel_proof.json", "source_wheel_policy.json"):
        (output / name).unlink()
    state_path = output / "proof_state.json"
    state = json.loads(state_path.read_bytes())
    state["post_run_validation"] = None
    state_path.write_bytes(canonical_json(state) + b"\n")
    state_path.chmod(0o600)
    resumed_fleet = FakeFleet(artifacts)

    result = asyncio.run(
        run_source_wheel_proof(
            _config(
                discovery,
                output,
                resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                slurm_job_id="12346",
            ),
            runtime_factory=resumed_fleet.factory,
        )
    )

    assert result == original
    assert resumed_fleet.start_count == 0


def test_post_validation_state_without_immutable_record_fails_closed(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory))
    for name in (
        "finalization.json",
        "source_wheel_proof.json",
        "source_wheel_policy.json",
        "post_run_validation.json",
    ):
        (output / name).unlink()
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)

    with pytest.raises(SourceWheelProofError, match="^post_run_validation_record_missing$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state_path.read_bytes()),
                    slurm_job_id="12346",
                ),
                runtime_factory=resumed_fleet.factory,
            )
        )
    assert resumed_fleet.start_count == 0


def test_cancellation_stops_every_started_runtime_and_leaves_resumable_state(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"

    async def scenario() -> FakeFleet:
        fleet = FakeFleet(artifacts, block_builds=True)
        proof = asyncio.create_task(
            run_source_wheel_proof(
                _config(discovery, output, max_concurrent_entries=1, vacli_max_concurrent_leases=3),
                runtime_factory=fleet.factory,
            )
        )
        await asyncio.wait_for(fleet.two_builds_entered.wait(), timeout=2)
        proof.cancel()
        with pytest.raises(asyncio.CancelledError):
            await proof
        return fleet

    fleet = asyncio.run(scenario())

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert all(runtime.stopped for runtime in fleet.runtimes)
    state = output / "proof_state.json"
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert json.loads(state.read_bytes())["completed"] == {}
    with pytest.raises(SourceWheelProofError, match="^attempt_journal_state_mismatch$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state.read_bytes()),
                    slurm_job_id="12346",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=FakeFleet(artifacts).factory,
            )
        )
    journal_records = [json.loads(path.read_bytes()) for path in sorted((output / "attempt_journal").iterdir())]
    state_payload = json.loads(state.read_bytes())
    state_payload["attempt_journal"] = {
        "record_count": len(journal_records),
        "head_sha256": journal_records[-1]["record_sha256"],
        "start_intents": sum(record["event"] == "start_intent" for record in journal_records),
        "successful_starts": sum(record["event"] == "start_succeeded" for record in journal_records),
    }
    state.write_bytes(canonical_json(state_payload) + b"\n")
    state.chmod(0o600)
    with pytest.raises(SourceWheelProofError, match="^attempt_journal_prevents_exact_start_count$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    resume_state_sha256=sha256_bytes(state.read_bytes()),
                    slurm_job_id="12346",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=FakeFleet(artifacts).factory,
            )
        )
    aggregate = aggregate_failure(output, "cancelled")
    assert aggregate["attempt_journal"] == {
        "status": "valid",
        "record_count": 9,
        "distinct_entries": 1,
        "distinct_attempts": 3,
        "start_intents": 3,
        "successful_starts": 3,
        "failed_starts": 0,
        "indeterminate_starts": 0,
        "successful_stops": 3,
        "failed_stops": 0,
    }


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        (
            "ModuleNotFoundError: No module named 'synthetic_backend'",
            "source_build_failed_build_dependency_unavailable",
        ),
        (
            "Temporary failure in name resolution",
            "source_build_failed_network_access_required",
        ),
        (
            "unable to execute 'gcc': No such file or directory",
            "source_build_failed_native_toolchain_unavailable",
        ),
        (
            "This release requires a different Python",
            "source_build_failed_python_incompatible",
        ),
        (
            "neither 'setup.py' nor 'pyproject.toml' found",
            "source_build_failed_invalid_source_tree",
        ),
        (
            "synthetic opaque build failure containing private-marker",
            "source_build_failed_unclassified",
        ),
    ],
)
def test_source_build_failure_diagnostics_are_fixed_vocabulary(
    diagnostic: str,
    expected: str,
) -> None:
    result = ProgramResult(exit_code=1, stdout="private-marker", stderr=diagnostic)

    observed = classify_source_build_failure(result)

    assert observed == expected
    assert "private-marker" not in observed


def test_source_build_failure_exposes_only_classified_code(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(
        artifacts,
        source_build_stderr="ModuleNotFoundError: No module named 'private-marker'",
    )

    with pytest.raises(
        SourceWheelProofError,
        match="^source_build_failed$",
    ):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 3
    summary = json.dumps(
        aggregate_failure(output, "source_build_failed"),
        sort_keys=True,
    )
    assert "private-marker" not in summary
    assert '"successful_starts": 3' in summary
    assert '"successful_stops": 3' in summary


def test_source_build_diagnostic_mode_runs_all_entries_and_emits_only_private_receipts(
    tmp_path: Path,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(
        artifacts,
        source_build_stderr="ModuleNotFoundError: No module named 'private-marker'",
    )

    with pytest.raises(SourceWheelProofError, match="^source_build_diagnostics_complete$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    continue_on_source_build_failure=True,
                ),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 27
    assert fleet.live == 0
    assert all(runtime.stopped for runtime in fleet.runtimes)
    expected_diagnostics = {
        "source_build_diagnostics.json",
        "source_build_success_discovery.json",
        "source_build_diagnostic_summary.json",
    }
    assert all(stat.S_IMODE((output / name).stat().st_mode) == 0o400 for name in expected_diagnostics)
    for forbidden in (
        "post_run_validation.json",
        "finalization.json",
        "source_wheel_proof.json",
        "source_wheel_policy.json",
    ):
        assert not (output / forbidden).exists()
    private_diagnostics = json.loads((output / "source_build_diagnostics.json").read_bytes())
    assert private_diagnostics["complete"] is True
    assert private_diagnostics["post_run_environment_validation"] == "passed"
    assert private_diagnostics["accounted_entry_count"] == 9
    assert private_diagnostics["successful_entry_count"] == 0
    assert len(private_diagnostics["failures"]) == 9
    reduced = json.loads((output / "source_build_success_discovery.json").read_bytes())
    assert reduced["entries"] == []
    aggregate = aggregate_failure(output, "source_build_diagnostics_complete")
    aggregate_diagnostics = aggregate["source_build_diagnostics"]
    assert aggregate_diagnostics["status"] == "valid"
    assert aggregate_diagnostics["entry_count"] == 9
    assert aggregate_diagnostics["accounted_entry_count"] == 9
    assert aggregate_diagnostics["successful_entry_count"] == 0
    assert aggregate_diagnostics["failed_entry_count"] == 9
    assert aggregate_diagnostics["runtime_start_count"] == 27
    assert aggregate_diagnostics["runtime_stop_count"] == 27
    assert aggregate_diagnostics["category_counts"]["source_build_failed_build_dependency_unavailable"] == 9
    assert aggregate["attempt_journal"]["successful_starts"] == 27
    assert aggregate["attempt_journal"]["successful_stops"] == 27
    aggregate_payload = json.dumps(aggregate, sort_keys=True)
    assert "private-marker" not in aggregate_payload
    assert "private-task" not in aggregate_payload
    assert "https://" not in aggregate_payload
    assert b"private-marker" not in b"".join(path.read_bytes() for path in output.iterdir() if path.is_file())

    resumed_fleet = FakeFleet(artifacts)
    with pytest.raises(SourceWheelProofError, match="^source_build_diagnostic_root_not_resumable$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    continue_on_source_build_failure=True,
                    resume_state_sha256=sha256_bytes((output / "proof_state.json").read_bytes()),
                    slurm_job_id="12346",
                ),
                runtime_factory=resumed_fleet.factory,
            )
        )
    assert resumed_fleet.start_count == 0


def test_source_build_diagnostic_mode_derives_only_fully_validated_successes(
    tmp_path: Path,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    failed_images = list(artifacts)[:3]
    failures = {
        failed_images[0]: "Temporary failure in name resolution private-marker",
        failed_images[1]: "unable to execute 'gcc': private-marker",
        failed_images[2]: "opaque private-marker",
    }
    fleet = FakeFleet(artifacts, source_build_stderr_by_image=failures)

    with pytest.raises(SourceWheelProofError, match="^source_build_diagnostics_complete$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    continue_on_source_build_failure=True,
                ),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 27
    state = json.loads((output / "proof_state.json").read_bytes())
    reduced_payload = (output / "source_build_success_discovery.json").read_bytes()
    reduced = json.loads(reduced_payload)
    assert len(state["completed"]) == 6
    assert len(reduced["entries"]) == 6
    summary_payload = (output / "source_build_diagnostic_summary.json").read_bytes()
    summary = json.loads(summary_payload)
    diagnostics_payload = (output / "source_build_diagnostics.json").read_bytes()
    assert summary["original_discovery_input_sha256"] == sha256_bytes(discovery.read_bytes())
    assert summary["diagnostic_receipt_sha256"] == sha256_bytes(diagnostics_payload)
    assert summary["successful_discovery_input_sha256"] == sha256_bytes(reduced_payload)
    assert summary["successful_entry_count"] == 6
    assert summary["failed_entry_count"] == 3
    aggregate = aggregate_failure(output, "source_build_diagnostics_complete")
    aggregate_diagnostics = aggregate["source_build_diagnostics"]
    assert aggregate_diagnostics["status"] == "valid"
    assert aggregate_diagnostics["successful_entry_count"] == 6
    assert aggregate_diagnostics["failed_entry_count"] == 3
    assert aggregate_diagnostics["summary_receipt_sha256"] == sha256_bytes(summary_payload)
    assert sum(aggregate_diagnostics["category_counts"].values()) == 3
    assert "private-marker" not in json.dumps(aggregate, sort_keys=True)


def test_source_build_diagnostic_mode_never_publishes_when_every_entry_succeeds(
    tmp_path: Path,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(artifacts)

    with pytest.raises(SourceWheelProofError, match="^source_build_diagnostics_complete$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    continue_on_source_build_failure=True,
                ),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 27
    diagnostics = aggregate_failure(output, "source_build_diagnostics_complete")["source_build_diagnostics"]
    assert diagnostics["status"] == "valid"
    assert diagnostics["successful_entry_count"] == 9
    assert diagnostics["failed_entry_count"] == 0
    assert sum(diagnostics["category_counts"].values()) == 0
    assert len(json.loads((output / "source_build_success_discovery.json").read_bytes())["entries"]) == 9
    assert not (output / "source_wheel_policy.json").exists()
    assert not (output / "source_wheel_proof.json").exists()


def test_source_build_diagnostic_mode_does_not_continue_unrelated_failures(
    tmp_path: Path,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(artifacts, fingerprint_failure=True)

    with pytest.raises(SourceWheelProofError, match="^runtime_fingerprint_failed$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                    continue_on_source_build_failure=True,
                ),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert not (output / "source_build_diagnostics.json").exists()
    assert not (output / "source_build_success_discovery.json").exists()
    assert not (output / "source_build_diagnostic_summary.json").exists()
    assert "private-marker" not in json.dumps(
        aggregate_failure(output, "runtime_fingerprint_failed"),
        sort_keys=True,
    )


def test_source_build_diagnostic_summary_tampering_fails_closed(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(artifacts, source_build_stderr="opaque private-marker")
    with pytest.raises(SourceWheelProofError, match="^source_build_diagnostics_complete$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    continue_on_source_build_failure=True,
                ),
                runtime_factory=fleet.factory,
            )
        )
    summary_path = output / "source_build_diagnostic_summary.json"
    summary = json.loads(summary_path.read_bytes())
    summary["failed_entry_count"] = 8
    summary_path.chmod(0o600)
    summary_path.write_bytes(canonical_json(summary) + b"\n")
    summary_path.chmod(0o400)

    aggregate = aggregate_failure(output, "source_build_diagnostics_complete")

    assert aggregate["source_build_diagnostics"] == {"status": "invalid"}
    assert "private-marker" not in json.dumps(aggregate, sort_keys=True)


@pytest.mark.parametrize(
    "retained",
    [
        frozenset({"source_build_diagnostics.json"}),
        frozenset(
            {
                "source_build_diagnostics.json",
                "source_build_success_discovery.json",
            }
        ),
        frozenset(
            {
                "source_build_success_discovery.json",
                "source_build_diagnostic_summary.json",
            }
        ),
    ],
)
def test_source_build_diagnostic_partial_publication_fails_closed(
    tmp_path: Path,
    retained: frozenset[str],
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    fleet = FakeFleet(artifacts, source_build_stderr="opaque private-marker")
    with pytest.raises(SourceWheelProofError, match="^source_build_diagnostics_complete$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    output,
                    continue_on_source_build_failure=True,
                ),
                runtime_factory=fleet.factory,
            )
        )
    diagnostic_artifacts = {
        "source_build_diagnostics.json",
        "source_build_success_discovery.json",
        "source_build_diagnostic_summary.json",
    }
    for name in diagnostic_artifacts - retained:
        (output / name).unlink()

    aggregate = aggregate_failure(output, "source_build_diagnostics_complete")

    assert aggregate["source_build_diagnostics"] == {"status": "invalid"}
    assert "private-marker" not in json.dumps(aggregate, sort_keys=True)


def test_cancellation_drains_runtime_start_before_stopping_leases(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)

    async def scenario() -> FakeFleet:
        fleet = FakeFleet(artifacts, block_starts=True)
        proof = asyncio.create_task(
            run_source_wheel_proof(
                _config(
                    discovery,
                    tmp_path / "proof",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=fleet.factory,
            )
        )
        await asyncio.wait_for(fleet.all_starts_entered.wait(), timeout=2)
        proof.cancel()
        await asyncio.sleep(0)
        assert not any(runtime.stopped for runtime in fleet.runtimes)
        fleet.release_starts.set()
        with pytest.raises(asyncio.CancelledError):
            await proof
        return fleet

    fleet = asyncio.run(scenario())

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert all(runtime.started and runtime.stopped for runtime in fleet.runtimes)


def test_duplicate_resolved_lease_identity_fails_and_stops_all_runtimes(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    fleet = FakeFleet(artifacts, duplicate_descriptors=True)

    with pytest.raises(SourceWheelProofError, match="^runtime_lease_identity_duplicate$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(
                    discovery,
                    tmp_path / "proof",
                    max_concurrent_entries=1,
                    vacli_max_concurrent_leases=3,
                ),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert all(runtime.stopped for runtime in fleet.runtimes)


def test_real_vacli_session_shape_produces_stable_secret_independent_identity() -> None:
    first = json.dumps(
        {
            "sessionId": {"cell": "synthetic", "id": "session-a"},
            "auth_token": {"token": "secret-a"},
        }
    )
    rotated_token = json.dumps(
        {
            "sessionId": {"id": "session-a", "cell": "synthetic"},
            "auth_token": {"token": "secret-b"},
        }
    )
    different_session = json.dumps(
        {
            "sessionId": {"cell": "synthetic", "id": "session-b"},
            "auth_token": {"token": "secret-a"},
        }
    )

    assert _vacli_lease_identity_sha256(first) == _vacli_lease_identity_sha256(rotated_token)
    assert _vacli_lease_identity_sha256(first) != _vacli_lease_identity_sha256(different_session)
    extracted = _extract_vacli_lease_response(f"prefix {rotated_token} trailing diagnostics")
    assert extracted is not None
    assert extracted[1] == _vacli_lease_identity_sha256(first)
    backend = object.__new__(VacliVMVMBackend)
    backend._lease = SimpleNamespace(session_identity_sha256=extracted[1])
    assert backend.lease_identity_sha256 == extracted[1]
    backend._lease = SimpleNamespace(session_identity_sha256=None)
    with pytest.raises(BackendInitError, match="session identity is unavailable"):
        _ = backend.lease_identity_sha256
    with pytest.raises(BackendInitError, match="session identity"):
        _vacli_lease_identity_sha256(
            json.dumps({"sessionId": "container-like-fallback", "auth_token": {"token": "secret"}})
        )


def test_discovery_requires_external_exact_nine_entry_and_missing_evidence_bindings(tmp_path: Path) -> None:
    short_discovery, _ = _write_discovery(tmp_path / "short", 8)
    with pytest.raises(SourceWheelProofError, match="^discovery_input_invalid$"):
        load_private_discovery_input(_config(short_discovery, tmp_path / "short-output"))

    discovery, _ = _write_discovery(tmp_path / "exact", 9)
    config = _config(discovery, tmp_path / "exact-output")
    payload = json.loads(discovery.read_bytes())
    payload["missing_required_evidence"].append("unexpected-evidence-field")
    discovery.write_bytes(canonical_json(payload) + b"\n")
    discovery.chmod(0o600)
    with pytest.raises(SourceWheelProofError, match="^discovery_input_invalid$"):
        load_private_discovery_input(replace(config, input_sha256=sha256_bytes(discovery.read_bytes())))
    with pytest.raises(SourceWheelProofError, match="^expected_entry_count_invalid$"):
        replace(config, expected_entry_count=8).validate()


def test_reproducibility_and_concurrency_contracts_fail_closed(tmp_path: Path) -> None:
    wheel_a = _wheel_file("proof-package", "1.0")
    wheel_b = wheel_a + b"different"
    evidence = (inspect_wheel("proof_package-1.0-py3-none-any.whl", wheel_a),)
    first = BuildResult(
        wheels={evidence[0].filename: wheel_a},
        wheel_evidence=evidence,
        closure=(("proof-package", "1.0"),),
        wheelhouse=pack_wheelhouse({evidence[0].filename: wheel_a}),
        input_artifacts=(("proof_package-1.0.tar.gz", 1, "a" * 64),),
        build_argv_sha256="b" * 64,
    )
    second = replace(
        first,
        wheels={evidence[0].filename: wheel_b},
        wheelhouse=pack_wheelhouse({evidence[0].filename: wheel_b}),
    )
    with pytest.raises(SourceWheelProofError, match="^cross_builder_reproducibility_failed$"):
        compare_build_payloads(first, second)

    discovery, _ = _write_discovery(tmp_path, 1)
    with pytest.raises(SourceWheelProofError, match="^entry_concurrency_invalid$"):
        _config(discovery, tmp_path / "proof", max_concurrent_entries=4).validate()
    with pytest.raises(SourceWheelProofError, match="^base_runtime_revision_invalid$"):
        _config(discovery, tmp_path / "proof", base_runtime_commit="f" * 40).validate()
    with pytest.raises(SourceWheelProofError, match="^vacli_retry_invalid$"):
        _config(discovery, tmp_path / "proof", vacli_lease_retries=2).validate()
    with pytest.raises(
        SourceWheelProofError,
        match="^vacli_lease_concurrency_exceeds_runtime_cap$",
    ):
        _config(
            discovery,
            tmp_path / "proof",
            max_concurrent_entries=1,
            vacli_max_concurrent_leases=4,
        ).validate()


def test_hard_cap_runs_three_entries_with_at_most_nine_live_runtimes(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    fleet = FakeFleet(artifacts)
    config = _config(
        discovery,
        tmp_path / "proof",
        max_concurrent_entries=3,
        vacli_max_concurrent_leases=9,
    )

    result = asyncio.run(run_source_wheel_proof(config, runtime_factory=fleet.factory))

    assert result["runtime_starts"] == 27
    assert result["peak_live_runtimes"] == 9
    assert result["peak_concurrent_entries"] == 3
    assert fleet.peak_live == 9


def test_vacli_environment_and_binary_are_exactly_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, _ = _write_discovery(tmp_path, 1)
    binary = tmp_path / "vacli"
    binary.write_bytes(b"pinned-runtime")
    binary.chmod(0o700)
    for name, value in {
        "VACLI_BIN": str(binary),
        "VACLI_LEASE_RETRIES": "1",
        "VACLI_MAX_CONCURRENT_LEASES": "6",
        "VACLI_MAX_PULL_RETRIES": "20",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": "3600",
        "VACLI_CONTAINER_PRIVILEGED": "1",
    }.items():
        monkeypatch.setenv(name, value)
    config = _config(
        discovery,
        tmp_path / "proof",
        vacli_path=binary,
        vacli_binary_sha256=sha256_bytes(binary.read_bytes()),
    )

    validate_vacli_environment(config)
    binary.write_bytes(b"changed-runtime")
    with pytest.raises(SourceWheelProofError, match="^vacli_binary_invalid$"):
        validate_vacli_environment(config)


def test_execution_environment_rejects_tool_site_and_inherited_python_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, _ = _write_discovery(tmp_path / "input", 9)
    project = (tmp_path / "project").resolve()
    launcher = project / "user/tianhaowu/terminal_bench_vmvm/run_source_wheel_proof.sbatch"
    vmvm_source = project / "environments/vmvm_tb_v2/vmvm_tb_v2/_vacli"
    site_packages = (tmp_path / "site-packages").resolve()
    launcher.parent.mkdir(parents=True)
    vmvm_source.mkdir(parents=True)
    site_packages.mkdir()
    launcher.write_bytes(b"pinned launcher\n")
    (vmvm_source / "backend.py").write_bytes(b"pinned runtime\n")
    (site_packages / "dependency.py").write_bytes(b"pinned dependency\n")
    for relative in ("deps/verifiers", "deps/renderers", "deps/pydantic-config"):
        dependency = project / relative
        dependency.mkdir(parents=True)
        (dependency / ".git").write_text("gitdir: synthetic\n")
    (project / "deps/pydantic-config/src").mkdir()
    uv_path = tmp_path / "uv"
    vacli_path = tmp_path / "vacli"
    for path, payload in ((uv_path, b"pinned uv\n"), (vacli_path, b"pinned vacli\n")):
        path.write_bytes(payload)
        path.chmod(0o700)
    python_path = Path(sys.executable).resolve()
    python_stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    config = replace(
        _config(discovery, tmp_path / "proof"),
        project_dir=project,
        canonical_launcher_path=launcher,
        executed_launcher_path=launcher,
        uv_path=uv_path.resolve(),
        python_path=python_path,
        python_stdlib_path=python_stdlib,
        site_packages_path=site_packages,
        vacli_path=vacli_path.resolve(),
        launcher_sha256=sha256_bytes(launcher.read_bytes()),
        uv_sha256=sha256_bytes(uv_path.read_bytes()),
        python_sha256=sha256_bytes(python_path.read_bytes()),
        python_runtime_manifest_sha256="9" * 64,
        site_packages_manifest_sha256=proof_bootstrap.canonical_tree_manifest_sha256(site_packages),
        vmvm_tb_v2_sha256=proof_bootstrap.python_sources_sha256(vmvm_source),
        vacli_binary_sha256=sha256_bytes(vacli_path.read_bytes()),
    )
    dependency_commits = {
        "deps/verifiers": config.verifiers_commit,
        "deps/renderers": config.renderers_commit,
        "deps/pydantic-config": config.pydantic_config_commit,
    }

    def fake_git(path: Path, *arguments: str) -> str:
        if arguments == ("rev-parse", "--verify", "HEAD"):
            if path == project:
                return config.source_commit
            return dependency_commits[str(path.relative_to(project))]
        if arguments == ("rev-parse", "--verify", "HEAD^{tree}"):
            return config.source_git_tree
        if arguments[0] == "status":
            return ""
        if arguments[0] == "merge-base":
            return config.base_runtime_commit
        if arguments[:2] == ("ls-tree", "HEAD"):
            relative = arguments[2]
            return f"160000 commit {dependency_commits[relative]}\t{relative}"
        raise AssertionError("unexpected Git probe")

    monkeypatch.setattr(proof_bootstrap, "git_output", fake_git)
    monkeypatch.setattr(proof_bootstrap, "_validate_bootstrap_flags", lambda: None)
    for name in tuple(os.environ):
        if name.startswith("PYTHON"):
            monkeypatch.delenv(name, raising=False)
    for name in ("VIRTUAL_ENV", "CONDA_PREFIX", "LD_PRELOAD", "LD_LIBRARY_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    monkeypatch.setenv("VACLI_BIN", str(vacli_path.resolve()))
    import_roots = proof_bootstrap.expected_import_roots(project, site_packages)
    zip_path = python_stdlib.parent / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    stdlib_sys_path = [str(zip_path), str(python_stdlib)]
    lib_dynload = python_stdlib / "lib-dynload"
    if lib_dynload.is_dir():
        stdlib_sys_path.append(str(lib_dynload))
    monkeypatch.setattr(sys, "path", [*(str(path) for path in import_roots), *stdlib_sys_path])
    bindings = proof_bootstrap.ExecutionBindings(
        **{field: getattr(config, field) for field in proof_bootstrap.ExecutionBindings.__dataclass_fields__}
    )
    runtime_manifest = proof_bootstrap.python_runtime_manifest_sha256(
        python_path,
        python_stdlib,
        import_roots,
        proof_bootstrap._import_root_bindings(bindings, import_roots),
    )
    config = replace(config, python_runtime_manifest_sha256=runtime_manifest)
    bindings = replace(bindings, python_runtime_manifest_sha256=runtime_manifest)
    monkeypatch.setenv(
        proof_bootstrap.BOOTSTRAP_ATTESTATION_ENV,
        proof_bootstrap.bootstrap_attestation_sha256(bindings, runtime_manifest),
    )

    validate_execution_environment(config)
    noncanonical_launchers = {
        "copied": tmp_path / "copied_launcher.sbatch",
        "symlinked": tmp_path / "symlinked_launcher.sbatch",
        "spooled": tmp_path / "slurm_spool" / "job_script",
    }
    noncanonical_launchers["copied"].write_bytes(launcher.read_bytes())
    noncanonical_launchers["copied"].chmod(0o600)
    noncanonical_launchers["symlinked"].symlink_to(launcher)
    noncanonical_launchers["spooled"].parent.mkdir()
    noncanonical_launchers["spooled"].write_bytes(launcher.read_bytes())
    noncanonical_launchers["spooled"].chmod(0o600)
    for noncanonical_launcher in noncanonical_launchers.values():
        with pytest.raises(SourceWheelProofError, match="^execution_binding_invalid$"):
            validate_execution_environment(replace(config, executed_launcher_path=noncanonical_launcher))
    for field in ("launcher_sha256", "uv_sha256", "python_sha256", "vacli_binary_sha256"):
        with pytest.raises(SourceWheelProofError, match="^execution_tool_sha256_mismatch$"):
            validate_execution_environment(replace(config, **{field: "a" * 64}))
    with pytest.raises(SourceWheelProofError, match="^python_runtime_manifest_mismatch$"):
        validate_execution_environment(replace(config, python_runtime_manifest_sha256="a" * 64))
    with pytest.raises(SourceWheelProofError, match="^site_packages_manifest_mismatch$"):
        validate_execution_environment(replace(config, site_packages_manifest_sha256="a" * 64))
    with pytest.raises(SourceWheelProofError, match="^vmvm_runtime_source_mismatch$"):
        validate_execution_environment(replace(config, vmvm_tb_v2_sha256="a" * 64))
    monkeypatch.setenv("PYTHONHOME", "/untrusted")
    with pytest.raises(SourceWheelProofError, match="^execution_environment_not_sanitized$"):
        validate_execution_environment(config)
    monkeypatch.delenv("PYTHONHOME")
    (site_packages / "dependency.py").write_bytes(b"changed dependency\n")
    with pytest.raises(SourceWheelProofError, match="^site_packages_manifest_mismatch$"):
        validate_execution_environment(config)


def test_resume_requires_exact_external_state_hash(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    result = asyncio.run(
        run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory)
    )
    assert result["runtime_starts"] == 27

    resumed = _config(
        discovery,
        output,
        resume_state_sha256="d" * 64,
        slurm_job_id="12346",
    )
    with pytest.raises(SourceWheelProofError, match="^resume_state_sha256_mismatch$"):
        asyncio.run(run_source_wheel_proof(resumed, runtime_factory=FakeFleet(artifacts).factory))


def test_resume_revalidates_completed_entries_and_runs_only_missing_work(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    output = tmp_path / "proof"
    initial_config = _config(
        discovery,
        output,
        max_concurrent_entries=1,
        vacli_max_concurrent_leases=3,
    )
    parsed, _ = load_private_discovery_input(initial_config)
    initial_fleet = FakeFleet(artifacts)
    with ProofStore(initial_config, parsed) as store:
        runner = SourceWheelProofRunner(
            initial_config,
            parsed,
            store._journal(),
            runtime_factory=initial_fleet.factory,
        )
        key, proof = asyncio.run(runner._prove_entry(parsed.entries[0]))
        store.publish_entry(
            key,
            proof,
            {
                **runner.telemetry.as_dict(),
                "peak_concurrent_entries": runner.peak_entries,
            },
        )

    assert initial_fleet.start_count == 3
    state_path = output / "proof_state.json"
    resumed_fleet = FakeFleet(artifacts)
    config = _config(
        discovery,
        output,
        resume_state_sha256=sha256_bytes(state_path.read_bytes()),
        slurm_job_id="12346",
        max_concurrent_entries=1,
        vacli_max_concurrent_leases=3,
    )

    result = asyncio.run(run_source_wheel_proof(config, runtime_factory=resumed_fleet.factory))

    assert result["runtime_starts"] == 27
    assert resumed_fleet.start_count == 24
    assert len(json.loads((output / "source_wheel_policy.json").read_bytes())["entries"]) == 9


def test_readme_uses_exact_clean_tmux_wrap_launcher_form() -> None:
    workflow = Path(__file__).resolve().parents[1]
    readme = (workflow / "README.md").read_text()
    launcher = (workflow / "run_source_wheel_proof.sbatch").read_text()

    assert "tmux send-keys -t source-wheel-proof" in readme
    assert '"/usr/bin/env -i PATH=/usr/bin:/bin' in readme
    assert "/usr/bin/sbatch --parsable --export=ALL" in readme
    assert (
        "--wrap='exec /bin/bash --noprofile --norc "
        "/path/to/clean-reviewed-checkout/user/tianhaowu/terminal_bench_vmvm/"
        "run_source_wheel_proof.sbatch'\" C-m"
    ) in readme
    assert 'exec "$python_bin" -I -S -B' in launcher
    assert '"$workflow_dir/source_wheel_proof_bootstrap.py" run' in launcher
    assert "SOURCE_WHEEL_PROOF_CONTINUE_ON_SOURCE_BUILD_FAILURE" in launcher
    assert "args+=(--continue-on-source-build-failure)" in launcher
    assert "Source-build diagnostics require a fresh output root" in launcher
    assert "uv run --no-project" not in launcher
    for rejected in ("BASH_ENV", "LD_PRELOAD"):
        assert rejected in (launcher + readme)
    assert "declare -F" in launcher


def test_bootstrap_requires_isolated_no_site_python_before_import_roots() -> None:
    bootstrap = Path(__file__).resolve().parents[1] / "source_wheel_proof_bootstrap.py"
    probe = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("proof_bootstrap_probe", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    module._validate_bootstrap_flags()
except module.BindingError:
    raise SystemExit(17)
raise SystemExit(0)
"""
    clean_environment = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "/untrusted/import/root"}

    isolated = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", probe, str(bootstrap)],
        check=False,
        capture_output=True,
        env=clean_environment,
    )
    unsafe = subprocess.run(
        [sys.executable, "-S", "-B", "-c", probe, str(bootstrap)],
        check=False,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert isolated.returncode == 0
    assert unsafe.returncode == 17


def test_execution_validation_precedes_private_input_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 9)
    fleet = FakeFleet(artifacts)
    factory = fleet.factory
    private_input_loaded = False

    def reject_environment(_: SourceWheelProofConfig) -> None:
        raise SourceWheelProofError("synthetic_pre_import_rejection")

    def observe_private_input(_: SourceWheelProofConfig) -> None:
        nonlocal private_input_loaded
        private_input_loaded = True
        raise AssertionError("private input loaded before environment validation")

    monkeypatch.setattr(source_wheel_proof, "_runtime_factory", factory)
    monkeypatch.setattr(source_wheel_proof, "validate_execution_environment", reject_environment)
    monkeypatch.setattr(source_wheel_proof, "load_private_discovery_input", observe_private_input)

    with pytest.raises(SourceWheelProofError, match="^synthetic_pre_import_rejection$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(discovery, tmp_path / "proof"),
                runtime_factory=factory,
            )
        )
    assert private_input_loaded is False
    assert fleet.start_count == 0
