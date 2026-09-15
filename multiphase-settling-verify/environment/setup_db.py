#!/usr/bin/env python3
"""Create history.db with normalized schema across 5 tables."""

import sqlite3
import math

# Physical parameters (must match config.toml)
G = 9.81
RHO_G = 1000.0
RHO_S = 2500.0
MU = 0.001
D_P = 1e-4
N_RZ = 4.65
EPS_MAX = 0.63
Y0 = 0.8
T_EVAL = 50.0
CONC = [0.05, 0.10, 0.20]
RE_VALS = [0.1, 1.0, 10.0, 100.0, 1500.0]

ALPHA = 1.0
A_MMS = 300.0
B_MMS = 50.0
K_MMS = 2
L_MMS = 1.0
GRIDS = [8, 16, 32, 64, 128]


def drag_cd(Re, exponent=0.687):
    if Re > 1000.0:
        return 0.44
    return (24.0 / Re) * (1.0 + 0.15 * Re ** exponent)


def compute_drag(exponent=0.687):
    return {Re: drag_cd(Re, exponent) for Re in RE_VALS}


def compute_settling(use_correct_exponent=True):
    u_t = G * (RHO_S - RHO_G) * D_P ** 2 / (18.0 * MU)
    Re_t = RHO_G * u_t * D_P / MU
    exp = N_RZ + 1 if use_correct_exponent else N_RZ
    fronts = []
    for eps_s0 in CONC:
        eps_g0 = 1.0 - eps_s0
        u_r = u_t * eps_g0 ** N_RZ
        sigma_s = -u_t * eps_g0 ** exp
        sigma_f = u_t * eps_s0 * eps_g0 ** exp / (EPS_MAX - eps_s0)
        fronts.append({
            "eps_s0": eps_s0,
            "settling_front": Y0 + sigma_s * T_EVAL,
            "filling_front": sigma_f * T_EVAL,
            "hindered_velocity": u_r,
        })
    return {"terminal_velocity": u_t, "reynolds_number": Re_t, "fronts": fronts}


def compute_mms(correct_sign=True):
    kpi_L = K_MMS * math.pi / L_MMS
    sign = 1.0 if correct_sign else -1.0
    l2_norms = {}
    for N in GRIDS:
        h = L_MMS / N
        n_int = N - 1
        x = [(i + 1) * h for i in range(n_int)]
        u_exact = [A_MMS + B_MMS * math.sin(kpi_L * xi) for xi in x]
        source = [sign * ALPHA * B_MMS * kpi_L ** 2 * math.sin(kpi_L * xi)
                  for xi in x]
        u_left = A_MMS + B_MMS * math.sin(0.0)
        u_right = A_MMS + B_MMS * math.sin(kpi_L * L_MMS)
        coeff = ALPHA / h ** 2
        b = [2.0 * coeff] * n_int
        c = [-coeff] * n_int
        a = [-coeff] * n_int
        d = list(source)
        d[0] += coeff * u_left
        d[-1] += coeff * u_right
        for i in range(1, n_int):
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            d[i] -= w * d[i - 1]
        u_num = [0.0] * n_int
        u_num[-1] = d[-1] / b[-1]
        for i in range(n_int - 2, -1, -1):
            u_num[i] = (d[i] - c[i] * u_num[i + 1]) / b[i]
        err_sq = sum((u_num[j] - u_exact[j]) ** 2 for j in range(n_int))
        l2_norms[N] = math.sqrt(err_sq / n_int)
    return l2_norms


