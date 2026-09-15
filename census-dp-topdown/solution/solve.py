#!/usr/bin/env python3

"""
Census-style Disclosure Avoidance System.
Implements zCDP Gaussian mechanism with hierarchical top-down post-processing.
"""

import json
import os
import numpy as np
from functools import reduce
from scipy.optimize import minimize, linprog


def build_query_matrix(dim_sizes, sum_over_dims):
    """Build query matrix as Kronecker product of per-dimension factors.

    For each dimension:
      - If in sum_over_dims: factor = ones(1, dim_size) (marginalizes)
      - Otherwise: factor = eye(dim_size) (preserves)
    """
    factors = []
    for d, size in enumerate(dim_sizes):
        if d in sum_over_dims:
            factors.append(np.ones((1, size)))
        else:
            factors.append(np.eye(size))
    return reduce(np.kron, factors)


def compute_sensitivity(Q):
    """Compute L1 and L2 column sensitivities of query matrix Q."""
    col_l1 = np.abs(Q).sum(axis=0)
    col_l2 = np.sqrt((Q ** 2).sum(axis=0))
    if hasattr(col_l1, 'A1'):
        col_l1 = np.asarray(col_l1).flatten()
        col_l2 = np.asarray(col_l2).flatten()
    return float(np.max(col_l1)), float(np.max(col_l2))


def get_zero_info(dim_sizes, zero_positions):
    """Compute flat indices and boolean mask for structural zeros."""
    n_cells = int(np.prod(dim_sizes))
    zero_indices = []
    for pos in zero_positions:
        idx = 0
        for d, p in enumerate(pos):
            stride = int(np.prod(dim_sizes[d + 1:])) if d + 1 < len(dim_sizes) else 1
            idx += p * stride
        zero_indices.append(idx)
    zero_mask = np.zeros(n_cells, dtype=bool)
    zero_mask[zero_indices] = True
    return zero_indices, zero_mask


def optimize_single(Q_list, noisy_list, sigma_list, total, n_cells, zero_indices, zero_mask):
    """Optimize a single geography's histogram via constrained least-squares."""

    def fun(x):
        obj = 0.0
        for Q, m, sigma in zip(Q_list, noisy_list, sigma_list):
            r = Q @ x - m
            obj += np.sum(r ** 2) / (sigma ** 2)
        return obj

    def jac(x):
        g = np.zeros(n_cells)
        for Q, m, sigma in zip(Q_list, noisy_list, sigma_list):
            r = Q @ x - m
            g += 2.0 * (Q.T @ r) / (sigma ** 2)
        return g

    # Initial point: uniform over active cells
    active = n_cells - len(zero_indices)
    x0 = np.full(n_cells, total / max(active, 1))
    x0[zero_mask] = 0.0

    bounds = [(0, None)] * n_cells
    for zi in zero_indices:
        bounds[zi] = (0, 0)

    cons = [{"type": "eq",
             "fun": lambda x: np.sum(x) - total,
             "jac": lambda x: np.ones(n_cells)}]

    result = minimize(fun, x0, jac=jac, method="SLSQP",
                      bounds=bounds, constraints=cons,
                      options={"ftol": 1e-14, "maxiter": 3000})
    return np.maximum(result.x, 0)


