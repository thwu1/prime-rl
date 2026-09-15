#!/usr/bin/env python3
"""Benchmark coupled MCMC configurations against target distributions.

Populates /app/results.db with convergence metrics.
Requires the couplings library at /app/couplings/ to be fully implemented.

"""
import sys
import sqlite3
import numpy as np
import scipy.stats as st

sys.path.insert(0, "/app")

np.random.seed(42)

from couplings import metropolis_hastings

# === Target distributions ===
targets = {}

rv_1d = st.norm()
targets["standard_normal"] = {"log_prob": rv_1d.logpdf, "dim": 1}

dim3 = 3
cov3 = np.array([[1.0, 0.8, 0.5],
                  [0.8, 1.0, 0.6],
                  [0.5, 0.6, 1.0]])
rv_3d = st.multivariate_normal(np.zeros(dim3), cov3)
targets["correlated_3d"] = {"log_prob": rv_3d.logpdf, "dim": dim3}

dim8 = 8
cov8 = 0.3 * np.eye(dim8) + 0.7 * np.ones((dim8, dim8))
rv_8d = st.multivariate_normal(np.zeros(dim8), cov8)
targets["correlated_8d"] = {"log_prob": rv_8d.logpdf, "dim": dim8}

# === Sampler configurations (all isotropic) ===
configs = {
    "identity_small": lambda d: 0.1 * np.eye(d),
    "identity_unit": lambda d: 1.0 * np.eye(d),
    "identity_large": lambda d: 10.0 * np.eye(d),
    "scaled_optimal": lambda d: (2.38 ** 2 / d) * np.eye(d),
}

# === Database setup ===
db = sqlite3.connect("/app/results.db")
db.execute("DROP TABLE IF EXISTS results")
db.execute("""
    CREATE TABLE results (
        target TEXT NOT NULL,
        config TEXT NOT NULL,
        chain_id INTEGER NOT NULL,
        meeting_time INTEGER NOT NULL,
        x_accept_rate REAL NOT NULL,
        y_accept_rate REAL NOT NULL
    )
""")

CHAINS = 32
ITERS = 300

for tname, tspec in targets.items():
    dim = tspec["dim"]
    log_prob = tspec["log_prob"]
    init_x = 4 * np.ones(dim) if dim > 1 else 4.0
    init_y = -4 * np.ones(dim) if dim > 1 else -4.0

    for cname, cfn in configs.items():
        pcov = cfn(dim)
        print(f"Running {tname}/{cname}...", end=" ", flush=True)
        try:
            data = metropolis_hastings(
                log_prob=log_prob,
                proposal_cov=pcov,
                init_x=init_x,
                init_y=init_y,
                lag=1,
                iters=ITERS,
                chains=CHAINS,
            )
            for c in range(CHAINS):
                mt = int(data.meeting_time[c])
                if mt < 0:
                    mt = ITERS  # chain did not meet within budget
                xar = float(data.x_accept[1:, c].mean())
                yar = float(data.y_accept[1:, c].mean())
                db.execute(
                    "INSERT INTO results VALUES (?,?,?,?,?,?)",
                    (tname, cname, c, mt, xar, yar),
                )
            met_times = data.meeting_time.copy()
            met_times[met_times < 0] = ITERS
            print(f"mean_mt={met_times.mean():.1f}")
        except Exception as e:
            print(f"FAILED: {e}", file=sys.stderr)

db.commit()
db.close()
print("\nBenchmark complete. Results in /app/results.db")
