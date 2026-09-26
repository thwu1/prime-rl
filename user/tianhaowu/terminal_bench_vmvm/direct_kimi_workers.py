#!/usr/bin/env python3
"""Bind the fixed Kimi deployment to a secret-free direct-router manifest."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import stat
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from direct_kimi_router import (
    ALLOWED_REQUEST_TIMEOUT_SECONDS,
    C23_CAPACITY_PROFILE,
    C64_CAPACITY_PROFILE,
    C64_W2_CAPACITY_PROFILE,
    DEFAULT_CAPACITY_PROFILE,
    LEGACY_CAPACITY_PROFILE,
    capacity_for_profile,
    per_worker_capacity_for_profile,
    validate_endpoint_identifier,
    validate_request_timeout_seconds,
    worker_count_for_profile,
)

EXPECTED_MODEL = "Kimi-K3"
EXPECTED_ENDPOINTS = 24
EXPECTED_SPEC_SHA256 = "ab00213a43083eba87f8b5999a3046e8d27ebe42b933ee845fd0cf4928b266e2"
EXPECTED_PROXY_CONFIG_SHA256 = "b120abbe67932d220fb28dcde4a6a1a4d34ffa70abc4b9a2b5a2894b42d7c2d2"
EXPECTED_SOURCE_REQUEST_TIMEOUT_SECONDS = 600
EXPECTED_SOURCE_RETRIES = 2
ROUTER_POLICY = "consistent_hash"
ROUTER_REQUEST_ID_HEADERS = ("x-session-id",)
ROUTER_REQUEST_TIMEOUT_SECONDS = 43_200
ROUTER_RETRIES = 0
ROUTER_PROVIDER_CONCURRENCY = 24
ROUTER_MAX_PROVIDER_CONCURRENCY = 64
ROUTER_QUEUE_SIZE = ROUTER_PROVIDER_CONCURRENCY
ROUTER_QUEUE_TIMEOUT_SECONDS = ROUTER_REQUEST_TIMEOUT_SECONDS
ROUTER_IMPLEMENTATION = "direct-kimi-transparent-v2"
HISTORICAL_LEGACY_ROUTER_IMPLEMENTATION = "direct-kimi-transparent-v1"
HISTORICAL_LEGACY_ROUTER_SHA256 = "7fd5bc463bd0fa86567c21b72e2b4988fbb42aeca4c0a7d40959f8466c8f820d"
HISTORICAL_CURRENT_ROUTER_SHA256 = "03ea138f164526dc39ab721a9ff3413d3b7299900d496204a5510799d7fb4e56"
HISTORICAL_PRE_C23_ROUTER_SHA256 = "33cb7dbc46e00a04a29b7cc765885a7aefba6a100b54019259d93a855bc61ffe"
EXPECTED_ENDPOINT_IDENTIFIER = "cpu-132-021_8103"
MANIFEST_SCHEMA_VERSION = 1
C64_MANIFEST_SCHEMA_VERSION = 2
W2_MANIFEST_SCHEMA_VERSION = 3
C23_MANIFEST_SCHEMA_VERSION = 4
C23_SELECTION_PROFILE = "exclude-one-from-c24-v1"
W2_PER_WORKER_CAPACITY = 2
W2_FORWARDED_CAPACITY = EXPECTED_ENDPOINTS * W2_PER_WORKER_CAPACITY
MAX_CONFIG_BYTES = 4 * 1024 * 1024
MAX_MODELS_BYTES = 1 << 20
MAX_RUN_BINDING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GENERATION_MARKER_NAME = ".direct_kimi_generation.complete"
GENERATION_MARKER_KIND = "direct-kimi-generation-publication"
SOURCE_SNAPSHOT_MARKER_NAME = ".direct_kimi_source_snapshot.complete"
SOURCE_SNAPSHOT_MARKER_KIND = "direct-kimi-source-snapshot-publication"
FILE_MARKER_KIND = "direct-kimi-file-publication"
GENERATION_MANIFEST_NAME = "direct_kimi_workers.json"
GENERATION_URLS_NAME = "worker_urls.private.txt"
GENERATION_PORTS_NAME = "router_ports.private.txt"
GENERATION_FILE_NAMES = {
    GENERATION_MANIFEST_NAME,
    GENERATION_URLS_NAME,
    GENERATION_PORTS_NAME,
}
SOURCE_SNAPSHOT_FILE_NAMES = {"spec.yaml", "proxy_litellm_config.yaml"}


class DirectKimiWorkerError(ValueError):
    """The direct Kimi worker generation does not match the pinned source."""


@dataclass(frozen=True)
class Worker:
    url: str
    backend_sha256: str
    model_sha256: str

    @property
    def public_record(self) -> dict[str, str]:
        return {
            "backend_sha256": self.backend_sha256,
            "model_sha256": self.model_sha256,
        }


@dataclass(slots=True)
class _HeldArtifact:
    path: Path
    parent_path: Path
    parent: int
    parent_identity: tuple[int, int, int, int]
    name: str
    descriptor: int
    identity: tuple[int, ...]
    body: bytes
    private: bool
    changed_code: str


@dataclass(slots=True)
class _HeldArtifactSet:
    """Retain each exact evidence inode and its parent through publication."""

    artifacts: dict[Path, _HeldArtifact]

    @classmethod
    def create(cls) -> _HeldArtifactSet:
        return cls(artifacts={})

    def capture(
        self,
        path: Path,
        *,
        maximum_bytes: int,
        private: bool,
        code: str,
    ) -> bytes:
        absolute = _absolute_path(path, code=code)
        changed_code = "run_binding_changed" if code == "run_binding_invalid" else f"{code}_changed"
        existing = self.artifacts.get(absolute)
        if existing is not None:
            if len(existing.body) > maximum_bytes or (private and not existing.private):
                raise DirectKimiWorkerError(code)
            return existing.body

        directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
        file_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
            file_flags |= os.O_NOFOLLOW
        parent = os.open("/", directory_flags)
        try:
            for component in absolute.parts[1:-1]:
                child = os.open(component, directory_flags, dir_fd=parent)
                os.close(parent)
                parent = child
            descriptor = os.open(absolute.name, file_flags, dir_fd=parent)
        except OSError as error:
            os.close(parent)
            raise DirectKimiWorkerError(code) from error
        try:
            before = os.fstat(descriptor)
            parent_before = os.fstat(parent)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > maximum_bytes
                or (not private and stat.S_IMODE(before.st_mode) & 0o022)
                or (private and before.st_uid != os.getuid())
                or (private and stat.S_IMODE(before.st_mode) != 0o600)
                or (
                    private
                    and (
                        not stat.S_ISDIR(parent_before.st_mode)
                        or parent_before.st_uid != os.getuid()
                        or stat.S_IMODE(parent_before.st_mode) != 0o700
                    )
                )
            ):
                raise DirectKimiWorkerError(code)
            body = bytearray()
            while chunk := os.read(descriptor, 1 << 20):
                body.extend(chunk)
                if len(body) > maximum_bytes:
                    raise DirectKimiWorkerError(code)
            after = os.fstat(descriptor)
            visible = os.stat(absolute.name, dir_fd=parent, follow_symlinks=False)
            parent_after = os.fstat(parent)
            parent_visible = absolute.parent.lstat()
            resolved_parent = absolute.parent.resolve(strict=True)
            parent_identity = _directory_identity(parent_after)
            if (
                _stat_identity(before) != _stat_identity(after)
                or _stat_identity(after) != _stat_identity(visible)
                or _directory_identity(parent_before) != parent_identity
                or _directory_identity(parent_visible) != parent_identity
                or resolved_parent != absolute.parent
                or len(body) != after.st_size
                or any(
                    artifact.parent_path == absolute.parent and artifact.parent_identity != parent_identity
                    for artifact in self.artifacts.values()
                )
            ):
                raise DirectKimiWorkerError(changed_code)
            self.artifacts[absolute] = _HeldArtifact(
                path=absolute,
                parent_path=absolute.parent,
                parent=parent,
                parent_identity=parent_identity,
                name=absolute.name,
                descriptor=descriptor,
                identity=_stat_identity(after),
                body=bytes(body),
                private=private,
                changed_code=changed_code,
            )
            return bytes(body)
        except DirectKimiWorkerError:
            os.close(descriptor)
            os.close(parent)
            raise
        except (OSError, RuntimeError) as error:
            os.close(descriptor)
            os.close(parent)
            raise DirectKimiWorkerError(changed_code) from error

    def revalidate(self) -> None:
        for artifact in self.artifacts.values():
            try:
                held_parent = os.fstat(artifact.parent)
                visible_parent = artifact.parent_path.lstat()
                resolved_parent = artifact.parent_path.resolve(strict=True)
                before = os.fstat(artifact.descriptor)
                visible = os.stat(
                    artifact.name,
                    dir_fd=artifact.parent,
                    follow_symlinks=False,
                )
                os.lseek(artifact.descriptor, 0, os.SEEK_SET)
                observed = bytearray()
                while chunk := os.read(artifact.descriptor, 1 << 20):
                    observed.extend(chunk)
                after = os.fstat(artifact.descriptor)
            except (OSError, RuntimeError) as error:
                raise DirectKimiWorkerError(artifact.changed_code) from error
            if (
                _directory_identity(held_parent) != artifact.parent_identity
                or _directory_identity(visible_parent) != artifact.parent_identity
                or resolved_parent != artifact.parent_path
                or _stat_identity(before) != artifact.identity
                or _stat_identity(after) != artifact.identity
                or _stat_identity(visible) != artifact.identity
                or bytes(observed) != artifact.body
            ):
                raise DirectKimiWorkerError(artifact.changed_code)

    def close(self) -> None:
        for artifact in self.artifacts.values():
            os.close(artifact.descriptor)
            os.close(artifact.parent)
        self.artifacts.clear()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _endpoint_bundle_sha256(workers: list[Worker]) -> str:
    return _sha256_bytes("".join(f"{worker.backend_sha256}\n" for worker in workers).encode())


def _read_bound_file(
    path: Path,
    *,
    maximum_bytes: int = MAX_CONFIG_BYTES,
    private: bool = False,
    code: str = "source_unreadable",
    held: _HeldArtifactSet | None = None,
) -> bytes:
    """Read one exact inode through retained no-follow descriptors."""

    if held is not None:
        return held.capture(
            path,
            maximum_bytes=maximum_bytes,
            private=private,
            code=code,
        )

    absolute = _absolute_path(path, code=code)
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    file_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    parent = os.open("/", directory_flags)
    try:
        for component in absolute.parts[1:-1]:
            child = os.open(component, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(absolute.name, file_flags, dir_fd=parent)
    except OSError as error:
        os.close(parent)
        raise DirectKimiWorkerError(code) from error
    try:
        before = os.fstat(descriptor)
        parent_before = os.fstat(parent)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum_bytes
            or (not private and stat.S_IMODE(before.st_mode) & 0o022)
            or (private and before.st_uid != os.getuid())
            or (private and stat.S_IMODE(before.st_mode) != 0o600)
            or (
                private
                and (
                    not stat.S_ISDIR(parent_before.st_mode)
                    or parent_before.st_uid != os.getuid()
                    or stat.S_IMODE(parent_before.st_mode) != 0o700
                )
            )
        ):
            raise DirectKimiWorkerError(code)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > maximum_bytes:
                raise DirectKimiWorkerError(code)
        after = os.fstat(descriptor)
        visible = os.stat(absolute.name, dir_fd=parent, follow_symlinks=False)
        parent_after = os.fstat(parent)
        parent_visible = absolute.parent.lstat()
        resolved_parent = absolute.parent.resolve(strict=True)
    except DirectKimiWorkerError:
        raise
    except (OSError, RuntimeError) as error:
        raise DirectKimiWorkerError(f"{code}_changed") from error
    finally:
        os.close(descriptor)
        os.close(parent)
    if (
        _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(visible)
        or _directory_identity(parent_before) != _directory_identity(parent_after)
        or _directory_identity(parent_after) != _directory_identity(parent_visible)
        or resolved_parent != absolute.parent
        or len(body) != after.st_size
    ):
        raise DirectKimiWorkerError(f"{code}_changed")
    return bytes(body)


def _sha256_file(
    path: Path,
    *,
    private: bool = False,
    held: _HeldArtifactSet | None = None,
) -> str:
    return _sha256_bytes(_read_bound_file(path, private=private, held=held))


def _read_yaml(body: bytes) -> dict[str, Any]:
    try:
        value = yaml.safe_load(body.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise DirectKimiWorkerError("source_invalid") from error
    if not isinstance(value, dict):
        raise DirectKimiWorkerError("source_invalid")
    return value


def _canonical_worker_url(value: Any) -> str:
    if not isinstance(value, str):
        raise DirectKimiWorkerError("worker_url_invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise DirectKimiWorkerError("worker_url_invalid") from error
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise DirectKimiWorkerError("worker_url_invalid")
    return urllib.parse.urlunsplit(("http", parsed.netloc, "", "", ""))


def load_workers(
    deployment_root: Path,
    *,
    held: _HeldArtifactSet | None = None,
) -> tuple[list[Worker], str, str, str]:
    root = _absolute_path(deployment_root, code="source_unreadable")
    spec = root / "spec.yaml"
    proxy_config = root / "proxy_litellm_config.yaml"
    spec_body = _read_bound_file(spec, held=held)
    proxy_body = _read_bound_file(proxy_config, held=held)
    if _sha256_bytes(spec_body) != EXPECTED_SPEC_SHA256 or _sha256_bytes(proxy_body) != EXPECTED_PROXY_CONFIG_SHA256:
        raise DirectKimiWorkerError("source_generation_mismatch")
    document = _read_yaml(proxy_body)
    settings = document.get("litellm_settings")
    entries = document.get("model_list")
    if (
        not isinstance(settings, dict)
        or settings.get("request_timeout") != EXPECTED_SOURCE_REQUEST_TIMEOUT_SECONDS
        or settings.get("num_retries") != EXPECTED_SOURCE_RETRIES
        or not isinstance(entries, list)
        or len(entries) != EXPECTED_ENDPOINTS
    ):
        raise DirectKimiWorkerError("source_generation_mismatch")

    workers: list[Worker] = []
    urls: set[str] = set()
    backend_models: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("model_name") != EXPECTED_MODEL
            or not isinstance(entry.get("litellm_params"), dict)
        ):
            raise DirectKimiWorkerError("worker_record_invalid")
        params = entry["litellm_params"]
        if set(params) != {"api_base", "api_key", "model"} or params.get("api_key") != "EMPTY":
            raise DirectKimiWorkerError("worker_record_invalid")
        model = params.get("model")
        if not isinstance(model, str) or not model or any(character in model for character in "\r\n"):
            raise DirectKimiWorkerError("worker_model_invalid")
        url = _canonical_worker_url(params.get("api_base"))
        if url in urls:
            raise DirectKimiWorkerError("worker_url_duplicate")
        urls.add(url)
        backend_models.add(model)
        workers.append(
            Worker(
                url=url,
                backend_sha256=_sha256_bytes(f"{url}/v1".encode()),
                model_sha256=_sha256_bytes(EXPECTED_MODEL.encode()),
            )
        )
    if len(backend_models) != 1:
        raise DirectKimiWorkerError("worker_model_generation_mismatch")
    workers.sort(key=lambda worker: worker.backend_sha256)
    endpoint_bundle_sha256 = _endpoint_bundle_sha256(workers)
    return workers, EXPECTED_SPEC_SHA256, EXPECTED_PROXY_CONFIG_SHA256, endpoint_bundle_sha256


def _read_exact_snapshot_input(path: Path, expected_sha256: str) -> bytes:
    """Read one mutable deployment source only when its exact bytes are pinned."""

    absolute = _absolute_path(path, code="source_snapshot_invalid")
    try:
        descriptor = os.open(absolute, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise DirectKimiWorkerError("source_snapshot_invalid") from error
    try:
        before = os.fstat(descriptor)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > MAX_CONFIG_BYTES:
                raise DirectKimiWorkerError("source_snapshot_invalid")
        after = os.fstat(descriptor)
        visible = absolute.lstat()
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(visible)
        or len(body) != after.st_size
        or _sha256_bytes(bytes(body)) != expected_sha256
    ):
        raise DirectKimiWorkerError("source_snapshot_invalid")
    return bytes(body)


def materialize_source_snapshot(deployment_root: Path, output_root: Path) -> dict[str, str]:
    """Publish a private exact-hash snapshot without weakening live-source checks."""

    source = _absolute_path(deployment_root, code="source_snapshot_invalid")
    output = _absolute_path(output_root, code="output_parent_invalid")
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise DirectKimiWorkerError("source_snapshot_invalid")
    files = {
        "spec.yaml": _read_exact_snapshot_input(source / "spec.yaml", EXPECTED_SPEC_SHA256),
        "proxy_litellm_config.yaml": _read_exact_snapshot_input(
            source / "proxy_litellm_config.yaml",
            EXPECTED_PROXY_CONFIG_SHA256,
        ),
    }
    _publish_marked_bundle(
        output,
        files,
        marker_name=SOURCE_SNAPSHOT_MARKER_NAME,
        kind=SOURCE_SNAPSHOT_MARKER_KIND,
    )
    workers, spec_sha256, proxy_sha256, endpoint_bundle_sha256 = load_workers(output)
    if len(workers) != EXPECTED_ENDPOINTS:
        raise DirectKimiWorkerError("source_snapshot_invalid")
    return {
        "path": str(output.resolve(strict=True)),
        "spec_sha256": spec_sha256,
        "proxy_config_sha256": proxy_sha256,
        "endpoint_bundle_sha256": endpoint_bundle_sha256,
    }


def derive_ports(output_root: Path) -> tuple[int, int]:
    digest = hashlib.sha256(str(output_root.resolve()).encode()).digest()
    return 20_000 + int.from_bytes(digest[:4], "big") % 10_000, 40_000 + int.from_bytes(digest[4:8], "big") % 10_000


def _manifest(
    deployment_root: Path,
    workers: list[Worker],
    spec_sha256: str,
    proxy_config_sha256: str,
    endpoint_bundle_sha256: str,
    router_port: int,
    metrics_port: int,
    *,
    capacity_profile: str = DEFAULT_CAPACITY_PROFILE,
    endpoint_identifier: str | None = None,
    request_timeout_seconds: int = ROUTER_REQUEST_TIMEOUT_SECONDS,
    source_endpoint_bundle_sha256: str | None = None,
    excluded_worker: Worker | None = None,
) -> dict[str, Any]:
    capacity = capacity_for_profile(capacity_profile)
    expected_worker_count = worker_count_for_profile(capacity_profile)
    request_timeout_seconds = validate_request_timeout_seconds(request_timeout_seconds)
    endpoint_identifier = validate_endpoint_identifier(
        endpoint_identifier,
        capacity_profile=capacity_profile,
    )
    if (
        capacity_profile in (C23_CAPACITY_PROFILE, C64_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE)
        and endpoint_identifier != EXPECTED_ENDPOINT_IDENTIFIER
    ):
        raise DirectKimiWorkerError("endpoint_identifier_invalid")
    if len(workers) != expected_worker_count:
        raise DirectKimiWorkerError("worker_count_invalid")
    if capacity_profile == C23_CAPACITY_PROFILE:
        if (
            SHA256_RE.fullmatch(str(source_endpoint_bundle_sha256 or "")) is None
            or excluded_worker is None
            or excluded_worker.backend_sha256 in {worker.backend_sha256 for worker in workers}
            or excluded_worker.model_sha256 != _sha256_bytes(EXPECTED_MODEL.encode())
        ):
            raise DirectKimiWorkerError("worker_selection_invalid")
    elif source_endpoint_bundle_sha256 is not None or excluded_worker is not None:
        raise DirectKimiWorkerError("worker_selection_unexpected")
    router = {
        "implementation": ROUTER_IMPLEMENTATION,
        "implementation_sha256": _sha256_file(Path(__file__).with_name("direct_kimi_router.py")),
        "host": "127.0.0.1",
        "port": router_port,
        "metrics_host": "127.0.0.1",
        "metrics_port": metrics_port,
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "request_timeout_seconds": request_timeout_seconds,
        "max_concurrent_requests": capacity,
        "queue_size": capacity,
        "queue_timeout_seconds": request_timeout_seconds,
        "retries": ROUTER_RETRIES,
    }
    schema_version = MANIFEST_SCHEMA_VERSION
    if capacity_profile in (C23_CAPACITY_PROFILE, C64_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE):
        schema_version = {
            C23_CAPACITY_PROFILE: C23_MANIFEST_SCHEMA_VERSION,
            C64_CAPACITY_PROFILE: C64_MANIFEST_SCHEMA_VERSION,
            C64_W2_CAPACITY_PROFILE: W2_MANIFEST_SCHEMA_VERSION,
        }[capacity_profile]
        router.update(
            {
                "capacity_profile": capacity_profile,
                "endpoint_identifier": endpoint_identifier,
            }
        )
        if capacity_profile == C64_W2_CAPACITY_PROFILE:
            router["per_worker_capacity"] = per_worker_capacity_for_profile(capacity_profile)
    manifest = {
        "schema_version": schema_version,
        "kind": "direct-kimi-worker-generation",
        "deployment_root": str(deployment_root.resolve()),
        "model": EXPECTED_MODEL,
        "source_spec_sha256": spec_sha256,
        "source_proxy_config_sha256": proxy_config_sha256,
        "endpoint_bundle_sha256": endpoint_bundle_sha256,
        "workers": [worker.public_record for worker in workers],
        "router": router,
    }
    if capacity_profile == C23_CAPACITY_PROFILE:
        assert source_endpoint_bundle_sha256 is not None and excluded_worker is not None
        manifest.update(
            {
                "selection_profile": C23_SELECTION_PROFILE,
                "source_endpoint_bundle_sha256": source_endpoint_bundle_sha256,
                "excluded_worker": excluded_worker.public_record,
            }
        )
    return manifest


def _atomic_write(
    path: Path,
    raw: bytes,
    *,
    exclusive: bool,
    evidence: _HeldArtifactSet | None = None,
) -> None:
    if not exclusive:
        raise DirectKimiWorkerError("output_overwrite_forbidden")
    absolute = _absolute_path(path, code="output_path_invalid")
    _publish_marked_bundle(
        absolute.parent,
        {absolute.name: raw},
        marker_name=f".{absolute.name}.complete",
        kind=FILE_MARKER_KIND,
        evidence=evidence,
    )


def _marker_body(kind: str, files: dict[str, bytes]) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "kind": kind,
                "files": {
                    name: {"bytes": len(body), "sha256": _sha256_bytes(body)} for name, body in sorted(files.items())
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _write_final_at(parent: int, name: str, body: bytes) -> int:
    if not name or "/" in name or name in {".", ".."}:
        raise DirectKimiWorkerError("output_path_invalid")
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=parent)
    except FileExistsError as error:
        raise DirectKimiWorkerError("output_already_exists") from error
    except OSError as error:
        raise DirectKimiWorkerError("output_publish_failed") from error
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(body)
        while view:
            count = os.write(descriptor, view)
            if count < 1:
                raise DirectKimiWorkerError("output_write_failed")
            view = view[count:]
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            observed.extend(chunk)
        held = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(held.st_mode)
            or held.st_uid != os.getuid()
            or stat.S_IMODE(held.st_mode) != 0o600
            or held.st_nlink != 1
            or held.st_size != len(body)
            or held.st_dev != visible.st_dev
            or held.st_ino != visible.st_ino
            or bytes(observed) != body
        ):
            raise DirectKimiWorkerError("output_write_changed")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _publish_marked_bundle(
    parent_path: Path,
    files: dict[str, bytes],
    *,
    marker_name: str,
    kind: str,
    evidence: _HeldArtifactSet | None = None,
) -> None:
    parent_path = _absolute_path(parent_path, code="output_parent_invalid")
    try:
        parent_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as error:
        raise DirectKimiWorkerError("output_parent_invalid") from error
    if (
        not files
        or marker_name in files
        or not marker_name
        or "/" in marker_name
        or marker_name in {".", ".."}
        or len(set(files)) != len(files)
    ):
        raise DirectKimiWorkerError("output_path_invalid")
    marker = _marker_body(kind, files)
    parent, parent_identity = _open_private_directory(parent_path, code="output_parent_invalid")
    descriptors: dict[str, int] = {}
    marker_committed = False
    try:
        existing = []
        for name in (*files, marker_name):
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            existing.append(name)
        if existing:
            if set(existing) == {*files, marker_name}:
                observed_marker = _read_private_at(
                    parent,
                    marker_name,
                    invalid_code="output_existing_invalid",
                    changed_code="output_existing_changed",
                )
                observed_files = {
                    name: _read_private_at(
                        parent,
                        name,
                        invalid_code="output_existing_invalid",
                        changed_code="output_existing_changed",
                    )
                    for name in files
                }
                _validate_private_directory(
                    parent_path,
                    parent,
                    parent_identity,
                    code="output_existing_changed",
                )
                if observed_marker == marker and observed_files == files:
                    if evidence is not None:
                        evidence.revalidate()
                    return
            raise DirectKimiWorkerError("output_incomplete_or_conflicting")

        for name, body in files.items():
            descriptors[name] = _write_final_at(parent, name, body)
        _validate_private_directory(parent_path, parent, parent_identity, code="output_parent_changed")
        os.fsync(parent)
        if evidence is not None:
            evidence.revalidate()
        # The marker name is the commit point.  Once its O_EXCL creation is
        # attempted, any uncertain failure is publication-indeterminate and
        # callers may only adopt an exact complete bundle or choose a fresh
        # output namespace.
        marker_committed = True
        descriptors[marker_name] = _write_final_at(parent, marker_name, marker)
        for name, expected in {**files, marker_name: marker}.items():
            descriptor = descriptors[name]
            held = os.fstat(descriptor)
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            os.lseek(descriptor, 0, os.SEEK_SET)
            observed = bytearray()
            while chunk := os.read(descriptor, 1 << 20):
                observed.extend(chunk)
            if held.st_dev != visible.st_dev or held.st_ino != visible.st_ino or bytes(observed) != expected:
                raise DirectKimiWorkerError("output_publication_indeterminate")
        os.fsync(parent)
        if evidence is not None:
            evidence.revalidate()
        _validate_private_directory(
            parent_path,
            parent,
            parent_identity,
            code="output_publication_indeterminate",
        )
    except OSError as error:
        code = "output_publication_indeterminate" if marker_committed else "output_publish_failed"
        raise DirectKimiWorkerError(code) from error
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)
        os.close(parent)


def _read_marked_bundle(
    parent_path: Path,
    *,
    marker_name: str,
    kind: str,
    expected_file_count: int,
    code: str,
    held: _HeldArtifactSet | None = None,
) -> dict[str, bytes]:
    """Read a marker-authorized bundle through one retained directory fd."""

    parent_path = _absolute_path(parent_path, code=code)
    if held is not None:
        marker_body = _read_bound_file(
            parent_path / marker_name,
            maximum_bytes=MAX_RUN_BINDING_BYTES,
            private=True,
            code=code,
            held=held,
        )
        try:
            marker = json.loads(marker_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DirectKimiWorkerError(code) from error
        records = marker.get("files") if isinstance(marker, dict) else None
        if (
            not isinstance(marker, dict)
            or set(marker) != {"schema_version", "kind", "files"}
            or marker.get("schema_version") != 1
            or marker.get("kind") != kind
            or not isinstance(records, dict)
            or len(records) != expected_file_count
            or marker_name in records
            or any(
                not isinstance(name, str)
                or not name
                or "/" in name
                or name in {".", ".."}
                or not isinstance(record, dict)
                or set(record) != {"bytes", "sha256"}
                or type(record.get("bytes")) is not int
                or not 0 <= record["bytes"] <= MAX_RUN_BINDING_BYTES
                or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
                for name, record in records.items()
            )
        ):
            raise DirectKimiWorkerError(code)
        bodies = {
            name: _read_bound_file(
                parent_path / name,
                maximum_bytes=MAX_RUN_BINDING_BYTES,
                private=True,
                code=code,
                held=held,
            )
            for name in records
        }
        if any(
            len(bodies[name]) != record["bytes"] or _sha256_bytes(bodies[name]) != record["sha256"]
            for name, record in records.items()
        ):
            raise DirectKimiWorkerError(code)
        held.revalidate()
        return bodies

    parent, parent_identity = _open_private_directory(parent_path, code=code)
    try:
        marker_body = _read_private_at(
            parent,
            marker_name,
            invalid_code=code,
            changed_code=f"{code}_changed",
        )
        try:
            marker = json.loads(marker_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DirectKimiWorkerError(code) from error
        records = marker.get("files") if isinstance(marker, dict) else None
        if (
            not isinstance(marker, dict)
            or set(marker) != {"schema_version", "kind", "files"}
            or marker.get("schema_version") != 1
            or marker.get("kind") != kind
            or not isinstance(records, dict)
            or len(records) != expected_file_count
            or marker_name in records
            or any(
                not isinstance(name, str)
                or not name
                or "/" in name
                or name in {".", ".."}
                or not isinstance(record, dict)
                or set(record) != {"bytes", "sha256"}
                or type(record.get("bytes")) is not int
                or not 0 <= record["bytes"] <= MAX_RUN_BINDING_BYTES
                or SHA256_RE.fullmatch(str(record.get("sha256", ""))) is None
                for name, record in records.items()
            )
        ):
            raise DirectKimiWorkerError(code)
        bodies = {
            name: _read_private_at(
                parent,
                name,
                invalid_code=code,
                changed_code=f"{code}_changed",
            )
            for name in records
        }
        if any(
            len(bodies[name]) != record["bytes"] or _sha256_bytes(bodies[name]) != record["sha256"]
            for name, record in records.items()
        ):
            raise DirectKimiWorkerError(code)
        _validate_private_directory(
            parent_path,
            parent,
            parent_identity,
            code=f"{code}_changed",
        )
        return bodies
    finally:
        os.close(parent)


def read_published_file(path: Path) -> bytes:
    """Read an exact one-file publication only when its marker authorizes it."""

    absolute = _absolute_path(path, code="published_file_invalid")
    bodies = _read_marked_bundle(
        absolute.parent,
        marker_name=f".{absolute.name}.complete",
        kind=FILE_MARKER_KIND,
        expected_file_count=1,
        code="published_file_invalid",
    )
    if set(bodies) != {absolute.name}:
        raise DirectKimiWorkerError("published_file_invalid")
    return bodies[absolute.name]


def prepare_generation(
    deployment_root: Path,
    output_root: Path,
    manifest_path: Path,
    urls_path: Path,
    ports_path: Path,
    *,
    capacity_profile: str = DEFAULT_CAPACITY_PROFILE,
    endpoint_identifier: str | None = None,
    request_timeout_seconds: int = ROUTER_REQUEST_TIMEOUT_SECONDS,
    excluded_backend_sha256: str | None = None,
) -> dict[str, Any]:
    output_root = _absolute_path(output_root, code="output_parent_invalid")
    publication_paths = tuple(
        _absolute_path(path, code="output_path_invalid") for path in (manifest_path, urls_path, ports_path)
    )
    if (
        any(path.parent != output_root for path in publication_paths)
        or {path.name for path in publication_paths} != GENERATION_FILE_NAMES
        or publication_paths[0].name != GENERATION_MANIFEST_NAME
        or publication_paths[1].name != GENERATION_URLS_NAME
        or publication_paths[2].name != GENERATION_PORTS_NAME
    ):
        raise DirectKimiWorkerError("output_path_invalid")
    source_workers, spec_sha256, proxy_config_sha256, source_endpoint_bundle_sha256 = load_workers(deployment_root)
    workers = source_workers
    excluded_worker = None
    if capacity_profile == C23_CAPACITY_PROFILE:
        if SHA256_RE.fullmatch(str(excluded_backend_sha256 or "")) is None:
            raise DirectKimiWorkerError("excluded_backend_sha256_invalid")
        excluded = [worker for worker in source_workers if worker.backend_sha256 == excluded_backend_sha256]
        if len(excluded) != 1:
            raise DirectKimiWorkerError("excluded_backend_not_found")
        excluded_worker = excluded[0]
        workers = [worker for worker in source_workers if worker.backend_sha256 != excluded_backend_sha256]
    elif excluded_backend_sha256 is not None:
        raise DirectKimiWorkerError("excluded_backend_unexpected")
    endpoint_bundle_sha256 = _endpoint_bundle_sha256(workers)
    router_port, metrics_port = derive_ports(output_root)
    manifest = _manifest(
        deployment_root,
        workers,
        spec_sha256,
        proxy_config_sha256,
        endpoint_bundle_sha256,
        router_port,
        metrics_port,
        capacity_profile=capacity_profile,
        endpoint_identifier=endpoint_identifier,
        request_timeout_seconds=request_timeout_seconds,
        source_endpoint_bundle_sha256=(
            source_endpoint_bundle_sha256 if capacity_profile == C23_CAPACITY_PROFILE else None
        ),
        excluded_worker=excluded_worker,
    )
    files = {
        publication_paths[0].name: (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        publication_paths[1].name: "".join(f"{worker.url}\n" for worker in workers).encode(),
        publication_paths[2].name: f"{router_port}\n{metrics_port}\n".encode(),
    }
    _publish_marked_bundle(
        output_root,
        files,
        marker_name=GENERATION_MARKER_NAME,
        kind=GENERATION_MARKER_KIND,
    )
    return manifest


def validate_manifest_value(
    manifest: object,
    *,
    revalidate_live_source: bool = True,
    held: _HeldArtifactSet | None = None,
) -> dict[str, Any]:
    """Validate one already-snapshotted worker manifest.

    Callers that already hold and authenticate manifest bytes must not reopen a
    pathname merely to validate them.  This pure-value entry point keeps that
    single-snapshot property while retaining the same live-source checks as the
    saved-manifest loader.
    """

    expected_keys = {
        "schema_version",
        "kind",
        "deployment_root",
        "model",
        "source_spec_sha256",
        "source_proxy_config_sha256",
        "endpoint_bundle_sha256",
        "workers",
        "router",
    }
    router = manifest.get("router") if isinstance(manifest, dict) else None
    workers = manifest.get("workers") if isinstance(manifest, dict) else None
    schema_version = manifest.get("schema_version") if isinstance(manifest, dict) else None
    capacity_profile = (
        router.get("capacity_profile")
        if isinstance(router, dict) and "capacity_profile" in router
        else DEFAULT_CAPACITY_PROFILE
    )
    c23_profile = capacity_profile == C23_CAPACITY_PROFILE
    if c23_profile:
        expected_keys.update(
            {
                "selection_profile",
                "source_endpoint_bundle_sha256",
                "excluded_worker",
            }
        )
    try:
        capacity = capacity_for_profile(capacity_profile)
        expected_worker_count = worker_count_for_profile(capacity_profile)
        request_timeout_seconds = validate_request_timeout_seconds(
            router.get("request_timeout_seconds") if isinstance(router, dict) else None
        )
        endpoint_identifier = validate_endpoint_identifier(
            router.get("endpoint_identifier") if isinstance(router, dict) else None,
            capacity_profile=capacity_profile,
        )
    except ValueError as error:
        raise DirectKimiWorkerError("manifest_invalid") from error
    if (
        capacity_profile in (C23_CAPACITY_PROFILE, C64_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE)
        and endpoint_identifier != EXPECTED_ENDPOINT_IDENTIFIER
    ):
        raise DirectKimiWorkerError("manifest_invalid")
    historical_legacy = (
        capacity_profile == LEGACY_CAPACITY_PROFILE
        and schema_version == MANIFEST_SCHEMA_VERSION
        and isinstance(router, dict)
        and router.get("implementation") == HISTORICAL_LEGACY_ROUTER_IMPLEMENTATION
        and router.get("implementation_sha256") == HISTORICAL_LEGACY_ROUTER_SHA256
    )
    current_router_sha256 = _sha256_file(
        Path(__file__).with_name("direct_kimi_router.py"),
        held=held,
    )
    historical_current = (
        isinstance(router, dict)
        and router.get("implementation") == ROUTER_IMPLEMENTATION
        and not c23_profile
        and (
            (
                router.get("implementation_sha256") == HISTORICAL_CURRENT_ROUTER_SHA256
                and request_timeout_seconds == ROUTER_REQUEST_TIMEOUT_SECONDS
            )
            or router.get("implementation_sha256") == HISTORICAL_PRE_C23_ROUTER_SHA256
        )
    )
    current_router = (
        isinstance(router, dict)
        and router.get("implementation") == ROUTER_IMPLEMENTATION
        and router.get("implementation_sha256") == current_router_sha256
    )
    expected_router = {
        "implementation": (HISTORICAL_LEGACY_ROUTER_IMPLEMENTATION if historical_legacy else ROUTER_IMPLEMENTATION),
        "implementation_sha256": (
            HISTORICAL_LEGACY_ROUTER_SHA256 if historical_legacy else router.get("implementation_sha256")
        ),
        "host": "127.0.0.1",
        "port": router.get("port") if isinstance(router, dict) else None,
        "metrics_host": "127.0.0.1",
        "metrics_port": router.get("metrics_port") if isinstance(router, dict) else None,
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "request_timeout_seconds": request_timeout_seconds,
        "max_concurrent_requests": capacity,
        "queue_size": capacity,
        "queue_timeout_seconds": request_timeout_seconds,
        "retries": ROUTER_RETRIES,
    }
    if capacity_profile in (C23_CAPACITY_PROFILE, C64_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE):
        expected_router.update(
            {
                "capacity_profile": capacity_profile,
                "endpoint_identifier": endpoint_identifier,
            }
        )
        if capacity_profile == C64_W2_CAPACITY_PROFILE:
            expected_router["per_worker_capacity"] = W2_PER_WORKER_CAPACITY
    expected_schema_version = {
        LEGACY_CAPACITY_PROFILE: MANIFEST_SCHEMA_VERSION,
        C23_CAPACITY_PROFILE: C23_MANIFEST_SCHEMA_VERSION,
        C64_CAPACITY_PROFILE: C64_MANIFEST_SCHEMA_VERSION,
        C64_W2_CAPACITY_PROFILE: W2_MANIFEST_SCHEMA_VERSION,
    }.get(capacity_profile)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != expected_keys
        or schema_version != expected_schema_version
        or manifest.get("kind") != "direct-kimi-worker-generation"
        or manifest.get("model") != EXPECTED_MODEL
        or manifest.get("source_spec_sha256") != EXPECTED_SPEC_SHA256
        or manifest.get("source_proxy_config_sha256") != EXPECTED_PROXY_CONFIG_SHA256
        or SHA256_RE.fullmatch(str(manifest.get("endpoint_bundle_sha256", ""))) is None
        or not isinstance(workers, list)
        or len(workers) != expected_worker_count
        or not isinstance(router, dict)
        or not (historical_legacy or historical_current or current_router)
        or router != expected_router
        or any(
            not isinstance(router.get(key), int) or isinstance(router.get(key), bool) or not 1 <= router[key] <= 65_535
            for key in ("port", "metrics_port")
        )
    ):
        raise DirectKimiWorkerError("manifest_invalid")
    if any(
        not isinstance(worker, dict)
        or set(worker) != {"backend_sha256", "model_sha256"}
        or any(SHA256_RE.fullmatch(str(worker.get(key, ""))) is None for key in worker)
        for worker in workers
    ):
        raise DirectKimiWorkerError("manifest_invalid")
    backend_sha256s = [worker["backend_sha256"] for worker in workers]
    if (
        len(set(backend_sha256s)) != expected_worker_count
        or backend_sha256s != sorted(backend_sha256s)
        or any(worker["model_sha256"] != _sha256_bytes(EXPECTED_MODEL.encode()) for worker in workers)
        or manifest["endpoint_bundle_sha256"]
        != _sha256_bytes("".join(f"{digest}\n" for digest in backend_sha256s).encode())
    ):
        raise DirectKimiWorkerError("manifest_invalid")
    if c23_profile:
        excluded_worker = manifest.get("excluded_worker")
        source_endpoint_bundle_sha256 = manifest.get("source_endpoint_bundle_sha256")
        if (
            manifest.get("selection_profile") != C23_SELECTION_PROFILE
            or SHA256_RE.fullmatch(str(source_endpoint_bundle_sha256 or "")) is None
            or not isinstance(excluded_worker, dict)
            or set(excluded_worker) != {"backend_sha256", "model_sha256"}
            or SHA256_RE.fullmatch(str(excluded_worker.get("backend_sha256", ""))) is None
            or excluded_worker.get("model_sha256") != _sha256_bytes(EXPECTED_MODEL.encode())
            or excluded_worker["backend_sha256"] in set(backend_sha256s)
            or source_endpoint_bundle_sha256
            != _sha256_bytes(
                "".join(
                    f"{digest}\n" for digest in sorted([*backend_sha256s, excluded_worker["backend_sha256"]])
                ).encode()
            )
        ):
            raise DirectKimiWorkerError("manifest_invalid")
    if revalidate_live_source:
        observed, spec_sha256, proxy_config_sha256, endpoint_bundle_sha256 = load_workers(
            Path(manifest["deployment_root"]),
            held=held,
        )
        observed_workers = observed
        observed_endpoint_bundle_sha256 = endpoint_bundle_sha256
        if c23_profile:
            excluded_backend_sha256 = manifest["excluded_worker"]["backend_sha256"]
            excluded = [worker for worker in observed if worker.backend_sha256 == excluded_backend_sha256]
            if len(excluded) != 1 or excluded[0].public_record != manifest["excluded_worker"]:
                raise DirectKimiWorkerError("source_generation_changed")
            observed_workers = [worker for worker in observed if worker.backend_sha256 != excluded_backend_sha256]
            observed_endpoint_bundle_sha256 = _endpoint_bundle_sha256(observed_workers)
        if (
            [worker.public_record for worker in observed_workers] != workers
            or spec_sha256 != manifest["source_spec_sha256"]
            or proxy_config_sha256 != manifest["source_proxy_config_sha256"]
            or observed_endpoint_bundle_sha256 != manifest["endpoint_bundle_sha256"]
            or (c23_profile and endpoint_bundle_sha256 != manifest["source_endpoint_bundle_sha256"])
        ):
            raise DirectKimiWorkerError("source_generation_changed")
    return manifest


def worker_generation_contract(
    manifest: object,
    *,
    revalidate_live_source: bool = True,
    held: _HeldArtifactSet | None = None,
) -> dict[str, Any]:
    """Return the stable worker-generation semantics for cross-run matching.

    The two partition jobs intentionally bind different loopback ports.  Those
    four local transport fields are excluded only after the complete manifest
    has been validated; worker order and every source/router policy field stay
    bound.
    """

    value = validate_manifest_value(
        manifest,
        revalidate_live_source=revalidate_live_source,
        held=held,
    )
    router = dict(value["router"])
    for key in ("host", "port", "metrics_host", "metrics_port"):
        router.pop(key)
    contract = {
        "schema_version": value["schema_version"],
        "kind": value["kind"],
        "deployment_root": value["deployment_root"],
        "model": value["model"],
        "source_spec_sha256": value["source_spec_sha256"],
        "source_proxy_config_sha256": value["source_proxy_config_sha256"],
        "endpoint_bundle_sha256": value["endpoint_bundle_sha256"],
        "workers": value["workers"],
        "router": router,
    }
    if value["router"].get("capacity_profile") == C23_CAPACITY_PROFILE:
        contract.update(
            {
                "selection_profile": value["selection_profile"],
                "source_endpoint_bundle_sha256": value["source_endpoint_bundle_sha256"],
                "excluded_worker": value["excluded_worker"],
            }
        )
    return contract


def load_saved_manifest(
    path: Path,
    *,
    revalidate_live_source: bool = True,
    held: _HeldArtifactSet | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Return the exact marker-authorized body and its validated value."""

    absolute = _absolute_path(path, code="manifest_invalid")
    bodies = _read_marked_bundle(
        absolute.parent,
        marker_name=GENERATION_MARKER_NAME,
        kind=GENERATION_MARKER_KIND,
        expected_file_count=3,
        code="manifest_invalid",
        held=held,
    )
    if absolute.name != GENERATION_MANIFEST_NAME or set(bodies) != GENERATION_FILE_NAMES:
        raise DirectKimiWorkerError("manifest_invalid")
    body = bodies[absolute.name]
    try:
        manifest = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiWorkerError("manifest_invalid") from error
    return body, validate_manifest_value(
        manifest,
        revalidate_live_source=revalidate_live_source,
        held=held,
    )


