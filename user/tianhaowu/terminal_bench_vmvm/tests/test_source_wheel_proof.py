from __future__ import annotations

import asyncio
import hashlib
import io
import json
import stat
import tarfile
from dataclasses import dataclass, replace
from pathlib import Path
from zipfile import ZipFile

import pytest
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
    SourceWheelProofConfig,
    SourceWheelProofError,
    aggregate_failure,
    compare_build_payloads,
    run_source_wheel_proof,
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
    config = SourceWheelProofConfig(
        input_path=discovery,
        input_sha256=sha256_bytes(discovery.read_bytes()),
        output_dir=output,
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
    ) -> None:
        self.artifacts = artifacts
        self.block_builds = block_builds
        self.block_starts = block_starts
        self.duplicate_descriptors = duplicate_descriptors
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
        self.descriptor = "duplicate-lease" if fleet.duplicate_descriptors else f"lease-{name}"
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
    assert proof["source"]["vacli_binary_sha256"] == "f" * 64
    assert proof["source_wheel_policy_sha256"] == sha256_bytes((output / "source_wheel_policy.json").read_bytes())
    assert len(policy["entries"]) == 9
    assert all(entry["build_tools"] == BUILD_TOOLS for entry in policy["entries"])
    assert all(len(entry["binary_wheels"]) == 1 for entry in policy["entries"])
    assert all(entry["cross_builder"]["wheel_bytes_equal"] for entry in proof["entries"])
    assert all(len(set(entry["lease_identity_sha256s"].values())) == 3 for entry in proof["entries"])
    assert len({digest for entry in proof["entries"] for digest in entry["lease_identity_sha256s"].values()}) == 27
    assert b"lease-source-proof" not in (output / "source_wheel_proof.json").read_bytes()

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


def test_cancellation_stops_every_started_runtime_and_leaves_resumable_state(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 1)
    output = tmp_path / "proof"

    async def scenario() -> FakeFleet:
        fleet = FakeFleet(artifacts, block_builds=True)
        proof = asyncio.create_task(run_source_wheel_proof(_config(discovery, output), runtime_factory=fleet.factory))
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


def test_cancellation_drains_runtime_start_before_stopping_leases(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 1)

    async def scenario() -> FakeFleet:
        fleet = FakeFleet(artifacts, block_starts=True)
        proof = asyncio.create_task(
            run_source_wheel_proof(
                _config(discovery, tmp_path / "proof"),
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
    discovery, artifacts = _write_discovery(tmp_path, 1)
    fleet = FakeFleet(artifacts, duplicate_descriptors=True)

    with pytest.raises(SourceWheelProofError, match="^runtime_lease_identity_duplicate$"):
        asyncio.run(
            run_source_wheel_proof(
                _config(discovery, tmp_path / "proof"),
                runtime_factory=fleet.factory,
            )
        )

    assert fleet.start_count == 3
    assert fleet.live == 0
    assert all(runtime.stopped for runtime in fleet.runtimes)


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
    discovery, artifacts = _write_discovery(tmp_path, 3)
    fleet = FakeFleet(artifacts)
    config = _config(
        discovery,
        tmp_path / "proof",
        max_concurrent_entries=3,
        vacli_max_concurrent_leases=9,
    )

    result = asyncio.run(run_source_wheel_proof(config, runtime_factory=fleet.factory))

    assert result["runtime_starts"] == 9
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
        "VACLI_LEASE_RETRIES": "20",
        "VACLI_MAX_CONCURRENT_LEASES": "6",
        "VACLI_MAX_PULL_RETRIES": "20",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": "3600",
        "VACLI_CONTAINER_PRIVILEGED": "1",
    }.items():
        monkeypatch.setenv(name, value)
    config = _config(
        discovery,
        tmp_path / "proof",
        vacli_binary_sha256=sha256_bytes(binary.read_bytes()),
    )

    validate_vacli_environment(config)
    binary.write_bytes(b"changed-runtime")
    with pytest.raises(SourceWheelProofError, match="^vacli_binary_invalid$"):
        validate_vacli_environment(config)


def test_resume_requires_exact_external_state_hash(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 1)
    output = tmp_path / "proof"
    result = asyncio.run(
        run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory)
    )
    assert result["runtime_starts"] == 3

    resumed = _config(
        discovery,
        output,
        resume_state_sha256="d" * 64,
        slurm_job_id="12346",
    )
    with pytest.raises(SourceWheelProofError, match="^resume_state_sha256_mismatch$"):
        asyncio.run(run_source_wheel_proof(resumed, runtime_factory=FakeFleet(artifacts).factory))


def test_resume_revalidates_completed_entries_and_runs_only_missing_work(tmp_path: Path) -> None:
    discovery, artifacts = _write_discovery(tmp_path, 3)
    output = tmp_path / "proof"
    asyncio.run(run_source_wheel_proof(_config(discovery, output), runtime_factory=FakeFleet(artifacts).factory))

    (output / "source_wheel_policy.json").unlink()
    (output / "source_wheel_proof.json").unlink()
    state_path = output / "proof_state.json"
    state = json.loads(state_path.read_bytes())
    state_path.chmod(0o600)
    state["completed"].pop(next(iter(state["completed"])))
    state["telemetry"]["attested_runtime_starts"] = 6
    state_path.write_bytes(canonical_json(state) + b"\n")
    state_path.chmod(0o600)
    resumed_fleet = FakeFleet(artifacts)
    config = _config(
        discovery,
        output,
        resume_state_sha256=sha256_bytes(state_path.read_bytes()),
        slurm_job_id="12346",
    )

    result = asyncio.run(run_source_wheel_proof(config, runtime_factory=resumed_fleet.factory))

    assert result["runtime_starts"] == 9
    assert resumed_fleet.start_count == 3
    assert len(json.loads((output / "source_wheel_policy.json").read_bytes())["entries"]) == 3
