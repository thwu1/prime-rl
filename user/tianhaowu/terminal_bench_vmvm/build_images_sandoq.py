#!/usr/bin/env python3
"""Build Harbor OCI images inside disposable Sandoq Firecracker sessions."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shlex
import tarfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from sandoq_provider.gateway import get_gateway_adapter
from sandoq_provider.secrets import read_secret_file

GATEWAY = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
ENVIRONMENT = "oci-runner-firecracker"
REGISTRY = "588845226011.dkr.ecr.us-east-2.amazonaws.com"
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
QUOTED_HEREDOC = re.compile(r"<<(-?)\s*(['\"])([A-Za-z_][A-Za-z0-9_]*)\2\s*$")
ANY_HEREDOC = re.compile(r"<<-?\s*['\"]?[A-Za-z_][A-Za-z0-9_]*['\"]?")
UPLOAD_CHUNK = 60_000
_T = TypeVar("_T")


class BuildStageError(RuntimeError):
    """A redacted, stable image-build failure classification."""

    def __init__(
        self,
        stage: str,
        cause_type: str,
        *,
        cleanup_verified: bool,
        diagnostic_class: str | None = None,
        diagnostic_sha256: str | None = None,
    ) -> None:
        super().__init__(f"Sandoq image build failed during {stage} ({cause_type})")
        self.stage = stage
        self.cause_type = cause_type
        self.cleanup_verified = cleanup_verified
        self.diagnostic_class = diagnostic_class
        self.diagnostic_sha256 = diagnostic_sha256


def _call_stage(stage: str, operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except BuildStageError:
        raise
    except Exception as error:
        raise BuildStageError(stage, type(error).__name__, cleanup_verified=False) from error


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    _ensure_private_dir(path.parent)
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    _ensure_private_dir(path.parent)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _classify_build_log(payload: bytes) -> str:
    text = payload.decode(errors="replace").lower()
    patterns = (
        ("disk_exhausted", ("no space left on device", "disk quota exceeded")),
        ("memory_exhausted", ("out of memory", "cannot allocate memory", "exit code: 137")),
        ("registry_auth", ("unauthorized", "authentication required", "denied: requested access")),
        (
            "network_resolution",
            ("temporary failure in name resolution", "could not resolve host", "name or service not known"),
        ),
        ("network_timeout", ("connection timed out", "operation timed out", "i/o timeout")),
        ("missing_build_input", ("no such file or directory", "not found in build context")),
        ("package_resolution", ("no matching distribution found", "unable to locate package")),
        ("dockerfile_syntax", ("unknown instruction", "dockerfile parse error")),
    )
    for label, needles in patterns:
        if any(needle in text for needle in needles):
            return label
    return "unclassified"


def _capture_build_failure(
    session: "Session",
    root: str,
    row: dict[str, str],
    status_root: Path,
) -> tuple[str, str]:
    result = session.exec(f"tail -c 65536 {shlex.quote(root + '/build.log')}", timeout=30)
    payload = (str(result.get("stdout", "")) + str(result.get("stderr", ""))).encode(errors="replace")
    digest = hashlib.sha256(payload).hexdigest()
    path = status_root / "failure-logs" / f"{row['context_sha256']}.{row['role']}.log"
    _atomic_bytes(path, payload)
    return _classify_build_log(payload), digest


def _podman_compatible_dockerfile(source: str) -> str:
    """Lower quoted Dockerfile heredocs to portable shell pipelines."""

    lines = source.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        marker = QUOTED_HEREDOC.search(lines[index])
        if marker is None:
            if ANY_HEREDOC.search(lines[index]) is not None:
                raise ValueError("Dockerfile contains an unsupported heredoc form")
            output.append(lines[index])
            index += 1
            continue

        start = index
        while start > 0 and lines[start - 1].rstrip().endswith("\\"):
            start -= 1
        if not lines[start].lstrip().upper().startswith("RUN "):
            raise ValueError("Dockerfile heredoc must belong to a RUN instruction")
        delimiter = marker.group(3)
        strip_tabs = marker.group(1) == "-"
        terminator = index + 1
        while terminator < len(lines):
            candidate = lines[terminator].lstrip("\t") if strip_tabs else lines[terminator]
            if candidate == delimiter:
                break
            terminator += 1
        if terminator == len(lines):
            raise ValueError("Dockerfile heredoc has no terminator")

        logical_parts = []
        for part_index in range(start, index + 1):
            part = lines[part_index].strip()
            if part_index < index:
                if not part.endswith("\\"):
                    raise ValueError("Dockerfile heredoc continuation is malformed")
                part = part[:-1].rstrip()
            logical_parts.append(part)
        logical = " ".join(logical_parts)
        logical_marker = QUOTED_HEREDOC.search(logical)
        if logical_marker is None:
            raise ValueError("Dockerfile heredoc marker could not be normalized")
        command_line = logical[: logical_marker.start()].rstrip()
        run_match = re.fullmatch(r"RUN\s+(.+)", command_line, flags=re.IGNORECASE)
        if run_match is None:
            raise ValueError("Dockerfile heredoc RUN instruction is malformed")
        shell = run_match.group(1)
        operators = list(re.finditer(r"&&|\|\||;|\|", shell))
        if operators:
            split = operators[-1].end()
            prefix = shell[:split] + " "
            command = shell[split:].strip()
        else:
            prefix = ""
            command = shell.strip()
        if not command:
            raise ValueError("Dockerfile heredoc command is empty")

        body_lines = lines[index + 1 : terminator]
        if strip_tabs:
            body_lines = [line.lstrip("\t") for line in body_lines]
        body = ("\n".join(body_lines) + "\n").encode()
        encoded = base64.b64encode(body).decode()
        lowered = f"RUN {prefix}printf %s {shlex.quote(encoded)} | base64 -d | {command}"
        continued_prefix_lines = index - start
        if continued_prefix_lines:
            del output[-continued_prefix_lines:]
        output.append(lowered)
        index = terminator + 1
    return "\n".join(output) + ("\n" if source.endswith("\n") else "")


def _context_archive(context: Path) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path in sorted(context.rglob("*"), key=lambda item: item.relative_to(context).as_posix()):
            relative = path.relative_to(context).as_posix()
            if relative == "Dockerfile" and path.is_file():
                payload = _podman_compatible_dockerfile(path.read_text()).encode()
                info = archive.gettarinfo(str(path), arcname=relative)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            else:
                archive.add(path, arcname=relative, recursive=False)
    return output.getvalue()


def _parse_plan(path: Path, dataset_dir: Path, index: int, count: int) -> list[dict[str, str]]:
    rows = []
    for line_number, raw in enumerate(path.read_text().splitlines()):
        if not raw.strip() or line_number % count != index:
            continue
        fields = raw.split("\t")
        if len(fields) != 5:
            raise ValueError("build plan contains an invalid row")
        task, role, context_sha256, context_raw, image = fields
        context = Path(context_raw).resolve(strict=True)
        if (
            re.fullmatch(r"[A-Za-z0-9._-]+", task) is None
            or role not in {"agent", "verifier"}
            or re.fullmatch(r"[0-9a-f]{64}", context_sha256) is None
            or not context.is_relative_to(dataset_dir)
            or not (context / "Dockerfile").is_file()
            or image.partition("/")[0] != REGISTRY
        ):
            raise ValueError("build plan contains an unsafe row")
        rows.append(
            {
                "task": task,
                "role": role,
                "context_sha256": context_sha256,
                "context": str(context),
                "image": image,
            }
        )
    return rows


class Session:
    def __init__(self, token: str) -> None:
        self.token = token
        self.gateway = get_gateway_adapter(GATEWAY, os.environ.get("USER", "frontier-oracle-builder"))
        self.info = None

    def start(self) -> None:
        self.info = self.gateway.create_session(
            ENVIRONMENT,
            "1h",
            "frontier-oracle-build-" + uuid.uuid4().hex,
            timeout=900,
        )

    def exec(self, script: str, timeout: int = 270) -> dict[str, object]:
        if self.info is None:
            raise RuntimeError("Sandoq build session is not active")
        response = self.gateway.request_json(
            "POST",
            self.info.port_urls["exec"].rstrip("/") + "/v1/exec",
            body={"command": ["bash", "-lc", script], "timeout": timeout},
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=float(timeout + 20),
        )
        if response.status_code != 200:
            raise RuntimeError(f"Sandoq build exec returned HTTP {response.status_code}")
        body = response.body
        exit_code = body.get("exitCode", body.get("exit_code"))
        if exit_code != 0:
            raise RuntimeError(f"Sandoq build exec failed with exit code {exit_code}")
        return body

    def upload(self, destination: str, payload: bytes, timeout: int = 900) -> None:
        encoded = base64.b64encode(payload).decode()
        prefix = f"{destination}.b64."
        self.exec(f"mkdir -p {shlex.quote(str(Path(destination).parent))}", timeout=30)
        chunks = []
        deadline = time.monotonic() + timeout
        for offset in range(0, len(encoded), UPLOAD_CHUNK):
            if time.monotonic() >= deadline:
                raise TimeoutError("Sandoq build upload exceeded its deadline")
            chunk_path = f"{prefix}{len(chunks):08d}"
            chunks.append(chunk_path)
            self.exec(
                f"printf %s {shlex.quote(encoded[offset:offset + UPLOAD_CHUNK])} > {shlex.quote(chunk_path)}",
                timeout=30,
            )
        chunk_glob = shlex.quote(prefix) + "*"
        expected_sha256 = hashlib.sha256(payload).hexdigest()
        self.exec(
            f"cat {chunk_glob} | base64 -d > {shlex.quote(destination + '.tmp')} "
            f"&& test \"$(sha256sum {shlex.quote(destination + '.tmp')} | cut -d' ' -f1)\" = "
            f"{shlex.quote(expected_sha256)} "
            f"&& mv -f {shlex.quote(destination + '.tmp')} {shlex.quote(destination)} "
            f"&& rm -f -- {chunk_glob}",
            timeout=120,
        )

    def stop(self) -> None:
        if self.info is None:
            return
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.gateway.delete_session(self.info.session_id, timeout=180, prime=True)
                if response.verified_http_status not in {200, 202, 204, 404}:
                    raise RuntimeError("Sandoq build session cleanup was not verified")
                self.info = None
                return
            except Exception as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2**attempt)
        assert last_error is not None
        raise last_error


def _build_one(row: dict[str, str], args: argparse.Namespace) -> None:
    status = args.status_root / f"{row['context_sha256']}.{row['role']}.json"
    if status.is_file():
        existing = json.loads(status.read_text())
        if (
            existing.get("state") == "success"
            and existing.get("cleanup_verified") is True
            and existing.get("task") == row["task"]
            and existing.get("role") == row["role"]
            and existing.get("context_sha256") == row["context_sha256"]
            and existing.get("image") == row["image"]
            and isinstance(existing.get("digest"), str)
            and SHA256.fullmatch(existing["digest"]) is not None
        ):
            return

    session = Session(read_secret_file(args.token_file, "Sandoq build token", RuntimeError))
    build_id = uuid.uuid4().hex
    root = f"/tmp/frontier-build-{build_id}"
    success: dict[str, object] | None = None
    failure: BuildStageError | None = None
    try:
        _call_stage("session_start", session.start)
        context_archive = _call_stage("context_archive", lambda: _context_archive(Path(row["context"])))
        _call_stage("context_upload", lambda: session.upload(f"{root}/context.tar.gz", context_archive))
        ecr_token = _call_stage(
            "credential_read",
            lambda: read_secret_file(args.ecr_push_token_file, "ECR push token", RuntimeError).encode(),
        )
        _call_stage("credential_upload", lambda: session.upload(f"{root}/ecr-token", ecr_token))
        local_image = f"localhost/frontier-{row['role']}-{row['context_sha256'][:24]}"
        inner = "\n".join(
            (
                "set +e",
                f"mkdir -p {shlex.quote(root + '/context')}",
                f"tar -xzf {shlex.quote(root + '/context.tar.gz')} -C {shlex.quote(root + '/context')}",
                f"podman login --username AWS --password-stdin {REGISTRY} < {shlex.quote(root + '/ecr-token')} >/dev/null 2>&1",
                f"podman build --network host --pull=missing --tag {shlex.quote(local_image)} {shlex.quote(root + '/context')} > {shlex.quote(root + '/build.log')} 2>&1",
                "rc=$?",
                f"if [ \"$rc\" -eq 0 ]; then podman tag {shlex.quote(local_image)} {shlex.quote(row['image'])}; fi",
                f"if [ \"$rc\" -eq 0 ]; then podman push --digestfile {shlex.quote(root + '/digest')} {shlex.quote(row['image'])} >> {shlex.quote(root + '/build.log')} 2>&1; rc=$?; fi",
                f"printf '%s\\n' \"$rc\" > {shlex.quote(root + '/status.tmp')}",
                f"mv -f {shlex.quote(root + '/status.tmp')} {shlex.quote(root + '/status')}",
            )
        )
        _call_stage(
            "build_start",
            lambda: session.exec(
                f"setsid bash -lc {shlex.quote(inner)} </dev/null >/dev/null 2>&1 & echo started",
                timeout=30,
            ),
        )
        deadline = time.monotonic() + args.build_timeout
        while time.monotonic() < deadline:
            result = _call_stage(
                "build_poll",
                lambda: session.exec(
                    f"if test -f {shlex.quote(root + '/status')}; then "
                    f"printf 'done:'; cat {shlex.quote(root + '/status')}; else echo running; fi",
                    timeout=30,
                ),
            )
            output = str(result.get("stdout", "")).strip()
            if output.startswith("done:"):
                if output != "done:0":
                    diagnostic_class, diagnostic_sha256 = _call_stage(
                        "build_log_capture",
                        lambda: _capture_build_failure(session, root, row, args.status_root),
                    )
                    raise BuildStageError(
                        "image_build",
                        "NonzeroExit",
                        cleanup_verified=False,
                        diagnostic_class=diagnostic_class,
                        diagnostic_sha256=diagnostic_sha256,
                    )
                digest_result = _call_stage(
                    "digest_read",
                    lambda: session.exec(f"cat {shlex.quote(root + '/digest')}", timeout=30),
                )
                digest = str(digest_result.get("stdout", "")).strip()
                if SHA256.fullmatch(digest) is None:
                    raise BuildStageError("digest_validation", "InvalidDigest", cleanup_verified=False)
                success = {**row, "state": "success", "digest": digest, "cleanup_verified": True}
                break
            time.sleep(10)
        if success is None:
            raise BuildStageError("image_build", "TimeoutError", cleanup_verified=False)
    except BuildStageError as error:
        failure = error
    except Exception as error:
        failure = BuildStageError("unexpected", type(error).__name__, cleanup_verified=False)
    finally:
        try:
            session.stop()
        except Exception as error:
            stage = "session_cleanup" if failure is None else f"{failure.stage}+session_cleanup"
            failure = BuildStageError(stage, type(error).__name__, cleanup_verified=False)
        else:
            if failure is not None:
                failure = BuildStageError(
                    failure.stage,
                    failure.cause_type,
                    cleanup_verified=True,
                    diagnostic_class=failure.diagnostic_class,
                    diagnostic_sha256=failure.diagnostic_sha256,
                )
    if failure is not None:
        raise failure
    assert success is not None
    _atomic_json(status, success)


def _build_with_retries(row: dict[str, str], args: argparse.Namespace, row_index: int) -> bool:
    last_error: BuildStageError | None = None
    for attempt in range(1, args.row_attempts + 1):
        try:
            _build_one(row, args)
            print(f"row={row_index} state=success attempts={attempt}", flush=True)
            return True
        except BuildStageError as error:
            last_error = error
            print(
                f"row={row_index} state=retry attempt={attempt} "
                f"stage={error.stage} type={error.cause_type} cleanup_verified={error.cleanup_verified}",
                flush=True,
            )
            if attempt < args.row_attempts:
                time.sleep(min(30, 2 ** (attempt - 1)))
    assert last_error is not None
    status = args.status_root / f"{row['context_sha256']}.{row['role']}.json"
    _atomic_json(
        status,
        {
            **row,
            "state": "failed",
            "attempts": args.row_attempts,
            "failure_stage": last_error.stage,
            "failure_type": last_error.cause_type,
            "cleanup_verified": last_error.cleanup_verified,
            "diagnostic_class": last_error.diagnostic_class,
            "diagnostic_sha256": last_error.diagnostic_sha256,
        },
    )
    print(
        f"row={row_index} state=failed attempts={args.row_attempts} "
        f"stage={last_error.stage} type={last_error.cause_type} "
        f"cleanup_verified={last_error.cleanup_verified}",
        flush=True,
    )
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--status-root", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--ecr-push-token-file", type=Path, required=True)
    parser.add_argument("--array-index", type=int, default=0)
    parser.add_argument("--array-count", type=int, default=1)
    parser.add_argument("--build-timeout", type=int, default=7200)
    parser.add_argument("--row-attempts", type=int, default=3)
    args = parser.parse_args()
    if args.array_count < 1 or not 0 <= args.array_index < args.array_count:
        parser.error("array index must be within array count")
    if args.row_attempts < 1:
        parser.error("row attempts must be positive")
    dataset_dir = args.dataset_dir.resolve(strict=True)
    _ensure_private_dir(args.status_root)
    rows = _parse_plan(args.plan, dataset_dir, args.array_index, args.array_count)
    passed = 0
    for row_index, row in enumerate(rows):
        passed += int(_build_with_retries(row, args, row_index))
    print(f"build_summary selected={len(rows)} passed={passed} failed={len(rows) - passed}")
    if passed != len(rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
