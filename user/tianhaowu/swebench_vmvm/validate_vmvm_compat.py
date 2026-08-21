import argparse
import asyncio
import json
from urllib.parse import urlsplit

from swebench_vmvm_compat import (
    ensure_tunnel_probe_python,
    install_java_forward_proxy_ca,
)
from verifiers.v1.runtimes import VMVMConfig, VMVMRuntime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--lease-ttl", default="10m")
    parser.add_argument("--require-python-missing", action="store_true")
    parser.add_argument("--check-java-ca", action="store_true")
    return parser.parse_args()


async def validate(args: argparse.Namespace) -> dict[str, object]:
    runtime = VMVMRuntime(
        VMVMConfig(
            image=args.image,
            workdir=args.workdir,
            session_timeout=1800,
            lease_ttl=args.lease_ttl,
            max_session_buffer_size=64 * 1024 * 1024,
        ),
        name="swebench-vmvm-local-compat",
    )
    await runtime.start()
    try:
        python_before = await runtime.run(["sh", "-c", "command -v python"], {})
        if args.require_python_missing and python_before.exit_code == 0:
            raise RuntimeError(f"image unexpectedly includes Python: {python_before.stdout.strip()}")
        await ensure_tunnel_probe_python(runtime)

        connections = 0

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal connections
            connections += 1
            data = await reader.read(4)
            if data == b"ping":
                writer.write(b"pong\n")
                await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            async with runtime.host_endpoint(port) as endpoint:
                parsed = urlsplit(endpoint)
                command = (
                    f"exec 3<>/dev/tcp/{parsed.hostname}/{parsed.port}; "
                    'printf ping >&3; IFS= read -r reply <&3; [ "$reply" = pong ]'
                )
                probe = await runtime.run(["bash", "-c", command], {})
                if probe.exit_code != 0:
                    raise RuntimeError(f"VMVM host endpoint probe failed: {probe.stdout[-2000:]}")
        finally:
            server.close()
            await server.wait_closed()

        if args.check_java_ca:
            await install_java_forward_proxy_ca(runtime)
            java_ca = await runtime.run(
                [
                    "keytool",
                    "-list",
                    "-cacerts",
                    "-storepass",
                    "changeit",
                    "-alias",
                    "swe-rebench-forward-proxy",
                ],
                {},
            )
            if java_ca.exit_code != 0:
                output = java_ca.stdout + java_ca.stderr
                raise RuntimeError(f"Java forward-proxy CA validation failed: {output[-2000:]}")

        return {
            "image": args.image,
            "python_before": python_before.stdout.strip() or None,
            "host_endpoint_connections": connections,
            "java_ca": args.check_java_ca,
        }
    finally:
        await runtime.stop()


def main() -> None:
    print(json.dumps(asyncio.run(validate(parse_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
