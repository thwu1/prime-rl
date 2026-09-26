"""Deterministically reduce a pinned source-wheel probe to the supported subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import terminal_bench_vmvm.source_wheel_proof as source_wheel_proof_module
import terminal_bench_vmvm.source_wheels as source_wheels_module
from terminal_bench_vmvm.source_wheel_proof import (
    MAX_DISCOVERY_INPUT_BYTES,
    DiscoverySource,
    SourceWheelProofError,
    parse_discovery_input_payload,
)
from terminal_bench_vmvm.source_wheels import (
    SETUP_CFG_GRAMMAR_ID,
    SETUP_PY_GRAMMAR_ID,
    SourceArtifactPolicy,
    canonical_json,
    extract_static_build_requirements,
    sha256_bytes,
)

INPUT_ENTRY_COUNT = 9
OUTPUT_ENTRY_COUNT = 6
OUTPUT_FILENAME = "probe_inputs.private.json"
RECEIPT_FILENAME = "reduction_receipt.json"
RECEIPT_SCHEMA_VERSION = 3
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAX_TIMEOUT_SECONDS = 3_600.0

SourceFetcher = Callable[[DiscoverySource, frozenset[str], float], bytes]
FileIdentity = tuple[int, int, int, int, int, int, int]
CodeBinding = tuple[Path, FileIdentity, str]


class SourceWheelInputReductionError(RuntimeError):
    """A fail-closed reduction error with an aggregate-safe public code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _read_private_input(path: Path, expected_sha256: str) -> bytes:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise SourceWheelInputReductionError("input_sha256_invalid")
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise SourceWheelInputReductionError("input_not_private")
        parent_status = path.parent.lstat()
        path_status = path.lstat()
        if (
            not stat.S_ISDIR(parent_status.st_mode)
            or stat.S_IMODE(parent_status.st_mode) != 0o700
            or not stat.S_ISREG(path_status.st_mode)
            or stat.S_IMODE(path_status.st_mode) not in {0o400, 0o600}
            or path_status.st_nlink != 1
        ):
            raise SourceWheelInputReductionError("input_not_private")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except SourceWheelInputReductionError:
        raise
    except OSError as error:
        raise SourceWheelInputReductionError("input_not_private") from error
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_DISCOVERY_INPUT_BYTES:
                raise SourceWheelInputReductionError("input_size_invalid")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    path_identity = (
        path_status.st_dev,
        path_status.st_ino,
        path_status.st_mode,
        path_status.st_nlink,
        path_status.st_size,
        path_status.st_mtime_ns,
        path_status.st_ctime_ns,
    )
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    payload = b"".join(chunks)
    if not payload or path_identity != before_identity or before_identity != after_identity:
        raise SourceWheelInputReductionError("input_changed")
    if sha256_bytes(payload) != expected_sha256:
        raise SourceWheelInputReductionError("input_sha256_mismatch")
    return payload


def _validate_download_url(url: str, allowed_hosts: frozenset[str], expected_host: str) -> None:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise SourceWheelInputReductionError("source_download_redirect_invalid") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise SourceWheelInputReductionError("source_download_redirect_invalid")


class _PinnedHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str], expected_host: str) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.expected_host = expected_host

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> urllib.request.Request | None:
        _validate_download_url(new_url, self.allowed_hosts, self.expected_host)
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _fetch_source(source: DiscoverySource, allowed_hosts: frozenset[str], timeout: float) -> bytes:
    requested_host = urlsplit(source.url).hostname
    if requested_host is None:
        raise SourceWheelInputReductionError("source_download_failed")
    _validate_download_url(source.url, allowed_hosts, requested_host)
    try:
        opener = urllib.request.build_opener(_PinnedHostRedirectHandler(allowed_hosts, requested_host))
        with opener.open(source.url, timeout=timeout) as response:
            _validate_download_url(response.geturl(), allowed_hosts, requested_host)
            status = response.getcode()
            if status is not None and not 200 <= status < 300:
                raise SourceWheelInputReductionError("source_download_failed")
            payload = bytearray()
            while chunk := response.read(min(1024 * 1024, source.size + 1 - len(payload))):
                payload.extend(chunk)
                if len(payload) > source.size:
                    raise SourceWheelInputReductionError("source_download_integrity_mismatch")
    except SourceWheelInputReductionError:
        raise
    except Exception as error:
        raise SourceWheelInputReductionError("source_download_failed") from error
    return bytes(payload)


