#!/usr/bin/env python3

"""Regenerate ground truth labels at test time.
Uses identical PRNG seed and flow generation logic as generate_data.py.
MUST be kept in exact sync with generate_data.py's flow generation functions."""

import random

SEED = 0x7B42CF19
TARGETS = ["10.0.1.10", "10.0.1.11", "10.0.1.12"]
START_TS = 1700000000.0
DURATION = 7200


def rand_pub_ip():
    while True:
        a = random.randint(1, 223)
        if a in (10, 127, 169, 172, 192):
            continue
        b = random.randint(0, 255)
        c = random.randint(0, 255)
        d = random.randint(1, 254)
        return f"{a}.{b}.{c}.{d}"


def gen_legitimate():
    flows, labels = [], []
    for _ in range(32000):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        dst = random.choice(TARGETS)
        sp = random.randint(1024, 65535)
        dp = random.choice([80, 443, 8080])
        if random.random() < 0.015:
            flags, pkts = "S", random.randint(1, 3)
            bts, dur = pkts * random.randint(40, 80), random.randint(0, 3000)
        else:
            flags = "S,SA,A,PA,FA"
            pkts = random.randint(5, 200)
            bts, dur = pkts * random.randint(100, 1500), random.randint(50, 15000)
        flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                       "proto": "TCP", "flags": flags, "pkts": pkts, "bytes": bts, "dur_ms": dur})
        labels.append("legitimate")
    for _ in range(5000):
        ts = START_TS + random.uniform(0, DURATION)
        src, dst = rand_pub_ip(), random.choice(TARGETS)
        sp, dp = random.randint(1024, 65535), random.choice([53, 123, 443])
        pkts = random.randint(1, 10)
        bts, dur = pkts * random.randint(40, 300), random.randint(0, 2000)
        flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                       "proto": "UDP", "flags": "", "pkts": pkts, "bytes": bts, "dur_ms": dur})
        labels.append("legitimate")
    for _ in range(800):
        ts = START_TS + random.uniform(0, DURATION)
        src, dst = rand_pub_ip(), random.choice(TARGETS)
        sp, dp = 53, random.randint(1024, 65535)
        pkts = random.randint(1, 3)
        bts, dur = random.randint(64, 512), random.randint(0, 200)
        flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                       "proto": "UDP", "flags": "", "pkts": pkts, "bytes": bts, "dur_ms": dur})
        labels.append("legitimate")
    for _ in range(60):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        extra_dsts = [rand_pub_ip() for _ in range(5)]
        dst = random.choice(TARGETS + extra_dsts)
        sp, dp = 53, random.randint(1024, 65535)
        pkts = random.randint(2, 8)
        bts, dur = random.randint(800, 2200), random.randint(0, 500)
        flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                       "proto": "UDP", "flags": "", "pkts": pkts, "bytes": bts, "dur_ms": dur})
        labels.append("legitimate")
    for _ in range(1500):
        ts = START_TS + random.uniform(0, DURATION)
        src, dst = rand_pub_ip(), random.choice(TARGETS)
        sp, dp = random.randint(1024, 65535), random.choice([80, 443])
        pkts = random.randint(200, 5000)
        bts, dur = pkts * random.randint(500, 1500), random.randint(10000, 90000)
        flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                       "proto": "TCP", "flags": "S,SA,A,PA,FA", "pkts": pkts, "bytes": bts, "dur_ms": dur})
        labels.append("legitimate")
    for _ in range(80):
        ts = START_TS + random.uniform(0, DURATION)
        src, dst = rand_pub_ip(), random.choice(TARGETS)
        sp, dp = random.randint(1024, 65535), random.choice([22, 443, 8443])
        pkts = random.randint(10, 30)
        bts, dur = random.randint(5000, 50000), random.randint(20000, 120000)
        flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                       "proto": "TCP", "flags": "S,SA,A,PA", "pkts": pkts, "bytes": bts, "dur_ms": dur})
        labels.append("legitimate")
    for _ in range(20):
        ts = START_TS + random.uniform(0, DURATION)
        src, dst = rand_pub_ip(), random.choice(TARGETS)
        sp, dp = random.randint(1024, 65535), 80
        pkts = random.randint(20, 50)
        bts, dur = random.randint(4000, 25000), random.randint(25000, 70000)
        flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                       "proto": "TCP", "flags": "S,SA,A,PA,FA", "pkts": pkts, "bytes": bts, "dur_ms": dur})
        labels.append("legitimate")
    return flows, labels


def gen_burst_health_checks():
    flows, labels = [], []
    burst_offsets = [350, 550, 750, 950, 1250, 1550]
    for offset in burst_offsets:
        burst_start = START_TS + offset
        burst_dur = random.randint(20, 35)
        n_flows = random.randint(300, 450)
        for _ in range(n_flows):
            ts = burst_start + random.uniform(0, burst_dur)
            src, dst = rand_pub_ip(), random.choice(TARGETS[:2])
            sp, dp = random.randint(1024, 65535), random.choice([80, 443])
            flows.append({"ts": round(ts, 3), "src": src, "dst": dst, "sp": sp, "dp": dp,
                           "proto": "TCP", "flags": "S,SA,A,FA",
                           "pkts": random.randint(1, 3), "bytes": random.randint(40, 200),
                           "dur_ms": random.randint(0, 100)})
            labels.append("legitimate")
    return flows, labels


