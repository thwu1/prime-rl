#!/usr/bin/env python3
"""Generate synthetic network flow data with embedded DDoS attack patterns.
Deterministic output via fixed seed. Produces flows.jsonl and ground truth."""
import json
import random
import os

SEED = 0x7B42CF19
random.seed(SEED)

TARGETS = ["10.0.1.10", "10.0.1.11", "10.0.1.12"]
START_TS = 1700000000.0
DURATION = 7200  # 2 hours in seconds


def rand_pub_ip():
    """Generate a random public-looking IPv4 address."""
    while True:
        a = random.randint(1, 223)
        if a in (10, 127, 169, 172, 192):
            continue
        b = random.randint(0, 255)
        c = random.randint(0, 255)
        d = random.randint(1, 254)
        return f"{a}.{b}.{c}.{d}"


def gen_legitimate():
    """Generate legitimate traffic flows."""
    flows = []
    labels = []

    # --- Normal web traffic (TCP) ---
    for _ in range(32000):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        dst = random.choice(TARGETS)
        sp = random.randint(1024, 65535)
        dp = random.choice([80, 443, 8080])

        if random.random() < 0.015:
            # SYN-only: connection timeout / refused
            flags = "S"
            pkts = random.randint(1, 3)
            bts = pkts * random.randint(40, 80)
            dur = random.randint(0, 3000)
        else:
            flags = "S,SA,A,PA,FA"
            pkts = random.randint(5, 200)
            bts = pkts * random.randint(100, 1500)
            dur = random.randint(50, 15000)

        flows.append({
            "ts": round(ts, 3), "src": src, "dst": dst,
            "sp": sp, "dp": dp, "proto": "TCP", "flags": flags,
            "pkts": pkts, "bytes": bts, "dur_ms": dur
        })
        labels.append("legitimate")

    # --- Normal UDP traffic ---
    for _ in range(5000):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        dst = random.choice(TARGETS)
        sp = random.randint(1024, 65535)
        dp = random.choice([53, 123, 443])
        pkts = random.randint(1, 10)
        bts = pkts * random.randint(40, 300)
        dur = random.randint(0, 2000)

        flows.append({
            "ts": round(ts, 3), "src": src, "dst": dst,
            "sp": sp, "dp": dp, "proto": "UDP", "flags": "",
            "pkts": pkts, "bytes": bts, "dur_ms": dur
        })
        labels.append("legitimate")

    # --- Legitimate DNS responses (small, from port 53) ---
    for _ in range(800):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        dst = random.choice(TARGETS)
        sp = 53
        dp = random.randint(1024, 65535)
        pkts = random.randint(1, 3)
        bts = random.randint(64, 512)
        dur = random.randint(0, 200)

        flows.append({
            "ts": round(ts, 3), "src": src, "dst": dst,
            "sp": sp, "dp": dp, "proto": "UDP", "flags": "",
            "pkts": pkts, "bytes": bts, "dur_ms": dur
        })
        labels.append("legitimate")

    # --- Legitimate large DNS (DNSSEC / zone transfers) ---
    # Key: destinations are varied (not concentrated on attack targets)
    for _ in range(60):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        extra_dsts = [rand_pub_ip() for _ in range(5)]
        dst = random.choice(TARGETS + extra_dsts)
        sp = 53
        dp = random.randint(1024, 65535)
        pkts = random.randint(2, 8)
        bts = random.randint(800, 2200)
        dur = random.randint(0, 500)

        flows.append({
            "ts": round(ts, 3), "src": src, "dst": dst,
            "sp": sp, "dp": dp, "proto": "UDP", "flags": "",
            "pkts": pkts, "bytes": bts, "dur_ms": dur
        })
        labels.append("legitimate")

    # --- Long download connections ---
    for _ in range(1500):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        dst = random.choice(TARGETS)
        sp = random.randint(1024, 65535)
        dp = random.choice([80, 443])
        pkts = random.randint(200, 5000)
        bts = pkts * random.randint(500, 1500)
        dur = random.randint(10000, 90000)

        flows.append({
            "ts": round(ts, 3), "src": src, "dst": dst,
            "sp": sp, "dp": dp, "proto": "TCP", "flags": "S,SA,A,PA,FA",
            "pkts": pkts, "bytes": bts, "dur_ms": dur
        })
        labels.append("legitimate")

    # --- Keep-alive connections (SSH, WebSocket) ---
    # Long duration, moderate packets, HIGH bytes (unlike slowloris)
    # On non-HTTP ports (unlike slowloris which targets port 80)
    for _ in range(80):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        dst = random.choice(TARGETS)
        sp = random.randint(1024, 65535)
        dp = random.choice([22, 443, 8443])
        pkts = random.randint(10, 30)
        bts = random.randint(5000, 50000)
        dur = random.randint(20000, 120000)

        flows.append({
            "ts": round(ts, 3), "src": src, "dst": dst,
            "sp": sp, "dp": dp, "proto": "TCP", "flags": "S,SA,A,PA",
            "pkts": pkts, "bytes": bts, "dur_ms": dur
        })
        labels.append("legitimate")

    # --- Legitimate slow API calls on port 80 ---
    # Long duration but MORE packets and MORE bytes than slowloris
    for _ in range(20):
        ts = START_TS + random.uniform(0, DURATION)
        src = rand_pub_ip()
        dst = random.choice(TARGETS)
        sp = random.randint(1024, 65535)
        dp = 80
        pkts = random.randint(20, 50)
        bts = random.randint(4000, 25000)
        dur = random.randint(25000, 70000)

        flows.append({
            "ts": round(ts, 3), "src": src, "dst": dst,
            "sp": sp, "dp": dp, "proto": "TCP", "flags": "S,SA,A,PA,FA",
            "pkts": pkts, "bytes": bts, "dur_ms": dur
        })
        labels.append("legitimate")

    return flows, labels


