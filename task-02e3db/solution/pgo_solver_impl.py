"""Complete PGO solver implementation.

"""
import numpy as np
import json
import scipy.sparse
import scipy.sparse.linalg
from se3 import se3_log, se3_retract, se3_inverse, se3_compose


def load_graph(path):
    """Load pose graph from JSON."""
    with open(path) as f:
        data = json.load(f)
    init_poses = [(np.array(p['R']), np.array(p['t'])) for p in data['init_poses']]
    edges = [{'i': e['i'], 'j': e['j'],
              'R': np.array(e['R']), 't': np.array(e['t']),
              'info_weight': e['info_weight']} for e in data['edges']]
    return {
        'n_poses': data['n_poses'],
        'fixed_poses': set(data['fixed_poses']),
        'init_poses': init_poses,
        'edges': edges,
    }


def save_trajectory(poses, path):
    """Save optimized poses to JSON."""
    out = [{'R': R.tolist(), 't': t.tolist()} for R, t in poses]
    with open(path, 'w') as f:
        json.dump(out, f)


def compute_residual(Ra, ta, Rb, tb, R_meas, t_meas):
    """Compute 6D relative-pose residual: r = log(T_meas^{-1} * T_b * T_a^{-1})."""
    Rm_inv, tm_inv = se3_inverse(R_meas, t_meas)
    Ra_inv, ta_inv = se3_inverse(Ra, ta)
    R_ba, t_ba = se3_compose(Rb, tb, Ra_inv, ta_inv)
    R_err, t_err = se3_compose(Rm_inv, tm_inv, R_ba, t_ba)
    return se3_log(R_err, t_err)


def compute_jacobian_numerical(Ra, ta, Rb, tb, R_meas, t_meas, eps=1e-6):
    """Numerical Jacobians via central differences in SE(3) tangent."""
    Ja = np.zeros((6, 6))
    Jb = np.zeros((6, 6))
    for k in range(6):
        delta = np.zeros(6)
        delta[k] = eps
        Ra_p, ta_p = se3_retract(Ra, ta, delta)
        Ra_m, ta_m = se3_retract(Ra, ta, -delta)
        rp = compute_residual(Ra_p, ta_p, Rb, tb, R_meas, t_meas)
        rm = compute_residual(Ra_m, ta_m, Rb, tb, R_meas, t_meas)
        Ja[:, k] = (rp - rm) / (2.0 * eps)
    for k in range(6):
        delta = np.zeros(6)
        delta[k] = eps
        Rb_p, tb_p = se3_retract(Rb, tb, delta)
        Rb_m, tb_m = se3_retract(Rb, tb, -delta)
        rp = compute_residual(Ra, ta, Rb_p, tb_p, R_meas, t_meas)
        rm = compute_residual(Ra, ta, Rb_m, tb_m, R_meas, t_meas)
        Jb[:, k] = (rp - rm) / (2.0 * eps)
    return Ja, Jb


def huber_weight(residual_norm, scale):
    """Huber IRLS weight."""
    if not np.isfinite(scale) or scale <= 0:
        return 1.0
    if residual_norm <= scale:
        return 1.0
    return scale / max(residual_norm, 1e-12)


def huber_cost(residual_norm, scale, info_weight):
    """Actual Huber cost for a single edge."""
    if not np.isfinite(scale) or scale <= 0:
        return 0.5 * info_weight * residual_norm ** 2
    if residual_norm <= scale:
        return 0.5 * info_weight * residual_norm ** 2
    return info_weight * (scale * residual_norm - 0.5 * scale ** 2)


def _total_cost(Rs, ts, edges, huber_scale):
    """Compute total Huber cost over all edges."""
    cost = 0.0
    for e in edges:
        r = compute_residual(Rs[e['i']], ts[e['i']],
                             Rs[e['j']], ts[e['j']],
                             e['R'], e['t'])
        rn = np.linalg.norm(r)
        cost += huber_cost(rn, huber_scale, e['info_weight'])
    return cost


