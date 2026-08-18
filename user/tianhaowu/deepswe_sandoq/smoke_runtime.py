"""Live Sandoq Runtime contract smoke test."""

import argparse
import asyncio
import hashlib
import json
import logging
import os

from provider_env import provider_environment_context
from verifiers.v1.runtimes import SandoqConfig, make_runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("environment", "oci-runner"),
        default="environment",
    )
    parser.add_argument("--skip-host-endpoint", action="store_true")
    return parser.parse_args()


async def run(mode: str, *, check_host_endpoint: bool) -> None:
    payload = b"sandoq-runtime-smoke\x00\xff\n"
    tunnel_response = b"sandoq-host-tunnel-ok"

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(4096)
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Length: {len(tunnel_response)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + tunnel_response
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    host_port = server.sockets[0].getsockname()[1]
    runtime = make_runtime(
        SandoqConfig(
            image="docker.io/library/python:3.11-slim",
            workdir="/app",
            mode=mode,
            session_timeout=600,
        ),
        name=f"deepswe-sandoq-{mode}-smoke",
    )
    await runtime.start()
    try:
        await runtime.write("payload.bin", payload)
        downloaded = await runtime.read("payload.bin")
        if downloaded != payload:
            raise RuntimeError("Sandoq binary file round trip changed the payload")
        result = await runtime.run(
            ["sh", "-c", 'test "$(pwd)" = /app && sha256sum payload.bin'],
            {"SANDOQ_SMOKE": "enabled"},
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or result.stdout)
        expected_hash = hashlib.sha256(payload).hexdigest()
        if not result.stdout.startswith(expected_hash):
            raise RuntimeError(f"unexpected remote hash: {result.stdout!r}")
        tunnel_output = None
        if check_host_endpoint:
            async with runtime.host_endpoint(host_port) as url:
                tunnel_result = await runtime.run(
                    [
                        "python",
                        "-c",
                        "import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1]).read().decode())",
                        url,
                    ],
                    {},
                )
            if tunnel_result.exit_code != 0:
                raise RuntimeError(tunnel_result.stderr or tunnel_result.stdout)
            if tunnel_result.stdout.strip() != tunnel_response.decode():
                raise RuntimeError(f"unexpected tunnel response: {tunnel_result.stdout!r}")
            tunnel_output = tunnel_result.stdout.strip()
        print(
            json.dumps(
                {
                    "descriptor": runtime.descriptor,
                    "mode": mode,
                    "payload_sha256": expected_hash,
                    "remote_output": result.stdout.strip(),
                    "tunnel_output": tunnel_output,
                },
                sort_keys=True,
            )
        )
    finally:
        await runtime.stop()
        server.close()
        await server.wait_closed()


def main() -> None:
    args = parse_args()
    with provider_environment_context("sandoq") as env:
        os.environ.clear()
        os.environ.update(env)
        asyncio.run(run(args.mode, check_host_endpoint=not args.skip_host_endpoint))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
