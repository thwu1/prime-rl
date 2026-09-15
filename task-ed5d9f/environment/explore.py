#!/usr/bin/env python3
"""Exploration harness for the reference block manager module."""


import sys
import os
import json

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/reference")

from block_manager_interface import BlockManagerConfig, PreemptionMode

try:
    from block_manager_ref import BlockManager as RefBM
except ImportError as e:
    print(f"ERROR: Could not import reference module: {e}")
    print("Files in /app/reference/:", os.listdir("/app/reference/"))
    sys.exit(1)


def create_config(**kwargs):
    defaults = {
        "num_gpu_blocks": 16,
        "num_cpu_blocks": 8,
        "block_size": 4,
        "enable_prefix_caching": False,
        "preemption_mode": PreemptionMode.SWAP,
    }
    defaults.update(kwargs)
    return BlockManagerConfig(**defaults)


def snapshot_dict(snap):
    return {
        "gpu_used": snap.gpu_blocks_used,
        "gpu_free": snap.gpu_blocks_free,
        "gpu_cached": snap.gpu_blocks_cached,
        "cpu_used": snap.cpu_blocks_used,
        "cpu_free": snap.cpu_blocks_free,
        "active_seqs": snap.num_active_sequences,
        "swapped_seqs": snap.num_swapped_sequences,
        "cache_hits": snap.prefix_cache_hits,
        "cache_misses": snap.prefix_cache_misses,
        "cow_copies": snap.cow_copies,
    }


def status_dict(status):
    if status is None:
        return None
    return {
        "seq_id": status.seq_id,
        "num_blocks": status.num_logical_blocks,
        "num_tokens": status.num_tokens,
        "is_swapped": status.is_swapped,
        "block_table": status.block_table,
    }


def replay_trace(trace_path):
    with open(trace_path) as f:
        trace = json.load(f)

    config_kwargs = trace.get("config", {})
    if "preemption_mode" in config_kwargs:
        config_kwargs["preemption_mode"] = PreemptionMode(config_kwargs["preemption_mode"])
    if "enable_prefix_caching" in config_kwargs:
        config_kwargs["enable_prefix_caching"] = bool(config_kwargs["enable_prefix_caching"])
    bm = RefBM(create_config(**config_kwargs))

    for step in trace["operations"]:
        op = step["op"]
        args = step.get("args", {})

        if op == "allocate":
            result = bm.allocate(args["seq_id"], args["token_ids"])
        elif op == "append_tokens":
            result = bm.append_tokens(args["seq_id"], args["token_ids"])
        elif op == "fork":
            result = bm.fork(args["parent_seq_id"], args["child_seq_id"])
        elif op == "free":
            bm.free(args["seq_id"])
            result = None
        elif op == "swap_out":
            result = bm.swap_out(args["seq_id"])
        elif op == "swap_in":
            result = bm.swap_in(args["seq_id"])
        elif op == "select_preemption_victim":
            result = bm.select_preemption_victim()
        elif op == "can_allocate":
            result = bm.can_allocate(args["num_tokens"])
        else:
            print(f"Unknown op: {op}")
            continue

        snap = snapshot_dict(bm.get_memory_snapshot())
        print(f"{op}({args}) -> {result}")
        print(f"  snapshot: {json.dumps(snap)}")

        if "check_seq" in step:
            for sid in step["check_seq"]:
                st = status_dict(bm.get_sequence_status(sid))
                print(f"  seq {sid}: {json.dumps(st)}")
        print()


def interactive():
    print("Reference Block Manager Explorer")
    print("Commands: config, allocate, append, fork, free, swap_out, swap_in,")
    print("          snapshot, status, victim, can_alloc, quit")
    print()

    bm = None

    while True:
        try:
            line = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0]

        try:
            if cmd == "quit":
                break
            elif cmd == "config":
                kwargs = {}
                for p in parts[1:]:
                    k, v = p.split("=")
                    if k == "preemption_mode":
                        kwargs[k] = PreemptionMode(v)
                    elif k == "enable_prefix_caching":
                        kwargs[k] = v.lower() == "true"
                    else:
                        kwargs[k] = int(v)
                bm = RefBM(create_config(**kwargs))
                print(f"Created BlockManager with: {kwargs or 'defaults'}")
                print(f"  {json.dumps(snapshot_dict(bm.get_memory_snapshot()))}")
            elif bm is None:
                print("Run 'config' first to create a BlockManager instance")
            elif cmd == "allocate":
                sid = int(parts[1])
                tokens = list(map(int, parts[2:]))
                result = bm.allocate(sid, tokens)
                print(f"-> {result}")
                print(f"  {json.dumps(snapshot_dict(bm.get_memory_snapshot()))}")
            elif cmd == "append":
                sid = int(parts[1])
                tokens = list(map(int, parts[2:]))
                result = bm.append_tokens(sid, tokens)
                print(f"-> {result}")
                print(f"  {json.dumps(snapshot_dict(bm.get_memory_snapshot()))}")
            elif cmd == "fork":
                pid = int(parts[1])
                cid = int(parts[2])
                result = bm.fork(pid, cid)
                print(f"-> {result}")
                print(f"  {json.dumps(snapshot_dict(bm.get_memory_snapshot()))}")
            elif cmd == "free":
                sid = int(parts[1])
                bm.free(sid)
                print(f"  {json.dumps(snapshot_dict(bm.get_memory_snapshot()))}")
            elif cmd == "swap_out":
                sid = int(parts[1])
                result = bm.swap_out(sid)
                print(f"-> {result}")
                print(f"  {json.dumps(snapshot_dict(bm.get_memory_snapshot()))}")
            elif cmd == "swap_in":
                sid = int(parts[1])
                result = bm.swap_in(sid)
                print(f"-> {result}")
                print(f"  {json.dumps(snapshot_dict(bm.get_memory_snapshot()))}")
            elif cmd == "snapshot":
                print(json.dumps(snapshot_dict(bm.get_memory_snapshot()), indent=2))
            elif cmd == "status":
                sid = int(parts[1])
                st = status_dict(bm.get_sequence_status(sid))
                print(json.dumps(st, indent=2))
            elif cmd == "victim":
                result = bm.select_preemption_victim()
                print(f"-> {result}")
            elif cmd == "can_alloc":
                n = int(parts[1])
                result = bm.can_allocate(n)
                print(f"-> {result}")
            else:
                print(f"Unknown command: {cmd}")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        replay_trace(sys.argv[1])
    else:
        interactive()