def gen_syn_flood():
    """Generate pulsing SYN flood attack.
    8 pulses of SYN-only traffic with rotating source subnets.
    Phase 1 (pulses 0-3): concentrated /24 subnets.
    Phase 2 (pulses 4-7): dispersed random IPs (harder to detect by subnet).
    """
    flows = []
    labels = []

    pulse_offsets = [300, 480, 720, 900, 1200, 1500, 1800, 2100]

    for pidx, offset in enumerate(pulse_offsets):
        pulse_start = START_TS + offset
        pulse_dur = random.randint(25, 35)

        if pidx < 4:
            # Phase 1: concentrated /24 subnets
            subnets = []
            for _ in range(random.randint(3, 6)):
                while True:
                    a = random.randint(50, 200)
                    if a not in (127, 169, 172, 192):
                        break
                b = random.randint(0, 255)
                c = random.randint(0, 255)
                subnets.append(f"{a}.{b}.{c}")
        else:
            subnets = None  # Phase 2: fully random IPs

        n_flows = random.randint(400, 700)
        for _ in range(n_flows):
            ts = pulse_start + random.uniform(0, pulse_dur)

            if subnets:
                net = random.choice(subnets)
                src = f"{net}.{random.randint(1, 254)}"
            else:
                src = rand_pub_ip()

            flows.append({
                "ts": round(ts, 3),
                "src": src,
                "dst": random.choice(TARGETS[:2]),
                "sp": random.randint(1024, 65535),
                "dp": random.choice([80, 443]),
                "proto": "TCP", "flags": "S",
                "pkts": random.randint(1, 3),
                "bytes": random.randint(40, 120),
                "dur_ms": random.randint(0, 100)
            })
            labels.append("syn_flood")

    return flows, labels


