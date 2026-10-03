#!/usr/bin/env python3
"""Lease a SandoQ session and drive the structured /exec API end-to-end.

Pure stdlib (urllib) so it runs anywhere python3 is present -- no pip installs.
Demonstrates the full agent loop:
  1. create session (with 429 warm-pool retry + stable requestId)
  2. wait for the exec API to be ready (/healthz)
  3. run commands: state persistence, stderr+exit_code capture, timeout
  4. destroy the session (always, via finally)

Usage:
  python3 exec_client.py
  BASE=https://sandoq.eks-prod.cf.aws.metafb.cloud ENVIRONMENT=ram-ubuntu-terminal \
    python3 exec_client.py
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("BASE", "https://sandoq.eks-prod.cf.aws.metafb.cloud")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "ram-ubuntu-terminal")
OWNER = os.environ.get("USER", "exec-client")
LEASE = os.environ.get("LEASE", "15m")


def _req(method: str, url: str, body: dict | None = None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode(errors="replace")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def create_session(max_attempts: int = 20) -> dict:
    rid = str(uuid.uuid4())  # stable across retries -> claims the reserved pod
    for attempt in range(1, max_attempts + 1):
        code, body = _req(
            "POST",
            f"{BASE}/api/v1/environments/{ENVIRONMENT}/sessions",
            {"leaseDuration": LEASE, "owner": OWNER, "requestId": rid},
        )
        if code == 201:
            return body
        if code == 429:
            delay = min(attempt * 2, 10)
            print(f"  attempt {attempt}: HTTP 429 (warm pool warming), retry in {delay}s")
            time.sleep(delay)
            continue
        raise RuntimeError(f"create session failed: HTTP {code}: {body}")
    raise RuntimeError(f"gave up after {max_attempts} attempts (still 429)")


def wait_healthz(exec_url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            code, body = _req("GET", exec_url + "healthz", timeout=5)
            if code == 200 and body.get("status") == "ok":
                return
        except urllib.error.URLError:
            pass  # pod networking not up yet
        time.sleep(1)
    raise RuntimeError("exec API /healthz not ready in time")


def run(exec_url: str, cmd: str, timeout: float = 60.0) -> dict:
    code, body = _req("POST", exec_url + "exec", {"cmd": cmd, "timeout": timeout}, timeout=timeout + 15)
    if code != 200:
        raise RuntimeError(f"/exec failed: HTTP {code}: {body}")
    return body


def show(label: str, res: dict) -> None:
    print(
        f"{label} exit={res.get('exit_code')} "
        f"timed_out={res.get('timed_out')} shell_died={res.get('shell_died')} "
        f"({res.get('duration_s')}s)"
    )
    if res.get("stdout"):
        print("    stdout:", res["stdout"].rstrip())
    if res.get("stderr"):
        print("    stderr:", res["stderr"].rstrip())


def main() -> None:
    print(f"Leasing {ENVIRONMENT} on {BASE} ...")
    sess = create_session()
    sid = sess["sessionId"]
    exec_url = sess["portUrls"]["exec"]  # https://<sid>-exec.sessions.../
    print(f"  sessionId = {sid}")
    print(f"  exec URL  = {exec_url}")
    print(f"  terminal  = {sess['portUrls'].get('terminal')}")
    try:
        print("Waiting for exec API readiness ...")
        wait_healthz(exec_url)

        print("\n[1] state persists across calls (cwd + files):")
        show("  a)", run(exec_url, "cd /tmp && echo hello > f.txt && ls -l f.txt"))
        show("  b)", run(exec_url, "pwd && cat f.txt"))  # still /tmp, sees f.txt

        print("\n[2] stderr + non-zero exit_code captured separately:")
        show("   ", run(exec_url, "ls /does-not-exist; echo still-running"))

        print("\n[3] timeout -> kill + respawn (timed_out=True):")
        show("   ", run(exec_url, "echo start && sleep 5 && echo end", timeout=2))
    finally:
        code, _ = _req("DELETE", f"{BASE}/api/v1/sessions/{sid}")
        print(f"\nDeleted session {sid}: HTTP {code}")


if __name__ == "__main__":
    main()
