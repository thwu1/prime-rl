"""Probabilistic ODE solver with HDF5 pipeline and gnuplot convergence visualization.

"""

import json
import os
import sqlite3
import subprocess
import tempfile
from math import factorial

import h5py
import numpy as np
from scipy.integrate import solve_ivp


# ---------------------------------------------------------------------------
# IWP state-space model
# ---------------------------------------------------------------------------


def build_iwp_transition(q, h):
    """IWP(q) transition matrix A(h): A[i,j] = h^(j-i) / (j-i)! for j>=i."""
    d = q + 1
    A = np.zeros((d, d))
    for i in range(d):
        for j in range(i, d):
            A[i, j] = h ** (j - i) / factorial(j - i)
    return A


def build_iwp_process_noise(q, h):
    """IWP(q) process noise covariance Q(h)."""
    d = q + 1
    Q = np.zeros((d, d))
    for i in range(d):
        for j in range(d):
            power = 2 * q + 1 - i - j
            Q[i, j] = h ** power / (factorial(q - i) * factorial(q - j) * power)
    return Q


# ---------------------------------------------------------------------------
# Lotka-Volterra specifics
# ---------------------------------------------------------------------------


def lotka_volterra_vf(y, params):
    a, b, g, d = params["alpha"], params["beta"], params["gamma"], params["delta"]
    return np.array([a * y[0] - b * y[0] * y[1], -g * y[1] + d * y[0] * y[1]])


def compute_taylor_coefficients(y0, params, q):
    """Taylor coefficients [y(0), y'(0), ..., y^(q)(0)] for Lotka-Volterra."""
    a = params["alpha"]
    b = params["beta"]
    g = params["gamma"]
    d = params["delta"]
    y0 = np.asarray(y0, dtype=float)
    coeffs = [y0.copy()]

    f0 = lotka_volterra_vf(y0, params)
    coeffs.append(f0.copy())

    if q >= 2:
        J = np.array([
            [a - b * y0[1], -b * y0[0]],
            [d * y0[1], -g + d * y0[0]],
        ])
        y2 = J @ f0
        coeffs.append(y2.copy())

    if q >= 3:
        H_f1 = np.array([[0.0, -b], [-b, 0.0]])
        H_f2 = np.array([[0.0, d], [d, 0.0]])
        y3 = J @ y2 + np.array([f0 @ H_f1 @ f0, f0 @ H_f2 @ f0])
        coeffs.append(y3.copy())

    return coeffs


# ---------------------------------------------------------------------------
# EK0 solver
# ---------------------------------------------------------------------------


def solve_ek0(problem, step_size=None):
    """Solve the ODE with EK0 probabilistic filtering and MLE calibration."""
    params = problem["parameters"]
    y0 = np.array(problem["initial_conditions"], dtype=float)
    t0, t1 = problem["time_span"]
    h = step_size if step_size is not None else problem["solver"]["step_size"]
    q = problem["solver"]["prior_order"]

    d_ode = len(y0)
    d_state = q + 1

    A = build_iwp_transition(q, h)
    Q = build_iwp_process_noise(q, h)
    tcoeffs = compute_taylor_coefficients(y0, params, q)

    # Initialize per-dimension state
    m_blocks = []
    for dim in range(d_ode):
        m_dim = np.zeros(d_state)
        for k in range(min(len(tcoeffs), d_state)):
            m_dim[k] = tcoeffs[k][dim]
        m_blocks.append(m_dim)

    P_blocks = [np.zeros((d_state, d_state)) for _ in range(d_ode)]

    N_steps = int(round((t1 - t0) / h))
    times = np.linspace(t0, t1, N_steps + 1)
    T = len(times)

    means = np.zeros((T, d_ode))
    stds_raw = np.zeros((T, d_ode))

    for dim in range(d_ode):
        means[0, dim] = m_blocks[dim][0]
        stds_raw[0, dim] = np.sqrt(max(P_blocks[dim][0, 0], 0.0))

    sum_z2_over_s = 0.0
    n_innovations = 0

    for n in range(1, T):
        m_pred = [A @ m_blocks[dim] for dim in range(d_ode)]
        P_pred = [A @ P_blocks[dim] @ A.T + Q for dim in range(d_ode)]

        y_pred = np.array([m_pred[dim][0] for dim in range(d_ode)])
        f_pred = lotka_volterra_vf(y_pred, params)
        z = np.array([m_pred[dim][1] - f_pred[dim] for dim in range(d_ode)])

        for dim in range(d_ode):
            s = P_pred[dim][1, 1]
            k_gain = P_pred[dim][:, 1] / s
            m_blocks[dim] = m_pred[dim] - k_gain * z[dim]
            P_blocks[dim] = P_pred[dim] - np.outer(k_gain, P_pred[dim][1, :])
            P_blocks[dim] = 0.5 * (P_blocks[dim] + P_blocks[dim].T)
            sum_z2_over_s += z[dim] ** 2 / s
            n_innovations += 1

        for dim in range(d_ode):
            means[n, dim] = m_blocks[dim][0]
            stds_raw[n, dim] = np.sqrt(max(P_blocks[dim][0, 0], 0.0))

    sigma_sq_mle = sum_z2_over_s / n_innovations
    sigma_mle = np.sqrt(sigma_sq_mle)
    stds_calibrated = stds_raw * sigma_mle

    return times, means, stds_calibrated, sigma_mle, N_steps


