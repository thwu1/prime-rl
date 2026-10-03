#!/usr/bin/env python3
"""Mount an agent-toolbox OCI image into a raw Sandoq Firecracker session.

This probe deliberately does not import Prime-RL or Verifiers. It leases the
outer environment through the maintained Sandoq transport, drives Podman over
the authenticated exec endpoint, and always deletes the outer session.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from sandoq_provider.gateway import get_gateway_adapter
from sandoq_provider.secrets import read_secret_file

DEFAULT_BASE_IMAGE = "168653207203.dkr.ecr.us-east-2.amazonaws.com/pt_dockerio/library/ubuntu:24.04"
DEFAULT_ENVIRONMENT = "oci-runner-firecracker"
DEFAULT_GATEWAY = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
DEV_ECR_ACCOUNT = "588845226011"
DEV_ECR_REGISTRY = f"{DEV_ECR_ACCOUNT}.dkr.ecr.us-east-2.amazonaws.com"
PROD_ECR_REGISTRY = "168653207203.dkr.ecr.us-east-2.amazonaws.com"


def _credential_environment() -> dict[str, str]:
    environment = os.environ.copy()
    username = os.environ.get("USER", "")
    certificate = Path("/var/facebook/credentials") / username / "x509" / f"{username}.pem"
    if certificate.is_file():
        environment["THRIFT_TLS_CL_CERT_PATH"] = str(certificate)
        environment["THRIFT_TLS_CL_KEY_PATH"] = str(certificate)
    return environment


def _secret(command: list[str], *, label: str) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=_credential_environment(),
    )
    secret = completed.stdout.strip()
    if completed.returncode or not secret or "\n" in secret or "\r" in secret:
        raise RuntimeError(f"failed to obtain {label}; exit_code={completed.returncode}")
    return secret


def _dev_ecr_password() -> str:
    command = (
        'eval "$(ucloud aws get-credentials --role SSOContainerRegistryReadOnly "$1")" '
        '&& exec aws ecr get-login-password --region "$2"'
    )
    return _secret(
        ["bash", "-lc", command, "agent-toolbox-ecr", DEV_ECR_ACCOUNT, "us-east-2"],
        label="development ECR credential",
    )


def _prod_ecr_password() -> str:
    return _secret(
        ["ucloud", "ecr", "get-credentials", "--prod", "--region", "us-east-2", "--log-level", "error"],
        label="production ECR credential",
    )


def _login_command(registry: str, password: str) -> str:
    encoded = base64.b64encode(password.encode()).decode()
    return f"printf %s {encoded} | base64 -d | podman login --username AWS --password-stdin {registry} >/dev/null"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolbox-image", required=True)
    parser.add_argument("--base-image", default=DEFAULT_BASE_IMAGE)
    parser.add_argument("--environment", default=DEFAULT_ENVIRONMENT)
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path("~/.config/oci-runner/firecracker-token").expanduser(),
    )
    args = parser.parse_args()
    if not args.toolbox_image.startswith(DEV_ECR_REGISTRY + "/"):
        raise ValueError(f"toolbox image must be hosted under {DEV_ECR_REGISTRY}")
    if not re.fullmatch(r"[A-Za-z0-9._:/@+-]+", args.toolbox_image):
        raise ValueError("toolbox image contains unsupported characters")
    if not re.fullmatch(r"[A-Za-z0-9._:/@+-]+", args.base_image):
        raise ValueError("base image contains unsupported characters")

    token = read_secret_file(args.token_file, "Sandoq exec token", RuntimeError)
    dev_password = _dev_ecr_password()
    prod_password = _prod_ecr_password()
    gateway = get_gateway_adapter(args.gateway, os.environ.get("USER", "agent-toolbox-probe"))
    session = None

    def guest(script: str, timeout: int = 270) -> dict[str, object]:
        assert session is not None
        response = gateway.request_json(
            "POST",
            session.port_urls["exec"].rstrip("/") + "/v1/exec",
            body={"command": ["bash", "-lc", script], "timeout": timeout},
            headers={"Authorization": f"Bearer {token}"},
            timeout=float(timeout + 20),
        )
        if response.status_code != 200:
            raise RuntimeError(f"guest exec failed with HTTP {response.status_code}")
        body = response.body
        if body.get("exitCode", body.get("exit_code")) != 0:
            raise RuntimeError(f"guest command failed: {json.dumps(body, sort_keys=True)}")
        return body

    def pull_image(image: str, timeout: float = 1200) -> None:
        pull_id = uuid.uuid4().hex
        pull_dir = f"/tmp/agent-toolbox-pull-{pull_id}"
        log_path = f"{pull_dir}/pull.log"
        status_path = f"{pull_dir}/status"
        temporary_status = f"{status_path}.tmp"
        inner = "\n".join(
            [
                "set +e",
                f"podman pull {shlex.quote(image)} >{shlex.quote(log_path)} 2>&1",
                "rc=$?",
                f"printf '%s\\n' \"$rc\" >{shlex.quote(temporary_status)}",
                f"mv -f {shlex.quote(temporary_status)} {shlex.quote(status_path)}",
            ]
        )
        launch = "\n".join(
            [
                "set -eu",
                f"rm -rf {shlex.quote(pull_dir)}",
                f"mkdir -p {shlex.quote(pull_dir)}",
                f"setsid bash -lc {shlex.quote(inner)} </dev/null >/dev/null 2>&1 &",
                "echo STARTED",
            ]
        )
        guest(launch, timeout=30)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            poll = guest(
                "\n".join(
                    [
                        f"if test -f {shlex.quote(status_path)}; then",
                        f"  echo FINISHED:$(cat {shlex.quote(status_path)})",
                        f"  tail -c 4000 {shlex.quote(log_path)} || true",
                        "else",
                        "  echo RUNNING",
                        "fi",
                    ]
                ),
                timeout=30,
            )
            output = str(poll.get("stdout", ""))
            first_line = output.partition("\n")[0].strip()
            if first_line.startswith("FINISHED:"):
                try:
                    exit_code = int(first_line.removeprefix("FINISHED:"))
                except ValueError as error:
                    raise RuntimeError(f"invalid image-pull status: {first_line!r}") from error
                if exit_code:
                    raise RuntimeError(f"podman pull failed for {image}: {output[-4000:]}")
                inspection = guest(
                    f"podman image inspect {shlex.quote(image)} --format '{{{{.Id}}}}'",
                    timeout=30,
                )
                print(str(inspection.get("stdout", "")).strip(), flush=True)
                guest(f"rm -rf {shlex.quote(pull_dir)}", timeout=30)
                return
            time.sleep(5)
        raise TimeoutError(f"timed out pulling {image}")

    try:
        session = gateway.create_session(
            args.environment,
            "30m",
            "agent-toolbox-smoke-" + uuid.uuid4().hex,
            timeout=600,
        )
        print(f"session={session.session_id}", flush=True)
        guest(_login_command(DEV_ECR_REGISTRY, dev_password))
        guest(_login_command(PROD_ECR_REGISTRY, prod_password))
        pull_image(args.toolbox_image)
        pull_image(args.base_image)

        version_command = " && ".join(
            [
                "/toolbox/opt/prime-agents/opencode/opencode --version",
                "/toolbox/opt/prime-agents/pi/pi --version",
                "/toolbox/opt/prime-agents/muse/muse --version",
            ]
        )
        mount_command = (
            f"podman run --rm --network host "
            f"--mount type=image,source={args.toolbox_image},target=/toolbox "
            f"{args.base_image} bash -lc {json.dumps(version_command)}"
        )
        mount_result = gateway.request_json(
            "POST",
            session.port_urls["exec"].rstrip("/") + "/v1/exec",
            body={"command": ["bash", "-lc", mount_command], "timeout": 120},
            headers={"Authorization": f"Bearer {token}"},
            timeout=140,
        ).body
        if mount_result.get("exitCode", mount_result.get("exit_code")) == 0:
            method = "podman-image-mount"
            result = mount_result
        else:
            cache = "/home/runner/agent-cache/probe"
            fallback = " && ".join(
                [
                    f"rm -rf {cache}",
                    f"mkdir -p {cache}",
                    "podman rm -f agent-toolbox-source >/dev/null 2>&1 || true",
                    f"podman create --name agent-toolbox-source {args.toolbox_image} /unused >/dev/null",
                    f"podman cp agent-toolbox-source:/opt/prime-agents/. {cache}/",
                    "podman rm -f agent-toolbox-source >/dev/null",
                    f"podman run --rm --network host --volume {cache}:/toolbox:ro {args.base_image} "
                    f"bash -lc {json.dumps(version_command)}",
                ]
            )
            result = guest(fallback, timeout=180)
            method = "digest-image-extract-bind-mount"
        print(f"mount_method={method}")
        print(str(result.get("stdout", "")).strip())
        print("PASS")
        return 0
    finally:
        if session is not None:
            deletion = gateway.delete_session(session.session_id, timeout=180, prime=True)
            print(f"deleted={session.session_id} http={deletion.verified_http_status}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
