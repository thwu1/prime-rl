import asyncio
import shlex

from verifiers.v1.runtimes import Runtime

_ZERO_GENERATION_BUDGET = "max_tokens must be at least 1, got 0"
_FORWARD_PROXY_CA = "/etc/pki/ca-trust/extracted/pem/directory-hash/ForwardProxyTermCA.pem"
_CONTAINER_CA = "/tmp/swe-rebench-forward-proxy-ca.crt"
_TUNNEL_PROBE_PYTHON = b"""#!/bin/bash
set -eu

if command -v python3 >/dev/null 2>&1; then
    exec "$(command -v python3)" "$@"
fi

pattern="socket\\.create_connection\\(\\('([0-9.]+)',[[:space:]]*([0-9]+)\\)"
if [ "${1:-}" = -c ] && [[ "${2:-}" =~ $pattern ]]; then
    exec 3<>"/dev/tcp/${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    exit 0
fi

exit 127
"""


def install_context_limit_compatibility() -> None:
    """Treat vLLM's zero-generation-budget response as a context limit."""
    from verifiers.v1 import errors

    phrases = errors._CONTEXT_LENGTH_PHRASES
    if _ZERO_GENERATION_BUDGET not in phrases:
        errors._CONTEXT_LENGTH_PHRASES = (*phrases, _ZERO_GENERATION_BUDGET)


async def ensure_tunnel_probe_python(runtime: Runtime) -> None:
    """Provide only the Python socket probe expected by the shared VMVM backend."""
    available = await runtime.run(["sh", "-c", "command -v python >/dev/null 2>&1"], {})
    if available.exit_code == 0:
        return
    await runtime.write("/usr/local/bin/python", _TUNNEL_PROBE_PYTHON)
    installed = await runtime.run(["chmod", "0755", "/usr/local/bin/python"], {})
    if installed.exit_code != 0:
        output = installed.stdout + installed.stderr
        raise RuntimeError(f"installing the VMVM tunnel probe shim failed: {output[-2000:]}")


async def install_java_forward_proxy_ca(runtime: Runtime) -> None:
    """Copy VMVM's forward-proxy CA into a Java task's default trust store."""
    has_keytool = await runtime.run(["sh", "-c", "command -v keytool >/dev/null 2>&1"], {})
    if has_keytool.exit_code != 0:
        return

    backend = getattr(runtime, "backend", None)
    read_host = getattr(backend, "_ssh_call_raw", None)
    if not callable(read_host):
        raise RuntimeError("VMVM backend does not expose its host command channel")
    result = await asyncio.to_thread(
        read_host,
        f"cat {shlex.quote(_FORWARD_PROXY_CA)}",
        timeout=30,
    )
    ca = result.stdout or b""
    if result.returncode != 0 or not ca:
        output = ca.decode("utf-8", errors="replace")
        raise RuntimeError(f"reading the VMVM forward-proxy CA failed: {output[-2000:]}")

    await runtime.write(_CONTAINER_CA, ca)
    command = f"""set -e
keytool -delete -alias swe-rebench-forward-proxy -cacerts -storepass changeit \
    >/dev/null 2>&1 || true
keytool -importcert -noprompt -trustcacerts -alias swe-rebench-forward-proxy \
    -file {shlex.quote(_CONTAINER_CA)} -cacerts -storepass changeit >/dev/null
"""
    installed = await runtime.run(["sh", "-c", command], {})
    if installed.exit_code != 0:
        output = installed.stdout + installed.stderr
        raise RuntimeError(f"installing the Java forward-proxy CA failed: {output[-2000:]}")