# ---------------------------------------------------------------------------
# Reference solution (high-precision)
# ---------------------------------------------------------------------------


def compute_reference_terminal(problem):
    params = problem["parameters"]
    y0 = problem["initial_conditions"]
    t0, t1 = problem["time_span"]

    def rhs(t, y):
        return lotka_volterra_vf(y, params)

    sol = solve_ivp(rhs, [t0, t1], y0, method="DOP853", rtol=1e-12, atol=1e-14)
    return sol.y[:, -1]


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------


def create_database(db_path, times, means, stds, sigma_mle, q, convergence_data):
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute(
        "CREATE TABLE trajectory "
        "(step_idx INTEGER, time REAL, dim INTEGER, mean REAL, std REAL)"
    )
    c.execute(
        "CREATE TABLE convergence "
        "(step_size REAL, terminal_rmse REAL, num_steps INTEGER)"
    )
    c.execute(
        "CREATE TABLE metadata "
        "(key TEXT PRIMARY KEY, value TEXT)"
    )

    # Populate trajectory
    T, d = means.shape
    rows = []
    for i in range(T):
        for dim in range(d):
            rows.append(
                (i, float(times[i]), dim, float(means[i, dim]), float(stds[i, dim]))
            )
    c.executemany("INSERT INTO trajectory VALUES (?, ?, ?, ?, ?)", rows)

    # Populate convergence
    for h, rmse, nsteps in convergence_data:
        c.execute("INSERT INTO convergence VALUES (?, ?, ?)", (h, rmse, nsteps))

    # Populate metadata
    c.execute("INSERT INTO metadata VALUES (?, ?)", ("output_scale", str(sigma_mle)))
    c.execute("INSERT INTO metadata VALUES (?, ?)", ("solver_type", "ek0"))
    c.execute("INSERT INTO metadata VALUES (?, ?)", ("prior_order", str(q)))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# HDF5 persistence
# ---------------------------------------------------------------------------


def create_hdf5(h5_path, times, means, stds, sigma_mle, q, num_steps):
    if os.path.exists(h5_path):
        os.remove(h5_path)

    with h5py.File(h5_path, "w") as f:
        # Root attribute
        f.attrs["schema_version"] = "1.0"

        # /trajectory group with compressed, chunked datasets
        traj = f.create_group("trajectory")
        traj.create_dataset(
            "times", data=times, dtype="float64",
            compression="gzip", compression_opts=5,
            chunks=(min(256, len(times)),),
        )
        T, d = means.shape
        traj.create_dataset(
            "mean", data=means, dtype="float64",
            compression="gzip", compression_opts=5,
            chunks=(min(256, T), d),
        )
        traj.create_dataset(
            "std", data=stds, dtype="float64",
            compression="gzip", compression_opts=5,
            chunks=(min(256, T), d),
        )

        # /metadata group with typed attributes
        meta = f.create_group("metadata")
        meta.attrs["output_scale"] = float(sigma_mle)
        meta.attrs["solver_type"] = "ek0"
        meta.attrs["prior_order"] = int(q)
        meta.attrs["num_steps"] = int(num_steps)