def gen_syn_flood():
    flows, labels = [], []
    pulse_offsets = [300, 480, 720, 900, 1200, 1500, 1800, 2100]
    for pidx, offset in enumerate(pulse_offsets):
        pulse_start = START_TS + offset
        pulse_dur = random.randint(25, 35)
        if pidx < 4:
            subnets = []
            for _ in range(random.randint(3, 6)):
                while True:
                    a = random.randint(50, 200)
                    if a not in (127, 169, 172, 192):
                        break
                b, c = random.randint(0, 255), random.randint(0, 255)
                subnets.append(f"{a}.{b}.{c}")
        else:
            subnets = None
        n_flows = random.randint(400, 700)
        for _ in range(n_flows):
            ts = pulse_start + random.uniform(0, pulse_dur)
            if subnets:
                net = random.choice(subnets)
                src = f"{net}.{random.randint(1, 254)}"
            else:
                src = rand_pub_ip()
            flows.append({"ts": round(ts, 3), "src": src,
                           "dst": random.choice(TARGETS[:2]),
                           "sp": random.randint(1024, 65535),
                           "dp": random.choice([80, 443]),
                           "proto": "TCP", "flags": "S",
                           "pkts": random.randint(1, 3),
                           "bytes": random.randint(40, 120),
                           "dur_ms": random.randint(0, 100)})
            labels.append("syn_flood")
    return flows, labels


def gen_slowloris():
    attack_flows, attack_labels = [], []
    camo_flows, camo_labels = [], []
    attacker_ips = [rand_pub_ip() for _ in range(40)]
    for ip in attacker_ips:
        for _ in range(random.randint(3, 8)):
            ts = START_TS + random.uniform(600, 6600)
            attack_flows.append({"ts": round(ts, 3), "src": ip,
                                  "dst": random.choice(TARGETS),
                                  "sp": random.randint(1024, 65535), "dp": 80,
                                  "proto": "TCP", "flags": "S,SA,A,PA",
                                  "pkts": random.randint(3, 15),
                                  "bytes": random.randint(200, 1500),
                                  "dur_ms": random.randint(30000, 180000)})
            attack_labels.append("slowloris")
        for _ in range(random.randint(1, 3)):
            ts = START_TS + random.uniform(600, 6600)
            camo_flows.append({"ts": round(ts, 3), "src": ip,
                                "dst": random.choice(TARGETS),
                                "sp": random.randint(1024, 65535),
                                "dp": random.choice([80, 443]),
                                "proto": "TCP", "flags": "S,SA,A,PA,FA",
                                "pkts": random.randint(10, 100),
                                "bytes": random.randint(1000, 50000),
                                "dur_ms": random.randint(100, 5000)})
            camo_labels.append("legitimate")
    return attack_flows, attack_labels, camo_flows, camo_labels


def gen_dns_amplification():
    flows, labels = [], []
    resolvers = []
    for _ in range(200):
        a = random.choice([8, 9, 64, 65, 74, 75, 76, 77])
        b, c = random.randint(0, 255), random.randint(0, 255)
        d = random.randint(1, 254)
        resolvers.append(f"{a}.{b}.{c}.{d}")
    amp_targets = TARGETS[:2]
    for _ in range(3000):
        ts = START_TS + random.uniform(1800, 5400)
        flows.append({"ts": round(ts, 3),
                       "src": random.choice(resolvers),
                       "dst": random.choice(amp_targets),
                       "sp": 53, "dp": random.randint(1024, 65535),
                       "proto": "UDP", "flags": "",
                       "pkts": random.randint(1, 5),
                       "bytes": random.randint(1500, 4096),
                       "dur_ms": random.randint(0, 500)})
        labels.append("dns_amp")
    return flows, labels


def generate():
    """Regenerate ground truth. Returns {attack_type: set(flow_ids)}."""
    random.seed(SEED)

    _, legit_labels = gen_legitimate()
    _, burst_labels = gen_burst_health_checks()
    _, syn_labels = gen_syn_flood()
    _, slow_atk_labels, _, slow_camo_labels = gen_slowloris()
    _, dns_labels = gen_dns_amplification()

    all_labels = (legit_labels + burst_labels + syn_labels
                  + slow_atk_labels + slow_camo_labels + dns_labels)

    # Reproduce identical shuffle permutation (depends only on list length + PRNG state)
    indexed = list(enumerate(all_labels))
    random.shuffle(indexed)

    ground_truth = {"syn_flood": [], "slowloris": [], "dns_amp": []}
    for new_idx, (_orig_idx, label) in enumerate(indexed):
        fid = f"f-{new_idx:06d}"
        if label in ground_truth:
            ground_truth[label].append(fid)

    for k in ground_truth:
        ground_truth[k].sort()

    return {k: set(v) for k, v in ground_truth.items()}