def _source_policy(source: DiscoverySource) -> SourceArtifactPolicy:
    return SourceArtifactPolicy(
        distribution=source.distribution,
        version=source.version,
        filename=source.filename,
        url=source.url,
        size=source.size,
        sha256=source.sha256,
        wheel_filename="unused.whl",
        wheel_size=1,
        wheel_sha256="0" * 64,
    )


def _file_identity(status: os.stat_result) -> FileIdentity:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _stable_code_binding(path: Path) -> CodeBinding:
    try:
        canonical = path.resolve(strict=True)
        if not path.is_absolute() or canonical != path:
            raise SourceWheelInputReductionError("code_binding_invalid")
        path_status = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except SourceWheelInputReductionError:
        raise
    except OSError as error:
        raise SourceWheelInputReductionError("code_binding_invalid") from error
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(path_status.st_mode)
        or path_status.st_nlink != 1
        or _file_identity(path_status) != _file_identity(before)
        or _file_identity(before) != _file_identity(after)
    ):
        raise SourceWheelInputReductionError("code_binding_invalid")
    return path, _file_identity(before), digest.hexdigest()


def _executed_code_paths() -> dict[str, Path]:
    workflow_dir = Path(__file__).resolve(strict=True).parents[1]
    return {
        "reducer_cli_sha256": workflow_dir / "reduce_source_wheel_probe_input.py",
        "reducer_implementation_sha256": Path(__file__),
        "discovery_parser_sha256": Path(source_wheel_proof_module.__file__),
        "source_wheel_contract_sha256": Path(source_wheels_module.__file__),
    }


def _capture_code_bindings() -> dict[str, CodeBinding]:
    return {name: _stable_code_binding(path) for name, path in _executed_code_paths().items()}


def _revalidate_code_bindings(bindings: dict[str, CodeBinding]) -> None:
    if set(bindings) != set(_executed_code_paths()):
        raise SourceWheelInputReductionError("code_binding_changed")
    for name, binding in bindings.items():
        try:
            observed = _stable_code_binding(binding[0])
        except SourceWheelInputReductionError as error:
            raise SourceWheelInputReductionError("code_binding_changed") from error
        if observed != binding or _executed_code_paths()[name] != binding[0]:
            raise SourceWheelInputReductionError("code_binding_changed")


def _open_canonical_directory(path: Path, code: str) -> tuple[int, os.stat_result]:
    try:
        canonical = path.resolve(strict=True)
        if not path.is_absolute() or canonical != path:
            raise SourceWheelInputReductionError(code)
        path_status = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptor_status = os.fstat(descriptor)
    except SourceWheelInputReductionError:
        raise
    except OSError as error:
        raise SourceWheelInputReductionError(code) from error
    if (
        not stat.S_ISDIR(path_status.st_mode)
        or _file_identity(path_status)[:4] != _file_identity(descriptor_status)[:4]
    ):
        os.close(descriptor)
        raise SourceWheelInputReductionError(code)
    return descriptor, descriptor_status


