#!/usr/bin/env python3
"""
Generates a random microkernel system configuration for the isolation analysis task.
Each seed produces a unique system with guaranteed interesting properties:
- Cycles in the information flow graph (non-trivial transitive closure)
- Multi-path resources creating min-cuts > 1
- Mix of violated and non-violated isolation constraints
- Isolated PDs with singleton TCBs
- At least one sink PD (impacts only itself)

"""
import json
import os
import random
import sys
from collections import defaultdict, deque


PD_NAME_POOL = [
    "timer_drv", "eth_drv", "serial_drv", "block_drv", "can_drv",
    "usb_drv", "spi_drv", "i2c_drv", "gpio_ctrl", "dma_ctrl",
    "net_stack", "crypto_svc", "firewall", "ipsec_gw", "tls_proxy",
    "vm_guest_a", "vm_guest_b", "vm_mission", "vm_debug", "vm_sandbox",
    "sensor_hub", "actuator_ctrl", "flight_ctrl", "motor_ctrl",
    "health_mon", "log_svc", "telemetry_tx", "auth_svc",
    "config_store", "watchdog", "diag_svc", "nav_compute",
    "power_mgr", "audio_proc", "video_enc", "display_mgr",
    "fault_handler", "raid_ctrl", "cache_mgr", "ipc_broker",
]

TRUST_LEVELS = ["system", "app", "guest"]
CRITICALITIES = ["critical", "high", "medium", "low"]


def _bfs_reach(adj, src):
    visited = {src}
    q = deque([src])
    while q:
        n = q.popleft()
        for nb in adj.get(n, set()):
            if nb not in visited:
                visited.add(nb)
                q.append(nb)
    return visited


def _compute_flow_adj(access_rights):
    resource_writers = defaultdict(set)
    resource_readers = defaultdict(set)
    for ar in access_rights:
        pd, res, perm = ar["pd_id"], ar["resource_id"], ar["permissions"]
        if perm in ("write", "readwrite"):
            resource_writers[res].add(pd)
        if perm in ("read", "readwrite"):
            resource_readers[res].add(pd)
    adj = defaultdict(set)
    for res in set(resource_writers) | set(resource_readers):
        for w in resource_writers[res]:
            for r in resource_readers[res]:
                if w != r:
                    adj[w].add(r)
    return adj


def _count_edges(adj):
    return sum(len(v) for v in adj.values())


def _has_cycle(adj, nodes):
    for start in nodes:
        visited = set()
        q = deque([start])
        while q:
            n = q.popleft()
            for nb in adj.get(n, set()):
                if nb == start and n != start:
                    return True
                if nb not in visited:
                    visited.add(nb)
                    q.append(nb)
    return False


