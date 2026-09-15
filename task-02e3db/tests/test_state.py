"""Verification tests for pose graph optimization solver.

"""
import sys
sys.path.insert(0, '/app')

import numpy as np
from pgo_solver import load_graph, optimize_pose_graph


def _reference_trajectory():
    """Compute reference trajectory for verification."""
    _n, _r = 40, 5.0
    poses = []
    for i in range(_n):
        a = 2.0 * np.pi * i / _n
        h = a + np.pi / 2.0
        ch, sh = np.cos(h), np.sin(h)
        R = np.array([[ch, sh, 0.0], [-sh, ch, 0.0], [0.0, 0.0, 1.0]])
        p = np.array([_r * np.cos(a), _r * np.sin(a), 0.3 * np.sin(2.0 * a)])
        poses.append((R, -R @ p))
    return poses


def _pose_errors(opt_poses, ref_poses, fixed):
    """Compute max translation and rotation errors over non-fixed poses."""
    max_t = 0.0
    max_r = 0.0
    for i in range(len(ref_poses)):
        if i in fixed:
            continue
        R_ref, t_ref = ref_poses[i]
        R_opt, t_opt = opt_poses[i]
        t_err = np.linalg.norm(t_opt - t_ref)
        max_t = max(max_t, t_err)
        R_err = R_ref.T @ R_opt
        cos_a = np.clip((np.trace(R_err) - 1.0) / 2.0, -1.0, 1.0)
        r_err = np.degrees(np.arccos(cos_a))
        max_r = max(max_r, r_err)
    return max_t, max_r


def test_convergence():
    """PGO solver must converge within 100 iterations."""
    graph = load_graph('/app/pose_graph.json')
    result = optimize_pose_graph(graph, huber_scale=1.0)
    assert result['converged'], (
        f"Solver did not converge after {result['iterations']} iterations"
    )


def test_translation_accuracy():
    """Optimized trajectory must be within 0.10 m of reference."""
    graph = load_graph('/app/pose_graph.json')
    result = optimize_pose_graph(graph, huber_scale=1.0)
    ref = _reference_trajectory()
    max_t, _ = _pose_errors(result['optimized_poses'], ref, graph['fixed_poses'])
    assert max_t < 0.10, (
        f"Max translation error {max_t:.4f} m exceeds 0.10 m threshold"
    )


def test_rotation_accuracy():
    """Optimized poses must be within 1.0 deg of reference."""
    graph = load_graph('/app/pose_graph.json')
    result = optimize_pose_graph(graph, huber_scale=1.0)
    ref = _reference_trajectory()
    _, max_r = _pose_errors(result['optimized_poses'], ref, graph['fixed_poses'])
    assert max_r < 1.0, (
        f"Max rotation error {max_r:.4f} deg exceeds 1.0 deg threshold"
    )


def test_robust_loss_effectiveness():
    """Robust estimation must significantly improve results over non-robust.

    The dataset contains outlier loop closure edges with deliberately
    incorrect measurements. Without robust estimation, these corrupt the solution.
    """
    graph = load_graph('/app/pose_graph.json')
    ref = _reference_trajectory()

    # With robust estimation
    result_robust = optimize_pose_graph(graph, huber_scale=1.0)
    err_robust, _ = _pose_errors(result_robust['optimized_poses'], ref,
                                  graph['fixed_poses'])

    # Without robust estimation (scale=inf disables it)
    result_no_robust = optimize_pose_graph(graph, huber_scale=float('inf'))
    err_no_robust, _ = _pose_errors(result_no_robust['optimized_poses'], ref,
                                     graph['fixed_poses'])

    assert err_robust < 0.10, (
        f"Error with robust estimation {err_robust:.4f} m exceeds 0.10 m"
    )
    assert err_robust < 0.5 * err_no_robust, (
        f"Robust estimation not effective: with={err_robust:.4f} m, "
        f"without={err_no_robust:.4f} m (need at least 2x improvement)"
    )
