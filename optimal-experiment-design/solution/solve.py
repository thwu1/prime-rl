#!/usr/bin/env python3

"""Reference solution: diagnose and fix the buggy optimizer."""

import numpy as np
import cvxpy as cp
import json

# Load problem data
V = np.load('/app/experiments.npy')
with open('/app/config.json') as f:
    config = json.load(f)

d = config['dimension']
m = config['num_experiments']
N = config['budget']
max_per = config['max_per_experiment']
max_weight = max_per / N

# Precompute outer products
outers = [np.outer(V[i], V[i]) for i in range(m)]


def build_fim_expr(weights_var):
    """Build FIM as a CVXPY expression from variable weights."""
    expr = weights_var[0] * outers[0]
    for i in range(1, m):
        expr = expr + weights_var[i] * outers[i]
    return expr


def compute_fim_np(weights):
    """Compute FIM from numpy weights."""
    w = np.asarray(weights, dtype=float)
    return (V.T * w) @ V


def standard_constraints(lam_var):
    return [cp.sum(lam_var) == 1, lam_var >= 0, lam_var <= max_weight]


# ===== D-OPTIMAL (correct in the original) =====
print("Solving D-optimal...")
lam_d = cp.Variable(m)
FIM_d = build_fim_expr(lam_d)
prob_d = cp.Problem(
    cp.Maximize(cp.log_det(FIM_d)),
    standard_constraints(lam_d)
)
prob_d.solve(solver=cp.SCS, max_iters=100000, eps=1e-9)
assert prob_d.status in ('optimal', 'optimal_inaccurate'), \
    f"D-optimal failed: {prob_d.status}"

d_weights = np.clip(lam_d.value, 0, None)
d_weights /= d_weights.sum()
d_fim = compute_fim_np(d_weights)
d_obj = float(np.log(np.linalg.det(d_fim)))
print(f"  D-optimal objective: {d_obj:.6f}")

# ===== A-OPTIMAL (BUG FIX: minimize trace(FIM^{-1}), not maximize trace(FIM)) =====
print("Solving A-optimal...")
lam_a = cp.Variable(m)
FIM_a = build_fim_expr(lam_a)
# trace(FIM^{-1}) = sum_j e_j^T FIM^{-1} e_j = sum_j matrix_frac(e_j, FIM)
identity_cols = [np.eye(d)[:, j] for j in range(d)]
a_obj_expr = sum(cp.matrix_frac(identity_cols[j], FIM_a) for j in range(d))
prob_a = cp.Problem(
    cp.Minimize(a_obj_expr),
    standard_constraints(lam_a)
)
prob_a.solve(solver=cp.SCS, max_iters=100000, eps=1e-9)
assert prob_a.status in ('optimal', 'optimal_inaccurate'), \
    f"A-optimal failed: {prob_a.status}"

a_weights = np.clip(lam_a.value, 0, None)
a_weights /= a_weights.sum()
a_fim = compute_fim_np(a_weights)
a_obj = float(np.trace(np.linalg.inv(a_fim)))
print(f"  A-optimal objective: {a_obj:.6f}")

# ===== E-OPTIMAL (BUG FIX: maximize lambda_min, not minimize lambda_max) =====
print("Solving E-optimal...")
lam_e = cp.Variable(m)
FIM_e = build_fim_expr(lam_e)
prob_e = cp.Problem(
    cp.Maximize(cp.lambda_min(FIM_e)),
    standard_constraints(lam_e)
)
prob_e.solve(solver=cp.SCS, max_iters=100000, eps=1e-9)
assert prob_e.status in ('optimal', 'optimal_inaccurate'), \
    f"E-optimal failed: {prob_e.status}"

e_weights = np.clip(lam_e.value, 0, None)
e_weights /= e_weights.sum()
e_fim = compute_fim_np(e_weights)
e_obj = float(np.min(np.linalg.eigvalsh(e_fim)))
print(f"  E-optimal objective: {e_obj:.6f}")


# ===== INTEGER ROUNDING (with cap enforcement) =====
def round_design(weights, budget, cap):
    """Greedy rounding of continuous weights to integer allocation."""
    scaled = np.maximum(weights, 0) * budget
    alloc = np.floor(scaled).astype(int)
    alloc = np.minimum(alloc, cap)
    remaining = budget - alloc.sum()

    # Distribute remaining budget by largest fractional part
    fracs = scaled - alloc.astype(float)
    fracs[alloc >= cap] = -1.0  # don't add to capped experiments
    order = np.argsort(-fracs)
    for idx in order:
        if remaining <= 0:
            break
        space = cap - alloc[idx]
        add = min(remaining, space)
        alloc[idx] += add
        remaining -= add
    return alloc


print("Rounding to integer allocations...")
d_alloc = round_design(d_weights, N, max_per)
a_alloc = round_design(a_weights, N, max_per)
e_alloc = round_design(e_weights, N, max_per)


def compute_all_objectives(alloc):
    fim = compute_fim_np(alloc)
    ld = float(np.log(np.linalg.det(fim)))
    ti = float(np.trace(np.linalg.inv(fim)))
    me = float(np.min(np.linalg.eigvalsh(fim)))
    return ld, ti, me


d_int_ld, _, _ = compute_all_objectives(d_alloc)
_, a_int_ti, _ = compute_all_objectives(a_alloc)
_, _, e_int_me = compute_all_objectives(e_alloc)

# ===== EFFICIENCY MATRIX (BUG FIX: correct formulas) =====
print("Computing efficiency matrix...")
designs_w = [d_weights, a_weights, e_weights]
fims = [compute_fim_np(w) for w in designs_w]
log_dets = [np.log(np.linalg.det(f)) for f in fims]
trace_invs = [np.trace(np.linalg.inv(f)) for f in fims]
min_eigs = [np.min(np.linalg.eigvalsh(f)) for f in fims]

eff_matrix = []
for i in range(3):
    row = [
        float(np.exp((log_dets[i] - log_dets[0]) / d)),   # D-eff with 1/d root
        float(trace_invs[1] / trace_invs[i]),                # A-eff: best/current
        float(min_eigs[i] / min_eigs[2]),                    # E-eff: current/best
    ]
    eff_matrix.append(row)

# ===== ROBUST EXPERIMENTS (BUG FIX: intersection, not union) =====
threshold = 1e-4
supports = [set(i for i in range(m) if w[i] > threshold) for w in designs_w]
robust = sorted(supports[0] & supports[1] & supports[2])
print(f"Robust experiments: {robust}")

# ===== OUTPUT =====
results = {
    "d_optimal": {
        "relaxed_weights": d_weights.tolist(),
        "relaxed_objective": d_obj,
        "integer_allocation": d_alloc.tolist(),
        "integer_objective": d_int_ld,
    },
    "a_optimal": {
        "relaxed_weights": a_weights.tolist(),
        "relaxed_objective": a_obj,
        "integer_allocation": a_alloc.tolist(),
        "integer_objective": a_int_ti,
    },
    "e_optimal": {
        "relaxed_weights": e_weights.tolist(),
        "relaxed_objective": e_obj,
        "integer_allocation": e_alloc.tolist(),
        "integer_objective": e_int_me,
    },
    "efficiency_matrix": eff_matrix,
    "robust_experiments": robust,
}

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