def main():
    conn = sqlite3.connect("/app/history.db")
    c = conn.cursor()

    # Create normalized schema
    c.execute("""CREATE TABLE runs (
        run_id INTEGER PRIMARY KEY,
        code_version TEXT NOT NULL,
        run_date TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE drag_data (
        run_id INTEGER NOT NULL REFERENCES runs(run_id),
        reynolds REAL NOT NULL,
        cd_value REAL NOT NULL,
        PRIMARY KEY (run_id, reynolds)
    )""")

    c.execute("""CREATE TABLE settling_params (
        run_id INTEGER PRIMARY KEY REFERENCES runs(run_id),
        terminal_velocity REAL NOT NULL,
        reynolds_number REAL NOT NULL
    )""")

    c.execute("""CREATE TABLE settling_fronts (
        run_id INTEGER NOT NULL REFERENCES runs(run_id),
        eps_s0 REAL NOT NULL,
        settling_front REAL NOT NULL,
        filling_front REAL NOT NULL,
        hindered_velocity REAL NOT NULL,
        PRIMARY KEY (run_id, eps_s0)
    )""")

    c.execute("""CREATE TABLE mms_data (
        run_id INTEGER NOT NULL REFERENCES runs(run_id),
        grid_level INTEGER NOT NULL,
        l2_norm REAL NOT NULL,
        PRIMARY KEY (run_id, grid_level)
    )""")

    c.execute("CREATE INDEX idx_drag_runid ON drag_data(run_id)")
    c.execute("CREATE INDEX idx_sfronts_runid ON settling_fronts(run_id)")
    c.execute("CREATE INDEX idx_mms_runid ON mms_data(run_id)")

    c.execute("""CREATE VIEW run_summary AS
        SELECT r.run_id, r.code_version, r.run_date,
               COUNT(DISTINCT d.reynolds) as n_drag_points,
               COUNT(DISTINCT f.eps_s0) as n_settling_conc,
               COUNT(DISTINCT m.grid_level) as n_mms_levels
        FROM runs r
        LEFT JOIN drag_data d ON r.run_id = d.run_id
        LEFT JOIN settling_fronts f ON r.run_id = f.run_id
        LEFT JOIN mms_data m ON r.run_id = m.run_id
        GROUP BY r.run_id
    """)

    # Precompute variants
    drag_ok = compute_drag(0.687)
    drag_bad = compute_drag(0.678)
    settle_ok = compute_settling(True)
    settle_bad = compute_settling(False)
    mms_ok = compute_mms(True)
    mms_bad = compute_mms(False)

    # 12 runs with interleaved defects:
    #   correct: 1, 4, 7
    #   drag bug: 2, 6, 10
    #   settling bug: 3, 8, 11
    #   mms bug: 5, 9, 12
    run_configs = [
        (1,  "v2.1.0", "2024-01-15", drag_ok,  settle_ok,  mms_ok),
        (2,  "v1.8.3", "2023-11-02", drag_bad, settle_ok,  mms_ok),
        (3,  "v1.9.1", "2023-12-10", drag_ok,  settle_bad, mms_ok),
        (4,  "v2.1.1", "2024-01-22", drag_ok,  settle_ok,  mms_ok),
        (5,  "v1.7.0", "2023-09-05", drag_ok,  settle_ok,  mms_bad),
        (6,  "v1.8.5", "2023-11-18", drag_bad, settle_ok,  mms_ok),
        (7,  "v2.0.0", "2024-01-03", drag_ok,  settle_ok,  mms_ok),
        (8,  "v1.9.0", "2023-12-01", drag_ok,  settle_bad, mms_ok),
        (9,  "v1.6.2", "2023-08-14", drag_ok,  settle_ok,  mms_bad),
        (10, "v1.8.1", "2023-10-20", drag_bad, settle_ok,  mms_ok),
        (11, "v1.9.2", "2023-12-15", drag_ok,  settle_bad, mms_ok),
        (12, "v1.5.0", "2023-07-01", drag_ok,  settle_ok,  mms_bad),
    ]

    for run_id, ver, date, drag, settle, mms_l2 in run_configs:
        c.execute("INSERT INTO runs VALUES (?, ?, ?)", (run_id, ver, date))

        for Re, cd in drag.items():
            c.execute("INSERT INTO drag_data VALUES (?, ?, ?)",
                      (run_id, Re, cd))

        c.execute("INSERT INTO settling_params VALUES (?, ?, ?)",
                  (run_id, settle["terminal_velocity"], settle["reynolds_number"]))

        for fr in settle["fronts"]:
            c.execute("INSERT INTO settling_fronts VALUES (?, ?, ?, ?, ?)",
                      (run_id, fr["eps_s0"], fr["settling_front"],
                       fr["filling_front"], fr["hindered_velocity"]))

        for grid_level, l2 in mms_l2.items():
            c.execute("INSERT INTO mms_data VALUES (?, ?, ?)",
                      (run_id, grid_level, l2))

    conn.commit()
    conn.close()
    print("Created /app/history.db with 12 runs across 5 normalized tables")


if __name__ == "__main__":
    main()
