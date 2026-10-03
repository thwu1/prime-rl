import hashlib
from pathlib import Path
from types import SimpleNamespace
from weakref import WeakKeyDictionary

import pytest
from verifiers.v1.runtimes import ProgramResult

import terminal_bench_vmvm.taskset as taskset_module
from terminal_bench_vmvm.offline_verifier_catalog import CatalogIdentity, RuntimeFingerprint
from terminal_bench_vmvm.source_wheels import canonical_json
from terminal_bench_vmvm.taskset import (
    CatalogPrefetchedTestDependencies,
    TerminalBenchVMVMTaskset,
)


def _digest(payload: bytes | str) -> str:
    if isinstance(payload, str):
        payload = payload.encode()
    return hashlib.sha256(payload).hexdigest()


def _fingerprint_payload() -> tuple[RuntimeFingerprint, str]:
    marker = {"python_version": "3.12", "sys_platform": "linux"}
    tags = ["py3-none-any"]
    record = {
        "schema_version": 1,
        "implementation": "cpython",
        "python_full_version": "3.12.8",
        "abi": "cpython-312-x86_64-linux-gnu",
        "platform": "linux-x86_64",
        "machine": "x86_64",
        "libc": "glibc-2.36",
        "pip_version": "24.3.1",
        "marker_environment": marker,
        "supported_tags": tags,
    }
    return RuntimeFingerprint.from_probe_payload(canonical_json(record)), canonical_json(record).decode()


class _Seal:
    def __init__(self) -> None:
        self.reads = 0

    def read_verified(self, *_args, **_kwargs) -> bytes:
        self.reads += 1
        return b"sealed"


class _Plan:
    def __init__(self, guarantee: str, closure: tuple[tuple[str, str], ...]) -> None:
        self.guarantee = guarantee
        self.closure = closure
        self.revalidations = 0

    def revalidate(self) -> None:
        self.revalidations += 1

    def read_verified_archive(self) -> bytes:
        return b"archive"

    def install_request_payload(self, wheel_directory: str) -> bytes:
        return f"{wheel_directory}/root_pkg.whl --hash=sha256:{'1' * 64}\n".encode()

    def probe_control_payload(self, site_directory: str | None) -> bytes:
        return canonical_json(
            {
                "schema_version": 1,
                "site_directory": site_directory,
                "requirements": ["root-pkg==1.0.0"] if self.closure else [],
                "inventory": [list(item) for item in self.closure],
                "inventory_sha256": "2" * 64,
                "closure": [list(item) for item in self.closure],
                "closure_sha256": "2" * 64,
            }
        )


class _Runtime:
    def __init__(self, image: str, fingerprint_payload: str = "") -> None:
        self.config = SimpleNamespace(image=image)
        self.fingerprint_payload = fingerprint_payload
        self.commands: list[tuple[list[str], dict[str, str]]] = []
        self.writes: list[tuple[str, bytes]] = []

    async def run(self, argv: list[str], environment: dict[str, str]) -> ProgramResult:
        self.commands.append((argv, environment))
        if argv[:2] == ["python3", "-c"]:
            return ProgramResult(exit_code=0, stdout=self.fingerprint_payload, stderr="")
        if argv[:4] == ["python3", "-m", "pip", "install"]:
            return ProgramResult(exit_code=0, stdout="", stderr="")
        count = 1 if "root-pkg" in "".join(payload.decode(errors="ignore") for _, payload in self.writes) else 0
        return ProgramResult(
            exit_code=0,
            stdout=canonical_json({"count": count, "status": "ok"}).decode() + "\n",
            stderr="",
        )

    async def write(self, path: str, payload: bytes) -> None:
        self.writes.append((path, payload))


