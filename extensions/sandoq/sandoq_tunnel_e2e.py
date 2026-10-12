#!/usr/bin/env python3
"""SandoQ reverse-tunnel diagnostic for :class:`SandoqRelayTunnel`.

`prime_tunnel.Tunnel(local_port)` opens an outbound connection to Prime's relay
and hands the sandbox a temporary public HTTPS URL. SandoQ cannot work that way:
its session pods run with no egress at all, so a public relay URL is unreachable
from inside one. The direction is inverted instead.

    prime-tunnel:  sandbox --outbound--> public relay <--outbound-- your host
    sandoq:        your host --inbound--> gateway --inbound--> pod
                   and `ssh -R`-style inversion is done by a vsock forwarder
                   inside the guest, so the guest sees a plain loopback URL

Consequences for the integration:

* There is no URL to hand the sandbox. The guest already has one, exported as
  `SANDOQ_TUNNEL_URL` (`http://127.0.0.1:<port>`), because the Environment set
  `TUNNEL_PORT`. You do not allocate or publish anything.
* The gateway only ever dials into the pod, so your controller cannot be reached
  on demand. It parks spare connections ahead of time and each guest connection
  claims one. Concurrency is the pool size, not a multiplexer.
* The parking protocol has one rule: the guest speaks first. This client relies
  on that, and so does the launcher.

Usage
-----

Serve mode, the drop-in. Parks a pool and forwards every guest connection to a
server you already run on loopback, which is where your interception server
lives::

    with-proxy ./sandoq_tunnel_e2e.py serve \\
        --session-id <session-id> --local-port 8000

Self-test mode. Starts its own loopback server, parks a pool, drives the guest
through the exec API, and asserts the round trip::

    with-proxy ./sandoq_tunnel_e2e.py selftest \\
        --session-id <session-id> \\
        --token-file ~/.config/oci-runner/firecracker-token

Prerequisites
-------------

1. The `oci-runner-firecracker-small` Environment on eks-prod. It exposes the
   named `tunnel` port at guest loopback port 8485. The guest has conventional
   pod networking in this tier; the tunnel is specifically the path back to a
   caller-local service that guest egress cannot reach.
2. A session on that Environment. The `sandoq` CLI blocks on its keychain lookup
   when stdout is not a terminal, so create it in your own shell::

       sandoq session create --cluster eks-prod \\
           --environment <env> --lease-duration 30m

3. The Environment's exec bearer token, for the `/v1/exec` calls this script
   makes in self-test mode. Serve mode does not need it. The token used by the
   OCI recipe normally lives at `~/.config/oci-runner/firecracker-token`.
4. Network reachability to the gateway. On a Meta devserver that means running
   under `with-proxy`; this script reads `https_proxy` and tunnels through it.

Install the extension requirements first; the relay reuses the official Sandoq
client's proxy and mTLS transport profile.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from sandoq_provider.gateway import get_gateway_adapter
from sandoq_provider.secrets import read_secret_file
from sandoq_provider.tunnel import SandoqRelayTunnel as SandoqTunnel

DEFAULT_CLUSTER = "eks-prod"
SELFTEST_MARKER = "sandoq-tunnel-selftest"


def port_url(cluster: str, session_id: str, port: str) -> str:
    return f"https://{session_id}-{port}.sessions.sandoq.{cluster}.cf.aws.metafb.cloud/"


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", 0))
        received = self.rfile.read(length)
        body = json.dumps({"marker": SELFTEST_MARKER, "echoedBytes": len(received)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def guest_exec(exec_url: str, token: str, script: str, timeout: int = 300) -> dict:
    base_url = os.environ.get("OCI_RUNNER_BASE_URL", "https://sandoq.eks-prod.cf.aws.metafb.cloud")
    owner = os.environ.get("SANDOQ_OWNER") or os.environ.get("USER") or "sandoq-tunnel-e2e"
    response = get_gateway_adapter(base_url, owner).request_json(
        "POST",
        exec_url.rstrip("/") + "/v1/exec",
        body={"command": ["sh", "-c", script]},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=float(timeout),
    )
    if response.status_code != 200:
        raise RuntimeError(f"guest exec returned HTTP {response.status_code}")
    return response.body


def selftest(args: argparse.Namespace) -> int:
    exec_url = args.exec_url or port_url(args.cluster, args.session_id, "exec")
    tunnel_url = args.tunnel_url or port_url(args.cluster, args.session_id, "tunnel")
    token = args.token
    if token is None:
        token = read_secret_file(Path(args.token_file).expanduser(), "Sandoq exec token", ValueError)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    local_port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  local interception server on 127.0.0.1:{local_port}")

    failures = []
    with SandoqTunnel(tunnel_url=tunnel_url, local_port=local_port, pool_size=args.pool) as tunnel:
        print(f"  parked a pool of {args.pool}")

        probe = guest_exec(exec_url, token, "echo url=[$SANDOQ_TUNNEL_URL]")
        print(f"  guest sees {probe['stdout'].strip()}")
        if "url=[]" in probe["stdout"]:
            print("FAIL: the guest has no SANDOQ_TUNNEL_URL. Is TUNNEL_PORT set on this Environment?")
            return 1

        started = time.time()
        result = guest_exec(
            exec_url,
            token,
            f"ok=0; for i in $(seq 1 {args.requests}); do "
            'out=$(curl -sS -m 30 -X POST "$SANDOQ_TUNNEL_URL/v1/responses" '
            '-H "Content-Type: application/json" -d "{\\"n\\":$i}"); '
            f'case "$out" in *{SELFTEST_MARKER}*) ok=$((ok+1));; esac; done; echo ok=$ok',
        )
        elapsed = time.time() - started
        print(f"  {result['stdout'].strip()} of {args.requests} in {elapsed:.1f}s")
        if f"ok={args.requests}" not in result["stdout"]:
            failures.append(f"{result['stdout'].strip()} stderr={result['stderr'][:200]}")

        isolation = guest_exec(
            exec_url,
            token,
            'echo ifaces=$(ls /sys/class/net | tr "\\n" ","); echo resolv=$(wc -c </etc/resolv.conf)',
        )
        print(f"  guest isolation: {isolation['stdout'].strip().replace(chr(10), '  ')}")

        served, errors = tunnel.stats()
        print(f"  tunnel served {served}, errors {len(errors)}")
        if errors:
            print(f"  first errors: {errors[:3]}")
            failures.append(f"{len(errors)} tunnel errors")

    server.shutdown()
    if failures:
        print("FAIL: " + " | ".join(failures))
        return 1
    print("PASS")
    return 0


def serve(args: argparse.Namespace) -> int:
    tunnel_url = args.tunnel_url or port_url(args.cluster, args.session_id, "tunnel")
    print(f"  forwarding guest connections to 127.0.0.1:{args.local_port}")
    with SandoqTunnel(tunnel_url=tunnel_url, local_port=args.local_port, pool_size=args.pool) as tunnel:
        print(f"  parked a pool of {args.pool}; Ctrl-C to stop")
        try:
            while True:
                time.sleep(10)
                served, errors = tunnel.stats()
                print(f"  served {served}, errors {len(errors)}")
        except KeyboardInterrupt:
            print("  stopping")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    for name in ("serve", "selftest"):
        p = sub.add_parser(name)
        p.add_argument("--session-id", required=True)
        p.add_argument("--cluster", default=DEFAULT_CLUSTER)
        p.add_argument("--pool", type=int, default=8)
        p.add_argument("--tunnel-url", help="override the derived tunnel port URL")
        if name == "serve":
            p.add_argument("--local-port", type=int, required=True)
        else:
            token = p.add_mutually_exclusive_group(required=True)
            token.add_argument("--token", help="the Environment's exec token (prefer --token-file)")
            token.add_argument("--token-file", help="mode-0600 file containing the Environment's exec token")
            p.add_argument("--requests", type=int, default=20)
            p.add_argument("--exec-url", help="override the derived exec port URL")

    args = parser.parse_args()
    return serve(args) if args.mode == "serve" else selftest(args)


if __name__ == "__main__":
    sys.exit(main())