def validate_saved_manifest(
    path: Path,
    *,
    revalidate_live_source: bool = True,
    body: bytes | None = None,
    held: _HeldArtifactSet | None = None,
) -> dict[str, Any]:
    published_body, manifest = load_saved_manifest(
        path,
        revalidate_live_source=revalidate_live_source,
        held=held,
    )
    if body is not None and body != published_body:
        raise DirectKimiWorkerError("manifest_invalid")
    return manifest


def _probe_worker(worker: Worker, timeout: float) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{worker.url}/health", timeout=timeout) as response:
            if response.status != 200:
                raise DirectKimiWorkerError("worker_health_failed")
            response.read(1)
        with opener.open(f"{worker.url}/v1/models", timeout=timeout) as response:
            if response.status != 200:
                raise DirectKimiWorkerError("worker_models_failed")
            raw = response.read(MAX_MODELS_BYTES + 1)
    except DirectKimiWorkerError:
        raise
    except Exception as error:
        raise DirectKimiWorkerError("worker_unreachable") from error
    if len(raw) > MAX_MODELS_BYTES:
        raise DirectKimiWorkerError("worker_models_invalid")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiWorkerError("worker_models_invalid") from error
    data = payload.get("data") if isinstance(payload, dict) else None
    models = (
        [item.get("id") for item in data]
        if isinstance(data, list) and all(isinstance(item, dict) for item in data)
        else []
    )
    if len(models) != 1 or not isinstance(models[0], str) or _sha256_bytes(models[0].encode()) != worker.model_sha256:
        raise DirectKimiWorkerError("worker_models_mismatch")


