#!/usr/bin/env python3
"""Generate synthetic protocol fuzzing campaign data with data quality issues.

Produces:
- 200 valid test executions with correct-size coverage bitmaps
- 10 corrupted entries (bitmap files with wrong sizes)
- 5 orphan coverage files (no matching execution record)
- A minimal campaign.conf for context
"""

import json
import os
import random


def main():
    rng = random.Random(20210113)
    BITMAP_SIZE = 8192

    DATA_DIR = "/opt/campaign"
    os.makedirs("{}/coverage".format(DATA_DIR), exist_ok=True)

    # Protocol state machine (FTP-like response codes)
    TRANSITIONS = {
        220: [(331, 0.50), (530, 0.15), (500, 0.10), (421, 0.05), (220, 0.20)],
        331: [(230, 0.60), (530, 0.20), (500, 0.10), (421, 0.10)],
        230: [(250, 0.40), (150, 0.25), (257, 0.10), (500, 0.10), (221, 0.10), (421, 0.05)],
        250: [(250, 0.20), (150, 0.35), (226, 0.20), (550, 0.10), (500, 0.10), (421, 0.05)],
        150: [(226, 0.55), (425, 0.20), (426, 0.10), (500, 0.10), (421, 0.05)],
        226: [(250, 0.40), (150, 0.25), (257, 0.10), (221, 0.15), (421, 0.10)],
        257: [(250, 0.40), (150, 0.30), (500, 0.15), (421, 0.15)],
        221: [],
        421: [],
        425: [(250, 0.30), (150, 0.30), (500, 0.20), (421, 0.20)],
        426: [(250, 0.30), (500, 0.30), (421, 0.40)],
        500: [(331, 0.20), (220, 0.20), (500, 0.20), (421, 0.40)],
        530: [(331, 0.40), (500, 0.20), (421, 0.20), (220, 0.20)],
        550: [(250, 0.35), (150, 0.20), (500, 0.25), (421, 0.20)],
    }

    # Assign deterministic edge sets to each protocol state
    state_edge_sets = {}
    all_assigned = set()

    for state in sorted(TRANSITIONS.keys()):
        num_edges = rng.randint(40, 100)
        edges = set()
        # Share some edges with previously-assigned states
        if all_assigned:
            avail = sorted(all_assigned)
            num_shared = rng.randint(5, 20)
            sample_size = min(num_shared, len(avail))
            indices = rng.sample(range(len(avail)), sample_size)
            for idx in indices:
                edges.add(avail[idx])
        # Fill remaining with unique edges
        while len(edges) < num_edges:
            e = rng.randint(0, BITMAP_SIZE - 1)
            if e not in all_assigned:
                edges.add(e)
                all_assigned.add(e)
        state_edge_sets[state] = frozenset(edges)

    def choose_next(current, config):
        """Select next state based on fuzzing configuration."""
        trans = TRANSITIONS.get(current, [])
        if not trans:
            return None
        if config == "A":
            # FAVOR strategy: bias toward deeper/rarer states
            deep_states = {257, 226, 425, 426, 550}
            weights = []
            for ns, p in trans:
                bonus = 1.8 if ns in deep_states else 1.0
                weights.append(p * bonus)
            total_w = sum(weights)
            r = rng.random() * total_w
            cum = 0.0
            for i, (ns, _) in enumerate(trans):
                cum += weights[i]
                if r < cum:
                    return ns
            return trans[-1][0]
        else:
            # Random strategy: follow original probabilities
            r = rng.random()
            cum = 0.0
            for ns, p in trans:
                cum += p
                if r < cum:
                    return ns
            return trans[-1][0]

    # Generate 200 valid test executions: t0000-t0099 = config A, t0100-t0199 = config B
    executions = []

    for i in range(200):
        config = "A" if i < 100 else "B"
        test_id = "t{:04d}".format(i)

        # Walk the state machine
        states = [220]
        current = 220
        max_steps = rng.randint(3, 12)
        for _ in range(max_steps):
            nxt = choose_next(current, config)
            if nxt is None:
                break
            states.append(nxt)
            current = nxt

        # Build coverage bitmap from visited states
        bitmap = bytearray(BITMAP_SIZE)
        for s in sorted(set(states)):
            if s in state_edge_sets:
                for edge in sorted(state_edge_sets[s]):
                    hit = rng.randint(1, 15)
                    bitmap[edge] = max(bitmap[edge], hit)

        coverage_path = "coverage/{}.bin".format(test_id)
        with open("{}/{}".format(DATA_DIR, coverage_path), "wb") as f:
            f.write(bytes(bitmap))

        executions.append({
            "test_id": test_id,
            "config": config,
            "states": states,
            "edges_file": coverage_path,
        })

    # Generate 10 corrupted entries (bitmap files with wrong sizes)
    bad_sizes = [4096, 4096, 4096, 4096, 4096, 16384, 16384, 16384, 1024, 1024]
    for j in range(10):
        idx = 200 + j
        config = "A" if rng.random() < 0.5 else "B"
        test_id = "t{:04d}".format(idx)

        states = [220]
        current = 220
        for _ in range(rng.randint(2, 5)):
            nxt = choose_next(current, config)
            if nxt is None:
                break
            states.append(nxt)
            current = nxt

        bitmap = bytearray(rng.randint(0, 255) for _ in range(bad_sizes[j]))
        coverage_path = "coverage/{}.bin".format(test_id)
        with open("{}/{}".format(DATA_DIR, coverage_path), "wb") as f:
            f.write(bytes(bitmap))

        executions.append({
            "test_id": test_id,
            "config": config,
            "states": states,
            "edges_file": coverage_path,
        })

    # Generate 5 orphan coverage files (no execution record)
    for j in range(5):
        idx = 210 + j
        orphan_id = "t{:04d}".format(idx)
        bitmap = bytearray(BITMAP_SIZE)
        for k in range(BITMAP_SIZE):
            if rng.random() < 0.01:
                bitmap[k] = rng.randint(1, 15)
        with open("{}/coverage/{}.bin".format(DATA_DIR, orphan_id), "wb") as f:
            f.write(bytes(bitmap))

    # Write execution log
    with open("{}/runs.jsonl".format(DATA_DIR), "w") as f:
        for ex in executions:
            f.write(json.dumps(ex) + "\n")

    # Write minimal campaign config
    config_lines = [
        "# Protocol Fuzzing Campaign",
        "# Target: network service (FTP-like protocol)",
        "# Duration: 24 hours",
        "# Configurations:",
        "#   A - state-aware seed scheduling",
        "#   B - random seed scheduling",
        "# Artifacts:",
        "#   runs.jsonl - per-execution records",
        "#   coverage/ - edge coverage bitmaps",
        "",
    ]
    with open("{}/campaign.conf".format(DATA_DIR), "w") as f:
        f.write("\n".join(config_lines))


if __name__ == "__main__":
    main()
