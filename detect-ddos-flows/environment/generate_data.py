#!/usr/bin/env python3

"""Generate synthetic network forensics data for DDoS classification task.
Creates pcap capture file, SQLite database (flow records without TCP flags,
server metrics, firewall events), and Apache access log.
Deterministic via fixed seed. No ground truth written to image."""

import json
import random
import sqlite3
import struct
import socket
import os
from datetime import datetime, timezone

SEED = 0x7B42CF19
random.seed(SEED)

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


# ========== Flow generation ==========
# These functions must be identical in tests/gen_ground_truth.py

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
    """Monitoring probes in rapid bursts — temporal pattern overlaps SYN flood
    but connections complete full TCP handshake (not SYN-only)."""
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


# ========== PCAP generation ==========

TCP_SYN = 0x02
TCP_ACK = 0x10
TCP_FINACK = 0x11
TCP_PSHACK = 0x18


def ip_to_bytes(ip_str):
    return socket.inet_aton(ip_str)


def make_tcp_packet(src_ip, dst_ip, sport, dport, flags_byte, ttl=64, window=65535):
    eth = b'\xff\xff\xff\xff\xff\xff\x02\x00\x00\x00\x00\x01'
    eth += struct.pack('>H', 0x0800)
    tcp = struct.pack('>HHIIBBHHH', sport, dport, 0, 0, 5 << 4, flags_byte, window, 0, 0)
    ip_hdr = struct.pack('>BBHHHBBH4s4s', 0x45, 0, 40, 0, 0x4000,
                         ttl, 6, 0, ip_to_bytes(src_ip), ip_to_bytes(dst_ip))
    return eth + ip_hdr + tcp


def make_udp_packet(src_ip, dst_ip, sport, dport, payload_size=0, ttl=64):
    eth = b'\xff\xff\xff\xff\xff\xff\x02\x00\x00\x00\x00\x01'
    eth += struct.pack('>H', 0x0800)
    payload = b'\x00' * payload_size
    udp_len = 8 + payload_size
    udp = struct.pack('>HHHH', sport, dport, udp_len, 0)
    ip_total = 20 + 8 + payload_size
    ip_hdr = struct.pack('>BBHHHBBH4s4s', 0x45, 0, ip_total, 0, 0x4000,
                         ttl, 17, 0, ip_to_bytes(src_ip), ip_to_bytes(dst_ip))
    return eth + ip_hdr + udp + payload


