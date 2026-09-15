#!/usr/bin/env python3
"""
Replays ground-truth states into a live etcd instance for verification,
then writes groundtruth.json.

Requires etcd to be running at http://127.0.0.1:2379.

"""

import json
import subprocess
import sys

ETCD_ENDPOINT = "http://127.0.0.1:2379"


def etcdctl(*args):
    """Run etcdctl command and return stdout."""
    cmd = ["etcdctl", f"--endpoints={ETCD_ENDPOINT}"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        print(f"etcdctl error: {result.stderr}", file=sys.stderr)
    return result.stdout.strip()


def main():
    # Load ground-truth KV states from checker output
    with open("/tmp/groundtruth_kv.json") as f:
        groundtruth_kv = json.load(f)

    # Replay each linearizable history's final state into etcd
    # using history-prefixed keys for isolation
    for hist_name, kv_state in sorted(groundtruth_kv.items()):
        print(f"Replaying {hist_name} into etcd...")
        for key, value in sorted(kv_state.items()):
            prefixed_key = f"{hist_name}/{key}"
            etcdctl("put", prefixed_key, value)

    # Verify by reading back
    groundtruth = {}
    for hist_name, kv_state in sorted(groundtruth_kv.items()):
        verified_kv = {}
        for key in sorted(kv_state.keys()):
            prefixed_key = f"{hist_name}/{key}"
            value = etcdctl("get", prefixed_key, "--print-value-only")
            verified_kv[key] = value
        groundtruth[hist_name] = verified_kv

        # Verify match
        if verified_kv == kv_state:
            print(f"  {hist_name}: verified OK")
        else:
            print(f"  {hist_name}: MISMATCH! expected={kv_state} got={verified_kv}")

    # Write groundtruth.json
    with open("/app/groundtruth.json", "w") as f:
        json.dump(groundtruth, f, indent=2)

    print("Ground-truth verification complete.")


if __name__ == "__main__":
    main()
