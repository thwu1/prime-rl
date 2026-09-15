#!/usr/bin/env python3
"""
Reference solver for Polyomino Field Inference Pipeline.

Starts PostgreSQL and the oracle server, solves all 5 cases using an
adaptive probabilistic strategy, logs to PostgreSQL, generates gnuplot
heatmaps, and produces report.json.

"""

import json
import math
import os
import re
import socket
import subprocess
import sys
import time
from collections import deque

NUM_CASES = 5

# ============================================================
# TCP Client for poly_server
# ============================================================

class OracleClient:
    def __init__(self, host="127.0.0.1", port=9999):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.buf = b""

    def send_cmd(self, cmd):
        self.sock.sendall((cmd + "\n").encode())
        while b"\n" not in self.buf:
            data = self.sock.recv(8192)
            if not data:
                raise ConnectionError("Server closed connection")
            self.buf += data
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode().strip()

    def close(self):
        try:
            self.send_cmd("QUIT")
        except Exception:
            pass
        self.sock.close()


def parse_kv(resp):
    """Parse KEY=VALUE pairs from a response line."""
    d = {}
    for token in resp.split():
        if "=" in token:
            k, v = token.split("=", 1)
            d[k] = v
    return d


def connect_oracle(host="127.0.0.1", port=9999, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client = OracleClient(host, port)
            r = client.send_cmd("PING")
            if "PONG" in r:
                return client
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    raise RuntimeError("Oracle server did not start")


# ============================================================
# PostgreSQL helpers
# ============================================================

def setup_postgres():
    """Start PostgreSQL, create database, apply schema."""
    subprocess.run(
        ["pg_ctlcluster", "16", "main", "start"],
        capture_output=True, check=False,
    )
    time.sleep(2)

    subprocess.run(
        ["createdb", "-U", "postgres", "polyfield"],
        capture_output=True, check=False,
    )
    subprocess.run(
        ["psql", "-U", "postgres", "-d", "polyfield",
         "-f", "/app/schema.sql"],
        capture_output=True, check=False,
    )


def get_pg_conn():
    import psycopg2
    return psycopg2.connect(dbname="polyfield", user="postgres")


# ============================================================
# Solver
# ============================================================

def solve_case(client, pg_conn, case_id):
    """Solve one case using adaptive row/column scanning + targeted drilling."""

    # --- INIT ---
    resp = client.send_cmd(f"INIT {case_id}")
    parts = resp.split()
    sid = parts[1]
    kv = parse_kv(resp)
    N = int(kv["N"])
    M = int(kv["M"])
    eps = float(kv["EPS"])
    max_ops = int(kv["MAXOPS"])

    cur = pg_conn.cursor()
    cur.execute(
        "INSERT INTO sessions (session_id, case_id, n, m, epsilon) "
        "VALUES (%s, %s, %s, %s, %s)",
        (sid, case_id, N, M, eps),
    )
    pg_conn.commit()

    # Query density tracker (for heatmap)
    density = [[0] * N for _ in range(N)]

    def log_query(qtype, params, value, cost, total):
        cur.execute(
            "INSERT INTO queries "
            "(session_id, query_type, params_json, result_value, "
            "query_cost, cumulative_cost) VALUES (%s,%s,%s,%s,%s,%s)",
            (sid, qtype, json.dumps(params), value, cost, total),
        )

    def do_drill(i, j):
        r = client.send_cmd(f"DRILL {sid} {i} {j}")
        kv = parse_kv(r)
        val = int(kv["VALUE"])
        cost = float(kv["COST"])
        total = float(kv["TOTAL"])
        log_query("drill", {"i": i, "j": j}, val, cost, total)
        density[i][j] += 1
        return val, total

    def do_divine(cells):
        cell_str = ";".join(f"{r},{c}" for r, c in cells)
        r = client.send_cmd(f"DIVINE {sid} {cell_str}")
        kv = parse_kv(r)
        val = int(kv["VALUE"])
        cost = float(kv["COST"])
        total = float(kv["TOTAL"])
        log_query("divine", {"cells": cells}, val, cost, total)
        for cr, cc in cells:
            density[cr][cc] += 1
        return val, total

    # --- Phase 1: Row divine scans ---
    SCAN_REPS = 4
    THRESH = 0.5

    row_est = []
    total_cost = 0.0
    for i in range(N):
        cells = [(i, j) for j in range(N)]
        values = []
        for _ in range(SCAN_REPS):
            val, total_cost = do_divine(cells)
            values.append(val)
        avg = sum(values) / SCAN_REPS
        denom = 1.0 - 2.0 * eps
        est = (avg - N * eps) / denom if abs(denom) > 1e-9 else avg
        row_est.append(max(0.0, est))

    pg_conn.commit()

    # --- Phase 2: Column divine scans ---
    col_est = []
    for j in range(N):
        cells = [(i, j) for i in range(N)]
        values = []
        for _ in range(SCAN_REPS):
            val, total_cost = do_divine(cells)
            values.append(val)
        avg = sum(values) / SCAN_REPS
        denom = 1.0 - 2.0 * eps
        est = (avg - N * eps) / denom if abs(denom) > 1e-9 else avg
        col_est.append(max(0.0, est))

    pg_conn.commit()

    # --- Phase 3: Drill candidates at row-column intersections ---
    candidates = sorted(
        [(i, j) for i in range(N) for j in range(N)
         if row_est[i] > THRESH and col_est[j] > THRESH],
        key=lambda c: -(row_est[c[0]] + col_est[c[1]]),
    )

    active = set()
    known = set()
    for i, j in candidates:
        val, total_cost = do_drill(i, j)
        known.add((i, j))
        if val > 0:
            active.add((i, j))

    pg_conn.commit()

    # --- Phase 4: BFS expansion from active cells ---
    queue = deque(list(active))
    while queue:
        ci, cj = queue.popleft()
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ni, nj = ci + di, cj + dj
            if 0 <= ni < N and 0 <= nj < N and (ni, nj) not in known:
                val, total_cost = do_drill(ni, nj)
                known.add((ni, nj))
                if val > 0:
                    active.add((ni, nj))
                    queue.append((ni, nj))

    pg_conn.commit()

    # --- SUBMIT ---
    cells_sorted = sorted(active)
    cell_str = ";".join(f"{r},{c}" for r, c in cells_sorted)
    resp = client.send_cmd(f"SUBMIT {sid} {cell_str}")
    kv = parse_kv(resp)
    correct = int(kv["CORRECT"])
    prec = float(kv["PREC"])
    recall = float(kv["RECALL"])
    total_cost = float(kv["TOTAL"])

    cells_list = [[r, c] for r, c in cells_sorted]
    cur.execute(
        "INSERT INTO submissions "
        "(session_id, case_id, num_cells, total_cost, correct, "
        "precision_score, recall_score, cells_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (sid, case_id, len(cells_list), total_cost,
         1 if correct else 0, prec, recall, json.dumps(cells_list)),
    )
    pg_conn.commit()

    print(f"Case {case_id}: cost={total_cost:.1f} correct={correct} "
          f"active={len(cells_list)}")

    return {
        "sid": sid,
        "total_cost": total_cost,
        "correct": correct,
        "num_active": len(cells_list),
        "density": density,
    }


