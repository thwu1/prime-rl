#!/usr/bin/env python3
"""Fix reward system bugs, recover weights, audit training history,
compute hypervolume indicator, and design optimal balanced configuration.

"""

import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, '/app')

WEIGHT_NAMES = [
    'tracking_lin_vel', 'tracking_ang_vel', 'lin_vel_z',
    'ang_vel_xy', 'orientation', 'action_rate', 'torques',
    'joint_limits', 'feet_air_time', 'feet_clearance',
]


def fix_reward_system():
    """Fix 3 bugs in /app/reward_system.py."""
    with open('/app/reward_system.py', 'r') as f:
        code = f.read()

    # Bug 1: Gaussian sigmoid uses log(1.0 - value_at_1) instead of log(value_at_1).
    code = code.replace(
        'np.sqrt(-2 * np.log(1.0 - value_at_1))',
        'np.sqrt(-2 * np.log(value_at_1))',
    )

    # Bug 2: tracking_lin_vel uses L1 absolute error instead of squared L2.
    code = code.replace(
        'np.sum(np.abs(commands[:2] - local_vel[:2]))',
        'np.sum((commands[:2] - local_vel[:2]) ** 2)',
    )

    # Bug 3: cost_ang_vel_xy includes z-component (yaw) — should only be xy (roll/pitch).
    # Yaw angular velocity is tracked by tracking_ang_vel, not penalized here.
    code = code.replace(
        'return np.sum(global_angvel ** 2)',
        'return np.sum(global_angvel[:2] ** 2)',
    )

    with open('/app/reward_system.py', 'w') as f:
        f.write(code)
    print("Fixed 3 bugs in reward_system.py")


def fix_gait_utils():
    """Fix 1 bug in /app/gait_utils.py."""
    with open('/app/gait_utils.py', 'r') as f:
        code = f.read()

    # Bug: Bezier uses x*(1-x)^2 instead of x^2*(1-x).
    code = code.replace(
        'x**3 + 3 * (x * (1 - x)**2)',
        'x**3 + 3 * (x**2 * (1 - x))',
    )

    with open('/app/gait_utils.py', 'w') as f:
        f.write(code)
    print("Fixed 1 bug in gait_utils.py")


def recover_weights():
    """Compute reward components and recover weights via least squares."""
    # Force reimport of fixed modules
    for mod_name in ['reward_system', 'gait_utils']:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    from reward_system import RewardComputer

    SIGMA = 0.25
    DT = 0.02
    SWING_HEIGHT = 0.08

    data = np.load('/app/data/trajectory.npz')
    ref_rewards = np.load('/app/data/reference_rewards.npy')

    rc = RewardComputer(sigma=SIGMA, swing_height=SWING_HEIGHT)

    N = len(ref_rewards)

    # Build component matrix R: shape (N, 10)
    R = np.zeros((N, len(WEIGHT_NAMES)))
    for t in range(N):
        components = rc.compute_all(
            commands=data['commands'][t],
            local_vel=data['local_vel'][t],
            ang_vel=data['ang_vel'][t],
            global_linvel=data['global_linvel'][t],
            global_angvel=data['global_angvel'][t],
            up_vector=data['up_vector'][t],
            actions=data['actions'][t],
            prev_actions=data['prev_actions'][t],
            actuator_force=data['actuator_force'][t],
            joint_pos=data['joint_pos'][t],
            soft_lowers=data['soft_lowers'],
            soft_uppers=data['soft_uppers'],
            air_time=data['air_time'][t],
            first_contact=data['first_contact'][t],
            foot_z=data['foot_z'][t],
            foot_vel=data['foot_vel'][t],
            gait_phase=data['gait_phase'][t],
        )
        for j, name in enumerate(WEIGHT_NAMES):
            R[t, j] = components[name]

    # Filter to non-clipped samples (total_reward > 0)
    mask = ref_rewards > 0
    y = ref_rewards[mask] / DT
    R_filtered = R[mask]

    print(f"Using {mask.sum()}/{N} non-clipped samples for regression")

    # Solve: R_filtered @ w = y
    w, residuals, rank, sv = np.linalg.lstsq(R_filtered, y, rcond=None)

    weights = {name: round(float(w[i]), 6) for i, name in enumerate(WEIGHT_NAMES)}

    config = {
        'sigma': SIGMA,
        'dt': DT,
        'swing_height': SWING_HEIGHT,
        'weights': weights,
    }

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/config.json', 'w') as f:
        json.dump(config, f, indent=2)

    print("\nRecovered weights:")
    for name, val in sorted(weights.items()):
        print(f"  {name:25s} = {val:+.6f}")

    # Validate reconstruction
    recon = np.clip(R @ w * DT, 0.0, 10000.0)
    max_err = np.max(np.abs(recon - ref_rewards))
    print(f"\nMax reconstruction error: {max_err:.2e}")

    return weights