def optimize_children(Q_list, children_noisy, sigma_list, parent_int,
                       child_totals, n_cells, zero_indices, zero_mask):
    """Optimize multiple children jointly to sum to (integer) parent."""
    n_ch = len(children_noisy)
    n_vars = n_ch * n_cells

    parent_zero = set(np.where(parent_int == 0)[0])
    forced_zero = set(zero_indices) | parent_zero

    def fun(x):
        obj = 0.0
        for j in range(n_ch):
            xj = x[j * n_cells:(j + 1) * n_cells]
            for q, (Q, sigma) in enumerate(zip(Q_list, sigma_list)):
                r = Q @ xj - children_noisy[j][q]
                obj += np.sum(r ** 2) / (sigma ** 2)
        return obj

    def jac(x):
        g = np.zeros(n_vars)
        for j in range(n_ch):
            xj = x[j * n_cells:(j + 1) * n_cells]
            for q, (Q, sigma) in enumerate(zip(Q_list, sigma_list)):
                r = Q @ xj - children_noisy[j][q]
                g[j * n_cells:(j + 1) * n_cells] += 2.0 * (Q.T @ r) / (sigma ** 2)
        return g

    # Initial point: proportional allocation from parent
    x0 = np.zeros(n_vars)
    total_ch = sum(child_totals)
    for j in range(n_ch):
        prop = child_totals[j] / max(total_ch, 1)
        x0[j * n_cells:(j + 1) * n_cells] = parent_int.astype(float) * prop
        for zi in forced_zero:
            x0[j * n_cells + zi] = 0.0

    bounds = [(0, None)] * n_vars
    for j in range(n_ch):
        for zi in forced_zero:
            bounds[j * n_cells + zi] = (0, 0)

    cons = []
    # Parent-child consistency
    for i in range(n_cells):
        if i in parent_zero:
            continue

        def _make_pc(cell, pval):
            def f(x):
                return sum(x[j * n_cells + cell] for j in range(n_ch)) - pval
            def g(x):
                gr = np.zeros(n_vars)
                for j in range(n_ch):
                    gr[j * n_cells + cell] = 1.0
                return gr
            return f, g

        f, g = _make_pc(i, float(parent_int[i]))
        cons.append({"type": "eq", "fun": f, "jac": g})

    # Individual total constraints
    for j in range(n_ch):
        def _make_tot(child, tot):
            def f(x):
                return np.sum(x[child * n_cells:(child + 1) * n_cells]) - tot
            def g(x):
                gr = np.zeros(n_vars)
                gr[child * n_cells:(child + 1) * n_cells] = 1.0
                return gr
            return f, g

        f, g = _make_tot(j, float(child_totals[j]))
        cons.append({"type": "eq", "fun": f, "jac": g})

    result = minimize(fun, x0, jac=jac, method="SLSQP",
                      bounds=bounds, constraints=cons,
                      options={"ftol": 1e-14, "maxiter": 5000})

    children = []
    for j in range(n_ch):
        c = result.x[j * n_cells:(j + 1) * n_cells]
        c = np.maximum(c, 0)
        c[list(forced_zero)] = 0
        children.append(c)
    return children


def round_histogram(x_cont, total, zero_mask):
    """Round a single histogram to integers preserving total and zeros."""
    x = np.maximum(x_cont.copy(), 0)
    x[zero_mask] = 0
    x_floor = np.floor(x).astype(int)
    deficit = int(total) - int(x_floor.sum())

    fracs = x - x_floor
    fracs[zero_mask] = -1

    if deficit > 0:
        order = np.argsort(-fracs)
        for idx in order[:deficit]:
            x_floor[idx] += 1
    elif deficit < 0:
        order = np.argsort(fracs)
        count = 0
        for idx in order:
            if count >= -deficit:
                break
            if x_floor[idx] > 0 and not zero_mask[idx]:
                x_floor[idx] -= 1
                count += 1
    return x_floor


