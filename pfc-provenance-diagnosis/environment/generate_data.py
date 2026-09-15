#!/usr/bin/env python3
"""Generate PFC telemetry data for a k=4 fat-tree RDMA network."""

import json
import os
import sqlite3


# ── topology (DOT) ──────────────────────────────────────────────────────────

def generate_topology_dot():
    lines = ["graph fabric {"]
    lines.append("    rankdir=TB;")
    lines.append("    node [fontsize=10];")
    lines.append("    edge [fontsize=8];")
    lines.append("")

    for i in range(4):
        lines.append(f'    c{i} [tier="core"];')
    lines.append("")

    for i in range(8):
        pod = i // 2
        lines.append(f'    a{i} [tier="aggregation", pod="{pod}"];')
    lines.append("")

    for i in range(8):
        pod = i // 2
        lines.append(f'    e{i} [tier="edge", pod="{pod}"];')
    lines.append("")

    for i in range(16):
        lines.append(f'    h{i} [tier="host"];')
    lines.append("")

    lines.append("    /* host -- edge links */")
    for pod in range(4):
        for ei in range(2):
            esw = f"e{pod * 2 + ei}"
            for hi in range(2):
                host = f"h{pod * 4 + ei * 2 + hi}"
                lines.append(
                    f'    {host} -- {esw} [src_port="{0}", dst_port="{hi}"];'
                )
    lines.append("")

    lines.append("    /* edge -- aggregation links */")
    for pod in range(4):
        for ei in range(2):
            esw = f"e{pod * 2 + ei}"
            for ai in range(2):
                asw = f"a{pod * 2 + ai}"
                lines.append(
                    f'    {esw} -- {asw} [src_port="{2 + ai}", dst_port="{ei}"];'
                )
    lines.append("")

    lines.append("    /* aggregation -- core links */")
    for pod in range(4):
        for ai in range(2):
            asw = f"a{pod * 2 + ai}"
            for ci in range(2):
                csw = f"c{ai * 2 + ci}"
                lines.append(
                    f'    {asw} -- {csw} [src_port="{2 + ci}", dst_port="{pod}"];'
                )

    lines.append("}")
    return "\n".join(lines)


# ── SQLite database ─────────────────────────────────────────────────────────

