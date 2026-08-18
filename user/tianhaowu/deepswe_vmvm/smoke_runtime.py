"""Live VMVM Runtime contract smoke test."""

import asyncio
import hashlib
import json
import logging

from verifiers.v1.runtimes import VMVMConfig, make_runtime


async def main() -> None:
    payload = b"vmvm-runtime-smoke\x00\xff\n"
    tunnel_response = b"vmvm-host-tunnel-ok"

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
        VMVMConfig(
            image="docker.io/library/python:3.11-slim",
            workdir="/app",
            session_timeout=600,
            lease_ttl="1200s",
        ),
        name="deepswe-vmvm-smoke",
    )
    await runtime.start()
    try:
        await runtime.write("payload.bin", payload)
        downloaded = await runtime.read("payload.bin")
        if downloaded != payload:
            raise RuntimeError("VMVM binary file round trip changed the payload")
        result = await runtime.run(
            [
                "sh",
                "-c",
                'test "$(pwd)" = /app && sha256sum payload.bin',
            ],
            {"VMVM_SMOKE": "enabled"},
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stdout)
        expected_hash = hashlib.sha256(payload).hexdigest()
        if not result.stdout.startswith(expected_hash):
            raise RuntimeError(f"unexpected remote hash: {result.stdout!r}")
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
            raise RuntimeError(tunnel_result.stdout)
        if tunnel_result.stdout.strip() != tunnel_response.decode():
            raise RuntimeError(f"unexpected tunnel response: {tunnel_result.stdout!r}")
        print(
            json.dumps(
                {
                    "descriptor": runtime.descriptor,
                    "payload_sha256": expected_hash,
                    "remote_output": result.stdout.strip(),
                    "tunnel_output": tunnel_result.stdout.strip(),
                },
                sort_keys=True,
            )
        )
    finally:
        await runtime.stop()
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