def write_pcap(filename, packets):
    with open(filename, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts_sec, ts_usec, data in packets:
            caplen = len(data)
            f.write(struct.pack('<IIII', ts_sec, ts_usec, caplen, caplen))
            f.write(data)


def gen_pcap_packets(all_data):
    """Generate representative pcap packets for each flow.
    Uses a separate PRNG to not disturb main sequence."""
    packets = []
    pcap_rng = random.Random(0xDEADBEEF)

    for flow, label in all_data:
        ts = flow["ts"]
        ts_sec = int(ts)
        ts_usec = int((ts - ts_sec) * 1000000)
        src, dst = flow["src"], flow["dst"]
        sp, dp = flow["sp"], flow["dp"]
        flags = flow["flags"]

        if flow["proto"] == "TCP":
            ttl = pcap_rng.randint(30, 255) if label == "syn_flood" else pcap_rng.choice([64, 64, 64, 128, 128, 255])
            window = pcap_rng.randint(128, 512) if label == "slowloris" else pcap_rng.randint(16384, 65535)

            pkt = make_tcp_packet(src, dst, sp, dp, TCP_SYN, ttl, window)
            packets.append((ts_sec, ts_usec, pkt))

            if flags != "S":
                delay = pcap_rng.randint(1000, 50000)
                us2 = ts_usec + delay
                s2 = ts_sec + us2 // 1000000
                us2 = us2 % 1000000
                packets.append((s2, us2, make_tcp_packet(src, dst, sp, dp, TCP_ACK, ttl, window)))

                if "FA" in flags:
                    delay2 = pcap_rng.randint(10000, 200000)
                    us3 = us2 + delay2
                    s3 = s2 + us3 // 1000000
                    us3 = us3 % 1000000
                    packets.append((s3, us3, make_tcp_packet(src, dst, sp, dp, TCP_FINACK, ttl, window)))
                elif "PA" in flags:
                    delay2 = pcap_rng.randint(10000, 200000)
                    us3 = us2 + delay2
                    s3 = s2 + us3 // 1000000
                    us3 = us3 % 1000000
                    packets.append((s3, us3, make_tcp_packet(src, dst, sp, dp, TCP_PSHACK, ttl, window)))
        else:
            ttl = pcap_rng.choice([64, 64, 128])
            payload_size = min(flow["bytes"], 200)
            pkt = make_udp_packet(src, dst, sp, dp, payload_size, ttl)
            packets.append((ts_sec, ts_usec, pkt))

    packets.sort(key=lambda x: (x[0], x[1]))
    return packets


# ========== Correlated data generation ==========

def gen_server_stats(all_data):
    minute_bins = {}
    for flow, label in all_data:
        minute = int((flow["ts"] - START_TS) / 60)
        key = (minute, flow["dst"])
        if key not in minute_bins:
            minute_bins[key] = {"total": 0, "syn_flood": 0, "slowloris": 0, "dns_amp": 0, "bytes": 0}
        minute_bins[key]["total"] += 1
        minute_bins[key]["bytes"] += flow["bytes"]
        if label in minute_bins[key]:
            minute_bins[key][label] += 1
    stats = []
    for minute in range(DURATION // 60):
        for server in TARGETS:
            bd = minute_bins.get((minute, server),
                                {"total": 0, "syn_flood": 0, "slowloris": 0, "dns_amp": 0, "bytes": 0})
            base_cpu, base_mem = random.uniform(15, 35), random.uniform(40, 55)
            base_conns, base_req = random.randint(50, 200), random.uniform(20, 80)
            base_to, base_syn = random.randint(0, 2), random.randint(0, 5)
            cpu_add = min(bd["syn_flood"] * 0.05, 40) if bd["syn_flood"] else 0
            conn_add = bd["slowloris"] * 3 if bd["slowloris"] else 0
            to_add = (bd["syn_flood"] // 5 + bd["slowloris"]) if (bd["syn_flood"] + bd["slowloris"]) else 0
            bytes_in = bd["bytes"] + random.randint(10000, 50000)
            bytes_out = random.randint(50000, 200000)
            if bd["dns_amp"]:
                bytes_in += bd["dns_amp"] * 2000
            stats.append({
                "ts": round(START_TS + minute * 60 + random.uniform(0, 5), 3),
                "server_ip": server,
                "cpu_pct": round(min(base_cpu + cpu_add, 99), 1),
                "mem_pct": round(min(base_mem + random.uniform(-2, 5), 95), 1),
                "active_conns": base_conns + conn_add,
                "req_rate": round(base_req + random.uniform(-5, 5), 1),
                "conn_timeouts": base_to + to_add,
                "syn_backlog": base_syn + bd["syn_flood"],
                "bytes_in": bytes_in, "bytes_out": bytes_out
            })
    return stats


def gen_fw_events(all_data):
    events = []
    for flow, label in all_data:
        if random.random() > 0.15:
            continue
        if label == "syn_flood":
            action = random.choice(["DROP", "DROP", "DROP", "ACCEPT"])
            reason = random.choice(["INVALID", "RATE_LIMIT", "SYN_FLOOD", "NEW"])
        elif label == "slowloris":
            action, reason = ("ACCEPT", "ESTABLISHED") if random.random() < 0.6 else ("DROP", "TIMEOUT")
        elif label == "dns_amp":
            action = random.choice(["ACCEPT", "ACCEPT", "DROP"])
            reason = random.choice(["NEW", "ESTABLISHED", "RATE_LIMIT"])
        else:
            action = random.choice(["ACCEPT", "ACCEPT", "ACCEPT", "DROP"])
            reason = random.choice(["NEW", "ESTABLISHED", "RELATED", "TIMEOUT"])
        events.append({"ts": round(flow["ts"] + random.uniform(-0.5, 0.5), 3),
                        "src": flow["src"], "dst": flow["dst"],
                        "sport": flow["sp"], "dport": flow["dp"],
                        "proto": flow["proto"], "action": action, "reason": reason})
    return events


def gen_httpd_access_log(all_data):
    paths = ["/", "/index.html", "/api/v1/status", "/api/v1/data",
             "/assets/style.css", "/assets/app.js", "/images/logo.png",
             "/favicon.ico", "/api/v1/users", "/api/v1/search",
             "/dashboard", "/login", "/healthcheck"]
    uas = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
           "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
           "curl/8.1.2", "python-requests/2.31.0"]
    lines = []
    for flow, label in all_data:
        if flow["proto"] != "TCP" or flow["dp"] not in (80, 8080):
            continue
        if random.random() > 0.3:
            continue
        dt = datetime.fromtimestamp(flow["ts"], tz=timezone.utc)
        ts_str = dt.strftime("%d/%b/%Y:%H:%M:%S +0000")
        if label == "slowloris":
            if random.random() < 0.7:
                method = random.choice(["GET", "POST"])
                path, status = random.choice(paths[:3]), random.choice([408, 408, 408, 400, 0])
                size, ua = random.randint(0, 200), random.choice(uas[:2])
            else:
                method, path = "GET", random.choice(paths)
                status, size, ua = 200, random.randint(200, 50000), random.choice(uas)
        elif label == "syn_flood":
            continue
        else:
            method = random.choice(["GET", "GET", "GET", "POST", "PUT", "DELETE"])
            path, status = random.choice(paths), random.choice([200, 200, 200, 200, 301, 304, 404, 500])
            size, ua = random.randint(200, 100000), random.choice(uas)
        line = f'{flow["src"]} - - [{ts_str}] "{method} {path} HTTP/1.1" {status} {size} "-" "{ua}"'
        lines.append((flow["ts"], line))
    lines.sort(key=lambda x: x[0])
    return [l[1] for l in lines]


# ========== Main ==========

def main():
    os.makedirs("/app/output", exist_ok=True)
    os.makedirs("/app/captures", exist_ok=True)

    legit_flows, legit_labels = gen_legitimate()
    burst_flows, burst_labels = gen_burst_health_checks()
    syn_flows, syn_labels = gen_syn_flood()
    slow_atk, slow_atk_labels, slow_camo, slow_camo_labels = gen_slowloris()
    dns_flows, dns_labels = gen_dns_amplification()

    all_data = list(zip(
        legit_flows + burst_flows + syn_flows + slow_atk + slow_camo + dns_flows,
        legit_labels + burst_labels + syn_labels + slow_atk_labels + slow_camo_labels + dns_labels
    ))
    random.shuffle(all_data)

    for i, (flow, _label) in enumerate(all_data):
        flow["id"] = f"f-{i:06d}"

    # Generate pcap (separate PRNG, does not affect main sequence)
    print("Generating pcap...")
    pcap_packets = gen_pcap_packets(all_data)
    write_pcap("/app/captures/traffic.pcap", pcap_packets)
    print(f"  {len(pcap_packets)} packets written")

    # Generate correlated data (uses main PRNG, but after shuffle/IDs)
    server_stats = gen_server_stats(all_data)
    fw_events = gen_fw_events(all_data)
    access_log = gen_httpd_access_log(all_data)

    # Create SQLite database — NOTE: no TCP flags column
    db = sqlite3.connect("/app/network.db")
    cur = db.cursor()
    cur.execute("""CREATE TABLE netflow (
        id TEXT PRIMARY KEY, ts REAL NOT NULL, src TEXT NOT NULL,
        dst TEXT NOT NULL, sport INTEGER NOT NULL, dport INTEGER NOT NULL,
        proto TEXT NOT NULL, pkts INTEGER NOT NULL,
        bytes INTEGER NOT NULL, dur_ms INTEGER NOT NULL
    )""")
    cur.execute("""CREATE TABLE server_stats (
        ts REAL NOT NULL, server_ip TEXT NOT NULL, cpu_pct REAL,
        mem_pct REAL, active_conns INTEGER, req_rate REAL,
        conn_timeouts INTEGER, syn_backlog INTEGER,
        bytes_in INTEGER, bytes_out INTEGER
    )""")
    cur.execute("""CREATE TABLE fw_events (
        ts REAL NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
        sport INTEGER, dport INTEGER, proto TEXT,
        action TEXT NOT NULL, reason TEXT
    )""")

    for flow, _ in all_data:
        cur.execute("INSERT INTO netflow VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (flow["id"], flow["ts"], flow["src"], flow["dst"],
                     flow["sp"], flow["dp"], flow["proto"],
                     flow["pkts"], flow["bytes"], flow["dur_ms"]))
    for s in server_stats:
        cur.execute("INSERT INTO server_stats VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (s["ts"], s["server_ip"], s["cpu_pct"], s["mem_pct"],
                     s["active_conns"], s["req_rate"], s["conn_timeouts"],
                     s["syn_backlog"], s["bytes_in"], s["bytes_out"]))
    for e in fw_events:
        cur.execute("INSERT INTO fw_events VALUES (?,?,?,?,?,?,?,?)",
                    (e["ts"], e["src"], e["dst"], e["sport"], e["dport"],
                     e["proto"], e["action"], e["reason"]))

    cur.execute("CREATE INDEX idx_nf_ts ON netflow(ts)")
    cur.execute("CREATE INDEX idx_nf_dst ON netflow(dst)")
    cur.execute("CREATE INDEX idx_nf_proto ON netflow(proto)")
    cur.execute("CREATE INDEX idx_ss_ts ON server_stats(ts)")
    cur.execute("CREATE INDEX idx_fw_ts ON fw_events(ts)")
    cur.execute("CREATE INDEX idx_fw_action ON fw_events(action)")
    db.commit()
    db.close()

    with open("/app/httpd_access.log", "w") as f:
        for line in access_log:
            f.write(line + "\n")

    total = len(all_data)
    print(f"Generated {total} flows, {len(pcap_packets)} pcap packets")
    print(f"Server stats: {len(server_stats)}, FW events: {len(fw_events)}, Access log: {len(access_log)}")


if __name__ == "__main__":
    main()
