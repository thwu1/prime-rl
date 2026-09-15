"""
Reference solver for Noisy Polyomino Localization via REST API.

Starts the API server, solves all 5 cases using an adaptive probabilistic
strategy, logs everything to SQLite, generates report.json, then shuts down.

"""

import json
import math
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections import deque

API_BASE = "http://127.0.0.1:5000"


def api_post(path, data):
    req = urllib.request.Request(
        API_BASE + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_get(path):
    with urllib.request.urlopen(API_BASE + path) as resp:
        return json.loads(resp.read())


def wait_for_server(timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            api_get("/health")
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("Server did not start within %ds" % timeout)


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    with open("/app/schema.sql") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def solve_case(case_id, conn):
    # Create session
    sess = api_post("/session", {"case_id": case_id})
    sid = sess["session_id"]
    N = sess["N"]
    eps = sess["epsilon"]

    conn.execute(
        "INSERT INTO sessions (session_id, case_id, n, m, epsilon) "
        "VALUES (?, ?, ?, ?, ?)",
        (sid, case_id, N, sess["M"], eps),
    )
    conn.commit()

    SCAN_REPS = 4
    THRESH = 0.5

    def log_query(qtype, params, resp):
        conn.execute(
            "INSERT INTO queries "
            "(session_id, query_type, params_json, result_value, "
            "query_cost, cumulative_cost) VALUES (?, ?, ?, ?, ?, ?)",
            (
                sid, qtype, json.dumps(params),
                resp["value"], resp["cost"], resp["total_cost"],
            ),
        )

    # Phase 1: row & column divine scans
    row_est = []
    for i in range(N):
        cells = [[i, j] for j in range(N)]
        values = []
        for _ in range(SCAN_REPS):
            r = api_post("/divine", {"session_id": sid, "cells": cells})
            log_query("divine", {"cells": cells}, r)
            values.append(r["value"])
        avg = sum(values) / SCAN_REPS
        denom = 1.0 - 2.0 * eps
        est = (avg - N * eps) / denom if abs(denom) > 1e-9 else avg
        row_est.append(max(0.0, est))

    col_est = []
    for j in range(N):
        cells = [[i, j] for i in range(N)]
        values = []
        for _ in range(SCAN_REPS):
            r = api_post("/divine", {"session_id": sid, "cells": cells})
            log_query("divine", {"cells": cells}, r)
            values.append(r["value"])
        avg = sum(values) / SCAN_REPS
        denom = 1.0 - 2.0 * eps
        est = (avg - N * eps) / denom if abs(denom) > 1e-9 else avg
        col_est.append(max(0.0, est))

    conn.commit()

    # Phase 2: drill candidates at row-column intersections
    candidates = sorted(
        [(i, j) for i in range(N) for j in range(N)
         if row_est[i] > THRESH and col_est[j] > THRESH],
        key=lambda c: -(row_est[c[0]] + col_est[c[1]]),
    )

    active = set()
    known = set()
    for i, j in candidates:
        r = api_post("/drill", {"session_id": sid, "i": i, "j": j})
        log_query("drill", {"i": i, "j": j}, r)
        known.add((i, j))
        if r["value"] > 0:
            active.add((i, j))

    conn.commit()

    # Phase 3: BFS expansion from active cells
    queue = deque(list(active))
    while queue:
        ci, cj = queue.popleft()
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ni, nj = ci + di, cj + dj
            if 0 <= ni < N and 0 <= nj < N and (ni, nj) not in known:
                r = api_post("/drill", {"session_id": sid, "i": ni, "j": nj})
                log_query("drill", {"i": ni, "j": nj}, r)
                known.add((ni, nj))
                if r["value"] > 0:
                    active.add((ni, nj))
                    queue.append((ni, nj))

    conn.commit()

    # Submit answer
    cells_list = sorted([list(c) for c in active])
    sub = api_post("/submit", {"session_id": sid, "cells": cells_list})

    conn.execute(
        "INSERT INTO submissions "
        "(session_id, case_id, num_cells, total_cost, correct, "
        "precision_score, recall_score, cells_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sid, case_id, len(cells_list), sub["total_cost"],
            1 if sub["correct"] else 0,
            sub["precision"], sub["recall"],
            json.dumps(cells_list),
        ),
    )
    conn.commit()

    return sub


def generate_report(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
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
    conn.close()

    report = {"cases": cases, "total_cost": total_cost}
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)
    return report


def main():
    db_path = "/app/results.db"

    # Start server
    server = subprocess.Popen(
        [sys.executable, "/app/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        wait_for_server()
        conn = init_db(db_path)

        total = 0.0
        for cid in range(5):
            result = solve_case(cid, conn)
            total += result["total_cost"]
            print(
                "Case %d: cost=%.1f correct=%s"
                % (cid, result["total_cost"], result["correct"])
            )

        conn.close()
        print("Total cost: %.1f" % total)

        report = generate_report(db_path)
        print("Report: %s" % json.dumps(report, indent=2))

    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