def generate_sqlite_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE switch_meta (
        switch_id TEXT PRIMARY KEY,
        tier TEXT NOT NULL,
        pod_id INTEGER
    )""")

    c.execute("""CREATE TABLE pfc_config (
        priority INTEGER PRIMARY KEY,
        xon_threshold_bytes INTEGER NOT NULL,
        xoff_threshold_bytes INTEGER NOT NULL,
        buffer_size_bytes INTEGER NOT NULL,
        causal_window_us INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE pfc_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_us INTEGER NOT NULL,
        switch_id TEXT NOT NULL,
        port_id INTEGER NOT NULL,
        queue_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        pause_duration_us INTEGER NOT NULL,
        queue_depth_bytes INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE port_counters (
        epoch_us INTEGER NOT NULL,
        switch_id TEXT NOT NULL,
        port_id INTEGER NOT NULL,
        tx_bytes INTEGER NOT NULL,
        rx_bytes INTEGER NOT NULL,
        tx_pfc_frames INTEGER NOT NULL,
        rx_pfc_frames INTEGER NOT NULL,
        PRIMARY KEY (epoch_us, switch_id, port_id)
    )""")

    c.execute("CREATE INDEX idx_pfc_switch ON pfc_events(switch_id, port_id, queue_id)")
    c.execute("CREATE INDEX idx_pfc_type   ON pfc_events(event_type)")
    c.execute("CREATE INDEX idx_pc_switch  ON port_counters(switch_id, port_id)")

    for i in range(4):
        c.execute("INSERT INTO switch_meta VALUES (?, 'core', NULL)", (f"c{i}",))
    for i in range(8):
        c.execute("INSERT INTO switch_meta VALUES (?, 'aggregation', ?)",
                  (f"a{i}", i // 2))
    for i in range(8):
        c.execute("INSERT INTO switch_meta VALUES (?, 'edge', ?)",
                  (f"e{i}", i // 2))

    c.execute("INSERT INTO pfc_config VALUES (3, 32768, 65536, 131072, 10)")

    all_switches = (
        [f"c{i}" for i in range(4)]
        + [f"a{i}" for i in range(8)]
        + [f"e{i}" for i in range(8)]
    )

    def ins_pfc(ts, sw, port, q, etype, dur, qdepth):
        c.execute(
            "INSERT INTO pfc_events "
            "(timestamp_us,switch_id,port_id,queue_id,event_type,"
            "pause_duration_us,queue_depth_bytes) "
            "VALUES (?,?,?,?,?,?,?)",
            (ts, sw, port, q, etype, dur, qdepth),
        )

    for i in range(30):
        t = i * 200
        sw = all_switches[i % len(all_switches)]
        ins_pfc(t, sw, (i * 3) % 4, 0, "NORMAL", 0,
                10000 + (i * 7) % 20000)

    for t, sw, port, q, dur in [
        (200, "e0", 1, 3, 3),   (450, "e4", 0, 2, 2),
        (700, "a1", 3, 3, 4),   (850, "e7", 1, 3, 2),
        (3200, "a4", 0, 1, 3),  (3800, "e3", 0, 2, 1),
        (4500, "a7", 2, 3, 5),  (5200, "c1", 0, 3, 2),
        (5800, "e5", 0, 1, 4),
    ]:
        ins_pfc(t, sw, port, q, "PFC_PAUSE_SENT", dur,
                62000 + t % 3000)

    grp1_s = [("e6", 2, 3), ("a6", 2, 3), ("c0", 0, 3),
              ("a0", 1, 3), ("e1", 1, 3)]
    grp1_r = [("a6", 0, 3), ("c0", 3, 3), ("a0", 2, 3), ("e1", 2, 3)]

    for n, base_t in enumerate(range(1000, 5000, 50)):
        for j, (sw, port, q) in enumerate(grp1_s):
            t = base_t + j * 5
            qdepth = 65536 + ((n * 7 + j * 3) % 4000)
            dur = 50 - j * 5
            ins_pfc(t, sw, port, q, "PFC_PAUSE_SENT", dur, qdepth)
        for j, (sw, port, q) in enumerate(grp1_r):
            t = base_t + j * 5 + 1
            qdepth = 30000 + ((n * 11 + j * 5) % 4000)
            dur = 50 - j * 5
            ins_pfc(t, sw, port, q, "PFC_PAUSE_RECEIVED", dur, qdepth)

    grp2_s = [("a3", 3, 3), ("c3", 2, 3), ("a5", 2, 3), ("c2", 1, 3)]
    grp2_r = [("c3", 1, 3), ("a5", 3, 3), ("c2", 2, 3), ("a3", 2, 3)]

    for n, base_t in enumerate(range(2000, 5000, 20)):
        for j, (sw, port, q) in enumerate(grp2_s):
            t = base_t + j * 5
            qdepth = 65536 + ((n * 13 + j * 7) % 4000)
            ins_pfc(t, sw, port, q, "PFC_PAUSE_SENT", 100, qdepth)
        for j, (sw, port, q) in enumerate(grp2_r):
            t = base_t + j * 5 + 2
            qdepth = 30000 + ((n * 17 + j * 11) % 4000)
            ins_pfc(t, sw, port, q, "PFC_PAUSE_RECEIVED", 100, qdepth)

    grp3_s = [("e4", 2, 3), ("a4", 3, 3)]
    grp3_r = [("a4", 0, 3), ("c1", 2, 3)]

    for n, base_t in enumerate(range(1500, 3500, 50)):
        t0 = base_t
        t1 = base_t + 4
        qd0 = 22000 + (n * 13) % 4000
        qd1 = 21000 + (n * 17) % 4000
        ins_pfc(t0, grp3_s[0][0], grp3_s[0][1], grp3_s[0][2],
                "PFC_PAUSE_SENT", 3, qd0)
        ins_pfc(t1, grp3_s[1][0], grp3_s[1][1], grp3_s[1][2],
                "PFC_PAUSE_SENT", 2, qd1)
        ins_pfc(t0 + 1, grp3_r[0][0], grp3_r[0][1], grp3_r[0][2],
                "PFC_PAUSE_RECEIVED", 3, qd0)
        ins_pfc(t1 + 1, grp3_r[1][0], grp3_r[1][1], grp3_r[1][2],
                "PFC_PAUSE_RECEIVED", 2, qd1)

    for epoch in range(0, 6000, 1000):
        for sw in all_switches:
            for port in range(4):
                tx = epoch * 1000 + port * 100
                rx = epoch * 1200 + port * 120
                c.execute(
                    "INSERT INTO port_counters VALUES (?,?,?,?,?,0,0)",
                    (epoch, sw, port, tx, rx),
                )

    conn.commit()
    conn.close()


# ── victim flows ────────────────────────────────────────────────────────────

def generate_victim_flows():
    return [
        {"flow_id": 0, "src": "h0", "dst": "h8", "priority": 3,
         "path": ["h0", "e0", "a0", "c0", "a4", "e4", "h8"],
         "expected_rtt_us": 20, "observed_rtt_us": 850},
        {"flow_id": 1, "src": "h1", "dst": "h9", "priority": 3,
         "path": ["h1", "e0", "a0", "c0", "a4", "e4", "h9"],
         "expected_rtt_us": 20, "observed_rtt_us": 920},
        {"flow_id": 2, "src": "h2", "dst": "h13", "priority": 3,
         "path": ["h2", "e1", "a0", "c0", "a6", "e6", "h13"],
         "expected_rtt_us": 20, "observed_rtt_us": 780},
        {"flow_id": 3, "src": "h5", "dst": "h11", "priority": 3,
         "path": ["h5", "e2", "a3", "c2", "a5", "e5", "h11"],
         "expected_rtt_us": 20, "observed_rtt_us": 1200},
        {"flow_id": 4, "src": "h6", "dst": "h4", "priority": 3,
         "path": ["h6", "e3", "a3", "e2", "h4"],
         "expected_rtt_us": 15, "observed_rtt_us": 1100},
    ]


# ── main ────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("/app", exist_ok=True)

    with open("/app/topology.dot", "w") as f:
        f.write(generate_topology_dot())

    db_path = "/app/fabric.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    generate_sqlite_db(db_path)

    with open("/app/victim_flows.json", "w") as f:
        json.dump(generate_victim_flows(), f, indent=2)


if __name__ == "__main__":
    main()