def query_training_history():
    """Query the SQLite training history database."""
    conn = sqlite3.connect('/app/data/training_history.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all runs
    cursor.execute("SELECT * FROM training_runs ORDER BY run_id")
    all_runs = [dict(row) for row in cursor.fetchall()]

    # Get quality-filtered runs for weight bounds
    cursor.execute(
        "SELECT * FROM training_runs WHERE gait_quality_score > 0.7 ORDER BY run_id"
    )
    quality_runs = [dict(row) for row in cursor.fetchall()]

    conn.close()

    print(f"\nDatabase: {len(all_runs)} total runs, "
          f"{len(quality_runs)} with gait_quality > 0.7")

    return all_runs, quality_runs


def compute_weight_bounds(quality_runs):
    """Compute per-weight [min, max] from quality-filtered runs."""
    bounds = {}
    for name in WEIGHT_NAMES:
        col = f'w_{name}'
        values = [r[col] for r in quality_runs]
        bounds[name] = [min(values), max(values)]
    return bounds


def find_ancestor(all_runs, recovered_weights):
    """Find the run with minimum L2 distance in weight space."""
    min_dist = float('inf')
    ancestor_id = None

    for run in all_runs:
        dist_sq = 0.0
        for name in WEIGHT_NAMES:
            col = f'w_{name}'
            dist_sq += (run[col] - recovered_weights[name]) ** 2
        dist = np.sqrt(dist_sq)
        if dist < min_dist:
            min_dist = dist
            ancestor_id = run['run_id']

    print(f"Ancestor: run_id={ancestor_id} (L2 distance={min_dist:.6f})")
    return ancestor_id


def compute_pareto_front(all_runs):
    """Compute Pareto front on (avg_episode_return, sim_to_real_transfer_score).

    A run is Pareto-optimal if no other run dominates it on both objectives.
    """
    pareto_ids = []
    for run in all_runs:
        dominated = False
        for other in all_runs:
            if (other['avg_episode_return'] > run['avg_episode_return'] and
                    other['sim_to_real_transfer_score'] > run['sim_to_real_transfer_score']):
                dominated = True
                break
        if not dominated:
            pareto_ids.append(run['run_id'])

    pareto_ids.sort()
    print(f"Pareto front: {pareto_ids}")
    return pareto_ids


def compute_component_sensitivity(all_runs, pareto_ids):
    """Compute coefficient of variation of each weight across Pareto-optimal runs.

    CV = population_std / |mean|
    """
    pareto_runs = [r for r in all_runs if r['run_id'] in set(pareto_ids)]
    sensitivity = {}

    for name in WEIGHT_NAMES:
        col = f'w_{name}'
        values = np.array([r[col] for r in pareto_runs])
        mean = np.mean(values)
        std = np.std(values)  # population std (ddof=0)
        cv = float(std / abs(mean))
        sensitivity[name] = round(cv, 6)

    print("\nComponent sensitivity (CV across Pareto front):")
    for name in sorted(sensitivity, key=sensitivity.get):
        print(f"  {name:25s} = {sensitivity[name]:.6f}")

    return sensitivity


def compute_hypervolume(all_runs, pareto_ids, ref_point=(38.5, 0.28)):
    """Compute 2D hypervolume indicator of the Pareto front.

    Uses the sweep-line algorithm for 2D hypervolume computation.
    The reference point is the per-objective minimum across all training runs.
    """
    pareto_points = [
        (r['avg_episode_return'], r['sim_to_real_transfer_score'])
        for r in all_runs if r['run_id'] in set(pareto_ids)
    ]
    # Sort by return (first objective) descending
    pareto_points.sort(key=lambda p: -p[0])

    ref_r, ref_t = ref_point
    hv = 0.0
    for i, (ret, trans) in enumerate(pareto_points):
        next_ret = pareto_points[i + 1][0] if i + 1 < len(pareto_points) else ref_r
        hv += (ret - next_ret) * (trans - ref_t)

    print(f"\nHypervolume indicator (ref={ref_point}): {hv:.4f}")
    return round(hv, 6)


def design_optimal_config(all_runs, pareto_ids):
    """Design optimal balanced config via maximin fairness LP.

    Find the convex combination of Pareto-optimal configurations that
    maximizes min(normalized_return, normalized_transfer), where
    normalization is by the per-objective maximum across the Pareto front.

    This is a linear program:
        maximize t
        subject to:
            sum(lambda_i * return_i / max_return) >= t
            sum(lambda_i * transfer_i / max_transfer) >= t
            sum(lambda_i) = 1
            lambda_i >= 0
    """
    from scipy.optimize import linprog

    pareto_runs = [r for r in all_runs if r['run_id'] in set(pareto_ids)]
    n = len(pareto_runs)

    returns = [r['avg_episode_return'] for r in pareto_runs]
    transfers = [r['sim_to_real_transfer_score'] for r in pareto_runs]

    max_return = max(returns)
    max_transfer = max(transfers)

    norm_returns = [r / max_return for r in returns]
    norm_transfers = [t / max_transfer for t in transfers]

    # Variables: [lambda_0, ..., lambda_{n-1}, t]
    # Minimize -t (maximize t)
    c = np.zeros(n + 1)
    c[-1] = -1.0

    # Inequality constraints: A_ub @ x <= b_ub
    # -sum(lambda_i * norm_return_i) + t <= 0
    # -sum(lambda_i * norm_transfer_i) + t <= 0
    A_ub = np.zeros((2, n + 1))
    A_ub[0, :n] = [-r for r in norm_returns]
    A_ub[0, n] = 1.0
    A_ub[1, :n] = [-t for t in norm_transfers]
    A_ub[1, n] = 1.0
    b_ub = np.zeros(2)

    # Equality constraint: sum(lambda_i) = 1
    A_eq = np.zeros((1, n + 1))
    A_eq[0, :n] = 1.0
    b_eq = np.array([1.0])

    # Bounds: lambda_i >= 0, t unbounded
    bounds = [(0, None)] * n + [(None, None)]

    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                     bounds=bounds, method='highs')

    if not result.success:
        raise RuntimeError(f"LP solver failed: {result.message}")

    lambdas = result.x[:n]
    t_opt = result.x[n]

    # Build blending weights (only non-zero entries)
    blending_weights = {}
    for i, run in enumerate(pareto_runs):
        if lambdas[i] > 1e-8:
            blending_weights[str(run['run_id'])] = round(float(lambdas[i]), 6)

    # Compute blended weight configuration
    designed_weights = {}
    for name in WEIGHT_NAMES:
        col = f'w_{name}'
        val = sum(lambdas[i] * pareto_runs[i][col] for i in range(n))
        designed_weights[name] = round(float(val), 6)

    print(f"\nDesigned config (maximin objective = {t_opt:.6f}):")
    print(f"Blending weights: {blending_weights}")
    for name, val in sorted(designed_weights.items()):
        print(f"  {name:25s} = {val:+.6f}")

    return {
        'blending_weights': blending_weights,
        'maximin_objective': round(float(t_opt), 6),
        'weights': designed_weights,
    }


def main():
    print("=== Fixing bugs ===")
    fix_reward_system()
    fix_gait_utils()

    print("\n=== Recovering weights ===")
    recovered_weights = recover_weights()

    print("\n=== Training history audit ===")
    all_runs, quality_runs = query_training_history()
    weight_bounds = compute_weight_bounds(quality_runs)
    ancestor_id = find_ancestor(all_runs, recovered_weights)
    pareto_ids = compute_pareto_front(all_runs)
    sensitivity = compute_component_sensitivity(all_runs, pareto_ids)
    hypervolume = compute_hypervolume(all_runs, pareto_ids)

    print("\n=== Designing optimal configuration ===")
    designed_config = design_optimal_config(all_runs, pareto_ids)

    analysis = {
        'ancestor_run_id': ancestor_id,
        'weight_bounds': weight_bounds,
        'pareto_front_run_ids': pareto_ids,
        'component_sensitivity': sensitivity,
        'hypervolume_indicator': hypervolume,
        'designed_config': designed_config,
    }

    with open('/app/results/analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)

    print("\nDone. Config written to /app/results/config.json")
    print("Analysis written to /app/results/analysis.json")


if __name__ == '__main__':
    main()