def probe_workers(workers: list[Worker], *, timeout: float = 30.0) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(workers))) as executor:
        futures = [executor.submit(_probe_worker, worker, timeout) for worker in workers]
        for future in concurrent.futures.as_completed(futures):
            future.result()


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)


def _absolute_path(path: Path, *, code: str = "run_binding_invalid") -> Path:
    if not path.is_absolute():
        raise DirectKimiWorkerError(code)
    try:
        absolute = Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as error:
        raise DirectKimiWorkerError(code) from error
    if absolute != path:
        raise DirectKimiWorkerError(code)
    return absolute


def _open_private_directory(
    path: Path,
    *,
    code: str = "run_binding_invalid",
) -> tuple[int, tuple[int, int, int, int]]:
    """Open every directory component without following links and retain the leaf."""

    absolute = _absolute_path(path, code=code)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in absolute.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        identity = _directory_identity(metadata)
        visible = absolute.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or _directory_identity(visible) != identity
            or absolute.resolve(strict=True) != absolute
        ):
            raise DirectKimiWorkerError(code)
    except (OSError, RuntimeError) as error:
        os.close(descriptor)
        raise DirectKimiWorkerError(code) from error
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, identity


def _validate_private_directory(
    path: Path,
    descriptor: int,
    expected: tuple[int, int, int, int],
    *,
    code: str = "run_binding_changed",
) -> None:
    try:
        held = os.fstat(descriptor)
        visible = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise DirectKimiWorkerError(code) from error
    if (
        _directory_identity(held) != expected
        or _directory_identity(visible) != expected
        or not stat.S_ISDIR(held.st_mode)
        or held.st_uid != os.getuid()
        or stat.S_IMODE(held.st_mode) != 0o700
        or resolved != path
    ):
        raise DirectKimiWorkerError(code)


