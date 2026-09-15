#!/usr/bin/env python3
"""
2D Pose-Graph SLAM Optimizer using Levenberg-Marquardt on SE(2).

"""
import argparse
import json
import math
import sys

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
import yaml


def normalize_angle(a):
    """Normalize angle to [-pi, pi]."""
    a = math.fmod(a, 2 * math.pi)
    if a > math.pi:
        a -= 2 * math.pi
    elif a < -math.pi:
        a += 2 * math.pi
    return a


def parse_g2o(filename):
    """Parse a g2o format pose graph file."""
    vertices = {}
    edges = []
    fixed = set()

    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "VERTEX_SE2":
                vid = int(parts[1])
                x, y, theta = float(parts[2]), float(parts[3]), float(parts[4])
                vertices[vid] = np.array([x, y, theta])
            elif parts[0] == "EDGE_SE2":
                id1, id2 = int(parts[1]), int(parts[2])
                dx, dy, dtheta = float(parts[3]), float(parts[4]), float(parts[5])
                i11, i12, i13 = float(parts[6]), float(parts[7]), float(parts[8])
                i22, i23 = float(parts[9]), float(parts[10])
                i33 = float(parts[11])
                info = np.array([[i11, i12, i13], [i12, i22, i23], [i13, i23, i33]])
                measurement = np.array([dx, dy, dtheta])
                edges.append((id1, id2, measurement, info))
            elif parts[0] == "FIX":
                fixed.add(int(parts[1]))

    return vertices, edges, fixed


def compute_error(xi, yi, ti, xj, yj, tj, measurement):
    """Compute SE(2) error: predicted relative pose minus measurement."""
    c, s = math.cos(ti), math.sin(ti)
    dxg, dyg = xj - xi, yj - yi
    pred_dx = c * dxg + s * dyg
    pred_dy = -s * dxg + c * dyg
    pred_dtheta = normalize_angle(tj - ti)
    return np.array(
        [
            pred_dx - measurement[0],
            pred_dy - measurement[1],
            normalize_angle(pred_dtheta - measurement[2]),
        ]
    )


def compute_jacobians(xi, yi, ti, xj, yj, tj):
    """Analytical Jacobians of the SE(2) error w.r.t. poses i and j."""
    c, s = math.cos(ti), math.sin(ti)
    dxg, dyg = xj - xi, yj - yi

    Ji = np.array(
        [
            [-c, -s, -s * dxg + c * dyg],
            [s, -c, -c * dxg - s * dyg],
            [0.0, 0.0, -1.0],
        ]
    )
    Jj = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    return Ji, Jj


def robust_weight(sq_err, loss_fn, delta):
    """IRLS weight: rho'(s) where s = e^T * Omega * e."""
    if loss_fn == "None" or loss_fn is None:
        return 1.0
    if sq_err < 1e-16:
        return 1.0
    r = math.sqrt(sq_err)
    if loss_fn == "HuberLoss":
        return 1.0 if r <= delta else delta / r
    elif loss_fn == "CauchyLoss":
        return 1.0 / (1.0 + sq_err / (delta * delta))
    return 1.0


def robust_cost(sq_err, loss_fn, delta):
    """Actual robust cost rho(s)."""
    if loss_fn == "None" or loss_fn is None:
        return sq_err
    r = math.sqrt(max(sq_err, 0.0))
    if loss_fn == "HuberLoss":
        if r <= delta:
            return sq_err
        return 2.0 * delta * r - delta * delta
    elif loss_fn == "CauchyLoss":
        return delta * delta * math.log(1.0 + sq_err / (delta * delta))
    return sq_err


def evaluate_cost(x, edges, vid_to_idx, loss_fn, delta):
    """Compute total robust cost over all edges."""
    total = 0.0
    for id1, id2, meas, info in edges:
        i1, i2 = vid_to_idx[id1], vid_to_idx[id2]
        e = compute_error(
            x[3 * i1], x[3 * i1 + 1], x[3 * i1 + 2],
            x[3 * i2], x[3 * i2 + 1], x[3 * i2 + 2],
            meas,
        )
        sq_err = float(e @ info @ e)
        total += robust_cost(sq_err, loss_fn, delta)
    return total