# ============================================================
# Gnuplot heatmap generation
# ============================================================

def generate_heatmaps(case_results):
    """Generate gnuplot SVG heatmaps for each case."""
    os.makedirs("/app/vis", exist_ok=True)

    for case_id, result in enumerate(case_results):
        density = result["density"]
        N = len(density)

        # Write data file
        data_path = f"/app/vis/data_{case_id}.dat"
        with open(data_path, "w") as f:
            for row in density:
                f.write(" ".join(str(v) for v in row) + "\n")

        # Write gnuplot script
        plt_path = f"/app/vis/heatmap_{case_id}.plt"
        svg_path = f"/app/vis/heatmap_{case_id}.svg"
        with open(plt_path, "w") as f:
            f.write(f'set terminal svg size 600,600 enhanced\n')
            f.write(f'set output "{svg_path}"\n')
            f.write(f'set title "Query Density Heatmap - Case {case_id}"\n')
            f.write(f'set xlabel "Column"\n')
            f.write(f'set ylabel "Row"\n')
            f.write(f'set yrange [{N - 0.5}:-0.5]\n')
            f.write(f'set xrange [-0.5:{N - 0.5}]\n')
            f.write(f'set palette defined (0 "white", 1 "light-blue", ')
            f.write(f'3 "blue", 6 "red", 10 "dark-red")\n')
            f.write(f'set cbrange [0:*]\n')
            f.write(f'set view map\n')
            f.write(f'set size square\n')
            f.write(f'splot "{data_path}" matrix with image notitle\n')

        # Run gnuplot
        subprocess.run(["gnuplot", plt_path], capture_output=True, check=True)
        print(f"Generated heatmap: {svg_path}")


# ============================================================
# Report generation
# ============================================================

def generate_report(pg_conn):
    """Generate /app/report.json from PostgreSQL data."""
    cur = pg_conn.cursor()
    cur.execute("""
        SELECT s.case_id, s.session_id, sub.total_cost, sub.num_cells,
               sub.correct,
               (SELECT COUNT(*) FROM queries q
                WHERE q.session_id = s.session_id) AS num_queries
        FROM submissions sub
        JOIN sessions s ON sub.session_id = s.session_id
        ORDER BY s.case_id
    """)
    cases = []
    for row in cur.fetchall():
        cases.append({
            "case_id": row[0],
            "session_id": row[1],
            "total_cost": row[2],
            "num_active_cells": row[3],
            "correct": bool(row[4]),
            "num_queries": row[5],
        })

    cur.execute("SELECT SUM(total_cost) FROM submissions")
    total_cost = cur.fetchone()[0]

    report = {"cases": cases, "total_cost": total_cost}
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written: total_cost={total_cost:.1f}")
    return report


# ============================================================
# Main
# ============================================================

def main():
    # 1. Start PostgreSQL and create database
    print("Setting up PostgreSQL...")
    setup_postgres()

    # 2. Start oracle server
    print("Starting oracle server...")
    server_proc = subprocess.Popen(
        ["/app/poly_server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # 3. Connect to oracle
        client = connect_oracle()
        print("Connected to oracle server.")

        # 4. Connect to PostgreSQL
        pg_conn = get_pg_conn()

        # 5. Solve all cases
        case_results = []
        for cid in range(NUM_CASES):
            result = solve_case(client, pg_conn, cid)
            case_results.append(result)

        # 6. Generate heatmaps
        generate_heatmaps(case_results)

        # 7. Generate report
        generate_report(pg_conn)

        # Cleanup
        pg_conn.close()
        client.close()

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()

    print("Done.")


if __name__ == "__main__":
    main()
