#!/usr/bin/env python3
"""Repro: SandoQ Cluster Gateway mis-routes create-session for an env deployed on eks-prod.

SYMPTOM
  POST /api/v1/environments/{env}/sessions via the multi-cluster **gateway**
  (https://sandoq-gateway.eks-prod.cf.aws.metafb.cloud) is routed by
  environment-name hashing to cluster `cua-eval-v2`, which does NOT host the env,
  so it returns HTTP 404 {"message":"environment not found: <env>","cluster":"cua-eval-v2"}.

  The IDENTICAL request against the **direct eks-prod cluster URL**
  (https://sandoq.eks-prod.cf.aws.metafb.cloud) succeeds (HTTP 201, cluster=eks-prod).

WHY THIS LOOKS LIKE A BUG
  The gateway is the documented/recommended endpoint. Per SandoQ/architecture, create-session
  requests "hash the environment name so a given environment is consistently assigned to the
  same active cluster." For an env deployed only on eks-prod, that hash lands on `cua-eval-v2`
  and there is no environment->cluster route back to eks-prod, so create-session 404s on the
  gateway while the env is healthy and leasable on its actual cluster.

  Routing priority (SandoQ/architecture) that seems relevant:
    1. Session-ID prefix (mutations)         2. X-Sandoq-Route-Key header
    3. Explicit per-environment route         4. Fallback: rendezvous hash of env name
  It looks like (3) is missing for this env, so it falls to (4) and picks the wrong cluster.

USAGE
  python3 gateway_misroute_repro.py
  python3 gateway_misroute_repro.py --env ram-prime-rl-sandbox

Pure stdlib (urllib); no installs. Leases are short and cleaned up. The direct call
creates+deletes one session; the gateway call 404s (nothing to clean up).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

GATEWAY = "https://sandoq-gateway.eks-prod.cf.aws.metafb.cloud"
DIRECT = "https://sandoq.eks-prod.cf.aws.metafb.cloud"


def create_session(base: str, env: str, owner: str, request_id: str, lease: str = "30s"):
    url = f"{base}/api/v1/environments/{env}/sessions"
    data = json.dumps({"leaseDuration": lease, "owner": owner, "requestId": request_id}).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}
    except urllib.error.URLError as e:
        return -1, {"error": str(e)}


def delete_session(base: str, session_id: str) -> int:
    req = urllib.request.Request(f"{base}/api/v1/sessions/{session_id}", method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError:
        return -1


def show(label: str, base: str, env: str, code, body: dict) -> None:
    print(f"\n[{label}]  POST {base}/api/v1/environments/{env}/sessions")
    print(f"    HTTP    : {code}")
    print(f"    cluster : {body.get('cluster')}")
    msg = body.get("message") or body.get("error") or body.get("raw")
    if msg:
        print(f"    message : {msg}")
    print(f"    body    : {json.dumps(body)[:500]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="ram-prime-rl-sandbox", help="environment name deployed on eks-prod")
    ap.add_argument("--gateway", default=GATEWAY)
    ap.add_argument("--direct", default=DIRECT)
    ap.add_argument("--owner", default=f"{os.environ.get('USER', 'repro')}-gw-repro")
    args = ap.parse_args()

    request_id = str(uuid.uuid4())  # identical for both requests
    print("=" * 80)
    print("SandoQ Cluster Gateway mis-route repro")
    print(f"  env       = {args.env}")
    print(f"  owner     = {args.owner}")
    print(f"  requestId = {request_id}")
    print("=" * 80)

    # 1) DIRECT cluster URL — env should be FOUND here (201 leased, or 429 warming).
    d_code, d_body = create_session(args.direct, args.env, args.owner, request_id)
    show("DIRECT eks-prod", args.direct, args.env, d_code, d_body)
    if d_body.get("sessionId"):
        rc = delete_session(args.direct, d_body["sessionId"])
        print(f"    cleanup : deleted {d_body['sessionId']} (HTTP {rc})")

    # 2) GATEWAY — observed to route to cua-eval-v2 and 404 "environment not found".
    g_code, g_body = create_session(args.gateway, args.env, args.owner, request_id)
    show("GATEWAY", args.gateway, args.env, g_code, g_body)
    if g_body.get("sessionId"):
        rc = delete_session(args.gateway, g_body["sessionId"])
        print(f"    cleanup : deleted {g_body['sessionId']} (HTTP {rc})")

    # Verdict
    print("\n" + "=" * 80)
    direct_found = d_code in (200, 201, 429)
    gateway_notfound = g_code == 404 and "not found" in json.dumps(g_body).lower()
    if direct_found and gateway_notfound:
        print("RESULT: BUG REPRODUCED")
        print(f"  direct  eks-prod : HTTP {d_code}  cluster={d_body.get('cluster')}  (env present + leasable)")
        print(f"  gateway          : HTTP {g_code}  cluster={g_body.get('cluster')}  (env absent -> 404)")
        print("  => Same env name, same request. The gateway routed create-session to the wrong")
        print("     cluster. Expected: gateway routes to (or discovers) the cluster hosting the env.")
        return 1
    print("RESULT: not reproduced in this run")
    print(
        f"  direct HTTP={d_code} (cluster={d_body.get('cluster')}) | gateway HTTP={g_code} (cluster={g_body.get('cluster')})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
