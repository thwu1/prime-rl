#!/usr/bin/env python3
"""Certify that full-size Sandoq Firecracker exposes its native tunnel port."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sandoq_provider.gateway import get_gateway_adapter

ENVIRONMENT = "oci-runner-firecracker"
KIND = "sandoq-firecracker-tunnel-capability"
EXPECTED_PORT_NAMES = ["exec", "tunnel"]
BASE_URL = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
MAX_RECEIPT_BYTES = 64 * 1024


class FullTunnelProbeError(RuntimeError):
    """A task-free full-environment tunnel capability check failed."""


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _publish_private(path: Path, value: Mapping[str, object]) -> None:
    body = _canonical_json(value)
    if len(body) > MAX_RECEIPT_BYTES or path.name != "receipt.json" or not path.is_absolute():
        raise FullTunnelProbeError("probe_output_invalid")
    try:
        parent = path.parent.resolve(strict=True)
        metadata = path.parent.lstat()
    except OSError as error:
        raise FullTunnelProbeError("probe_output_invalid") from error
    if (
        parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or os.path.lexists(path)
    ):
        raise FullTunnelProbeError("probe_output_invalid")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def run_probe(*, output: Path, gateway: Any | None = None) -> dict[str, object]:
    job_id = os.environ.get("SLURM_JOB_ID", "")
    if re.fullmatch(r"[1-9][0-9]*", job_id) is None or any(
        os.environ.get(name)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "SANDOQ_TUNNEL_HTTPS_PROXY",
            "SANDOQ_AUTH_TOKEN",
            "FIRECRACKER_KEY",
        )
    ):
        raise FullTunnelProbeError("probe_environment_invalid")
    owner = os.environ.get("USER", "")
    if re.fullmatch(r"[A-Za-z0-9._-]+", owner) is None:
        raise FullTunnelProbeError("probe_environment_invalid")

    adapter = gateway or get_gateway_adapter(BASE_URL, f"{owner}-full-tunnel-capability")
    session = None
    cleanup_verified = False
    try:
        session = adapter.create_session(
            ENVIRONMENT,
            "5m",
            f"full-tunnel-capability-{job_id}",
            timeout=600,
        )
        ports = getattr(session, "port_urls", None)
        if not isinstance(ports, dict) or sorted(ports) != EXPECTED_PORT_NAMES:
            raise FullTunnelProbeError("probe_tunnel_capability_invalid")
    finally:
        if session is not None:
            deletion = adapter.delete_session(session.session_id, timeout=180, prime=True)
            cleanup_verified = getattr(deletion, "verified_http_status", None) == 404
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    if not cleanup_verified:
        raise FullTunnelProbeError("probe_cleanup_unverified")
    receipt: dict[str, object] = {
        "schema_version": 1,
        "kind": KIND,
        "state": "passed",
        "environment": ENVIRONMENT,
        "port_names": EXPECTED_PORT_NAMES,
        "create_session_verified": True,
        "tunnel_available": True,
        "cleanup_verified": True,
        "slurm_job_id": job_id,
    }
    _publish_private(output, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        receipt = run_probe(output=_parser().parse_args(argv).output)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        print('{"kind":"sandoq-firecracker-tunnel-capability","state":"blocked"}', file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "kind": KIND,
                "receipt_sha256": hashlib.sha256(_canonical_json(receipt)).hexdigest(),
                "state": "passed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
