"""
Mesh convergence study for the 1D Euler solver.

Runs the Sod shock tube at multiple mesh resolutions, computes
L1 density error norms against the exact Riemann solution, and
determines the observed convergence rate.

"""

import json
import os
import sys
import numpy as np

sys.path.insert(0, '/app')
from solver.exact_riemann import solve_riemann_star, sample_riemann
from solver.fv_euler import solve_euler_1d


def compute_exact_density(x_cells, x0, t_end, left, right, gamma):
    """
    Compute the exact Riemann solution density at each cell center
    using the similarity variable S = (x - x0) / t_end.
    """
    rhoL, uL, pL = left['rho'], left['u'], left['p']
    rhoR, uR, pR = right['rho'], right['u'], right['p']

    pstar, ustar = solve_riemann_star(rhoL, uL, pL, rhoR, uR, pR, gamma)

    rho_exact = np.zeros(len(x_cells))
    for i, x in enumerate(x_cells):
        S = (x - x0) / t_end
        rho_ex, _, _ = sample_riemann(rhoL, uL, pL, rhoR, uR, pR,
                                       gamma, pstar, ustar, S)
        rho_exact[i] = rho_ex

    return rho_exact


def l1_norm(numerical, exact, dx, domain_length):
    """L1 error norm normalized by domain length."""
    return float(np.sum(np.abs(numerical - exact)) * dx / domain_length)


def fit_convergence_rate(dx_list, error_list):
    """
    Least-squares fit of log(error) = rate * log(dx) + const.
    Returns the slope (observed convergence rate).
    """
    log_dx = np.log(np.array(dx_list))
    log_err = np.log(np.array(error_list))
    A = np.vstack([log_dx, np.ones_like(log_dx)]).T
    result = np.linalg.lstsq(A, log_err, rcond=None)
    return float(result[0][0])


def run_study():
    """
    Main driver for the convergence study.
    """
    with open('/app/convergence/config.json') as f:
        config = json.load(f)

    with open('/app/problems.json') as f:
        all_problems = json.load(f)

    gamma = all_problems['gamma']
    prob_name = config['problem']
    prob = next(p for p in all_problems['problems'] if p['name'] == prob_name)

    xmin, xmax = prob['domain']
    x0 = prob['x0']
    left = prob['left']
    right = prob['right']
    t_end = prob['t_end']
    cfl = prob['cfl']
    domain_length = xmax - xmin

    resolutions = config['resolutions']
    min_rate = config['min_convergence_rate']
    max_err = config['max_finest_error']

    dx_list = []
    error_list = []

    print(f"Convergence study: {prob_name}")
    for ncells in resolutions:
        dx = domain_length / ncells
        x, rho, u, p = solve_euler_1d(
            left, right, gamma, xmin, xmax, x0, ncells, t_end, cfl
        )
        rho_exact = compute_exact_density(x, x0, t_end, left, right, gamma)
        err = l1_norm(rho, rho_exact, dx, domain_length)
        dx_list.append(dx)
        error_list.append(err)
        print(f"  N={ncells:4d}  dx={dx:.6f}  L1={err:.6e}")

    rate = fit_convergence_rate(dx_list, error_list)
    print(f"  Observed rate: {rate:.4f}")

    errors_decrease = all(
        error_list[i] > error_list[i + 1]
        for i in range(len(error_list) - 1)
    )
    rate_ok = rate >= min_rate
    finest_ok = error_list[-1] < max_err
    pass_all = errors_decrease and rate_ok and finest_ok

    results = {
        'problem': prob_name,
        'resolutions': resolutions,
        'dx_values': dx_list,
        'l1_errors': error_list,
        'convergence_rate': round(rate, 4),
        'checks': {
            'errors_decrease_monotonically': errors_decrease,
            'convergence_rate_sufficient': rate_ok,
            'finest_error_below_threshold': finest_ok
        },
        'pass': pass_all
    }

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/convergence.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Write CSV for gnuplot and sqlite import
    with open('/app/results/convergence_data.csv', 'w') as f:
        f.write('ncells,dx,l1_error\n')
        for n, d, e in zip(resolutions, dx_list, error_list):
            f.write(f'{n},{d:.10e},{e:.10e}\n')

    print(f"  Pass: {pass_all}")
    if not pass_all:
        print(f"  Checks: {results['checks']}")


if __name__ == '__main__':
    run_study()