def optimize_pose_graph(graph, max_iterations=100, initial_lambda=1e-4,
                        cost_tolerance=1e-6, huber_scale=1.0):
    """Run pose graph optimization with Levenberg-Marquardt."""
    n_poses = graph['n_poses']
    fixed = graph['fixed_poses']
    edges = graph['edges']

    # Variable indexing: free poses only
    pose_to_var = {}
    var_idx = 0
    for i in range(n_poses):
        if i not in fixed:
            pose_to_var[i] = var_idx
            var_idx += 1
    n_free = var_idx
    dim = n_free * 6

    # Mutable state
    Rs = [R.copy() for R, _ in graph['init_poses']]
    ts = [t.copy() for _, t in graph['init_poses']]

    lam = initial_lambda
    converged = False
    iterations = 0
    final_cost = float('inf')

    for _it in range(max_iterations):
        iterations += 1

        # Accumulate COO triplets for sparse Hessian
        rows, cols, vals = [], [], []
        g = np.zeros(dim)

        for e in edges:
            ii, jj = e['i'], e['j']
            r = compute_residual(Rs[ii], ts[ii], Rs[jj], ts[jj],
                                 e['R'], e['t'])
            Ja, Jb = compute_jacobian_numerical(Rs[ii], ts[ii], Rs[jj], ts[jj],
                                                 e['R'], e['t'])

            rn = np.linalg.norm(r)
            w_h = huber_weight(rn, huber_scale)
            w = e['info_weight'] * w_h
            sw = np.sqrt(w)
            r_w = sw * r
            Ja_w = sw * Ja
            Jb_w = sw * Jb

            var_list = []
            J_list = []
            if ii in pose_to_var:
                var_list.append(pose_to_var[ii])
                J_list.append(Ja_w)
            if jj in pose_to_var:
                var_list.append(pose_to_var[jj])
                J_list.append(Jb_w)

            for vi, Ji in zip(var_list, J_list):
                g[vi * 6:(vi + 1) * 6] -= Ji.T @ r_w
                for vj, Jj in zip(var_list, J_list):
                    block = Ji.T @ Jj
                    for br in range(6):
                        for bc in range(6):
                            rows.append(vi * 6 + br)
                            cols.append(vj * 6 + bc)
                            vals.append(block[br, bc])

        # Current actual Huber cost
        cost = _total_cost(Rs, ts, edges, huber_scale)

        # Assemble sparse Hessian
        H = scipy.sparse.coo_matrix((vals, (rows, cols)),
                                     shape=(dim, dim)).tocsc()

        # LM damping: H + lambda * diag(H)
        diag_h = np.array(H.diagonal())
        diag_h = np.maximum(diag_h, 1e-6)
        H_damped = H + scipy.sparse.diags(lam * diag_h)

        # Solve via sparse LU
        try:
            factor = scipy.sparse.linalg.splu(H_damped.tocsc())
            delta = factor.solve(g)
        except Exception:
            lam *= 10.0
            if lam > 1e10:
                break
            continue

        # Trial step: retract poses
        Rs_trial = [R.copy() for R in Rs]
        ts_trial = [t.copy() for t in ts]
        for i in range(n_poses):
            if i in pose_to_var:
                vi = pose_to_var[i]
                delta_i = delta[vi * 6:(vi + 1) * 6]
                Rs_trial[i], ts_trial[i] = se3_retract(Rs[i], ts[i], delta_i)

        # Evaluate trial cost using actual Huber cost
        new_cost = _total_cost(Rs_trial, ts_trial, edges, huber_scale)

        # Accept or reject
        if new_cost < cost:
            rel = (cost - new_cost) / max(cost, 1e-12)
            Rs, ts = Rs_trial, ts_trial
            final_cost = new_cost
            lam = max(lam / 3.0, 1e-8)
            if rel < cost_tolerance:
                converged = True
                break
        else:
            lam *= 10.0
            if lam > 1e10:
                break

    return {
        'optimized_poses': [(Rs[i], ts[i]) for i in range(n_poses)],
        'iterations': iterations,
        'converged': converged,
        'final_cost': final_cost,
    }


if __name__ == '__main__':
    graph = load_graph('/app/pose_graph.json')
    result = optimize_pose_graph(graph)
    save_trajectory(result['optimized_poses'], '/app/result_trajectory.json')
    print(f"Converged: {result['converged']}, iterations: {result['iterations']}, "
          f"cost: {result['final_cost']:.6f}")