def round_children(parent_int, children_cont, child_totals, zero_mask):
    """Round children to integers preserving parent-child consistency and totals.

    Uses an LP (transportation problem) for exact constraint satisfaction.
    Falls back to greedy if LP is infeasible.
    """
    n_ch = len(children_cont)
    n_cells = len(parent_int)

    # Clip and floor
    clipped = []
    for c in children_cont:
        cc = np.maximum(c.copy(), 0)
        cc[zero_mask] = 0
        clipped.append(cc)
    floors = [np.floor(c).astype(int) for c in clipped]
    fracs = [clipped[j] - floors[j] for j in range(n_ch)]

    # Ensure no floor exceeds what's possible
    for j in range(n_ch):
        excess = int(floors[j].sum()) - int(child_totals[j])
        if excess > 0:
            order = np.argsort([fracs[j][i] for i in range(n_cells)])
            for idx in order:
                if excess <= 0:
                    break
                if floors[j][idx] > 0 and not zero_mask[idx]:
                    floors[j][idx] -= 1
                    fracs[j][idx] += 1.0
                    excess -= 1

    # Compute deficits
    child_defs = [int(child_totals[j]) - int(floors[j].sum()) for j in range(n_ch)]
    cell_sums = np.zeros(n_cells, dtype=int)
    for j in range(n_ch):
        cell_sums += floors[j]
    cell_defs = (parent_int - cell_sums).astype(int)

    # Fix any negative cell deficits (from numerical issues)
    for i in range(n_cells):
        while cell_defs[i] < 0:
            reduced = False
            for j in range(n_ch):
                if floors[j][i] > 0:
                    floors[j][i] -= 1
                    cell_defs[i] += 1
                    child_defs[j] += 1
                    fracs[j][i] += 1.0
                    reduced = True
                    break
            if not reduced:
                break

    total_def = sum(max(0, d) for d in child_defs)
    if total_def == 0:
        return floors

    # LP-based transportation rounding
    n_vars = n_ch * n_cells
    c_obj = np.zeros(n_vars)
    for j in range(n_ch):
        for i in range(n_cells):
            c_obj[j * n_cells + i] = 1 - 2 * min(fracs[j][i], 1.0)

    # Equality constraints: cell sums and child sums
    A_rows = []
    b_vals = []
    for i in range(n_cells):
        row = np.zeros(n_vars)
        for j in range(n_ch):
            row[j * n_cells + i] = 1
        A_rows.append(row)
        b_vals.append(max(0, cell_defs[i]))
    for j in range(n_ch):
        row = np.zeros(n_vars)
        for i in range(n_cells):
            row[j * n_cells + i] = 1
        A_rows.append(row)
        b_vals.append(max(0, child_defs[j]))

    A_eq = np.array(A_rows)
    b_eq = np.array(b_vals, dtype=float)

    bnd = []
    for j in range(n_ch):
        for i in range(n_cells):
            if zero_mask[i] or fracs[j][i] < 1e-10:
                bnd.append((0, 0))
            else:
                bnd.append((0, 1))

    try:
        res = linprog(c_obj, A_eq=A_eq, b_eq=b_eq, bounds=bnd, method="highs")
        if res.success:
            b = np.round(res.x).astype(int)
            for j in range(n_ch):
                for i in range(n_cells):
                    floors[j][i] += b[j * n_cells + i]
            return floors
    except Exception:
        pass

    # Greedy fallback
    candidates = []
    for j in range(n_ch):
        for i in range(n_cells):
            if not zero_mask[i] and fracs[j][i] > 1e-10:
                candidates.append((fracs[j][i], j, i))
    candidates.sort(reverse=True)

    for _, j, i in candidates:
        if child_defs[j] > 0 and cell_defs[i] > 0:
            floors[j][i] += 1
            child_defs[j] -= 1
            cell_defs[i] -= 1

    # Final fixup for parent-child consistency
    for i in range(n_cells):
        current = sum(floors[j][i] for j in range(n_ch))
        diff = int(parent_int[i]) - current
        while diff > 0:
            best_j = max(range(n_ch), key=lambda j: fracs[j][i] if not zero_mask[i] else -1)
            floors[best_j][i] += 1
            diff -= 1
        while diff < 0:
            candidates_j = [j for j in range(n_ch) if floors[j][i] > 0]
            if not candidates_j:
                break
            best_j = min(candidates_j, key=lambda j: fracs[j][i])
            floors[best_j][i] -= 1
            diff += 1

    return floors


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    dim_sizes = config["schema"]["dim_sizes"]
    n_cells = int(np.prod(dim_sizes))
    hierarchy = config["hierarchy"]
    level_names = hierarchy["level_names"]
    tree = hierarchy["tree"]
    root = hierarchy["root"]
    queries_cfg = config["queries"]
    privacy = config["privacy"]

    # Read data
    data = {}
    for fname in os.listdir("/app/data"):
        if fname.endswith(".json"):
            geo = fname[:-5]
            with open(f"/app/data/{fname}") as f:
                data[geo] = np.array(json.load(f), dtype=float)

    # Build geographic level structure
    geos_by_level = {level_names[0]: [root]}
    for l_idx in range(1, len(level_names)):
        geos_by_level[level_names[l_idx]] = []
        for pg in geos_by_level[level_names[l_idx - 1]]:
            if pg in tree:
                geos_by_level[level_names[l_idx]].extend(tree[pg])

    # Build query matrices
    Q_mats = {}
    for q in queries_cfg:
        Q_mats[q["name"]] = build_query_matrix(dim_sizes, q["sum_over_dims"])

    # Compute sensitivities
    multiplier = privacy["bounded_dp_multiplier"]
    sensitivities = {}
    for q in queries_cfg:
        l1_u, l2_u = compute_sensitivity(Q_mats[q["name"]])
        sensitivities[q["name"]] = {
            "l1_unbounded": l1_u,
            "l2_unbounded": l2_u,
            "l1_bounded": l1_u * multiplier,
            "l2_bounded": l2_u * multiplier,
        }

    # Budget allocation
    total_rho = privacy["total_rho"]
    level_props = privacy["level_proportions"]
    budget = {}
    for l_idx, level in enumerate(level_names):
        rho_level = level_props[l_idx] * total_rho
        budget[level] = {}
        for q in queries_cfg:
            rho_q = q["proportion"] * rho_level
            delta2 = sensitivities[q["name"]]["l2_bounded"]
            sigma = delta2 / np.sqrt(2 * rho_q)
            budget[level][q["name"]] = {"rho": float(rho_q), "sigma": float(sigma)}

    # Structural zeros
    zero_indices, zero_mask = get_zero_info(
        dim_sizes, config["constraints"]["structural_zeros"]
    )

    # Generate noisy measurements (deterministic order)
    rng = np.random.RandomState(config["seed"])
    noisy = {}
    for l_idx, level in enumerate(level_names):
        for geo in sorted(geos_by_level[level]):
            noisy[geo] = {}
            for q in queries_cfg:
                Q = Q_mats[q["name"]]
                true_ans = Q @ data[geo]
                sigma = budget[level][q["name"]]["sigma"]
                noise = rng.normal(0, sigma, size=true_ans.shape)
                noisy[geo][q["name"]] = true_ans + noise

    # Top-down optimization + rounding
    synthetic = {}
    Q_list = [Q_mats[q["name"]] for q in queries_cfg]

    # Level 0: root
    level = level_names[0]
    sigma_list = [budget[level][q["name"]]["sigma"] for q in queries_cfg]
    noisy_list = [noisy[root][q["name"]] for q in queries_cfg]

    root_cont = optimize_single(Q_list, noisy_list, sigma_list,
                                float(data[root].sum()), n_cells,
                                zero_indices, zero_mask)
    synthetic[root] = round_histogram(root_cont, int(data[root].sum()), zero_mask)

    # Lower levels
    for l_idx in range(1, len(level_names)):
        level = level_names[l_idx]
        prev_level = level_names[l_idx - 1]
        sigma_list = [budget[level][q["name"]]["sigma"] for q in queries_cfg]

        for parent_geo in sorted(geos_by_level[prev_level]):
            if parent_geo not in tree:
                continue
            children_geos = tree[parent_geo]
            parent_int = synthetic[parent_geo]
            child_tots = [int(data[c].sum()) for c in children_geos]

            ch_noisy = []
            for c in children_geos:
                ch_noisy.append([noisy[c][q["name"]] for q in queries_cfg])

            ch_cont = optimize_children(Q_list, ch_noisy, sigma_list,
                                        parent_int, child_tots, n_cells,
                                        zero_indices, zero_mask)

            ch_int = round_children(parent_int, ch_cont, child_tots, zero_mask)
            for c, ci in zip(children_geos, ch_int):
                synthetic[c] = ci

    # Write outputs
    os.makedirs("/app/output/synthetic", exist_ok=True)

    with open("/app/output/sensitivities.json", "w") as f:
        json.dump(sensitivities, f, indent=2)

    budget_out = {}
    for lv, qd in budget.items():
        budget_out[lv] = {}
        for qn, vals in qd.items():
            budget_out[lv][qn] = {"rho": float(vals["rho"]), "sigma": float(vals["sigma"])}
    with open("/app/output/budget.json", "w") as f:
        json.dump(budget_out, f, indent=2)

    for geo, hist in synthetic.items():
        with open(f"/app/output/synthetic/{geo}.json", "w") as f:
            json.dump([int(x) for x in hist], f)

    print("Pipeline complete. Output written to /app/output/")


if __name__ == "__main__":
    main()
