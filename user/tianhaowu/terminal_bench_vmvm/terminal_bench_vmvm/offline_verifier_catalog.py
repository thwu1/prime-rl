"""Fail-closed offline verifier dependency catalogs.

The catalog is private launch input.  It binds every selected task to one
immutable image, one ordered exact-requirement set, and one statically proven
dependency path: either an immutable-image inventory attestation or a
content-addressed wheelhouse.  Runtime probes may revalidate that proof, but
they never create coverage dynamically.

Catalog directories are deliberately simple::

    catalog.json
    inventories/sha256/ab/<sha256>.json
    manifests/sha256/ab/<sha256>.json
    archives/sha256/ab/<sha256>.tar

The catalog root and every subdirectory must be mode 0700.  Files must be
regular, single-link, mode 0400 or 0600 files.  Paths in the JSON are not
accepted; artifact paths are derived from their content digests.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import sys
import sysconfig
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Iterable, Literal, Mapping, Sequence

try:
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import parse_wheel_filename
except ModuleNotFoundError:  # pragma: no cover - exercised inside minimal verifier images.
    from pip._vendor.packaging.requirements import InvalidRequirement, Requirement
    from pip._vendor.packaging.utils import parse_wheel_filename

from terminal_bench_vmvm.source_wheels import (
    MAX_WHEELHOUSE_BYTES,
    WheelEvidence,
    canonical_distribution_name,
    canonical_json,
    inspect_wheel_requirements,
    inspect_wheelhouse,
    is_digest_pinned_image,
    pack_wheelhouse,
    strict_json_loads,
)

CATALOG_SCHEMA_VERSION = 1
WHEELHOUSE_MANIFEST_SCHEMA_VERSION = 1
IMAGE_INVENTORY_SCHEMA_VERSION = 1
RUNTIME_FINGERPRINT_SCHEMA_VERSION = 1
PUBLIC_RECEIPT_CONTRACT_VERSION = 1
RUNTIME_STAGING_ROOT = PurePosixPath("/tmp/terminal-bench-offline-verifier")

MAX_CATALOG_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_TASKS = 100_000
MAX_REQUIREMENT_SETS = 100_000
MAX_REQUIREMENTS_PER_SET = 256
MAX_REQUIREMENT_BYTES = 1_024
MAX_TASK_KEY_BYTES = 512
MAX_TEXT_EVIDENCE_BYTES = 1_024
MAX_RUNTIME_PROBE_BYTES = 4 * 1024 * 1024
MAX_RUNTIME_TAGS = 16_384
MAX_MARKER_ENVIRONMENT_KEYS = 128

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REVISION_RE = re.compile(r"[0-9a-f]{40}")
_TASK_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_EXACT_REQUIREMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_-]+")
_SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")


class OfflineCatalogError(RuntimeError):
    """An aggregate-safe catalog validation failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise OfflineCatalogError(code)
    raise OfflineCatalogError(code) from error


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_path_descriptors(path: Path) -> list[int]:
    if (
        not path.is_absolute()
        or path.parent == path
        or ".." in path.parts
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in path.as_posix())
    ):
        _fail("verified_source_invalid")
    descriptors: list[int] = []
    try:
        current = os.open(
            "/",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptors.append(current)
        for part in path.parts[1:-1]:
            current = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            descriptors.append(current)
        descriptors.append(
            os.open(
                path.parts[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
        )
    except OSError as error:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        _fail("verified_source_invalid", error)
    return descriptors


def _source_descriptor_identity(status: os.stat_result, *, directory: bool) -> tuple[int, ...]:
    if (directory and not stat.S_ISDIR(status.st_mode)) or (
        not directory and (not stat.S_ISREG(status.st_mode) or status.st_nlink != 1)
    ):
        _fail("verified_source_invalid")
    common = (status.st_dev, status.st_ino, status.st_mode, status.st_uid)
    if directory:
        return common
    return (*common, status.st_nlink, status.st_size, status.st_mtime_ns, status.st_ctime_ns)


def _reject_source_bytecode(parent_descriptor: int) -> None:
    try:
        os.stat("__pycache__", dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        _fail("python_bytecode_present", error)
    _fail("python_bytecode_present")


def _verified_source_digest(entries: Sequence[tuple[str, Path]]) -> str:
    if not sys.dont_write_bytecode:
        _fail("python_bytecode_enabled")
    records: list[dict[str, object]] = []
    for name, path in entries:
        descriptors = _source_path_descriptors(path)
        try:
            _reject_source_bytecode(descriptors[-2])
            before = os.fstat(descriptors[-1])
            directory_identities = tuple(
                _source_descriptor_identity(os.fstat(descriptor), directory=True)
                for descriptor in descriptors[:-1]
            )
            source_identity = _source_descriptor_identity(before, directory=False)
            digest = hashlib.sha256()
            while chunk := os.read(descriptors[-1], 1024 * 1024):
                digest.update(chunk)
            after = os.fstat(descriptors[-1])
            if source_identity != _source_descriptor_identity(after, directory=False):
                _fail("verified_source_invalid")
            fresh_descriptors = _source_path_descriptors(path)
            try:
                _reject_source_bytecode(fresh_descriptors[-2])
                fresh_directory_identities = tuple(
                    _source_descriptor_identity(os.fstat(descriptor), directory=True)
                    for descriptor in fresh_descriptors[:-1]
                )
                fresh_source_identity = _source_descriptor_identity(
                    os.fstat(fresh_descriptors[-1]),
                    directory=False,
                )
            finally:
                for descriptor in reversed(fresh_descriptors):
                    os.close(descriptor)
        except OfflineCatalogError:
            raise
        except OSError as error:
            _fail("verified_source_invalid", error)
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
        if directory_identities != fresh_directory_identities or source_identity != fresh_source_identity:
            _fail("verified_source_invalid")
        records.append({"module": name, "sha256": digest.hexdigest(), "size": before.st_size})
    return _sha256(canonical_json({"schema_version": 1, "sources": records}))


def catalog_consumer_code_sha256() -> str:
    """Hash the source-only catalog consumer and reject adjacent bytecode."""

    return _verified_source_digest(
        (
            ("offline_verifier_catalog", Path(__file__)),
            ("source_wheels", Path(inspect_wheelhouse.__code__.co_filename)),
        )
    )


def ordered_requirements_sha256(requirements: Sequence[str]) -> str:
    """Return the canonical digest of an ordered exact-requirement set."""

    validated = _validate_requirements(requirements, "requirements_invalid")
    return _sha256(
        canonical_json(
            {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "requirements": list(validated),
            }
        )
    )


def closure_sha256(distributions: Sequence[Sequence[str]]) -> str:
    """Return the canonical digest of a sorted complete distribution closure."""

    validated = _validate_closure(distributions, "closure_invalid")
    return _sha256(
        canonical_json(
            {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "distributions": [list(item) for item in validated],
            }
        )
    )


def _allowlist_sha256(kind: str, values: Sequence[str]) -> str:
    return _sha256(
        canonical_json(
            {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "kind": kind,
                "values": list(values),
            }
        )
    )


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _exact_keys(value: object, expected: set[str], code: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected or not all(isinstance(key, str) for key in value):
        _fail(code)
    return value


def _bounded_text(value: object, code: str, *, allow_empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not value and not allow_empty)
        or len(value.encode("utf-8")) > MAX_TEXT_EVIDENCE_BYTES
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        _fail(code)
    return value


def _validate_requirements(values: Sequence[object], code: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        _fail(code)
    if len(values) > MAX_REQUIREMENTS_PER_SET:
        _fail(code)
    requirements: list[str] = []
    names: set[str] = set()
    for value in values:
        if (
            not isinstance(value, str)
            or len(value.encode("utf-8")) > MAX_REQUIREMENT_BYTES
            or _EXACT_REQUIREMENT_RE.fullmatch(value) is None
        ):
            _fail(code)
        name = canonical_distribution_name(value.partition("[")[0].partition("==")[0])
        if name in names:
            _fail(code)
        names.add(name)
        requirements.append(value)
    return tuple(requirements)


def _validate_closure(values: Sequence[object], code: str) -> tuple[tuple[str, str], ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        _fail(code)
    closure: list[tuple[str, str]] = []
    for raw in values:
        if (
            isinstance(raw, (str, bytes))
            or not isinstance(raw, Sequence)
            or len(raw) != 2
            or not isinstance(raw[0], str)
            or not isinstance(raw[1], str)
            or canonical_distribution_name(raw[0]) != raw[0]
            or not raw[1]
            or any(character.isspace() for character in raw[1])
        ):
            _fail(code)
        closure.append((raw[0], raw[1]))
    if closure != sorted(closure) or len(closure) != len({name for name, _ in closure}):
        _fail(code)
    return tuple(closure)


@dataclass(frozen=True)
class CatalogIdentity:
    dataset_revision: str
    task_selection_sha256: str
    expected_task_count: int
    binding_plan_sha256: str
    catalog_consumer_code_sha256: str
    image_manifest_sha256: str
    requirements_extractor_sha256: str
    inventory_probe_code_sha256: str
    inventory_probe_environment_sha256: str
    inventory_probe_approval_sha256: str
    source_policy_sha256: str
    source_policy_approval_sha256: str
    approved_binary_artifacts_sha256: str
    approved_source_attestations_sha256: str
    approved_toolchains_sha256: str

    def __post_init__(self) -> None:
        if (
            _REVISION_RE.fullmatch(self.dataset_revision) is None
            or isinstance(self.expected_task_count, bool)
            or not 1 <= self.expected_task_count <= MAX_TASKS
            or not all(
                _is_sha256(value)
                for value in (
                    self.task_selection_sha256,
                    self.binding_plan_sha256,
                    self.catalog_consumer_code_sha256,
                    self.image_manifest_sha256,
                    self.requirements_extractor_sha256,
                    self.inventory_probe_code_sha256,
                    self.inventory_probe_environment_sha256,
                    self.inventory_probe_approval_sha256,
                    self.source_policy_sha256,
                    self.source_policy_approval_sha256,
                    self.approved_binary_artifacts_sha256,
                    self.approved_source_attestations_sha256,
                    self.approved_toolchains_sha256,
                )
            )
        ):
            _fail("catalog_identity_invalid")

    def record(self) -> dict[str, object]:
        return {
            "dataset_revision": self.dataset_revision,
            "task_selection_sha256": self.task_selection_sha256,
            "expected_task_count": self.expected_task_count,
            "binding_plan_sha256": self.binding_plan_sha256,
            "catalog_consumer_code_sha256": self.catalog_consumer_code_sha256,
            "image_manifest_sha256": self.image_manifest_sha256,
            "requirements_extractor_sha256": self.requirements_extractor_sha256,
            "inventory_probe_code_sha256": self.inventory_probe_code_sha256,
            "inventory_probe_environment_sha256": self.inventory_probe_environment_sha256,
            "inventory_probe_approval_sha256": self.inventory_probe_approval_sha256,
            "source_policy_sha256": self.source_policy_sha256,
            "source_policy_approval_sha256": self.source_policy_approval_sha256,
            "approved_binary_artifacts_sha256": self.approved_binary_artifacts_sha256,
            "approved_source_attestations_sha256": self.approved_source_attestations_sha256,
            "approved_toolchains_sha256": self.approved_toolchains_sha256,
        }

    @property
    def sha256(self) -> str:
        return _sha256(canonical_json({"schema_version": CATALOG_SCHEMA_VERSION, **self.record()}))


@dataclass(frozen=True)
class RuntimeFingerprint:
    implementation: str
    python_full_version: str
    abi: str
    platform: str
    machine: str
    libc: str
    pip_version: str
    marker_environment_sha256: str
    supported_tags_sha256: str

    def __post_init__(self) -> None:
        if (
            not all(
                _bounded_text(value, "runtime_fingerprint_invalid")
                for value in (
                    self.implementation,
                    self.python_full_version,
                    self.abi,
                    self.platform,
                    self.machine,
                    self.libc,
                    self.pip_version,
                )
            )
            or not _is_sha256(self.marker_environment_sha256)
            or not _is_sha256(self.supported_tags_sha256)
        ):
            _fail("runtime_fingerprint_invalid")

    def record(self) -> dict[str, object]:
        return {
            "schema_version": RUNTIME_FINGERPRINT_SCHEMA_VERSION,
            "implementation": self.implementation,
            "python_full_version": self.python_full_version,
            "abi": self.abi,
            "platform": self.platform,
            "machine": self.machine,
            "libc": self.libc,
            "pip_version": self.pip_version,
            "marker_environment_sha256": self.marker_environment_sha256,
            "supported_tags_sha256": self.supported_tags_sha256,
        }

    @property
    def sha256(self) -> str:
        return _sha256(canonical_json(self.record()))

    @classmethod
    def from_record(cls, value: object) -> "RuntimeFingerprint":
        raw = _exact_keys(
            value,
            {
                "schema_version",
                "implementation",
                "python_full_version",
                "abi",
                "platform",
                "machine",
                "libc",
                "pip_version",
                "marker_environment_sha256",
                "supported_tags_sha256",
            },
            "runtime_fingerprint_invalid",
        )
        if type(raw["schema_version"]) is not int or raw["schema_version"] != RUNTIME_FINGERPRINT_SCHEMA_VERSION:
            _fail("runtime_fingerprint_invalid")
        return cls(
            implementation=_bounded_text(raw["implementation"], "runtime_fingerprint_invalid"),
            python_full_version=_bounded_text(raw["python_full_version"], "runtime_fingerprint_invalid"),
            abi=_bounded_text(raw["abi"], "runtime_fingerprint_invalid"),
            platform=_bounded_text(raw["platform"], "runtime_fingerprint_invalid"),
            machine=_bounded_text(raw["machine"], "runtime_fingerprint_invalid"),
            libc=_bounded_text(raw["libc"], "runtime_fingerprint_invalid"),
            pip_version=_bounded_text(raw["pip_version"], "runtime_fingerprint_invalid"),
            marker_environment_sha256=str(raw["marker_environment_sha256"]),
            supported_tags_sha256=str(raw["supported_tags_sha256"]),
        )

    @classmethod
    def from_probe_payload(cls, payload: bytes | str) -> "RuntimeFingerprint":
        try:
            if len(payload.encode("utf-8") if isinstance(payload, str) else payload) > MAX_RUNTIME_PROBE_BYTES:
                _fail("runtime_probe_invalid")
            raw = _exact_keys(
                strict_json_loads(payload),
                {
                    "schema_version",
                    "implementation",
                    "python_full_version",
                    "abi",
                    "platform",
                    "machine",
                    "libc",
                    "pip_version",
                    "marker_environment",
                    "supported_tags",
                },
                "runtime_probe_invalid",
            )
            marker_environment = raw["marker_environment"]
            supported_tags = raw["supported_tags"]
            if (
                type(raw["schema_version"]) is not int
                or raw["schema_version"] != RUNTIME_FINGERPRINT_SCHEMA_VERSION
                or not isinstance(marker_environment, dict)
                or not 1 <= len(marker_environment) <= MAX_MARKER_ENVIRONMENT_KEYS
                or not all(
                    isinstance(key, str)
                    and key
                    and len(key.encode("utf-8")) <= MAX_TEXT_EVIDENCE_BYTES
                    and isinstance(value, str)
                    and len(value.encode("utf-8")) <= MAX_TEXT_EVIDENCE_BYTES
                    for key, value in marker_environment.items()
                )
                or not isinstance(supported_tags, list)
                or not 1 <= len(supported_tags) <= MAX_RUNTIME_TAGS
                or not all(isinstance(tag, str) and tag for tag in supported_tags)
                or supported_tags != sorted(set(supported_tags))
            ):
                _fail("runtime_probe_invalid")
            return cls(
                implementation=_bounded_text(raw["implementation"], "runtime_probe_invalid"),
                python_full_version=_bounded_text(raw["python_full_version"], "runtime_probe_invalid"),
                abi=_bounded_text(raw["abi"], "runtime_probe_invalid"),
                platform=_bounded_text(raw["platform"], "runtime_probe_invalid"),
                machine=_bounded_text(raw["machine"], "runtime_probe_invalid"),
                libc=_bounded_text(raw["libc"], "runtime_probe_invalid"),
                pip_version=_bounded_text(raw["pip_version"], "runtime_probe_invalid"),
                marker_environment_sha256=_sha256(canonical_json(marker_environment)),
                supported_tags_sha256=_sha256(canonical_json(supported_tags)),
            )
        except OfflineCatalogError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            _fail("runtime_probe_invalid", error)


@dataclass(frozen=True)
class ExpectedTaskBinding:
    """Expected dependency runtime; ``image`` is never blindly the agent image."""

    task_key: str
    runtime_role: Literal["shared-agent", "separate-verifier"]
    image: str
    requirements: tuple[str, ...]


def _validated_expected_task(
    task: ExpectedTaskBinding,
) -> tuple[str, Literal["shared-agent", "separate-verifier"], str, tuple[str, ...]]:
    if (
        not isinstance(task, ExpectedTaskBinding)
        or not isinstance(task.task_key, str)
        or len(task.task_key.encode("utf-8")) > MAX_TASK_KEY_BYTES
        or _TASK_KEY_RE.fullmatch(task.task_key) is None
        or task.runtime_role not in {"shared-agent", "separate-verifier"}
        or not isinstance(task.image, str)
        or not is_digest_pinned_image(task.image)
    ):
        _fail("expected_task_invalid")
    requirements = _validate_requirements(task.requirements, "expected_task_invalid")
    return task.task_key, task.runtime_role, task.image, requirements


def _binding_plan_commitment(
    bindings: Mapping[
        str,
        tuple[Literal["shared-agent", "separate-verifier"], str, tuple[str, ...]],
    ],
) -> str:
    return _sha256(
        canonical_json(
            {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "expected_task_count": len(bindings),
                "bindings": [
                    {
                        "task_key": task_key,
                        "runtime_role": runtime_role,
                        "image": image,
                        "requirements_sha256": ordered_requirements_sha256(requirements),
                    }
                    for task_key, (runtime_role, image, requirements) in sorted(bindings.items())
                ],
            }
        )
    )


def binding_plan_sha256(tasks: Iterable[ExpectedTaskBinding]) -> str:
    """Bind the complete task set to its actual dependency runtimes and exact requirements."""

    bindings: dict[
        str,
        tuple[Literal["shared-agent", "separate-verifier"], str, tuple[str, ...]],
    ] = {}
    for task in tasks:
        task_key, runtime_role, image, requirements = _validated_expected_task(task)
        if task_key in bindings or len(bindings) >= MAX_TASKS:
            _fail("expected_tasks_duplicate")
        bindings[task_key] = (runtime_role, image, requirements)
    if not bindings:
        _fail("expected_task_count_invalid")
    return _binding_plan_commitment(bindings)


@dataclass(frozen=True)
class _FileSeal:
    path: Path
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int
    sha256: str

    def verify_identity(self, root: Path, *, code: str) -> None:
        observed = _private_file_status(root, self.path, code=code)
        if (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_nlink,
            observed.st_size,
            observed.st_mtime_ns,
            observed.st_ctime_ns,
        ) != (
            self.device,
            self.inode,
            self.mode,
            self.links,
            self.size,
            self.modified_ns,
            self.changed_ns,
        ):
            _fail(code)

    def read_verified(self, root: Path, *, maximum: int, code: str) -> bytes:
        payload, observed = _read_private_file(root, self.path, maximum=maximum, code=code)
        if observed != self:
            _fail(code)
        return payload


@dataclass(frozen=True)
class _Policy:
    source_policy_sha256: str
    source_policy_approval_sha256: str
    approved_binary_artifacts: frozenset[str]
    approved_source_attestations: frozenset[str]
    approved_toolchains: frozenset[str]


@dataclass(frozen=True)
class _RequirementSet:
    sha256: str
    requirements: tuple[str, ...]


@dataclass(frozen=True)
class _Closure:
    distributions: tuple[tuple[str, str], ...]
    sha256: str

    def record(self) -> dict[str, object]:
        return {
            "distributions": [list(item) for item in self.distributions],
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class _Coverage:
    sha256: str
    requirements_sha256: str
    runtime_fingerprint: RuntimeFingerprint
    scope: Literal["image", "universal"]
    image: str | None
    mode: Literal["image-inventory", "wheelhouse"]
    artifact_sha256: str


@dataclass(frozen=True)
class _TaskBinding:
    task_key: str
    runtime_role: Literal["shared-agent", "separate-verifier"]
    image: str
    requirements_sha256: str
    coverage_sha256: str


@dataclass(frozen=True)
class _WheelRecord:
    evidence: WheelEvidence
    origin: Literal["binary", "source-build"]
    binary_artifact_policy_sha256: str | None
    source_attestation_sha256: str | None


@dataclass(frozen=True)
class _ImageInventory:
    manifest_sha256: str
    seal: _FileSeal
    image: str
    requirements: tuple[str, ...]
    requirements_sha256: str
    runtime_fingerprint: RuntimeFingerprint
    installed_inventory: tuple[tuple[str, str], ...]
    installed_inventory_sha256: str
    closure: _Closure


@dataclass(frozen=True)
class _Wheelhouse:
    manifest_sha256: str
    manifest_seal: _FileSeal
    archive_seal: _FileSeal
    requirements: tuple[str, ...]
    requirements_sha256: str
    runtime_fingerprint: RuntimeFingerprint
    scope: Literal["image", "universal"]
    image: str | None
    closure: _Closure
    wheels: tuple[_WheelRecord, ...]
    toolchain_sha256: str


@dataclass(frozen=True)
class CoveragePlan:
    """A statically guaranteed dependency plan for one private task binding."""

    guarantee: Literal["image-inventory", "wheelhouse"]
    requirements: tuple[str, ...]
    runtime_fingerprint: RuntimeFingerprint
    closure: tuple[tuple[str, str], ...]
    _root: Path
    _catalog_seal: _FileSeal
    _inventory: _ImageInventory | None = None
    _wheelhouse: _Wheelhouse | None = None

    def verify_seals(self) -> None:
        self._catalog_seal.verify_identity(self._root, code="catalog_changed")
        if self._inventory is not None:
            self._inventory.seal.verify_identity(self._root, code="inventory_changed")
        if self._wheelhouse is not None:
            self._wheelhouse.manifest_seal.verify_identity(
                self._root,
                code="wheelhouse_manifest_changed",
            )
            self._wheelhouse.archive_seal.verify_identity(
                self._root,
                code="wheelhouse_archive_changed",
            )

    def revalidate(self) -> None:
        self._catalog_seal.read_verified(
            self._root,
            maximum=MAX_CATALOG_BYTES,
            code="catalog_changed",
        )
        if self._inventory is not None:
            self._inventory.seal.read_verified(
                self._root,
                maximum=MAX_MANIFEST_BYTES,
                code="inventory_changed",
            )
        if self._wheelhouse is not None:
            self._wheelhouse.manifest_seal.read_verified(
                self._root,
                maximum=MAX_MANIFEST_BYTES,
                code="wheelhouse_manifest_changed",
            )
            self._wheelhouse.archive_seal.read_verified(
                self._root,
                maximum=MAX_WHEELHOUSE_BYTES,
                code="wheelhouse_archive_changed",
            )

    def read_verified_archive(self) -> bytes:
        if self._wheelhouse is None:
            _fail("wheelhouse_not_available")
        self._catalog_seal.verify_identity(self._root, code="catalog_changed")
        self._wheelhouse.manifest_seal.verify_identity(self._root, code="wheelhouse_manifest_changed")
        return self._wheelhouse.archive_seal.read_verified(
            self._root,
            maximum=MAX_WHEELHOUSE_BYTES,
            code="wheelhouse_archive_changed",
        )

    def install_request_payload(self, wheel_directory: str) -> bytes:
        if self._wheelhouse is None:
            _fail("wheelhouse_not_available")
        directory = _runtime_staging_path(wheel_directory, "install_path_invalid")
        return "".join(
            f"{directory}/{record.evidence.filename} --hash=sha256:{record.evidence.sha256}\n"
            for record in self._wheelhouse.wheels
        ).encode("utf-8")

    def probe_control_payload(self, site_directory: str | None) -> bytes:
        self.verify_seals()
        if site_directory is not None:
            _runtime_staging_path(site_directory, "probe_path_invalid")
        if self._inventory is not None:
            if site_directory is not None:
                _fail("probe_path_invalid")
            inventory = self._inventory.installed_inventory
        elif self._wheelhouse is not None:
            if site_directory is None:
                _fail("probe_path_invalid")
            inventory = self._wheelhouse.closure.distributions
        else:  # pragma: no cover - construction is internal.
            _fail("coverage_plan_invalid")
        return canonical_json(
            {
                "schema_version": 1,
                "site_directory": site_directory,
                "requirements": list(self.requirements),
                "inventory": [list(item) for item in inventory],
                "inventory_sha256": closure_sha256(inventory),
                "closure": [list(item) for item in self.closure],
                "closure_sha256": closure_sha256(self.closure),
            }
        )


@dataclass(frozen=True)
class AggregateCatalogReceipt:
    tasks: int
    images: int
    requirement_sets: int
    coverage_records: int
    image_inventory_tasks: int
    wheelhouse_tasks: int
    image_inventories: int
    wheelhouses: int
    wheels: int
    source_built_wheels: int
    shared_agent_tasks: int
    separate_verifier_tasks: int
    uncovered: int = 0

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract_version": PUBLIC_RECEIPT_CONTRACT_VERSION,
            "status": "ready",
            "counts": {
                "tasks": self.tasks,
                "images": self.images,
                "requirement_sets": self.requirement_sets,
                "coverage_records": self.coverage_records,
                "image_inventory_tasks": self.image_inventory_tasks,
                "wheelhouse_tasks": self.wheelhouse_tasks,
                "image_inventories": self.image_inventories,
                "wheelhouses": self.wheelhouses,
                "wheels": self.wheels,
                "source_built_wheels": self.source_built_wheels,
                "shared_agent_tasks": self.shared_agent_tasks,
                "separate_verifier_tasks": self.separate_verifier_tasks,
                "uncovered": self.uncovered,
            },
        }


def _runtime_staging_path(value: str, code: str) -> str:
    if not isinstance(value, str):
        _fail(code)
    path = PurePosixPath(value)
    if (
        not value
        or not path.is_absolute()
        or value != path.as_posix()
        or ".." in path.parts
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        or path == RUNTIME_STAGING_ROOT
        or not path.is_relative_to(RUNTIME_STAGING_ROOT)
    ):
        _fail(code)
    return value


def _require_distinct_runtime_paths(first: str, second: str, code: str) -> None:
    first_path = PurePosixPath(first)
    second_path = PurePosixPath(second)
    if first_path == second_path or first_path.is_relative_to(second_path) or second_path.is_relative_to(first_path):
        _fail(code)


def validate_runtime_staging_paths(paths: Sequence[str]) -> tuple[str, ...]:
    """Validate one complete set of mutually non-aliasing runtime paths."""

    if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence) or len(paths) < 2:
        _fail("runtime_paths_invalid")
    validated = tuple(_runtime_staging_path(path, "runtime_paths_invalid") for path in paths)
    for index, first in enumerate(validated):
        for second in validated[index + 1 :]:
            _require_distinct_runtime_paths(first, second, "runtime_paths_invalid")
    return validated


def offline_install_argv(site_directory: str, request_path: str) -> tuple[str, ...]:
    """Return a no-index, no-resolution install command with no package names."""

    try:
        site, request = validate_runtime_staging_paths((site_directory, request_path))
    except OfflineCatalogError as error:
        _fail("install_path_invalid", error)
    return (
        "python3",
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-deps",
        "--no-cache-dir",
        "--disable-pip-version-check",
        "--no-input",
        "--require-hashes",
        "--target",
        site,
        "--requirement",
        request,
    )


def offline_install_environment() -> dict[str, str]:
    return {
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
    }


RUNTIME_FINGERPRINT_PROBE_CODE = r"""import json
import pip
import platform
import sys
import sysconfig

try:
    from packaging.markers import default_environment
    from packaging.tags import sys_tags
except ModuleNotFoundError:
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.tags import sys_tags

libc_name, libc_version = platform.libc_ver()
record = {
    "schema_version": 1,
    "implementation": sys.implementation.name,
    "python_full_version": platform.python_version(),
    "abi": sysconfig.get_config_var("SOABI") or "none",
    "platform": sysconfig.get_platform(),
    "machine": platform.machine() or "unknown",
    "libc": f"{libc_name or 'unknown'}-{libc_version or 'unknown'}",
    "pip_version": pip.__version__,
    "marker_environment": dict(sorted(default_environment().items())),
    "supported_tags": sorted({str(tag) for tag in sys_tags()}),
}
print(json.dumps(record, sort_keys=True, separators=(",", ":")))
""".strip()


CLOSURE_PROBE_CODE = r"""import hashlib
import importlib.metadata as metadata
import json
import sys

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ModuleNotFoundError:
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def digest(distributions):
    return hashlib.sha256(canonical_json({
        "schema_version": 1,
        "distributions": distributions,
    })).hexdigest()

try:
    with open(sys.argv[1], "rb") as handle:
        payload = handle.read()
    if hashlib.sha256(payload).hexdigest() != sys.argv[2]:
        raise RuntimeError
    control = json.loads(
        payload,
        object_pairs_hook=lambda pairs: (
            dict(pairs) if len(pairs) == len(dict(pairs)) else (_ for _ in ()).throw(RuntimeError())
        ),
        parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError()),
    )
    if set(control) != {
        "schema_version", "site_directory", "requirements", "inventory",
        "inventory_sha256", "closure", "closure_sha256",
    } or type(control["schema_version"]) is not int or control["schema_version"] != 1:
        raise RuntimeError
    site_directory = control["site_directory"]
    available = {}
    iterator = metadata.distributions(path=[site_directory]) if site_directory is not None else metadata.distributions()
    for distribution in iterator:
        name = distribution.metadata.get("Name")
        version = distribution.version
        if not name or not version:
            raise RuntimeError
        key = canonicalize_name(name)
        if key in available:
            raise RuntimeError
        available[key] = distribution
    inventory = sorted([[name, distribution.version] for name, distribution in available.items()])
    if inventory != control["inventory"] or digest(inventory) != control["inventory_sha256"]:
        raise RuntimeError
    pending = [(Requirement(text), frozenset(Requirement(text).extras)) for text in control["requirements"]]
    visited = set()
    resolved = set()
    while pending:
        requirement, parent_extras = pending.pop()
        name = canonicalize_name(requirement.name)
        key = (name, str(requirement.specifier), tuple(sorted(parent_extras)))
        if key in visited:
            continue
        visited.add(key)
        distribution = available.get(name)
        if distribution is None or (
            requirement.specifier
            and not requirement.specifier.contains(distribution.version, prereleases=True)
        ):
            raise RuntimeError
        resolved.add((name, distribution.version))
        environments = []
        for extra in parent_extras or {""}:
            environment = default_environment()
            environment["extra"] = extra
            environments.append(environment)
        for dependency_text in distribution.requires or ():
            dependency = Requirement(dependency_text)
            if dependency.url is not None:
                raise RuntimeError
            if dependency.marker is not None and not any(
                dependency.marker.evaluate(environment) for environment in environments
            ):
                continue
            pending.append((dependency, frozenset(dependency.extras)))
    closure = [list(item) for item in sorted(resolved)]
    if closure != control["closure"] or digest(closure) != control["closure_sha256"]:
        raise RuntimeError
except BaseException:
    print('{"status":"failed"}')
    raise SystemExit(1)
print(json.dumps({"count": len(closure), "status": "ok"}, sort_keys=True, separators=(",", ":")))
""".strip()


def runtime_fingerprint_probe_argv() -> tuple[str, ...]:
    return ("python3", "-I", "-c", RUNTIME_FINGERPRINT_PROBE_CODE)


def closure_probe_argv(script_path: str, control_path: str, control_sha256: str) -> tuple[str, ...]:
    try:
        script, control = validate_runtime_staging_paths((script_path, control_path))
    except OfflineCatalogError as error:
        _fail("probe_path_invalid", error)
    if not _is_sha256(control_sha256):
        _fail("probe_control_digest_invalid")
    return ("python3", "-I", script, control, control_sha256)


def _validate_private_root(root: Path, project_root: Path, dataset_root: Path) -> Path:
    try:
        if not root.is_absolute() or root.resolve(strict=True) != root:
            _fail("catalog_root_invalid")
        status = root.lstat()
        if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700 or status.st_uid != os.geteuid():
            _fail("catalog_root_invalid")
        if not project_root.is_absolute() or not dataset_root.is_absolute():
            _fail("catalog_protected_root_invalid")
        protected = (project_root.resolve(strict=True), dataset_root.resolve(strict=True))
        if not all(candidate.is_dir() for candidate in protected):
            _fail("catalog_protected_root_invalid")
    except OfflineCatalogError:
        raise
    except OSError as error:
        _fail("catalog_root_invalid", error)
    for candidate in protected:
        if root == candidate or root.is_relative_to(candidate) or candidate.is_relative_to(root):
            _fail("catalog_root_overlap")
    return root


def _open_private_file(root: Path, path: Path, *, code: str) -> tuple[int, os.stat_result]:
    try:
        listed_root = root.lstat()
        if (
            root.resolve(strict=True) != root
            or not stat.S_ISDIR(listed_root.st_mode)
            or stat.S_IMODE(listed_root.st_mode) != 0o700
            or listed_root.st_uid != os.geteuid()
        ):
            _fail(code)
        if not path.is_absolute() or path.parent == path or not path.is_relative_to(root):
            _fail(code)
        relative = path.relative_to(root)
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            _fail(code)
        current_descriptor = os.open(
            root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened_directories = [current_descriptor]
        root_status = os.fstat(current_descriptor)
        if (
            root_status.st_dev,
            root_status.st_ino,
            root_status.st_mode,
            root_status.st_uid,
        ) != (
            listed_root.st_dev,
            listed_root.st_ino,
            listed_root.st_mode,
            listed_root.st_uid,
        ):
            _fail(code)
        for part in relative.parts[:-1]:
            current_descriptor = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_descriptor,
            )
            opened_directories.append(current_descriptor)
            status = os.fstat(current_descriptor)
            if (
                not stat.S_ISDIR(status.st_mode)
                or stat.S_IMODE(status.st_mode) != 0o700
                or status.st_uid != os.geteuid()
            ):
                _fail(code)
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current_descriptor,
        )
        listed = os.fstat(descriptor)
    except OfflineCatalogError:
        if "descriptor" in locals():
            os.close(descriptor)
        for directory_descriptor in reversed(locals().get("opened_directories", [])):
            os.close(directory_descriptor)
        raise
    except OSError as error:
        if "descriptor" in locals():
            os.close(descriptor)
        for directory_descriptor in reversed(locals().get("opened_directories", [])):
            os.close(directory_descriptor)
        _fail(code, error)
    for directory_descriptor in reversed(opened_directories):
        os.close(directory_descriptor)
    if (
        not stat.S_ISREG(listed.st_mode)
        or stat.S_IMODE(listed.st_mode) not in {0o400, 0o600}
        or listed.st_nlink != 1
        or listed.st_uid != os.geteuid()
    ):
        os.close(descriptor)
        _fail(code)
    return descriptor, listed


def _private_file_status(root: Path, path: Path, *, code: str) -> os.stat_result:
    descriptor, status = _open_private_file(root, path, code=code)
    os.close(descriptor)
    return status


def _read_private_file(root: Path, path: Path, *, maximum: int, code: str) -> tuple[bytes, _FileSeal]:
    try:
        descriptor, listed = _open_private_file(root, path, code=code)
        if not 1 <= listed.st_size <= maximum:
            os.close(descriptor)
            _fail(code)
        try:
            before = os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                listed.st_dev,
                listed.st_ino,
                listed.st_mode,
                listed.st_nlink,
                listed.st_size,
                listed.st_mtime_ns,
                listed.st_ctime_ns,
            ):
                _fail(code)
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            total = 0
            while chunk := os.read(descriptor, min(1024 * 1024, maximum + 1)):
                chunks.append(chunk)
                digest.update(chunk)
                total += len(chunk)
                if total > maximum:
                    _fail(code)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OfflineCatalogError:
        raise
    except OSError as error:
        _fail(code, error)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        _fail(code)
    payload = b"".join(chunks)
    return payload, _FileSeal(
        path=path,
        device=before.st_dev,
        inode=before.st_ino,
        mode=before.st_mode,
        links=before.st_nlink,
        size=before.st_size,
        modified_ns=before.st_mtime_ns,
        changed_ns=before.st_ctime_ns,
        sha256=digest.hexdigest(),
    )


def _artifact_path(root: Path, kind: Literal["inventories", "manifests", "archives"], digest: str) -> Path:
    suffix = ".tar" if kind == "archives" else ".json"
    return root / kind / "sha256" / digest[:2] / f"{digest}{suffix}"


def _canonical_private_json(
    root: Path,
    path: Path,
    expected_sha256: str,
    *,
    maximum: int,
    code: str,
) -> tuple[dict[str, object], _FileSeal]:
    payload, seal = _read_private_file(root, path, maximum=maximum, code=code)
    if seal.sha256 != expected_sha256:
        _fail(code)
    try:
        raw = strict_json_loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        _fail(code, error)
    if not isinstance(raw, dict) or payload != canonical_json(raw):
        _fail(code)
    return raw, seal


def _parse_closure(value: object, code: str) -> _Closure:
    raw = _exact_keys(value, {"distributions", "sha256"}, code)
    distributions = _validate_closure(raw["distributions"], code)  # type: ignore[arg-type]
    digest = closure_sha256(distributions)
    if raw["sha256"] != digest:
        _fail(code)
    return _Closure(distributions=distributions, sha256=digest)


def _parse_toolchain(value: object, allowed: frozenset[str]) -> tuple[str, dict[str, object]]:
    raw = _exact_keys(value, {"record", "sha256"}, "toolchain_invalid")
    record = _exact_keys(
        raw["record"],
        {
            "schema_version",
            "python_version",
            "pip_version",
            "resolver",
            "resolver_version",
            "builder_code_sha256",
            "build_environment_sha256",
        },
        "toolchain_invalid",
    )
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        _fail("toolchain_invalid")
    for key in ("python_version", "pip_version", "resolver", "resolver_version"):
        _bounded_text(record[key], "toolchain_invalid")
    for key in ("builder_code_sha256", "build_environment_sha256"):
        if not _is_sha256(record[key]):
            _fail("toolchain_invalid")
    digest = _sha256(canonical_json(record))
    if raw["sha256"] != digest or digest not in allowed:
        _fail("toolchain_unapproved")
    return digest, record


def _deterministic_wheelhouse(payload: bytes) -> tuple[tuple[WheelEvidence, ...], dict[str, bytes]]:
    try:
        evidence = inspect_wheelhouse(payload)
        with tarfile.open(fileobj=BytesIO(payload), mode="r:") as archive:
            wheels = {
                Path(member.name).name: archive.extractfile(member).read()  # type: ignore[union-attr]
                for member in archive.getmembers()
                if member.isfile()
            }
        if pack_wheelhouse(wheels) != payload:
            _fail("wheelhouse_nondeterministic")
        return evidence, wheels
    except OfflineCatalogError:
        raise
    except (OSError, RuntimeError, tarfile.TarError) as error:
        _fail("wheelhouse_invalid", error)


def _validate_resolution_closure(
    requirements: tuple[str, ...],
    closure: _Closure,
    wheels: Mapping[str, bytes],
    marker_environment: Mapping[str, str],
    supported_tags: frozenset[str],
) -> None:
    distributions: dict[str, tuple[str, tuple[Requirement, ...]]] = {}
    for filename, payload in wheels.items():
        try:
            evidence, raw_requirements = inspect_wheel_requirements(filename, payload)
            _, _, _, wheel_tags = parse_wheel_filename(filename)
        except (InvalidRequirement, RuntimeError, ValueError) as error:
            _fail("wheelhouse_resolution_invalid", error)
        if not {str(tag) for tag in wheel_tags}.intersection(supported_tags):
            _fail("wheelhouse_incompatible")
        dependencies: list[Requirement] = []
        for raw_requirement in raw_requirements:
            try:
                dependency = Requirement(raw_requirement)
            except InvalidRequirement as error:
                _fail("wheelhouse_resolution_invalid", error)
            if dependency.url is not None:
                _fail("wheelhouse_resolution_invalid")
            dependencies.append(dependency)
        if evidence.distribution in distributions:
            _fail("wheelhouse_resolution_invalid")
        distributions[evidence.distribution] = (
            evidence.version,
            tuple(dependencies),
        )

    active_extras: dict[str, set[str]] = {}
    processed_extras: dict[str, frozenset[str]] = {}
    pending: list[str] = []

    def include(requirement: Requirement) -> None:
        name = canonical_distribution_name(requirement.name)
        candidate = distributions.get(name)
        if candidate is None or (
            requirement.specifier and not requirement.specifier.contains(candidate[0], prereleases=True)
        ):
            _fail("wheelhouse_resolution_invalid")
        extras = {extra.casefold() for extra in requirement.extras}
        current = active_extras.setdefault(name, set())
        expanded = frozenset((*current, *extras))
        if processed_extras.get(name) != expanded:
            current.update(extras)
            pending.append(name)

    for requirement_text in requirements:
        try:
            include(Requirement(requirement_text))
        except InvalidRequirement as error:  # pragma: no cover - exact syntax was validated first.
            _fail("wheelhouse_resolution_invalid", error)
    try:
        while pending:
            name = pending.pop()
            extras = frozenset(active_extras[name])
            if processed_extras.get(name) == extras:
                continue
            processed_extras[name] = extras
            for dependency in distributions[name][1]:
                environments = []
                for extra in extras or {""}:
                    environment = dict(marker_environment)
                    environment["extra"] = extra
                    environments.append(environment)
                if dependency.marker is not None and not any(
                    dependency.marker.evaluate(environment) for environment in environments
                ):
                    continue
                include(dependency)
    except (KeyError, TypeError, ValueError) as error:
        _fail("wheelhouse_resolution_invalid", error)
    resolved = tuple(sorted((name, distributions[name][0]) for name in processed_extras))
    if resolved != closure.distributions or set(processed_extras) != set(distributions):
        _fail("wheelhouse_resolution_invalid")


def _validate_root_requirements(requirements: tuple[str, ...], closure: _Closure, code: str) -> None:
    available = dict(closure.distributions)
    for requirement_text in requirements:
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement as error:  # pragma: no cover - exact syntax was validated first.
            _fail(code, error)
        version = available.get(canonical_distribution_name(requirement.name))
        if version is None or not requirement.specifier.contains(version, prereleases=True):
            _fail(code)


class OfflineVerifierCatalog:
    """A sealed catalog that must pass exhaustive preflight before resolution."""

    def __init__(
        self,
        *,
        root: Path,
        catalog_seal: _FileSeal,
        identity: CatalogIdentity,
        policy: _Policy,
        requirement_sets: Mapping[str, _RequirementSet],
        coverages: Mapping[str, _Coverage],
        task_bindings: Mapping[str, _TaskBinding],
    ) -> None:
        self._root = root
        self._catalog_seal = catalog_seal
        self.identity = identity
        self._policy = policy
        self._requirement_sets = dict(requirement_sets)
        self._coverages = dict(coverages)
        self._task_bindings = dict(task_bindings)
        self._inventories: dict[str, _ImageInventory] = {}
        self._wheelhouses: dict[str, _Wheelhouse] = {}
        self._preflight_expected_sha256: str | None = None
        self._receipt: AggregateCatalogReceipt | None = None

    @classmethod
    def load(
        cls,
        path: Path,
        expected_sha256: str,
        identity: CatalogIdentity,
        *,
        project_root: Path,
        dataset_root: Path,
    ) -> "OfflineVerifierCatalog":
        if not path.is_absolute() or path.parent == path or not _is_sha256(expected_sha256):
            _fail("catalog_path_invalid")
        root = _validate_private_root(path.parent, project_root, dataset_root)
        raw, seal = _canonical_private_json(
            root,
            path,
            expected_sha256,
            maximum=MAX_CATALOG_BYTES,
            code="catalog_invalid",
        )
        raw = _exact_keys(
            raw,
            {
                "schema_version",
                "identity",
                "identity_sha256",
                "policy",
                "requirement_sets",
                "coverages",
                "task_bindings",
            },
            "catalog_invalid",
        )
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != CATALOG_SCHEMA_VERSION
            or identity.catalog_consumer_code_sha256 != catalog_consumer_code_sha256()
            or raw["identity"] != identity.record()
            or raw["identity_sha256"] != identity.sha256
        ):
            _fail("catalog_identity_mismatch")
        policy = cls._parse_policy(raw["policy"], identity)
        requirement_sets = cls._parse_requirement_sets(raw["requirement_sets"])
        coverages = cls._parse_coverages(raw["coverages"], requirement_sets)
        task_bindings = cls._parse_task_bindings(raw["task_bindings"], requirement_sets, coverages)
        binding_commitment = _binding_plan_commitment(
            {
                task_key: (
                    binding.runtime_role,
                    binding.image,
                    requirement_sets[binding.requirements_sha256].requirements,
                )
                for task_key, binding in task_bindings.items()
            }
        )
        if len(task_bindings) != identity.expected_task_count or binding_commitment != identity.binding_plan_sha256:
            _fail("catalog_binding_plan_mismatch")
        return cls(
            root=root,
            catalog_seal=seal,
            identity=identity,
            policy=policy,
            requirement_sets=requirement_sets,
            coverages=coverages,
            task_bindings=task_bindings,
        )

    @staticmethod
    def _parse_policy(value: object, identity: CatalogIdentity) -> _Policy:
        raw = _exact_keys(
            value,
            {
                "source_policy_sha256",
                "source_policy_approval_sha256",
                "approved_binary_artifacts",
                "approved_binary_artifacts_sha256",
                "approved_source_attestations",
                "approved_source_attestations_sha256",
                "approved_toolchains",
                "approved_toolchains_sha256",
            },
            "catalog_policy_invalid",
        )
        binaries = raw["approved_binary_artifacts"]
        sources = raw["approved_source_attestations"]
        toolchains = raw["approved_toolchains"]
        if (
            raw["source_policy_sha256"] != identity.source_policy_sha256
            or raw["source_policy_approval_sha256"] != identity.source_policy_approval_sha256
            or not isinstance(binaries, list)
            or not all(_is_sha256(value) for value in binaries)
            or binaries != sorted(set(binaries))
            or not isinstance(sources, list)
            or not all(_is_sha256(value) for value in sources)
            or sources != sorted(set(sources))
            or not isinstance(toolchains, list)
            or not all(_is_sha256(value) for value in toolchains)
            or toolchains != sorted(set(toolchains))
            or raw["approved_binary_artifacts_sha256"] != _allowlist_sha256("binary-artifacts", binaries)
            or raw["approved_binary_artifacts_sha256"] != identity.approved_binary_artifacts_sha256
            or raw["approved_source_attestations_sha256"] != _allowlist_sha256("source-attestations", sources)
            or raw["approved_source_attestations_sha256"] != identity.approved_source_attestations_sha256
            or raw["approved_toolchains_sha256"] != _allowlist_sha256("toolchains", toolchains)
            or raw["approved_toolchains_sha256"] != identity.approved_toolchains_sha256
        ):
            _fail("catalog_policy_invalid")
        return _Policy(
            source_policy_sha256=identity.source_policy_sha256,
            source_policy_approval_sha256=identity.source_policy_approval_sha256,
            approved_binary_artifacts=frozenset(binaries),
            approved_source_attestations=frozenset(sources),
            approved_toolchains=frozenset(toolchains),
        )

    @staticmethod
    def _parse_requirement_sets(value: object) -> dict[str, _RequirementSet]:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_REQUIREMENT_SETS:
            _fail("requirement_sets_invalid")
        parsed: dict[str, _RequirementSet] = {}
        order: list[str] = []
        for item in value:
            raw = _exact_keys(item, {"requirements", "requirements_sha256"}, "requirement_sets_invalid")
            requirements = _validate_requirements(raw["requirements"], "requirement_sets_invalid")  # type: ignore[arg-type]
            digest = ordered_requirements_sha256(requirements)
            if raw["requirements_sha256"] != digest or digest in parsed:
                _fail("requirement_sets_invalid")
            parsed[digest] = _RequirementSet(digest, requirements)
            order.append(digest)
        if order != sorted(order):
            _fail("requirement_sets_invalid")
        return parsed

    @staticmethod
    def _parse_coverages(
        value: object,
        requirement_sets: Mapping[str, _RequirementSet],
    ) -> dict[str, _Coverage]:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_TASKS:
            _fail("coverages_invalid")
        parsed: dict[str, _Coverage] = {}
        order: list[str] = []
        for item in value:
            raw = _exact_keys(
                item,
                {
                    "coverage_sha256",
                    "requirements_sha256",
                    "runtime_fingerprint",
                    "runtime_fingerprint_sha256",
                    "scope",
                    "image",
                    "mode",
                    "artifact_sha256",
                },
                "coverages_invalid",
            )
            requirement_digest = raw["requirements_sha256"]
            fingerprint = RuntimeFingerprint.from_record(raw["runtime_fingerprint"])
            scope = raw["scope"]
            mode = raw["mode"]
            image = raw["image"]
            artifact_digest = raw["artifact_sha256"]
            if (
                requirement_digest not in requirement_sets
                or raw["runtime_fingerprint_sha256"] != fingerprint.sha256
                or scope not in {"image", "universal"}
                or mode not in {"image-inventory", "wheelhouse"}
                or not _is_sha256(artifact_digest)
                or (scope == "image" and (not isinstance(image, str) or not is_digest_pinned_image(image)))
                or (scope == "universal" and image is not None)
                or (mode == "image-inventory" and scope != "image")
            ):
                _fail("coverages_invalid")
            core = {key: raw[key] for key in raw if key != "coverage_sha256"}
            digest = _sha256(canonical_json(core))
            if raw["coverage_sha256"] != digest or digest in parsed:
                _fail("coverages_invalid")
            parsed[digest] = _Coverage(
                sha256=digest,
                requirements_sha256=str(requirement_digest),
                runtime_fingerprint=fingerprint,
                scope=scope,  # type: ignore[arg-type]
                image=image if isinstance(image, str) else None,
                mode=mode,  # type: ignore[arg-type]
                artifact_sha256=str(artifact_digest),
            )
            order.append(digest)
        if order != sorted(order):
            _fail("coverages_invalid")
        return parsed

    @staticmethod
    def _parse_task_bindings(
        value: object,
        requirement_sets: Mapping[str, _RequirementSet],
        coverages: Mapping[str, _Coverage],
    ) -> dict[str, _TaskBinding]:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_TASKS:
            _fail("task_bindings_invalid")
        parsed: dict[str, _TaskBinding] = {}
        order: list[str] = []
        for item in value:
            raw = _exact_keys(
                item,
                {
                    "task_key",
                    "runtime_role",
                    "image",
                    "requirements_sha256",
                    "coverage_sha256",
                    "binding_sha256",
                },
                "task_bindings_invalid",
            )
            task_key = raw["task_key"]
            runtime_role = raw["runtime_role"]
            image = raw["image"]
            requirement_digest = raw["requirements_sha256"]
            coverage_digest = raw["coverage_sha256"]
            if (
                not isinstance(task_key, str)
                or len(task_key.encode("utf-8")) > MAX_TASK_KEY_BYTES
                or _TASK_KEY_RE.fullmatch(task_key) is None
                or task_key in parsed
                or runtime_role not in {"shared-agent", "separate-verifier"}
                or not isinstance(image, str)
                or not is_digest_pinned_image(image)
                or requirement_digest not in requirement_sets
                or coverage_digest not in coverages
            ):
                _fail("task_bindings_invalid")
            coverage = coverages[str(coverage_digest)]
            if coverage.requirements_sha256 != requirement_digest or (
                coverage.scope == "image" and coverage.image != image
            ):
                _fail("task_bindings_invalid")
            core = {key: raw[key] for key in raw if key != "binding_sha256"}
            if raw["binding_sha256"] != _sha256(canonical_json(core)):
                _fail("task_bindings_invalid")
            parsed[task_key] = _TaskBinding(
                task_key=task_key,
                runtime_role=runtime_role,  # type: ignore[arg-type]
                image=image,
                requirements_sha256=str(requirement_digest),
                coverage_sha256=str(coverage_digest),
            )
            order.append(task_key)
        if order != sorted(order):
            _fail("task_bindings_invalid")
        return parsed

    def _load_inventory(self, coverage: _Coverage) -> _ImageInventory:
        cached = self._inventories.get(coverage.artifact_sha256)
        if cached is not None:
            if (
                cached.requirements_sha256 != coverage.requirements_sha256
                or cached.runtime_fingerprint != coverage.runtime_fingerprint
                or cached.image != coverage.image
            ):
                _fail("inventory_binding_mismatch")
            return cached
        path = _artifact_path(self._root, "inventories", coverage.artifact_sha256)
        raw, seal = _canonical_private_json(
            self._root,
            path,
            coverage.artifact_sha256,
            maximum=MAX_MANIFEST_BYTES,
            code="inventory_invalid",
        )
        raw = _exact_keys(
            raw,
            {
                "schema_version",
                "image",
                "requirements",
                "requirements_sha256",
                "runtime_fingerprint",
                "runtime_fingerprint_sha256",
                "installed_inventory",
                "installed_inventory_sha256",
                "closure",
                "probe",
            },
            "inventory_invalid",
        )
        requirements = _validate_requirements(raw["requirements"], "inventory_invalid")  # type: ignore[arg-type]
        fingerprint = RuntimeFingerprint.from_record(raw["runtime_fingerprint"])
        inventory = _validate_closure(raw["installed_inventory"], "inventory_invalid")  # type: ignore[arg-type]
        closure = _parse_closure(raw["closure"], "inventory_invalid")
        probe = _exact_keys(
            raw["probe"],
            {"code_sha256", "environment_sha256", "approval_sha256"},
            "inventory_invalid",
        )
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != IMAGE_INVENTORY_SCHEMA_VERSION
            or raw["image"] != coverage.image
            or ordered_requirements_sha256(requirements) != coverage.requirements_sha256
            or raw["requirements_sha256"] != coverage.requirements_sha256
            or fingerprint != coverage.runtime_fingerprint
            or raw["runtime_fingerprint_sha256"] != fingerprint.sha256
            or raw["installed_inventory_sha256"] != closure_sha256(inventory)
            or (not requirements and bool(closure.distributions))
            or not set(closure.distributions).issubset(set(inventory))
            or probe["code_sha256"] != self.identity.inventory_probe_code_sha256
            or probe["environment_sha256"] != self.identity.inventory_probe_environment_sha256
            or probe["approval_sha256"] != self.identity.inventory_probe_approval_sha256
        ):
            _fail("inventory_invalid")
        _validate_root_requirements(requirements, closure, "inventory_invalid")
        result = _ImageInventory(
            manifest_sha256=coverage.artifact_sha256,
            seal=seal,
            image=str(raw["image"]),
            requirements=requirements,
            requirements_sha256=coverage.requirements_sha256,
            runtime_fingerprint=fingerprint,
            installed_inventory=inventory,
            installed_inventory_sha256=str(raw["installed_inventory_sha256"]),
            closure=closure,
        )
        self._inventories[coverage.artifact_sha256] = result
        return result

    def _load_wheelhouse(self, coverage: _Coverage) -> _Wheelhouse:
        cached = self._wheelhouses.get(coverage.artifact_sha256)
        if cached is not None:
            if (
                cached.requirements_sha256 != coverage.requirements_sha256
                or cached.runtime_fingerprint != coverage.runtime_fingerprint
                or cached.scope != coverage.scope
                or cached.image != coverage.image
            ):
                _fail("wheelhouse_binding_mismatch")
            return cached
        path = _artifact_path(self._root, "manifests", coverage.artifact_sha256)
        raw, manifest_seal = _canonical_private_json(
            self._root,
            path,
            coverage.artifact_sha256,
            maximum=MAX_MANIFEST_BYTES,
            code="wheelhouse_manifest_invalid",
        )
        raw = _exact_keys(
            raw,
            {
                "schema_version",
                "requirements",
                "requirements_sha256",
                "archive",
                "closure",
                "compatibility",
                "toolchain",
                "source_policy",
                "wheels",
            },
            "wheelhouse_manifest_invalid",
        )
        requirements = _validate_requirements(raw["requirements"], "wheelhouse_manifest_invalid")  # type: ignore[arg-type]
        archive_record = _exact_keys(raw["archive"], {"sha256", "size"}, "wheelhouse_manifest_invalid")
        closure = _parse_closure(raw["closure"], "wheelhouse_manifest_invalid")
        compatibility = _exact_keys(
            raw["compatibility"],
            {
                "scope",
                "image",
                "runtime_fingerprint",
                "runtime_fingerprint_sha256",
                "marker_environment",
                "supported_tags",
            },
            "wheelhouse_manifest_invalid",
        )
        fingerprint = RuntimeFingerprint.from_record(compatibility["runtime_fingerprint"])
        marker_environment = compatibility["marker_environment"]
        supported_tags = compatibility["supported_tags"]
        source_policy = _exact_keys(
            raw["source_policy"],
            {"policy_sha256", "approval_sha256"},
            "wheelhouse_manifest_invalid",
        )
        toolchain_sha256, toolchain = _parse_toolchain(raw["toolchain"], self._policy.approved_toolchains)
        archive_digest = archive_record["sha256"]
        archive_size = archive_record["size"]
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != WHEELHOUSE_MANIFEST_SCHEMA_VERSION
            or raw["requirements_sha256"] != coverage.requirements_sha256
            or ordered_requirements_sha256(requirements) != coverage.requirements_sha256
            or compatibility["scope"] != coverage.scope
            or compatibility["image"] != coverage.image
            or compatibility["runtime_fingerprint_sha256"] != fingerprint.sha256
            or fingerprint != coverage.runtime_fingerprint
            or not isinstance(marker_environment, dict)
            or not 1 <= len(marker_environment) <= MAX_MARKER_ENVIRONMENT_KEYS
            or "extra" in marker_environment
            or not all(
                isinstance(key, str)
                and key
                and len(key.encode("utf-8")) <= MAX_TEXT_EVIDENCE_BYTES
                and isinstance(value, str)
                and len(value.encode("utf-8")) <= MAX_TEXT_EVIDENCE_BYTES
                for key, value in marker_environment.items()
            )
            or fingerprint.marker_environment_sha256 != _sha256(canonical_json(marker_environment))
            or not isinstance(supported_tags, list)
            or not 1 <= len(supported_tags) <= MAX_RUNTIME_TAGS
            or not all(isinstance(tag, str) and tag for tag in supported_tags)
            or supported_tags != sorted(set(supported_tags))
            or fingerprint.supported_tags_sha256 != _sha256(canonical_json(supported_tags))
            or toolchain["python_version"] != fingerprint.python_full_version
            or toolchain["pip_version"] != fingerprint.pip_version
            or source_policy["policy_sha256"] != self._policy.source_policy_sha256
            or source_policy["approval_sha256"] != self._policy.source_policy_approval_sha256
            or not _is_sha256(archive_digest)
            or isinstance(archive_size, bool)
            or not isinstance(archive_size, int)
            or not 1 <= archive_size <= MAX_WHEELHOUSE_BYTES
        ):
            _fail("wheelhouse_manifest_invalid")
        archive_path = _artifact_path(self._root, "archives", str(archive_digest))
        archive_payload, archive_seal = _read_private_file(
            self._root,
            archive_path,
            maximum=MAX_WHEELHOUSE_BYTES,
            code="wheelhouse_archive_invalid",
        )
        if archive_seal.sha256 != archive_digest or archive_seal.size != archive_size:
            _fail("wheelhouse_archive_invalid")
        evidence, wheel_payloads = _deterministic_wheelhouse(archive_payload)
        raw_wheels = raw["wheels"]
        if not isinstance(raw_wheels, list) or len(raw_wheels) != len(evidence):
            _fail("wheelhouse_inventory_invalid")
        records: list[_WheelRecord] = []
        for raw_wheel, observed in zip(raw_wheels, evidence, strict=True):
            wheel = _exact_keys(
                raw_wheel,
                {
                    "distribution",
                    "version",
                    "filename",
                    "size",
                    "sha256",
                    "universal",
                    "origin",
                    "binary_artifact_policy",
                    "binary_artifact_policy_sha256",
                    "source_attestation_sha256",
                },
                "wheelhouse_inventory_invalid",
            )
            if (
                wheel["distribution"] != observed.distribution
                or wheel["version"] != observed.version
                or wheel["filename"] != observed.filename
                or type(wheel["size"]) is not int
                or wheel["size"] != observed.size
                or wheel["sha256"] != observed.sha256
                or wheel["universal"] is not observed.universal
                or wheel["origin"] not in {"binary", "source-build"}
            ):
                _fail("wheelhouse_inventory_invalid")
            binary_policy = wheel["binary_artifact_policy"]
            binary_policy_sha256 = wheel["binary_artifact_policy_sha256"]
            source_attestation = wheel["source_attestation_sha256"]
            if wheel["origin"] == "binary":
                policy = _exact_keys(
                    binary_policy,
                    {
                        "schema_version",
                        "distribution",
                        "version",
                        "filename",
                        "size",
                        "sha256",
                        "source_url_sha256",
                        "source_snapshot_sha256",
                    },
                    "binary_input_unapproved",
                )
                policy_digest = _sha256(canonical_json(policy))
                if (
                    type(policy["schema_version"]) is not int
                    or policy["schema_version"] != 1
                    or policy["distribution"] != observed.distribution
                    or policy["version"] != observed.version
                    or policy["filename"] != observed.filename
                    or policy["size"] != observed.size
                    or policy["sha256"] != observed.sha256
                    or not _is_sha256(policy["source_url_sha256"])
                    or not _is_sha256(policy["source_snapshot_sha256"])
                    or binary_policy_sha256 != policy_digest
                    or policy_digest not in self._policy.approved_binary_artifacts
                    or source_attestation is not None
                ):
                    _fail("binary_input_unapproved")
            elif (
                binary_policy is not None
                or binary_policy_sha256 is not None
                or not _is_sha256(source_attestation)
                or source_attestation not in self._policy.approved_source_attestations
            ):
                _fail("source_input_unapproved")
            records.append(
                _WheelRecord(
                    evidence=observed,
                    origin=wheel["origin"],  # type: ignore[arg-type]
                    binary_artifact_policy_sha256=(
                        binary_policy_sha256 if isinstance(binary_policy_sha256, str) else None
                    ),
                    source_attestation_sha256=(source_attestation if isinstance(source_attestation, str) else None),
                )
            )
        inventory = tuple((record.evidence.distribution, record.evidence.version) for record in records)
        if closure.distributions != tuple(sorted(inventory)) or (
            coverage.scope == "universal" and not all(record.evidence.universal for record in records)
        ):
            _fail("wheelhouse_inventory_invalid")
        _validate_resolution_closure(
            requirements,
            closure,
            wheel_payloads,
            marker_environment,
            frozenset(supported_tags),
        )
        result = _Wheelhouse(
            manifest_sha256=coverage.artifact_sha256,
            manifest_seal=manifest_seal,
            archive_seal=archive_seal,
            requirements=requirements,
            requirements_sha256=coverage.requirements_sha256,
            runtime_fingerprint=fingerprint,
            scope=coverage.scope,
            image=coverage.image,
            closure=closure,
            wheels=tuple(records),
            toolchain_sha256=toolchain_sha256,
        )
        self._wheelhouses[coverage.artifact_sha256] = result
        return result

    def preflight(
        self,
        expected_tasks: Iterable[ExpectedTaskBinding],
        *,
        expected_task_count: int,
    ) -> AggregateCatalogReceipt:
        """Validate the entire catalog selection, never a launch-stage subset."""

        self._receipt = None
        if isinstance(expected_task_count, bool) or expected_task_count != self.identity.expected_task_count:
            _fail("expected_task_count_invalid")
        self._catalog_seal.read_verified(
            self._root,
            maximum=MAX_CATALOG_BYTES,
            code="catalog_changed",
        )
        for inventory in self._inventories.values():
            inventory.seal.read_verified(
                self._root,
                maximum=MAX_MANIFEST_BYTES,
                code="inventory_changed",
            )
        for wheelhouse in self._wheelhouses.values():
            wheelhouse.manifest_seal.read_verified(
                self._root,
                maximum=MAX_MANIFEST_BYTES,
                code="wheelhouse_manifest_changed",
            )
            wheelhouse.archive_seal.read_verified(
                self._root,
                maximum=MAX_WHEELHOUSE_BYTES,
                code="wheelhouse_archive_changed",
            )
        expected: dict[
            str,
            tuple[Literal["shared-agent", "separate-verifier"], str, tuple[str, ...]],
        ] = {}
        for task in expected_tasks:
            task_key, runtime_role, image, requirements = _validated_expected_task(task)
            if task_key in expected:
                _fail("expected_tasks_duplicate")
            expected[task_key] = (runtime_role, image, requirements)
            if len(expected) > MAX_TASKS:
                _fail("expected_task_count_invalid")
        if len(expected) != expected_task_count or set(expected) != set(self._task_bindings):
            _fail("catalog_coverage_incomplete")
        expected_commitment = _binding_plan_commitment(expected)
        if expected_commitment != self.identity.binding_plan_sha256:
            _fail("catalog_binding_plan_mismatch")
        if self._preflight_expected_sha256 is not None and self._preflight_expected_sha256 != expected_commitment:
            _fail("catalog_preflight_changed")
        used_requirements: set[str] = set()
        used_coverages: set[str] = set()
        inventory_tasks = 0
        wheelhouse_tasks = 0
        shared_agent_tasks = 0
        separate_verifier_tasks = 0
        images: set[str] = set()
        for task_key, (runtime_role, image, requirements) in expected.items():
            binding = self._task_bindings[task_key]
            requirement_digest = ordered_requirements_sha256(requirements)
            if (
                binding.runtime_role != runtime_role
                or binding.image != image
                or binding.requirements_sha256 != requirement_digest
            ):
                _fail("catalog_binding_mismatch")
            requirement_set = self._requirement_sets.get(requirement_digest)
            coverage = self._coverages.get(binding.coverage_sha256)
            if requirement_set is None or requirement_set.requirements != requirements or coverage is None:
                _fail("catalog_binding_mismatch")
            used_requirements.add(requirement_digest)
            used_coverages.add(coverage.sha256)
            images.add(image)
            if runtime_role == "shared-agent":
                shared_agent_tasks += 1
            else:
                separate_verifier_tasks += 1
            if coverage.mode == "image-inventory":
                inventory = self._load_inventory(coverage)
                if inventory.requirements != requirements or inventory.image != image:
                    _fail("catalog_binding_mismatch")
                inventory_tasks += 1
            else:
                wheelhouse = self._load_wheelhouse(coverage)
                if wheelhouse.requirements != requirements or (
                    wheelhouse.scope == "image" and wheelhouse.image != image
                ):
                    _fail("catalog_binding_mismatch")
                wheelhouse_tasks += 1
        if used_requirements != set(self._requirement_sets) or used_coverages != set(self._coverages):
            _fail("catalog_contains_unbound_records")
        used_inventory_digests = {
            coverage.artifact_sha256 for coverage in self._coverages.values() if coverage.mode == "image-inventory"
        }
        used_wheelhouse_digests = {
            coverage.artifact_sha256 for coverage in self._coverages.values() if coverage.mode == "wheelhouse"
        }
        if used_inventory_digests != set(self._inventories) or used_wheelhouse_digests != set(self._wheelhouses):
            _fail("catalog_coverage_incomplete")
        receipt = AggregateCatalogReceipt(
            tasks=len(expected),
            images=len(images),
            requirement_sets=len(used_requirements),
            coverage_records=len(used_coverages),
            image_inventory_tasks=inventory_tasks,
            wheelhouse_tasks=wheelhouse_tasks,
            image_inventories=len(self._inventories),
            wheelhouses=len(self._wheelhouses),
            wheels=sum(len(item.wheels) for item in self._wheelhouses.values()),
            source_built_wheels=sum(
                record.origin == "source-build" for item in self._wheelhouses.values() for record in item.wheels
            ),
            shared_agent_tasks=shared_agent_tasks,
            separate_verifier_tasks=separate_verifier_tasks,
        )
        self._preflight_expected_sha256 = expected_commitment
        self._receipt = receipt
        return receipt

    def resolve(
        self,
        task_key: str,
        runtime_role: Literal["shared-agent", "separate-verifier"],
        image: str,
        requirements: Sequence[str],
        runtime_fingerprint: RuntimeFingerprint,
    ) -> CoveragePlan:
        if self._receipt is None:
            _fail("catalog_preflight_required")
        if (
            not isinstance(task_key, str)
            or _TASK_KEY_RE.fullmatch(task_key) is None
            or runtime_role not in {"shared-agent", "separate-verifier"}
            or not isinstance(image, str)
            or not is_digest_pinned_image(image)
            or not isinstance(runtime_fingerprint, RuntimeFingerprint)
        ):
            _fail("coverage_lookup_invalid")
        validated_requirements = _validate_requirements(requirements, "coverage_lookup_invalid")
        binding = self._task_bindings.get(task_key)
        if binding is None:
            _fail("coverage_not_found")
        requirement_digest = ordered_requirements_sha256(validated_requirements)
        if (
            binding.runtime_role != runtime_role
            or binding.image != image
            or binding.requirements_sha256 != requirement_digest
        ):
            _fail("coverage_binding_mismatch")
        coverage = self._coverages[binding.coverage_sha256]
        if coverage.runtime_fingerprint != runtime_fingerprint or (
            coverage.scope == "image" and coverage.image != image
        ):
            _fail("runtime_fingerprint_mismatch")
        if coverage.mode == "image-inventory":
            inventory = self._inventories[coverage.artifact_sha256]
            plan = CoveragePlan(
                guarantee="image-inventory",
                requirements=validated_requirements,
                runtime_fingerprint=runtime_fingerprint,
                closure=inventory.closure.distributions,
                _root=self._root,
                _catalog_seal=self._catalog_seal,
                _inventory=inventory,
            )
        else:
            wheelhouse = self._wheelhouses[coverage.artifact_sha256]
            plan = CoveragePlan(
                guarantee="wheelhouse",
                requirements=validated_requirements,
                runtime_fingerprint=runtime_fingerprint,
                closure=wheelhouse.closure.distributions,
                _root=self._root,
                _catalog_seal=self._catalog_seal,
                _wheelhouse=wheelhouse,
            )
        plan.verify_seals()
        return plan


def local_runtime_fingerprint() -> RuntimeFingerprint:
    """Return the current interpreter fingerprint for builders and tests."""

    try:
        import pip
        from packaging.markers import default_environment
        from packaging.tags import sys_tags
    except ModuleNotFoundError:
        import pip
        from pip._vendor.packaging.markers import default_environment
        from pip._vendor.packaging.tags import sys_tags

    libc_name, libc_version = platform.libc_ver()
    return RuntimeFingerprint(
        implementation=platform.python_implementation().lower(),
        python_full_version=platform.python_version(),
        abi=sysconfig.get_config_var("SOABI") or "none",
        platform=sysconfig.get_platform(),
        machine=platform.machine() or "unknown",
        libc=f"{libc_name or 'unknown'}-{libc_version or 'unknown'}",
        pip_version=pip.__version__,
        marker_environment_sha256=_sha256(canonical_json(dict(sorted(default_environment().items())))),
        supported_tags_sha256=_sha256(canonical_json(sorted({str(tag) for tag in sys_tags()}))),
    )