@pytest.mark.asyncio
async def test_prefetch_resolves_actual_shared_runtime_binding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fingerprint, payload = _fingerprint_payload()
    image = f"registry.invalid/image@sha256:{'3' * 64}"
    runtime = _Runtime(image, payload)
    monkeypatch.setattr(taskset_module, "SandoqRuntime", _Runtime)
    plan = _Plan("wheelhouse", (("root-pkg", "1.0.0"),))

    class Catalog:
        identity = SimpleNamespace(requirements_extractor_sha256=taskset_module.offline_requirements_extractor_sha256())

        def resolve(self, *args):
            assert args == ("opaque", "shared-agent", image, ("root-pkg==1.0.0",), fingerprint)
            return plan

    selection = tmp_path / "selection"
    selection.write_text("opaque\n")
    seal = _Seal()
    taskset = TerminalBenchVMVMTaskset.__new__(TerminalBenchVMVMTaskset)
    taskset.config = SimpleNamespace(
        offline_verifier_catalog=tmp_path / "catalog.json",
        offline_verifier_catalog_task_file=selection,
    )
    taskset._offline_verifier_catalog = Catalog()
    taskset._offline_verifier_selection_seal = seal
    taskset._prefetched_test_dependencies = WeakKeyDictionary()
    taskset._test_requirements = lambda _task: ("root-pkg==1.0.0",)
    task = SimpleNamespace(
        verifier_mode="shared",
        image=image,
        verifier_image=None,
        verifier_tests_baked=False,
        slug="opaque",
    )
    await taskset._prefetch_test_dependencies(task, runtime)
    prefetched = taskset._prefetched_test_dependencies[runtime]
    assert isinstance(prefetched, CatalogPrefetchedTestDependencies)
    assert prefetched.plan is plan
    assert seal.reads == 1


@pytest.mark.asyncio
async def test_wheelhouse_activation_is_offline_hashed_and_closure_probed() -> None:
    image = f"registry.invalid/image@sha256:{'3' * 64}"
    runtime = _Runtime(image)
    plan = _Plan("wheelhouse", (("root-pkg", "1.0.0"),))
    prefetched = CatalogPrefetchedTestDependencies(
        task_key="opaque",
        runtime_role="shared-agent",
        image=image,
        requirements=("root-pkg==1.0.0",),
        plan=plan,
    )
    taskset = TerminalBenchVMVMTaskset.__new__(TerminalBenchVMVMTaskset)

    async def run_root(_runtime, _command):
        return ProgramResult(exit_code=0, stdout="", stderr="")

    taskset._run_root = run_root
    overlay = await taskset._install_catalog_test_dependencies(
        SimpleNamespace(name="opaque"),
        runtime,
        prefetched,
    )
    assert overlay is not None
    install = next((argv, env) for argv, env in runtime.commands if argv[:4] == ["python3", "-m", "pip", "install"])
    assert "--no-index" in install[0]
    assert "--require-hashes" in install[0]
    assert install[1]["PIP_NO_INDEX"] == "1"
    assert plan.revalidations >= 2


@pytest.mark.asyncio
async def test_image_inventory_is_revalidated_after_remote_probe() -> None:
    image = f"registry.invalid/image@sha256:{'3' * 64}"
    runtime = _Runtime(image)
    plan = _Plan("image-inventory", ())
    prefetched = CatalogPrefetchedTestDependencies(
        task_key="opaque",
        runtime_role="shared-agent",
        image=image,
        requirements=(),
        plan=plan,
    )
    taskset = TerminalBenchVMVMTaskset.__new__(TerminalBenchVMVMTaskset)

    async def run_root(_runtime, _command):
        return ProgramResult(exit_code=0, stdout="", stderr="")

    taskset._run_root = run_root
    overlay = await taskset._install_catalog_test_dependencies(
        SimpleNamespace(name="opaque"),
        runtime,
        prefetched,
    )
    assert overlay is None
    assert plan.revalidations >= 3


