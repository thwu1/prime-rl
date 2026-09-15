#!/usr/bin/env python3
"""
Feature Pipeline Simulation

Simulates one cycle of the feature generation and proxy loading pipeline.
The feature file is regenerated from a database shard and then loaded
into the proxy server. This script helps reproduce the intermittent
failure by allowing targeted shard selection.

Usage:
    python3 run_cycle.py                          # Random shard
    python3 run_cycle.py /app/db/shards/shard_0.db  # Specific shard
"""

import subprocess
import sys
import json
import os


def run_cycle(shard_path=None):
    """Run one feature generation and proxy load cycle."""
    print("=" * 60)
    print("Feature Pipeline Cycle")
    print("=" * 60)

    # Step 1: Generate feature file
    print("\n[1/3] Generating feature file...")
    cmd = [sys.executable, "/app/generator/generate.py"]
    if shard_path:
        cmd.append(shard_path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr}")
        return False
    print(f"  {result.stdout.strip()}")

    # Step 2: Inspect the generated feature file
    print("\n[2/3] Inspecting feature file...")
    try:
        with open("/app/features/bot_features.json") as f:
            data = json.load(f)
        count = len(data["features"])
        source = data.get("shard_source", "unknown")
        print(f"  Feature count: {count}")
        print(f"  Source shard: {source}")
        print(f"  Generated at: {data.get('generated_at', 'unknown')}")
        if count > 200:
            print(f"  WARNING: Feature count {count} exceeds proxy limit of 200!")
    except Exception as e:
        print(f"  Error reading feature file: {e}")
        return False

    # Step 3: Attempt to load into proxy
    print("\n[3/3] Loading features into proxy...")
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
sys.path.insert(0, '/app')
from proxy.server import ProxyServer
server = ProxyServer()
server.initialize()
result = server.handle_request({"user_agent_entropy": 0.5})
print(f"  Proxy OK - status: {result['status']}, bot_score: {result.get('bot_score', 'N/A')}")
print(f"  Server status: {server.get_status()}")
"""],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"  PROXY CRASHED (exit code {result.returncode})")
        if result.stderr:
            print(f"  stderr: {result.stderr.strip()}")
        return False

    print(result.stdout.strip())
    print("\n" + "=" * 60)
    return True


if __name__ == "__main__":
    shard = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_cycle(shard)
    print(f"\nResult: {'SUCCESS' if success else 'FAILURE'}")
    sys.exit(0 if success else 1)