def _read_private_at(
    directory: int,
    name: str,
    *,
    invalid_code: str = "run_binding_invalid",
    changed_code: str = "run_binding_changed",
) -> bytes:
    if not name or "/" in name or name in {".", ".."}:
        raise DirectKimiWorkerError(invalid_code)
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as error:
        raise DirectKimiWorkerError(invalid_code) from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > MAX_RUN_BINDING_BYTES
        ):
            raise DirectKimiWorkerError(invalid_code)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > MAX_RUN_BINDING_BYTES:
                raise DirectKimiWorkerError(invalid_code)
        after = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except DirectKimiWorkerError:
        raise
    except OSError as error:
        raise DirectKimiWorkerError(changed_code) from error
    finally:
        os.close(descriptor)
    if (
        _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(visible)
        or len(body) != after.st_size
    ):
        raise DirectKimiWorkerError(changed_code)
    return bytes(body)


def _canonical_json(value: Any, *, newline: bool = False) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DirectKimiWorkerError("run_binding_invalid") from error
    return encoded + (b"\n" if newline else b"")


def validate_run_binding_bytes(
    identity_body: bytes,
    invocations_body: bytes,
    provenance_body: bytes,
) -> tuple[str, str, dict[str, Any]]:
    """Validate one already-retained direct-Kimi invocation snapshot."""

    try:
        envelope = json.loads(identity_body)
        invocations = [json.loads(line) for line in invocations_body.splitlines() if line.strip()]
        provenance_lines = provenance_body.decode("utf-8").splitlines()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiWorkerError("run_binding_invalid") from error
    identity = envelope.get("identity") if isinstance(envelope, dict) else None
    identity_sha256 = envelope.get("eval_run_identity_sha256") if isinstance(envelope, dict) else None
    role = identity.get("role") if isinstance(identity, dict) else None
    source = identity.get("source") if isinstance(identity, dict) else None
    deployment = identity.get("deployment") if isinstance(identity, dict) else None
    worker_manifest = deployment.get("worker_manifest") if isinstance(deployment, dict) else None
    router = deployment.get("router") if isinstance(deployment, dict) else None
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"schema_version", "eval_run_identity_sha256", "identity"}
        or envelope.get("schema_version") != 1
        or not isinstance(identity, dict)
        or role
        not in {
            "kimi-direct-smoke",
            "kimi-direct-capacity-smoke",
            "kimi-direct-tb4",
            "kimi-direct-tb4-diagnostic",
            "kimi-direct-tb4-sandoq-fallback-diagnostic",
            "kimi-direct-mobius",
        }
        or not isinstance(source, dict)
        or source.get("sandbox_provider", "vmvm") not in {"sandoq", "vmvm"}
        or not isinstance(deployment, dict)
        or deployment.get("kind") != "direct_kimi"
        or not isinstance(worker_manifest, dict)
        or set(worker_manifest) != {"path", "sha256"}
        or not isinstance(worker_manifest.get("path"), str)
        or not Path(worker_manifest["path"]).is_absolute()
        or SHA256_RE.fullmatch(str(worker_manifest.get("sha256", ""))) is None
        or SHA256_RE.fullmatch(str(deployment.get("endpoint_bundle_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(deployment.get("spec_sha256", ""))) is None
        or not isinstance(router, dict)
        or not isinstance(identity_sha256, str)
        or SHA256_RE.fullmatch(identity_sha256) is None
        or _sha256_bytes(_canonical_json(identity)) != identity_sha256
    ):
        raise DirectKimiWorkerError("run_binding_invalid")
    records: dict[str, str] = {}
    for line in provenance_lines:
        key, separator, value = line.partition("=")
        if (
            not separator
            or re.fullmatch(r"[a-z][a-z0-9_]*", key) is None
            or not value
            or "\x00" in value
            or key in records
        ):
            raise DirectKimiWorkerError("run_binding_invalid")
        records[key] = value
    invocation = invocations[0] if len(invocations) == 1 else None
    host = records.get("host")
    slurm_job_id = records.get("slurm_job_id")
    if (
        records.get("eval_run_identity_sha256") != identity_sha256
        or records.get("eval_run_role") != role
        or not isinstance(host, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", host) is None
        or re.fullmatch(r"[1-9][0-9]*", str(slurm_job_id or "")) is None
        or not isinstance(invocation, dict)
        or set(invocation)
        != {
            "schema_version",
            "eval_run_identity_sha256",
            "role",
            "resume",
            "host",
            "slurm_job_id",
        }
        or invocation.get("schema_version") != 1
        or invocation.get("eval_run_identity_sha256") != identity_sha256
        or invocation.get("role") != role
        or invocation.get("resume") is not False
        or invocation.get("host") != host
        or invocation.get("slurm_job_id") != slurm_job_id
    ):
        raise DirectKimiWorkerError("run_binding_invalid")
    binding = {
        "schema_version": 1,
        "kind": "kimi-tb4-eval-invocation",
        "eval_run_identity_sha256": identity_sha256,
        "host": host,
        "slurm_job_id": slurm_job_id,
    }
    invocation_identity_sha256 = _sha256_bytes(_canonical_json(binding, newline=True))
    return identity_sha256, invocation_identity_sha256, identity


def _run_binding(
    eval_run_identity: Path,
    eval_invocations: Path,
    provenance: Path,
    *,
    held: _HeldArtifactSet | None = None,
) -> tuple[str, str, dict[str, Any]]:
    paths = tuple(_absolute_path(path) for path in (eval_run_identity, eval_invocations, provenance))
    run_directory = paths[0].parent
    if tuple(path.name for path in paths) != (
        "eval_run_identity.json",
        "eval_invocations.jsonl",
        "provenance.txt",
    ) or any(path.parent != run_directory for path in paths[1:]):
        raise DirectKimiWorkerError("run_binding_invalid")
    owned = held is None
    evidence = held if held is not None else _HeldArtifactSet.create()
    try:
        identity_body = _read_bound_file(
            paths[0],
            maximum_bytes=MAX_RUN_BINDING_BYTES,
            private=True,
            code="run_binding_invalid",
            held=evidence,
        )
        invocations_body = _read_bound_file(
            paths[1],
            maximum_bytes=MAX_RUN_BINDING_BYTES,
            private=True,
            code="run_binding_invalid",
            held=evidence,
        )
        provenance_body = _read_bound_file(
            paths[2],
            maximum_bytes=MAX_RUN_BINDING_BYTES,
            private=True,
            code="run_binding_invalid",
            held=evidence,
        )
        evidence.revalidate()
    finally:
        if owned:
            evidence.close()
    return validate_run_binding_bytes(identity_body, invocations_body, provenance_body)


def _validate_deployment_binding(
    deployment: dict[str, Any],
    manifest_path: Path,
    manifest_sha256: str,
    manifest: dict[str, Any],
) -> None:
    worker = deployment["worker_manifest"]
    router = deployment["router"]
    expected_router = {
        "implementation": manifest["router"]["implementation"],
        "implementation_sha256": manifest["router"]["implementation_sha256"],
        "policy": manifest["router"]["policy"],
        "request_id_headers": manifest["router"]["request_id_headers"],
        "provider_concurrency": manifest["router"]["max_concurrent_requests"],
        "request_timeout_seconds": manifest["router"]["request_timeout_seconds"],
        "retries": manifest["router"]["retries"],
        "worker_count": len(manifest["workers"]),
    }
    if manifest["router"].get("capacity_profile") in (
        C23_CAPACITY_PROFILE,
        C64_CAPACITY_PROFILE,
        C64_W2_CAPACITY_PROFILE,
    ):
        expected_router.update(
            {
                "capacity_profile": manifest["router"]["capacity_profile"],
                "endpoint_identifier": manifest["router"]["endpoint_identifier"],
            }
        )
        if manifest["router"]["capacity_profile"] == C64_W2_CAPACITY_PROFILE:
            expected_router["per_worker_capacity"] = manifest["router"]["per_worker_capacity"]
    if (
        set(router) != set(expected_router)
        or router != expected_router
        or Path(worker["path"]) != _absolute_path(manifest_path)
        or worker["sha256"] != manifest_sha256
        or deployment.get("spec_sha256") != manifest["source_spec_sha256"]
        or deployment.get("endpoint_bundle_sha256") != manifest["endpoint_bundle_sha256"]
        or deployment.get("base_url") != f"http://127.0.0.1:{manifest['router']['port']}/v1"
    ):
        raise DirectKimiWorkerError("run_binding_invalid")


def certify_router(
    manifest_path: Path,
    manifest_sha256: str,
    active_workers: int,
    router_stats_path: Path,
    output: Path,
    *,
    eval_run_identity: Path,
    eval_invocations: Path,
    provenance: Path,
) -> dict[str, Any]:
    held = _HeldArtifactSet.create()
    try:
        eval_run_identity_sha256, invocation_identity_sha256, identity = _run_binding(
            eval_run_identity,
            eval_invocations,
            provenance,
            held=held,
        )
        manifest_body, manifest = load_saved_manifest(manifest_path, held=held)
        if SHA256_RE.fullmatch(manifest_sha256) is None or _sha256_bytes(manifest_body) != manifest_sha256:
            raise DirectKimiWorkerError("manifest_sha256_mismatch")
        _validate_deployment_binding(identity["deployment"], manifest_path, manifest_sha256, manifest)
        capacity_profile = manifest["router"].get("capacity_profile", DEFAULT_CAPACITY_PROFILE)
        expected_worker_count = worker_count_for_profile(capacity_profile)
        if active_workers != expected_worker_count:
            raise DirectKimiWorkerError("active_worker_count_mismatch")
        try:
            router_stats = json.loads(
                _read_bound_file(
                    router_stats_path,
                    maximum_bytes=MAX_MODELS_BYTES,
                    private=True,
                    code="router_stats_invalid",
                    held=held,
                )
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DirectKimiWorkerError("router_stats_invalid") from error
        capacity = capacity_for_profile(capacity_profile)
        c23_profile = capacity_profile == C23_CAPACITY_PROFILE
        c64_profile = capacity_profile == C64_CAPACITY_PROFILE
        w2_profile = capacity_profile == C64_W2_CAPACITY_PROFILE
        profiled_capacity = c23_profile or c64_profile or w2_profile
        capacity_smoke = identity["role"] == "kimi-direct-capacity-smoke"
        w2_required = capacity_smoke or identity["role"] == "kimi-direct-mobius"
        w2_tb4 = identity["role"] == "kimi-direct-tb4" and w2_profile
        w2_allowed = w2_required or identity["role"] == "kimi-direct-tb4"
        c23_role_allowed = identity["role"] in {"kimi-direct-smoke", "kimi-direct-tb4"}
        if (
            (w2_required and not w2_profile)
            or (w2_profile and not w2_allowed)
            or (not w2_required and c23_profile and not c23_role_allowed)
            or (not w2_required and not w2_tb4 and not c23_profile and capacity_profile != LEGACY_CAPACITY_PROFILE)
        ):
            raise DirectKimiWorkerError("run_binding_invalid")
        expected_stats_keys = {
            "schema_version",
            "kind",
            "implementation",
            "policy",
            "request_id_headers",
            "request_timeout_seconds",
            "retries",
            "worker_count",
            "active_workers",
            "active_requests",
            "max_active_requests",
            "total_requests",
            "chat_requests",
            "missing_session_rejections",
            "upstream_failures",
            "worker_request_counts",
        }
        if profiled_capacity:
            expected_stats_keys.update(
                {
                    "capacity_profile",
                    "endpoint_identifier",
                    "configured_capacity",
                    "configured_per_worker_capacity",
                    "active_forwarded_requests",
                    "active_chat_requests",
                    "max_active_chat_requests",
                    "capacity_rejections",
                    "queue_overflow_rejections",
                    "route_tracking_overflows",
                    "cross_route_anomalies",
                    "tracked_sessions",
                    "worker_active_request_counts",
                    "worker_session_counts",
                    "active_worker_waiters",
                    "worker_waiting_request_counts",
                }
            )
        if w2_profile:
            expected_stats_keys.update(
                {
                    "max_active_forwarded_requests",
                    "worker_max_active_request_counts",
                    "worker_queue_timeouts",
                    "upstream_http_429",
                    "upstream_http_5xx",
                }
            )
        counts = router_stats.get("worker_request_counts") if isinstance(router_stats, dict) else None
        worker_active_counts = (
            router_stats.get("worker_active_request_counts") if isinstance(router_stats, dict) else None
        )
        worker_session_counts = router_stats.get("worker_session_counts") if isinstance(router_stats, dict) else None
        worker_waiting_counts = (
            router_stats.get("worker_waiting_request_counts") if isinstance(router_stats, dict) else None
        )
        worker_max_active_counts = (
            router_stats.get("worker_max_active_request_counts") if isinstance(router_stats, dict) else None
        )
        expected_stats_schema = 4 if w2_profile else 3 if (c23_profile or c64_profile) else 1
        if (
            not isinstance(router_stats, dict)
            or set(router_stats) != expected_stats_keys
            or router_stats.get("schema_version") != expected_stats_schema
            or router_stats.get("kind") != "direct-kimi-transparent-router"
            or router_stats.get("implementation") != manifest["router"]["implementation"]
            or router_stats.get("policy") != ROUTER_POLICY
            or router_stats.get("request_id_headers") != list(ROUTER_REQUEST_ID_HEADERS)
            or router_stats.get("request_timeout_seconds") != manifest["router"]["request_timeout_seconds"]
            or router_stats.get("retries") != ROUTER_RETRIES
            or router_stats.get("worker_count") != expected_worker_count
            or router_stats.get("active_workers") != expected_worker_count
            or type(router_stats.get("active_requests")) is not int
            or router_stats.get("active_requests") != 0
            or not isinstance(counts, list)
            or len(counts) != expected_worker_count
            or any(type(value) is not int or value < 0 for value in counts)
            or any(
                type(router_stats.get(key)) is not int or router_stats[key] < 0
                for key in (
                    "max_active_requests",
                    "total_requests",
                    "chat_requests",
                    "missing_session_rejections",
                    "upstream_failures",
                )
            )
            or not 0 <= router_stats["max_active_requests"] <= capacity
            or router_stats["chat_requests"] > router_stats["total_requests"]
            or sum(counts) != router_stats["total_requests"]
            or router_stats["missing_session_rejections"] != 0
            or router_stats["upstream_failures"] != 0
        ):
            raise DirectKimiWorkerError("router_stats_invalid")
        if profiled_capacity and (
            router_stats.get("capacity_profile") != capacity_profile
            or router_stats.get("endpoint_identifier") != manifest["router"]["endpoint_identifier"]
            or router_stats.get("configured_capacity") != capacity
            or type(router_stats.get("configured_per_worker_capacity")) is not int
            or router_stats.get("configured_per_worker_capacity") != per_worker_capacity_for_profile(capacity_profile)
            or type(router_stats.get("active_forwarded_requests")) is not int
            or router_stats.get("active_forwarded_requests") != 0
            or type(router_stats.get("active_chat_requests")) is not int
            or router_stats.get("active_chat_requests") != 0
            or not isinstance(worker_active_counts, list)
            or len(worker_active_counts) != expected_worker_count
            or any(type(value) is not int or value != 0 for value in worker_active_counts)
            or not isinstance(worker_session_counts, list)
            or len(worker_session_counts) != expected_worker_count
            or any(type(value) is not int or value < 0 for value in worker_session_counts)
            or sum(worker_session_counts) != router_stats.get("tracked_sessions")
            or type(router_stats.get("active_worker_waiters")) is not int
            or router_stats.get("active_worker_waiters") != 0
            or not isinstance(worker_waiting_counts, list)
            or len(worker_waiting_counts) != expected_worker_count
            or any(type(value) is not int or value != 0 for value in worker_waiting_counts)
            or any(
                type(router_stats.get(key)) is not int or router_stats[key] < 0
                for key in (
                    "max_active_chat_requests",
                    "capacity_rejections",
                    "queue_overflow_rejections",
                    "route_tracking_overflows",
                    "cross_route_anomalies",
                    "tracked_sessions",
                )
            )
            or router_stats["max_active_chat_requests"] > capacity
            or router_stats["max_active_chat_requests"] > router_stats["max_active_requests"]
            or router_stats["capacity_rejections"] != 0
            or router_stats["queue_overflow_rejections"] != router_stats["capacity_rejections"]
            or router_stats["route_tracking_overflows"] != 0
            or router_stats["cross_route_anomalies"] != 0
            or router_stats["tracked_sessions"] > router_stats["chat_requests"]
        ):
            raise DirectKimiWorkerError("router_stats_invalid")
        if w2_profile and (
            type(router_stats.get("max_active_forwarded_requests")) is not int
            or not 1 <= router_stats["max_active_forwarded_requests"] <= W2_FORWARDED_CAPACITY
            or not isinstance(worker_max_active_counts, list)
            or len(worker_max_active_counts) != expected_worker_count
            or any(
                type(value) is not int or not 0 <= value <= W2_PER_WORKER_CAPACITY for value in worker_max_active_counts
            )
            or router_stats.get("worker_queue_timeouts") != 0
            or router_stats.get("upstream_http_429") != 0
            or router_stats.get("upstream_http_5xx") != 0
            or router_stats["max_active_forwarded_requests"] > router_stats["max_active_requests"]
            or router_stats["max_active_forwarded_requests"] > sum(worker_max_active_counts)
            # The dedicated capacity run must demonstrate saturation.  A
            # scored TB4 run consumes that immutable proof and only has to
            # remain inside the proven per-worker envelope; task/model timing
            # is not expected to reproduce the synthetic peak exactly.
            or (capacity_smoke and router_stats["max_active_forwarded_requests"] != W2_FORWARDED_CAPACITY)
            or (capacity_smoke and any(value != W2_PER_WORKER_CAPACITY for value in worker_max_active_counts))
        ):
            raise DirectKimiWorkerError("router_stats_invalid")
        receipt = {
            "schema_version": 5 if w2_profile else 4 if (c23_profile or c64_profile) else 2,
            "kind": "direct-kimi-router-final",
            "state": "passed",
            "eval_run_identity_sha256": eval_run_identity_sha256,
            "invocation_identity_sha256": invocation_identity_sha256,
            "worker_manifest_sha256": manifest_sha256,
            "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
            "active_workers": active_workers,
            "implementation": manifest["router"]["implementation"],
            "implementation_sha256": manifest["router"]["implementation_sha256"],
            "policy": ROUTER_POLICY,
            "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
            "request_timeout_seconds": manifest["router"]["request_timeout_seconds"],
            "retries": ROUTER_RETRIES,
            "max_active_requests": router_stats["max_active_requests"],
            "total_requests": router_stats["total_requests"],
            "chat_requests": router_stats["chat_requests"],
            "worker_request_counts_sha256": _sha256_bytes((json.dumps(counts, separators=(",", ":")) + "\n").encode()),
            "source_generation_revalidated": True,
        }
        if profiled_capacity:
            assert isinstance(worker_active_counts, list)
            assert isinstance(worker_session_counts, list)
            assert isinstance(worker_waiting_counts, list)
            receipt.update(
                {
                    "capacity_profile": capacity_profile,
                    "endpoint_identifier": manifest["router"]["endpoint_identifier"],
                    "configured_capacity": capacity,
                    "configured_per_worker_capacity": per_worker_capacity_for_profile(capacity_profile),
                    "active_forwarded_requests": router_stats["active_forwarded_requests"],
                    "worker_active_request_counts_sha256": _sha256_bytes(
                        (json.dumps(worker_active_counts, separators=(",", ":")) + "\n").encode()
                    ),
                    "worker_session_counts_sha256": _sha256_bytes(
                        (json.dumps(worker_session_counts, separators=(",", ":")) + "\n").encode()
                    ),
                    "active_worker_waiters": router_stats["active_worker_waiters"],
                    "worker_waiting_request_counts_sha256": _sha256_bytes(
                        (json.dumps(worker_waiting_counts, separators=(",", ":")) + "\n").encode()
                    ),
                    "max_active_chat_requests": router_stats["max_active_chat_requests"],
                    "capacity_rejections": router_stats["capacity_rejections"],
                    "queue_overflow_rejections": router_stats["queue_overflow_rejections"],
                    "route_tracking_overflows": router_stats["route_tracking_overflows"],
                    "cross_route_anomalies": router_stats["cross_route_anomalies"],
                    "tracked_sessions": router_stats["tracked_sessions"],
                }
            )
        if w2_profile:
            assert isinstance(worker_max_active_counts, list)
            receipt.update(
                {
                    "max_active_forwarded_requests": router_stats["max_active_forwarded_requests"],
                    "worker_max_active_request_counts_sha256": _sha256_bytes(
                        (json.dumps(worker_max_active_counts, separators=(",", ":")) + "\n").encode()
                    ),
                    "worker_queue_timeouts": router_stats["worker_queue_timeouts"],
                    "upstream_http_429": router_stats["upstream_http_429"],
                    "upstream_http_5xx": router_stats["upstream_http_5xx"],
                }
            )
        held.revalidate()
        _atomic_write(
            output,
            (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            exclusive=True,
            evidence=held,
        )
        held.revalidate()
        return receipt
    finally:
        held.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--deployment-root", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--urls-output", type=Path, required=True)
    prepare.add_argument("--ports-output", type=Path, required=True)
    prepare.add_argument(
        "--capacity-profile",
        choices=(LEGACY_CAPACITY_PROFILE, C23_CAPACITY_PROFILE, C64_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE),
        default=DEFAULT_CAPACITY_PROFILE,
    )
    prepare.add_argument("--endpoint-identifier")
    prepare.add_argument("--excluded-backend-sha256")
    prepare.add_argument(
        "--request-timeout-seconds",
        type=int,
        choices=tuple(sorted(ALLOWED_REQUEST_TIMEOUT_SECONDS)),
        default=ROUTER_REQUEST_TIMEOUT_SECONDS,
    )
    prepare.add_argument("--probe", action="store_true")
    snapshot = subparsers.add_parser("snapshot-source")
    snapshot.add_argument("--deployment-root", type=Path, required=True)
    snapshot.add_argument("--output-root", type=Path, required=True)
    certify = subparsers.add_parser("certify-router")
    certify.add_argument("--manifest", type=Path, required=True)
    certify.add_argument("--manifest-sha256", required=True)
    certify.add_argument("--active-workers", type=int, required=True)
    certify.add_argument("--router-stats", type=Path, required=True)
    certify.add_argument("--eval-run-identity", type=Path, required=True)
    certify.add_argument("--eval-invocations", type=Path, required=True)
    certify.add_argument("--provenance", type=Path, required=True)
    certify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "snapshot-source":
        snapshot_value = materialize_source_snapshot(args.deployment_root, args.output_root)
        print(
            json.dumps({"endpoint_bundle_sha256": snapshot_value["endpoint_bundle_sha256"], "ok": True}, sort_keys=True)
        )
        return
    if args.command == "certify-router":
        receipt = certify_router(
            args.manifest,
            args.manifest_sha256,
            args.active_workers,
            args.router_stats,
            args.output,
            eval_run_identity=args.eval_run_identity,
            eval_invocations=args.eval_invocations,
            provenance=args.provenance,
        )
        print(json.dumps({"active_workers": receipt["active_workers"], "ok": True}, sort_keys=True))
        return
    manifest = prepare_generation(
        args.deployment_root,
        args.output_root,
        args.manifest,
        args.urls_output,
        args.ports_output,
        capacity_profile=args.capacity_profile,
        endpoint_identifier=args.endpoint_identifier,
        request_timeout_seconds=args.request_timeout_seconds,
        excluded_backend_sha256=args.excluded_backend_sha256,
    )
    if args.probe:
        workers, _, _, _ = load_workers(args.deployment_root)
        if args.capacity_profile == C23_CAPACITY_PROFILE:
            workers = [worker for worker in workers if worker.backend_sha256 != args.excluded_backend_sha256]
        probe_workers(workers)
    print(
        json.dumps(
            {
                "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
                "manifest_sha256": _sha256_file(args.manifest),
                "ok": True,
                "worker_count": len(manifest["workers"]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
