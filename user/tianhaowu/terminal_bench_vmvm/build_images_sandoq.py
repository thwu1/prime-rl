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
from pathlib import Path

from sandoq_provider.gateway import get_gateway_adapter
from sandoq_provider.secrets import read_secret_file

GATEWAY = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
ENVIRONMENT = "oci-runner-firecracker"
REGISTRY = "588845226011.dkr.ecr.us-east-2.amazonaws.com"
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
UPLOAD_CHUNK = 60_000


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _context_archive(context: Path) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path in sorted(context.rglob("*"), key=lambda item: item.relative_to(context).as_posix()):
            archive.add(path, arcname=path.relative_to(context).as_posix(), recursive=False)
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
        joined = " ".join(shlex.quote(path) for path in chunks)
        self.exec(
            f"cat {joined} | base64 -d > {shlex.quote(destination + '.tmp')} "
            f"&& mv -f {shlex.quote(destination + '.tmp')} {shlex.quote(destination)} "
            f"&& rm -f -- {joined}",
            timeout=120,
        )

    def stop(self) -> None:
        if self.info is None:
            return
        response = self.gateway.delete_session(self.info.session_id, timeout=180, prime=True)
        if response.verified_http_status not in {200, 202, 204, 404}:
            raise RuntimeError("Sandoq build session cleanup was not verified")
        self.info = None


def _build_one(row: dict[str, str], args: argparse.Namespace) -> None:
    status = args.status_root / f"{row['context_sha256']}.{row['role']}.json"
    if status.is_file():
        existing = json.loads(status.read_text())
        if (
            existing.get("state") == "success"
            and existing.get("image") == row["image"]
            and isinstance(existing.get("digest"), str)
            and SHA256.fullmatch(existing["digest"]) is not None
        ):
            return

    session = Session(read_secret_file(args.token_file, "Sandoq build token", RuntimeError))
    build_id = uuid.uuid4().hex
    root = f"/tmp/frontier-build-{build_id}"
    try:
        session.start()
        session.upload(f"{root}/context.tar.gz", _context_archive(Path(row["context"])))
        session.upload(f"{root}/ecr-token", read_secret_file(args.ecr_push_token_file, "ECR push token", RuntimeError).encode())
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
        session.exec(
            f"setsid bash -lc {shlex.quote(inner)} </dev/null >/dev/null 2>&1 & echo started",
            timeout=30,
        )
        deadline = time.monotonic() + args.build_timeout
        while time.monotonic() < deadline:
            result = session.exec(
                f"if test -f {shlex.quote(root + '/status')}; then "
                f"printf 'done:'; cat {shlex.quote(root + '/status')}; else echo running; fi",
                timeout=30,
            )
            output = str(result.get("stdout", "")).strip()
            if output.startswith("done:"):
                if output != "done:0":
                    raise RuntimeError("Sandoq image build failed")
                digest_result = session.exec(f"cat {shlex.quote(root + '/digest')}", timeout=30)
                digest = str(digest_result.get("stdout", "")).strip()
                if SHA256.fullmatch(digest) is None:
                    raise RuntimeError("Sandoq image build returned an invalid digest")
                _atomic_json(status, {**row, "state": "success", "digest": digest})
                return
            time.sleep(10)
        raise TimeoutError("Sandoq image build exceeded its deadline")
    finally:
        session.stop()


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
    args = parser.parse_args()
    if args.array_count < 1 or not 0 <= args.array_index < args.array_count:
        parser.error("array index must be within array count")
    dataset_dir = args.dataset_dir.resolve(strict=True)
    args.status_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    rows = _parse_plan(args.plan, dataset_dir, args.array_index, args.array_count)
    passed = 0
    for row_index, row in enumerate(rows):
        try:
            _build_one(row, args)
            passed += 1
            print(f"row={row_index} state=success", flush=True)
        except Exception as error:
            print(f"row={row_index} state=failed type={type(error).__name__}", flush=True)
    print(f"build_summary selected={len(rows)} passed={passed} failed={len(rows) - passed}")
    if passed != len(rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