def gen_slowloris():
    """Generate Slowloris (HTTP connection exhaustion) attack.
    40 attacker IPs each hold 3-8 slow connections on port 80.
    Each attacker also makes 1-3 normal connections (camouflage)."""
    attack_flows = []
    attack_labels = []
    camo_flows = []
    camo_labels = []

    attacker_ips = [rand_pub_ip() for _ in range(40)]

    for ip in attacker_ips:
        n_slow = random.randint(3, 8)
        for _ in range(n_slow):
            ts = START_TS + random.uniform(600, 6600)
            attack_flows.append({
                "ts": round(ts, 3), "src": ip,
                "dst": random.choice(TARGETS),
                "sp": random.randint(1024, 65535), "dp": 80,
                "proto": "TCP", "flags": "S,SA,A,PA",
                "pkts": random.randint(3, 15),
                "bytes": random.randint(200, 1500),
                "dur_ms": random.randint(30000, 180000)
            })
            attack_labels.append("slowloris")

        n_normal = random.randint(1, 3)
        for _ in range(n_normal):
            ts = START_TS + random.uniform(600, 6600)
            camo_flows.append({
                "ts": round(ts, 3), "src": ip,
                "dst": random.choice(TARGETS),
                "sp": random.randint(1024, 65535),
                "dp": random.choice([80, 443]),
                "proto": "TCP", "flags": "S,SA,A,PA,FA",
                "pkts": random.randint(10, 100),
                "bytes": random.randint(1000, 50000),
                "dur_ms": random.randint(100, 5000)
            })
            camo_labels.append("legitimate")

    return attack_flows, attack_labels, camo_flows, camo_labels


def gen_dns_amplification():
    """Generate DNS amplification / reflection attack.
    200 spoofed resolver IPs send large UDP responses to targets."""
    flows = []
    labels = []

    resolvers = []
    for _ in range(200):
        a = random.choice([8, 9, 64, 65, 74, 75, 76, 77])
        b = random.randint(0, 255)
        c = random.randint(0, 255)
        d = random.randint(1, 254)
        resolvers.append(f"{a}.{b}.{c}.{d}")

    amp_targets = TARGETS[:2]

    for _ in range(3000):
        ts = START_TS + random.uniform(1800, 5400)
        flows.append({
            "ts": round(ts, 3),
            "src": random.choice(resolvers),
            "dst": random.choice(amp_targets),
            "sp": 53,
            "dp": random.randint(1024, 65535),
            "proto": "UDP", "flags": "",
            "pkts": random.randint(1, 5),
            "bytes": random.randint(1500, 4096),
            "dur_ms": random.randint(0, 500)
        })
        labels.append("dns_amp")

    return flows, labels


def main():
    os.makedirs("/app/output", exist_ok=True)
    os.makedirs("/var/lib/tbench", exist_ok=True)

    legit_flows, legit_labels = gen_legitimate()
    syn_flows, syn_labels = gen_syn_flood()
    slow_atk, slow_atk_labels, slow_camo, slow_camo_labels = gen_slowloris()
    dns_flows, dns_labels = gen_dns_amplification()

    all_data = list(zip(
        legit_flows + syn_flows + slow_atk + slow_camo + dns_flows,
        legit_labels + syn_labels + slow_atk_labels + slow_camo_labels + dns_labels
    ))

    random.shuffle(all_data)

    ground_truth = {"syn_flood": [], "slowloris": [], "dns_amp": []}

    with open("/app/flows.jsonl", "w") as f:
        for i, (flow, label) in enumerate(all_data):
            fid = f"f-{i:06d}"
            flow["id"] = fid
            if label in ground_truth:
                ground_truth[label].append(fid)
            json.dump(flow, f)
            f.write("\n")

    # Sort IDs within each category for consistency
    for k in ground_truth:
        ground_truth[k].sort()

    with open("/var/lib/tbench/gt.json", "w") as f:
        json.dump(ground_truth, f)

    total = len(all_data)
    n_atk = sum(len(v) for v in ground_truth.values())
    print(f"Generated {total} flows ({n_atk} attack, {total - n_atk} legitimate)")
    for k, v in ground_truth.items():
        print(f"  {k}: {len(v)} flows")


if __name__ == "__main__":
    main()