# ---------------------------------------------------------------------------
# Gnuplot convergence plot
# ---------------------------------------------------------------------------


def generate_convergence_svg(svg_path, convergence_data, prior_order):
    """Generate a log-log convergence plot using gnuplot."""
    # Prepare inline data for gnuplot
    data_lines = []
    for h, rmse, _ in sorted(convergence_data, key=lambda x: x[0]):
        data_lines.append(f"{h} {rmse}")

    # Reference slope: RMSE ~ h^(prior_order)
    # Use the largest step size point as anchor
    h_max = max(row[0] for row in convergence_data)
    rmse_max = max(row[1] for row in convergence_data if abs(row[0] - h_max) < 1e-10)
    h_min = min(row[0] for row in convergence_data)
    ref_rmse_min = rmse_max * (h_min / h_max) ** prior_order

    ref_lines = [
        f"{h_max} {rmse_max}",
        f"{h_min} {ref_rmse_min}",
    ]

    # Write gnuplot script
    gnuplot_script = f"""set terminal svg size 800,600 enhanced
set output '{svg_path}'
set title "Convergence of Probabilistic ODE Solver"
set xlabel "Step size h"
set ylabel "Terminal RMSE"
set logscale xy
set grid
set key top left
set style data linespoints
set pointsize 1.5

$DATA << EOD
{chr(10).join(data_lines)}
EOD

$REF << EOD
{chr(10).join(ref_lines)}
EOD

plot $DATA using 1:2 title "EK0 solver" with linespoints pt 7 ps 1.5 lw 2, \\
     $REF using 1:2 title "Reference slope O(h^{prior_order})" with lines lt 2 lw 2 dt 2
"""

    # Write script to temp file and run gnuplot
    script_path = os.path.join(os.path.dirname(svg_path), "convergence.gp")
    with open(script_path, "w") as f:
        f.write(gnuplot_script)

    result = subprocess.run(
        ["gnuplot", script_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"gnuplot stderr: {result.stderr}")
        raise RuntimeError(f"gnuplot failed: {result.stderr}")

    print(f"Convergence plot written to {svg_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    with open("/app/problem.json", "r") as f:
        problem = json.load(f)

    # Primary solution
    times, means, stds, sigma_mle, num_steps = solve_ek0(problem)

    # High-precision reference for convergence analysis
    ref_terminal = compute_reference_terminal(problem)

    # Convergence analysis at multiple step sizes
    convergence_data = []
    for h in [0.04, 0.02, 0.01, 0.005]:
        _, m, _, _, ns = solve_ek0(problem, step_size=h)
        rmse = float(np.sqrt(np.mean((m[-1] - ref_terminal) ** 2)))
        convergence_data.append((h, rmse, ns))

    # Persist results
    os.makedirs("/app/results", exist_ok=True)

    q = problem["solver"]["prior_order"]

    # SQLite database
    create_database(
        "/app/results/benchmark.db",
        times, means, stds, sigma_mle, q, convergence_data,
    )

    # HDF5 archive
    create_hdf5(
        "/app/results/trajectory.h5",
        times, means, stds, sigma_mle, q, num_steps,
    )

    # JSON summary
    summary = {
        "terminal_mean": means[-1].tolist(),
        "terminal_std": stds[-1].tolist(),
        "output_scale": float(sigma_mle),
        "num_steps": int(num_steps),
    }
    with open("/app/results/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Gnuplot convergence SVG
    generate_convergence_svg(
        "/app/results/convergence.svg",
        convergence_data,
        q,
    )

    print(f"Solved: {num_steps} steps, output_scale={sigma_mle:.6e}")
    print(f"Terminal mean: {means[-1]}")
    print("Convergence:")
    for h, rmse, ns in convergence_data:
        print(f"  h={h}: RMSE={rmse:.6e}, steps={ns}")


if __name__ == "__main__":
    main()