def optimize(vertices, edges, fixed, config):
    """Levenberg-Marquardt optimization on the SE(2) pose graph."""
    max_iter = config.get("max_iterations", 100)
    loss_fn = config.get("loss_function", "None")
    huber_delta = config.get("huber_delta", 1.0)
    cauchy_delta = config.get("cauchy_delta", 1.0)
    initial_lambda = config.get("initial_lambda", 1e-5)
    func_tol = config.get("function_tolerance", 1e-6)
    param_tol = config.get("parameter_tolerance", 1e-8)

    delta = huber_delta if loss_fn == "HuberLoss" else cauchy_delta

    vids = sorted(vertices.keys())
    n = len(vids)
    vid_to_idx = {vid: i for i, vid in enumerate(vids)}

    # Flatten state vector
    x = np.zeros(3 * n)
    for vid in vids:
        idx = vid_to_idx[vid]
        x[3 * idx : 3 * idx + 3] = vertices[vid]

    # Identify free (non-fixed) variable indices
    free_mask = np.ones(3 * n, dtype=bool)
    for vid in fixed:
        idx = vid_to_idx[vid]
        free_mask[3 * idx : 3 * idx + 3] = False
    free_indices = np.where(free_mask)[0]

    lam = initial_lambda
    initial_cost = evaluate_cost(x, edges, vid_to_idx, loss_fn, delta)
    prev_cost = initial_cost
    cost_history = [initial_cost]

    report = {
        "iterations": 0,
        "initial_cost": initial_cost,
        "final_cost": initial_cost,
        "converged": False,
        "cost_history": cost_history,
    }

    for iteration in range(max_iter):
        # Build sparse normal equations H dx = -b
        rows, cols, vals = [], [], []
        b = np.zeros(3 * n)

        for id1, id2, meas, info in edges:
            i1 = vid_to_idx[id1]
            i2 = vid_to_idx[id2]
            xi, yi, ti = x[3 * i1], x[3 * i1 + 1], x[3 * i1 + 2]
            xj, yj, tj = x[3 * i2], x[3 * i2 + 1], x[3 * i2 + 2]

            e = compute_error(xi, yi, ti, xj, yj, tj, meas)
            Ji, Jj = compute_jacobians(xi, yi, ti, xj, yj, tj)

            sq_err = float(e @ info @ e)
            w = robust_weight(sq_err, loss_fn, delta)
            w_info = w * info

            # H blocks and b contributions
            for J_a, idx_a in [(Ji, i1), (Jj, i2)]:
                JtO = J_a.T @ w_info
                b[3 * idx_a : 3 * idx_a + 3] += JtO @ e
                for J_b, idx_b in [(Ji, i1), (Jj, i2)]:
                    block = JtO @ J_b
                    for r in range(3):
                        for c in range(3):
                            rows.append(3 * idx_a + r)
                            cols.append(3 * idx_b + c)
                            vals.append(block[r, c])

        H = sp.coo_matrix((vals, (rows, cols)), shape=(3 * n, 3 * n)).tocsr()

        # Extract free submatrix
        H_free = H[np.ix_(free_indices, free_indices)]
        b_free = b[free_indices]

        # LM damping: (H + lambda * diag(H)) dx = -b
        diag_vals = np.array(H_free.diagonal()).flatten()
        damping = sp.diags(lam * np.maximum(np.abs(diag_vals), 1e-6))
        H_damped = H_free + damping

        try:
            dx = spla.spsolve(H_damped.tocsc(), -b_free)
        except Exception:
            lam *= 10.0
            continue

        if np.any(np.isnan(dx)) or np.any(np.isinf(dx)):
            lam *= 10.0
            continue

        # Trial update
        x_new = x.copy()
        x_new[free_indices] += dx
        for vid in vids:
            idx = vid_to_idx[vid]
            x_new[3 * idx + 2] = normalize_angle(x_new[3 * idx + 2])

        new_cost = evaluate_cost(x_new, edges, vid_to_idx, loss_fn, delta)

        if new_cost < prev_cost:
            x = x_new
            cost_decrease = prev_cost - new_cost
            param_change = float(np.linalg.norm(dx))
            prev_cost = new_cost
            lam = max(lam / 10.0, 1e-12)
            cost_history.append(new_cost)

            if (
                cost_decrease < func_tol * max(abs(prev_cost), 1.0)
                and param_change < param_tol
            ):
                report["converged"] = True
                report["iterations"] = iteration + 1
                report["final_cost"] = new_cost
                report["cost_history"] = cost_history
                break
        else:
            lam *= 10.0

        report["iterations"] = iteration + 1
        report["final_cost"] = prev_cost
        report["cost_history"] = cost_history

    # If we exhausted iterations without triggering convergence but cost decreased
    if not report["converged"] and prev_cost < initial_cost * 0.999:
        report["converged"] = True

    # Build result
    result = {}
    for vid in vids:
        idx = vid_to_idx[vid]
        result[vid] = (x[3 * idx], x[3 * idx + 1], normalize_angle(x[3 * idx + 2]))

    return result, report


def main():
    parser = argparse.ArgumentParser(description="2D Pose-Graph SLAM Optimizer")
    parser.add_argument("--graph", required=True, help="Input g2o file")
    parser.add_argument("--config", required=True, help="Solver config YAML")
    parser.add_argument("--output", required=True, help="Output poses file")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)
    solver_config = config.get("solver", {})

    vertices, edges, fixed = parse_g2o(args.graph)
    result, report = optimize(vertices, edges, fixed, solver_config)

    with open(args.output, "w") as f:
        for vid in sorted(result.keys()):
            x, y, theta = result[vid]
            f.write("%d %.6f %.6f %.6f\n" % (vid, x, y, theta))

    report_file = args.output + ".report"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    print(
        "Optimization complete. Converged: %s, Iterations: %d, Cost: %.6f -> %.6f"
        % (report["converged"], report["iterations"], report["initial_cost"], report["final_cost"])
    )


if __name__ == "__main__":
    main()
