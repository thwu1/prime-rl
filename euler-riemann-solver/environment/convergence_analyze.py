"""
Mesh convergence study for the 1D Euler solver.

Output: /app/results/convergence.json and /app/results/convergence_data.csv
"""

import json
import os
import numpy as np


def compute_exact_density(x_cells, x0, t_end, left, right, gamma):
    """
    Compute the exact Riemann solution density at each cell center.

    Parameters
    ----------
    x_cells : array-like of float, cell-center x-coordinates
    x0 : float, initial discontinuity position
    t_end : float, evaluation time (must be > 0)
    left, right : dict with keys 'rho', 'u', 'p'
    gamma : float, ratio of specific heats

    Returns
    -------
    numpy array of exact density values at cell centers
    """
    raise NotImplementedError


def l1_norm(numerical, exact, dx, domain_length):
    """
    Compute the L1 error norm between numerical and exact solutions,
    normalized by domain length.
    """
    raise NotImplementedError


def fit_convergence_rate(dx_list, error_list):
    """
    Determine observed convergence rate from a sequence of
    (mesh spacing, error) pairs.

    Returns
    -------
    float : observed convergence rate
    """
    raise NotImplementedError


def run_study():
    """
    Main entry point. Reads config from /app/convergence/config.json,
    runs solver at each resolution, computes errors against exact
    solution, determines convergence rate, and writes results.

    Must produce:
      - /app/results/convergence.json with fields:
        "resolutions", "l1_errors", "convergence_rate", "pass"
      - /app/results/convergence_data.csv with columns:
        ncells,dx,l1_error
    """
    raise NotImplementedError


if __name__ == '__main__':
    run_study()