def _write_anchored_file(directory_fd: int, name: str, payload: bytes, mode: int) -> None:
    temporary = f".{name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SourceWheelInputReductionError("output_artifact_exists")
        os.rename(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
        status = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(status.st_mode)
            or stat.S_IMODE(status.st_mode) != mode
            or status.st_nlink != 1
            or status.st_size != len(payload)
        ):
            raise SourceWheelInputReductionError("output_artifact_invalid")
    except SourceWheelInputReductionError:
        raise
    except OSError as error:
        raise SourceWheelInputReductionError("output_write_failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _publish_outputs(output_dir: Path, artifacts: tuple[tuple[str, bytes], ...]) -> None:
    parent_fd, parent_status = _open_canonical_directory(output_dir.parent, "output_parent_invalid")
    output_fd = -1
    try:
        try:
            os.stat(output_dir.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SourceWheelInputReductionError("output_directory_not_fresh")
        try:
            os.mkdir(output_dir.name, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
            output_fd = os.open(
                output_dir.name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            os.fchmod(output_fd, 0o700)
            output_status = os.fstat(output_fd)
        except OSError as error:
            raise SourceWheelInputReductionError("output_directory_create_failed") from error
        if not stat.S_ISDIR(output_status.st_mode) or stat.S_IMODE(output_status.st_mode) != 0o700:
            raise SourceWheelInputReductionError("output_directory_not_private")
        for name, payload in artifacts:
            _write_anchored_file(output_fd, name, payload, 0o600)
        try:
            final_parent_fd, final_parent_status = _open_canonical_directory(
                output_dir.parent,
                "output_directory_changed",
            )
        except SourceWheelInputReductionError as error:
            raise SourceWheelInputReductionError("output_directory_changed") from error
        try:
            try:
                final_output_status = os.stat(
                    output_dir.name,
                    dir_fd=final_parent_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise SourceWheelInputReductionError("output_directory_changed") from error
            if (
                _file_identity(parent_status)[:3] != _file_identity(final_parent_status)[:3]
                or not stat.S_ISDIR(final_output_status.st_mode)
                or stat.S_IMODE(final_output_status.st_mode) != 0o700
                or (final_output_status.st_dev, final_output_status.st_ino)
                != (output_status.st_dev, output_status.st_ino)
            ):
                raise SourceWheelInputReductionError("output_directory_changed")
            os.fsync(output_fd)
            os.fsync(final_parent_fd)
        finally:
            os.close(final_parent_fd)
    finally:
        if output_fd >= 0:
            os.close(output_fd)
        os.close(parent_fd)


def reduce_source_wheel_probe_input(
    input_path: Path,
    input_sha256: str,
    output_dir: Path,
    *,
    timeout_seconds: float = 300.0,
    fetch_source: SourceFetcher = _fetch_source,
) -> dict[str, object]:
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise SourceWheelInputReductionError("download_timeout_invalid")
    if output_dir.exists() or output_dir.is_symlink():
        raise SourceWheelInputReductionError("output_directory_not_fresh")
    code_bindings = _capture_code_bindings()
    payload = _read_private_input(input_path, input_sha256)
    try:
        manifest, document = parse_discovery_input_payload(
            payload,
            path=input_path,
            input_sha256=input_sha256,
            expected_entry_count=INPUT_ENTRY_COUNT,
            expected_missing_evidence_sha256=None,
        )
    except SourceWheelProofError as error:
        raise SourceWheelInputReductionError("input_invalid") from error
    if payload != canonical_json(document) + b"\n":
        raise SourceWheelInputReductionError("input_not_canonical")

    allowed_hosts = frozenset(manifest.allowed_hosts)
    sources_by_sha256: dict[str, DiscoverySource] = {}
    source_records_by_sha256: dict[str, object] = {}
    raw_entries = document["entries"]
    assert isinstance(raw_entries, list)
    for entry, raw_entry in zip(manifest.entries, raw_entries, strict=True):
        assert isinstance(raw_entry, dict)
        raw_source = raw_entry["source"]
        existing = source_records_by_sha256.get(entry.source.sha256)
        if existing is not None and existing != raw_source:
            raise SourceWheelInputReductionError("source_identity_conflict")
        sources_by_sha256.setdefault(entry.source.sha256, entry.source)
        source_records_by_sha256.setdefault(entry.source.sha256, raw_source)

    accepted_sources: set[str] = set()
    rejected_sources: set[str] = set()
    for digest, source in sources_by_sha256.items():
        try:
            source_payload = fetch_source(source, allowed_hosts, timeout_seconds)
        except SourceWheelInputReductionError:
            raise
        except Exception as error:
            raise SourceWheelInputReductionError("source_download_failed") from error
        if (
            not isinstance(source_payload, bytes)
            or len(source_payload) != source.size
            or sha256_bytes(source_payload) != digest
        ):
            raise SourceWheelInputReductionError("source_download_integrity_mismatch")
        try:
            extract_static_build_requirements(_source_policy(source), source_payload)
        except RuntimeError:
            rejected_sources.add(digest)
        else:
            accepted_sources.add(digest)

    retained_entries = [
        raw_entry
        for entry, raw_entry in zip(manifest.entries, raw_entries, strict=True)
        if entry.source.sha256 in accepted_sources
    ]
    rejected_entries = len(raw_entries) - len(retained_entries)
    if (
        len(retained_entries) != OUTPUT_ENTRY_COUNT
        or rejected_entries != INPUT_ENTRY_COUNT - OUTPUT_ENTRY_COUNT
        or accepted_sources & rejected_sources
        or accepted_sources | rejected_sources != set(sources_by_sha256)
    ):
        raise SourceWheelInputReductionError("grammar_cardinality_invalid")

    reduced = dict(document)
    reduced["entries"] = retained_entries
    if any(reduced[key] != document[key] for key in document if key != "entries"):
        raise SourceWheelInputReductionError("envelope_changed")
    output_payload = canonical_json(reduced) + b"\n"
    output_sha256 = sha256_bytes(output_payload)
    try:
        reduced_manifest, validated_reduced = parse_discovery_input_payload(
            output_payload,
            path=output_dir / OUTPUT_FILENAME,
            input_sha256=output_sha256,
            expected_entry_count=OUTPUT_ENTRY_COUNT,
            expected_missing_evidence_sha256=manifest.missing_required_evidence_sha256,
        )
    except SourceWheelProofError as error:
        raise SourceWheelInputReductionError("output_invalid") from error
    if validated_reduced != reduced or len(reduced_manifest.entries) != OUTPUT_ENTRY_COUNT:
        raise SourceWheelInputReductionError("output_invalid")
    _revalidate_code_bindings(code_bindings)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "source-wheel-probe-input-reduction",
        "status": "complete",
        "counts": {
            "input_entries": len(raw_entries),
            "output_entries": len(retained_entries),
            "excluded_entries": rejected_entries,
            "distinct_sources": len(sources_by_sha256),
            "accepted_sources": len(accepted_sources),
            "rejected_sources": len(rejected_sources),
            "source_fetches": len(sources_by_sha256),
        },
        "hashes": {
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "missing_required_evidence_sha256": manifest.missing_required_evidence_sha256,
            **{name: binding[2] for name, binding in code_bindings.items()},
        },
        "grammar": {
            "setup_py": SETUP_PY_GRAMMAR_ID,
            "setup_cfg": SETUP_CFG_GRAMMAR_ID,
        },
    }
    receipt_payload = canonical_json(receipt) + b"\n"
    _publish_outputs(
        output_dir,
        (
            (OUTPUT_FILENAME, output_payload),
            (RECEIPT_FILENAME, receipt_payload),
        ),
    )
    return receipt


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        receipt = reduce_source_wheel_probe_input(
            args.input,
            args.input_sha256,
            args.output_dir,
            timeout_seconds=args.timeout_seconds,
        )
    except SourceWheelInputReductionError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, sort_keys=True), flush=True)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "failed", "error_code": "cancelled"}, sort_keys=True), flush=True)
        return 130
    except BaseException:
        print(json.dumps({"status": "failed", "error_code": "unexpected_failure"}, sort_keys=True), flush=True)
        return 1
    print(canonical_json(receipt).decode(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
