#!/usr/bin/env python3
"""Compute optimal experimental designs under D, A, and E criteria.

Given candidate experiments V (m x d) and a linear model y = v^T theta + eps,
find the design weights lambda that optimize the Fisher Information Matrix
FIM(lambda) = sum_i lambda_i v_i v_i^T.
"""

import numpy as np
import cvxpy as cp
import json
import sys

# Load data
V = np.load('/app/experiments.npy')
with open('/app/config.json') as f:
    cfg = json.load(f)

d = cfg['dimension']
m = cfg['num_experiments']
N = cfg['budget']
max_per = cfg['max_per_experiment']
w_max = max_per / N

outer_prods = [np.outer(V[i], V[i]) for i in range(m)]


def make_fim(w_var):
    S = w_var[0] * outer_prods[0]
    for i in range(1, m):
        S = S + w_var[i] * outer_prods[i]
    return S


def fim_numpy(w):
    return (V.T * np.asarray(w, dtype=float)) @ V


def base_constraints(w_var):
    return [cp.sum(w_var) == 1, w_var >= 0, w_var <= w_max]


# ===== D-optimal =====
print("[D-optimal] Solving...")
w_d = cp.Variable(m)
F_d = make_fim(w_d)
p_d = cp.Problem(cp.Maximize(cp.log_det(F_d)), base_constraints(w_d))
p_d.solve(solver=cp.SCS, max_iters=80000, eps=1e-9)
if p_d.status not in ('optimal', 'optimal_inaccurate'):
    print(f"D-optimal failed: {p_d.status}", file=sys.stderr)
    sys.exit(1)
d_weights = np.clip(w_d.value, 0, None)
d_weights /= d_weights.sum()
d_fim = fim_numpy(d_weights)
d_obj = float(np.log(np.linalg.det(d_fim)))
print(f"  Objective: {d_obj:.6f}")

# ===== A-optimal =====
# A-optimality: maximize the total information captured by the design.
# The trace of FIM measures total information across all parameter directions.
print("[A-optimal] Solving...")
w_a = cp.Variable(m)
F_a = make_fim(w_a)
p_a = cp.Problem(cp.Maximize(cp.trace(F_a)), base_constraints(w_a))
p_a.solve(solver=cp.SCS, max_iters=80000, eps=1e-9)
if p_a.status not in ('optimal', 'optimal_inaccurate'):
    print(f"A-optimal failed: {p_a.status}", file=sys.stderr)
    sys.exit(1)
a_weights = np.clip(w_a.value, 0, None)
a_weights /= a_weights.sum()
a_fim = fim_numpy(a_weights)
a_obj = float(np.trace(a_fim))
print(f"  Objective: {a_obj:.6f}")

# ===== E-optimal =====
# E-optimality: minimize the dominant eigenvalue of FIM to control spread.
print("[E-optimal] Solving...")
w_e = cp.Variable(m)
F_e = make_fim(w_e)
p_e = cp.Problem(cp.Minimize(cp.lambda_max(F_e)), base_constraints(w_e))
p_e.solve(solver=cp.SCS, max_iters=80000, eps=1e-9)
if p_e.status not in ('optimal', 'optimal_inaccurate'):
    print(f"E-optimal failed: {p_e.status}", file=sys.stderr)
    sys.exit(1)
e_weights = np.clip(w_e.value, 0, None)
e_weights /= e_weights.sum()
e_fim = fim_numpy(e_weights)
e_obj = float(np.max(np.linalg.eigvalsh(e_fim)))
print(f"  Objective: {e_obj:.6f}")


# ===== Integer rounding =====
def greedy_round(weights, budget):
    """Round continuous weights to integer allocation summing to budget."""
    scaled = weights * budget
    alloc = np.floor(scaled).astype(int)
    remaining = budget - alloc.sum()
    fracs = scaled - alloc.astype(float)
    order = np.argsort(-fracs)
    for idx in order[:remaining]:
        alloc[idx] += 1
    return alloc


print("Rounding to integer allocations...")
d_alloc = greedy_round(d_weights, N)
a_alloc = greedy_round(a_weights, N)
e_alloc = greedy_round(e_weights, N)


def eval_objectives(alloc):
    F = fim_numpy(alloc)
    eigv = np.linalg.eigvalsh(F)
    return {
        'logdet': float(np.log(np.linalg.det(F))),
        'trace': float(np.trace(F)),
        'max_eig': float(np.max(eigv)),
    }


d_int_stats = eval_objectives(d_alloc)
a_int_stats = eval_objectives(a_alloc)
e_int_stats = eval_objectives(e_alloc)

# ===== Efficiency matrix =====
# Rows = designs (D, A, E), columns = criteria (D, A, E)
print("Computing cross-efficiency matrix...")
fims = [fim_numpy(w) for w in [d_weights, a_weights, e_weights]]
ldets = [np.log(np.linalg.det(F)) for F in fims]
traces = [np.trace(F) for F in fims]
max_eigs = [np.max(np.linalg.eigvalsh(F)) for F in fims]

eff = []
for i in range(3):
    row = [
        float(np.exp(ldets[i] - ldets[0])),       # D-efficiency: det ratio
        float(traces[i] / traces[0]),               # A-efficiency: trace ratio
        float(max_eigs[i] / max_eigs[2]),           # E-efficiency: eigenvalue ratio
    ]
    eff.append(row)

# ===== Robust experiments =====
# Experiments appearing in any design's support are considered robust
thresh = 1e-4
supports = [set(j for j in range(m) if w[j] > thresh)
            for w in [d_weights, a_weights, e_weights]]
robust = sorted(supports[0] | supports[1] | supports[2])
print(f"Robust experiments: {robust}")

# ===== Write output =====
results = {
    "d_optimal": {
        "relaxed_weights": d_weights.tolist(),
        "relaxed_objective": d_obj,
        "integer_allocation": d_alloc.tolist(),
        "integer_objective": d_int_stats['logdet'],
    },
    "a_optimal": {
        "relaxed_weights": a_weights.tolist(),
        "relaxed_objective": a_obj,
        "integer_allocation": a_alloc.tolist(),
        "integer_objective": a_int_stats['trace'],
    },
    "e_optimal": {
        "relaxed_weights": e_weights.tolist(),
        "relaxed_objective": e_obj,
        "integer_allocation": e_alloc.tolist(),
        "integer_objective": e_int_stats['max_eig'],
    },
    "efficiency_matrix": eff,
    "robust_experiments": robust,
}

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Results saved to /app/results.json")