def test_full_binding_plan_preflight_precedes_stage_subset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selection_root = tmp_path / "selection-root"
    selection_root.mkdir(mode=0o700)
    selection = selection_root / "tasks.txt"
    selection.write_text("opaque-a\nopaque-b\n")
    selection.chmod(0o400)
    selection_sha256 = _digest(selection.read_bytes())
    project = tmp_path / "project"
    dataset = tmp_path / "dataset"
    project.mkdir()
    dataset.mkdir()
    identity = CatalogIdentity(
        dataset_revision="1" * 40,
        task_selection_sha256=selection_sha256,
        expected_task_count=2,
        binding_plan_sha256="2" * 64,
        catalog_consumer_code_sha256="3" * 64,
        image_manifest_sha256="4" * 64,
        requirements_extractor_sha256="5" * 64,
        inventory_probe_code_sha256="6" * 64,
        inventory_probe_environment_sha256="7" * 64,
        inventory_probe_approval_sha256="8" * 64,
        source_policy_sha256="9" * 64,
        source_policy_approval_sha256="a" * 64,
        approved_binary_artifacts_sha256="b" * 64,
        approved_source_attestations_sha256="c" * 64,
        approved_toolchains_sha256="d" * 64,
    )
    image_a = f"registry.invalid/a@sha256:{'a' * 64}"
    image_b = f"registry.invalid/b@sha256:{'b' * 64}"
    full_tasks = [
        SimpleNamespace(
            slug="opaque-a",
            verifier_mode="separate",
            verifier_image=image_a,
            verifier_network_mode="no-network",
            verifier_tests_baked=True,
        ),
        SimpleNamespace(
            slug="opaque-b",
            verifier_mode="separate",
            verifier_image=image_b,
            verifier_network_mode="no-network",
            verifier_tests_baked=True,
        ),
    ]

    class Config(SimpleNamespace):
        def model_copy(self, *, update):
            values = vars(self).copy()
            values.update(update)
            return Config(**values)

    config = Config(
        offline_verifier_catalog=selection_root / "catalog.json",
        offline_verifier_catalog_sha256="e" * 64,
        offline_verifier_catalog_identity=SimpleNamespace(catalog_identity=lambda: identity),
        offline_verifier_catalog_task_file=selection,
        offline_verifier_catalog_task_file_sha256=selection_sha256,
        offline_verifier_project_root=project,
        dataset_revision=identity.dataset_revision,
        image_manifest_sha256=identity.image_manifest_sha256,
        tasks=["stage-subset"],
        task_file=tmp_path / "stage.txt",
        task_file_sha256="f" * 64,
    )

    class Harness(TerminalBenchVMVMTaskset):
        def __init__(self, nested_config) -> None:
            self.config = nested_config

        def load_tasks(self):
            assert self.config.task_file is None
            assert self.config.task_file_sha256 is None
            assert self.config.tasks == ["opaque-a", "opaque-b"]
            return full_tasks

    class Receipt:
        tasks = 2
        uncovered = 0

        @staticmethod
        def to_public_dict():
            return {"contract_version": 1, "status": "ready", "counts": {"tasks": 2, "uncovered": 0}}

    class Catalog:
        def preflight(self, bindings, *, expected_task_count):
            assert len(bindings) == 2
            assert expected_task_count == 2
            observed = sorted(
                (binding.task_key, binding.runtime_role, binding.image, binding.requirements) for binding in bindings
            )
            assert observed == [
                ("opaque-a", "separate-verifier", image_a, ()),
                ("opaque-b", "separate-verifier", image_b, ()),
            ]
            return Receipt()

    monkeypatch.setattr(
        taskset_module, "offline_requirements_extractor_sha256", lambda: identity.requirements_extractor_sha256
    )
    monkeypatch.setattr(
        taskset_module, "OfflineVerifierCatalog", SimpleNamespace(load=lambda *_args, **_kwargs: Catalog())
    )
    taskset = Harness(config)
    taskset._offline_verifier_catalog = None
    taskset._offline_verifier_catalog_receipt = None
    taskset._offline_verifier_selection_seal = None
    taskset._preflight_offline_verifier_catalog(dataset.resolve(), [full_tasks[0]])
    assert taskset._offline_verifier_catalog is not None
    assert taskset.offline_verifier_catalog_receipt["counts"]["tasks"] == 2