def generate_system(seed_str):
    rng = random.Random(seed_str)

    num_pds = rng.randint(19, 24)
    selected_names = rng.sample(PD_NAME_POOL, num_pds)
    rng.shuffle(selected_names)

    pds = []
    for i, name in enumerate(selected_names):
        pds.append({
            "id": f"pd_{i+1:02d}",
            "name": name,
            "trust_level": rng.choice(TRUST_LEVELS),
            "criticality": rng.choice(CRITICALITIES),
        })
    pd_ids = [p["id"] for p in pds]

    num_resources = rng.randint(38, 48)
    num_devices = rng.randint(4, 7)
    resources = []
    for i in range(num_resources):
        rid = f"r_{i+1:02d}"
        if i < num_devices:
            resources.append({"id": rid, "name": f"dev_{i+1:02d}", "type": "device"})
        else:
            resources.append({
                "id": rid, "name": f"shm_{i+1:02d}",
                "type": "shared_memory",
                "size_kb": rng.choice([4, 8, 16, 32, 64, 128]),
            })
    res_ids = [r["id"] for r in resources]
    dev_ids = [r["id"] for r in resources if r["type"] == "device"]
    shm_ids = [r["id"] for r in resources if r["type"] == "shared_memory"]

    access_rights = []
    used_pairs = set()

    def add_ar(pd, res, perm):
        key = (pd, res)
        if key not in used_pairs:
            access_rights.append({"pd_id": pd, "resource_id": res, "permissions": perm})
            used_pairs.add(key)
            return True
        return False

    # Reserve some shm for isolated PDs (exclusive, no-flow resources)
    num_isolated = rng.randint(3, min(5, num_pds - 12))
    # Pick isolated PDs
    isolated = rng.sample(pd_ids, num_isolated)
    connected = [p for p in pd_ids if p not in isolated]
    rng.shuffle(connected)

    # Reserve exclusive resources for isolated PDs (one each, read-only)
    isolated_res = rng.sample(shm_ids, num_isolated)
    available_shm = [s for s in shm_ids if s not in isolated_res]

    for pd, res in zip(isolated, isolated_res):
        add_ar(pd, res, "read")  # read-only, no other PD touches this resource

    # Also give isolated PDs their own device (exclusive)
    for i, pd in enumerate(isolated):
        if i < len(dev_ids):
            add_ar(pd, dev_ids[i], "readwrite")

    # Phase 1: device owners for connected PDs
    remaining_devs = dev_ids[num_isolated:]
    for i, did in enumerate(remaining_devs):
        add_ar(connected[i % len(connected)], did, "readwrite")

    # Phase 2: connected backbone chain
    shm_pool = list(available_shm)
    rng.shuffle(shm_pool)
    shm_idx = [0]

    def pick_shm():
        r = shm_pool[shm_idx[0] % len(shm_pool)]
        shm_idx[0] += 1
        return r

    for i in range(len(connected) - 1):
        r = pick_shm()
        add_ar(connected[i], r, "write")
        add_ar(connected[i + 1], r, "read")

    # Phase 3: back-edges for cycles
    for _ in range(rng.randint(4, 8)):
        hi = rng.randint(len(connected) // 2, len(connected) - 1)
        lo = rng.randint(0, max(0, len(connected) // 2 - 1))
        if connected[hi] != connected[lo]:
            r = pick_shm()
            add_ar(connected[hi], r, "write")
            add_ar(connected[lo], r, "read")

    # Phase 4: multi-writer/reader resources for min-cuts > 1
    for _ in range(rng.randint(3, 6)):
        r = pick_shm()
        ws = rng.sample(connected, min(rng.randint(2, 3), len(connected)))
        pool = [p for p in connected if p not in ws]
        rs = rng.sample(pool, min(rng.randint(2, 3), len(pool))) if pool else []
        for w in ws:
            add_ar(w, r, "write")
        for rd in rs:
            add_ar(rd, r, "read")

    # Phase 5: readwrite for complexity
    for _ in range(rng.randint(4, 8)):
        add_ar(rng.choice(connected), rng.choice(available_shm), "readwrite")

    # Ensure at least one sink: a PD that can receive flow but doesn't send any
    # Pick last connected PD, remove its write/readwrite on shared memory
    sink_candidate = connected[-1]
    new_ar = []
    for ar in access_rights:
        if ar["pd_id"] == sink_candidate and ar["permissions"] in ("write", "readwrite") \
                and ar["resource_id"] in shm_ids:
            # Convert readwrite to read, drop write
            if ar["permissions"] == "readwrite":
                new_ar.append({**ar, "permissions": "read"})
            # skip pure write
        else:
            new_ar.append(ar)
    access_rights = new_ar
    used_pairs = {(ar["pd_id"], ar["resource_id"]) for ar in access_rights}

    # Give sink a read on one more shared resource to ensure it's reachable
    r = pick_shm()
    if connected[-2:]:
        add_ar(connected[-2], r, "write")
        add_ar(sink_candidate, r, "read")

    # Compute flow graph for constraint generation
    adj = _compute_flow_adj(access_rights)
    reachability = {pd: _bfs_reach(adj, pd) for pd in pd_ids}

    # Generate constraints
    num_constraints = rng.randint(8, 12)
    constraints = []
    used_cpairs = set()

    target_violated = rng.randint(max(3, num_constraints // 2), num_constraints - 2)

    # Violated constraints (between connected PDs that can reach each other)
    for _ in range(500):
        if len([c for c in constraints if c["_v"]]) >= target_violated:
            break
        a, b = rng.sample(pd_ids, 2)
        if (a, b) in used_cpairs or (b, a) in used_cpairs:
            continue
        if b in reachability[a] or a in reachability[b]:
            constraints.append({
                "pd_a": a, "pd_b": b,
                "label": f"{pds[pd_ids.index(a)]['name']} must be isolated from {pds[pd_ids.index(b)]['name']}",
                "_v": True,
            })
            used_cpairs.add((a, b))

    # Non-violated constraints (using isolated PDs or unreachable pairs)
    for _ in range(500):
        if len(constraints) >= num_constraints:
            break
        # Prefer isolated PDs for guaranteed non-violation
        if isolated and rng.random() < 0.7:
            a = rng.choice(isolated)
            b = rng.choice([p for p in pd_ids if p != a])
        else:
            a, b = rng.sample(pd_ids, 2)
        if (a, b) in used_cpairs or (b, a) in used_cpairs:
            continue
        if b not in reachability[a] and a not in reachability[b]:
            constraints.append({
                "pd_a": a, "pd_b": b,
                "label": f"{pds[pd_ids.index(a)]['name']} must be isolated from {pds[pd_ids.index(b)]['name']}",
                "_v": False,
            })
            used_cpairs.add((a, b))

    rng.shuffle(constraints)

    clean_constraints = [{"pd_a": c["pd_a"], "pd_b": c["pd_b"], "label": c["label"]}
                         for c in constraints]

    system = {
        "description": "Safety-critical embedded system with seL4-style protection domain isolation",
        "dna_token": seed_str,
        "protection_domains": pds,
        "resources": resources,
        "access_rights": access_rights,
        "isolation_constraints": clean_constraints,
    }
    return system


def validate(system):
    adj = _compute_flow_adj(system["access_rights"])
    pd_ids = [p["id"] for p in system["protection_domains"]]
    n_edges = _count_edges(adj)
    reachability = {pd: _bfs_reach(adj, pd) for pd in pd_ids}
    sinks = [p for p in pd_ids if reachability[p] == {p}]
    singletons = [p for p in pd_ids
                  if all(p not in reachability[o] or o == p for o in pd_ids)]

    violated = 0
    for c in system["isolation_constraints"]:
        a, b = c["pd_a"], c["pd_b"]
        if b in reachability[a] or a in reachability[b]:
            violated += 1
    non_violated = len(system["isolation_constraints"]) - violated

    ok = True
    if n_edges < 20:
        ok = False
    if not _has_cycle(adj, pd_ids):
        ok = False
    if len(sinks) < 1:
        ok = False
    if len(singletons) < 1:
        ok = False
    if violated < 3:
        ok = False
    if non_violated < 2:
        ok = False
    if len(system["access_rights"]) < 50:
        ok = False
    if len(system["isolation_constraints"]) < 8:
        ok = False
    return ok


def main():
    if len(sys.argv) > 1:
        seed = sys.argv[1]
    else:
        seed = os.urandom(16).hex()

    attempt = 0
    while True:
        current_seed = f"{seed}_{attempt}" if attempt > 0 else seed
        system = generate_system(current_seed)
        if validate(system):
            seed = current_seed
            break
        attempt += 1
        if attempt > 200:
            raise RuntimeError("Failed to generate valid system after 200 attempts")

    os.makedirs("/app", exist_ok=True)
    with open("/app/system.json", "w") as f:
        json.dump(system, f, indent=2)

    with open("/app/.dna", "w") as f:
        f.write(seed + "\n")

    adj = _compute_flow_adj(system["access_rights"])
    print(f"Generated system (seed={seed}): "
          f"{len(system['protection_domains'])} PDs, "
          f"{len(system['resources'])} resources, "
          f"{len(system['access_rights'])} access rights, "
          f"{_count_edges(adj)} flow edges, "
          f"{len(system['isolation_constraints'])} constraints")


if __name__ == "__main__":
    main()
