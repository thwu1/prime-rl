#!/usr/bin/env python3
"""Tidal turbine array wake interaction simulator and layout optimizer.

Implements a Jensen top-hat wake model with RSS superposition for
tidal turbine arrays, and optimizes turbine positions using SLSQP.
"""

import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import minimize as scipy_minimize
import yaml
import json
import os


def interpolate_coefficient(speed, speeds, coefficients):
    """Linearly interpolate a performance coefficient from tabulated data.

    Extrapolates using the nearest boundary value for out-of-range speeds.
    """
    f = interp1d(speeds, coefficients, kind='linear', bounds_error=False,
                 fill_value=(coefficients[0], coefficients[-1]))
    return float(f(speed))


def compute_wake_deficit(U_inf, Ct, D, x_downstream, y_offset, k):
    """Compute absolute velocity deficit (m/s) using Jensen top-hat wake model.

    Uses linear wake expansion: wake diameter Dw = D + 2*k*x at distance x.
    Deficit within the top-hat envelope: U_inf * (1 - sqrt(1 - Ct)) * (D/Dw)^2.

    Args:
        U_inf: Freestream or incident velocity (m/s)
        Ct: Thrust coefficient (dimensionless)
        D: Rotor diameter (m)
        x_downstream: Streamwise distance downstream of turbine (m)
        y_offset: Lateral offset from turbine centerline (m)
        k: Wake expansion coefficient (dimensionless)

    Returns:
        Absolute velocity deficit in m/s. Returns 0.0 if the point is
        upstream or outside the wake cone.
    """
    if x_downstream <= 0:
        return 0.0

    # Wake diameter at this downstream distance
    Dw = D + 2.0 * k * x_downstream

    # Check if point is within the top-hat wake envelope
    if abs(y_offset) > Dw / 2.0:
        return 0.0

    # Jensen velocity deficit
    deficit_ratio = (1.0 - np.sqrt(1.0 - Ct)) * (D / Dw) ** 2
    return U_inf * deficit_ratio


def compute_array_power(positions, config):
    """Compute total and per-turbine power for a tidal turbine array.

    Uses Jensen wake model with RSS (root-sum-of-squares) superposition.
    The thrust coefficient for wake deficit computation is evaluated at the
    freestream velocity.

    Args:
        positions: Nx2 numpy array of turbine (x, y) coordinates (m)
        config: Merged configuration dict with keys: channel, turbine,
                wake_model, optimization

    Returns:
        Tuple of (total_power_watts: float, individual_powers: np.ndarray)
    """
    channel = config['channel']
    turbine = config['turbine']
    wake_cfg = config['wake_model']

    U_inf = float(channel['inflow_velocity'])
    rho = float(channel['density'])
    D = float(turbine['diameter'])
    A = np.pi * (D / 2.0) ** 2
    k = float(wake_cfg['expansion_coefficient'])

    speeds = turbine['curves']['speeds']
    cp_vals = turbine['curves']['power_coefficients']
    ct_vals = turbine['curves']['thrust_coefficients']

    # Thrust coefficient at freestream for wake computation
    Ct_ref = interpolate_coefficient(U_inf, speeds, ct_vals)

    n = len(positions)
    positions = np.asarray(positions, dtype=float)

    # Compute effective velocity at each turbine via RSS superposition
    effective_vel = np.zeros(n)
    for i in range(n):
        deficit_sq_sum = 0.0
        for j in range(n):
            if i == j:
                continue
            dx = positions[i, 0] - positions[j, 0]
            dy = positions[i, 1] - positions[j, 1]
            deficit = compute_wake_deficit(U_inf, Ct_ref, D, dx, dy, k)
            deficit_sq_sum += deficit ** 2

        effective_vel[i] = max(0.0, U_inf - np.sqrt(deficit_sq_sum))

    # Compute power for each turbine using Cp at local effective velocity
    individual_powers = np.zeros(n)
    for i in range(n):
        Cp = interpolate_coefficient(effective_vel[i], speeds, cp_vals)
        individual_powers[i] = 0.5 * rho * A * Cp * effective_vel[i] ** 3

    return float(np.sum(individual_powers)), individual_powers


def optimize_layout(initial_positions, config):
    """Optimize turbine positions to maximize total power extraction.

    Uses multi-start SLSQP to escape local minima caused by the
    discontinuous top-hat wake model. Tries the original layout,
    random perturbations, and explicitly staggered configurations.

    Args:
        initial_positions: Nx2 numpy array of starting (x, y) positions
        config: Merged configuration dict

    Returns:
        Nx2 numpy array of optimized positions
    """
    opt = config['optimization']
    fb = opt['farm_bounds']
    min_dist = float(opt['min_distance'])
    D = float(config['turbine']['diameter'])
    r = D / 2.0

    n = len(initial_positions)
    x0 = np.asarray(initial_positions, dtype=float).flatten()

    # Objective: minimize negative power (= maximize power)
    def objective(x):
        pos = x.reshape(-1, 2)
        total_power, _ = compute_array_power(pos, config)
        return -total_power

    # Box bounds: turbine center must keep rotor disc within farm area
    x_lo = fb['x_min'] + r
    x_hi = fb['x_max'] - r
    y_lo = fb['y_min'] + r
    y_hi = fb['y_max'] - r
    bounds = []
    for _ in range(n):
        bounds.append((x_lo, x_hi))
        bounds.append((y_lo, y_hi))

    # Pairwise minimum distance constraints: d_ij^2 - min_dist^2 >= 0
    constraints = []
    for i in range(n):
        for j in range(i + 1, n):
            def dist_con(x, ii=i, jj=j):
                dx = x[2 * ii] - x[2 * jj]
                dy = x[2 * ii + 1] - x[2 * jj + 1]
                return dx * dx + dy * dy - min_dist * min_dist
            constraints.append({'type': 'ineq', 'fun': dist_con})

    maxiter = int(opt.get('max_iterations', 500))
    ftol = float(opt.get('ftol', 1e-10))

    best_x = x0.copy()
    best_power = -objective(x0)

    def run_slsqp(start):
        try:
            result = scipy_minimize(
                objective, start, method='SLSQP',
                bounds=bounds, constraints=constraints,
                options={'maxiter': maxiter, 'ftol': ftol}
            )
            return result.x, -result.fun
        except Exception:
            return start, -objective(start)

    # Collect diverse starting points
    starts = [x0.copy()]

    # Random perturbations with large enough scale to cross wake boundaries
    rng = np.random.default_rng(42)
    for _ in range(20):
        perturbed = x0 + rng.normal(0, 30, size=len(x0))
        for i in range(len(perturbed)):
            perturbed[i] = np.clip(perturbed[i], bounds[i][0], bounds[i][1])
        starts.append(perturbed)

    # Construct staggered two-column layouts where downstream turbines
    # fall outside upstream wake cones, eliminating wake losses
    if n == 8:
        y_range = y_hi - y_lo
        # Max spacing so both staggered columns fit: s = 2*(y_range)/7
        # but s must also be >= min_dist
        s = 2.0 * y_range / 7.0
        if s >= min_dist:
            ys1 = [y_lo + i * s for i in range(4)]
            ys2 = [y_lo + s / 2.0 + i * s for i in range(4)]
            # Try several column x-separations
            for x_frac1, x_frac2 in [(0.25, 0.75), (0.2, 0.8), (0.3, 0.7)]:
                cx1 = x_lo + (x_hi - x_lo) * x_frac1
                cx2 = x_lo + (x_hi - x_lo) * x_frac2
                stag = []
                for y in ys1:
                    stag.extend([cx1, y])
                for y in ys2:
                    stag.extend([cx2, y])
                starts.append(np.array(stag))

    # Run SLSQP from each start and keep the best
    for start in starts:
        sx, sp = run_slsqp(start)
        if sp > best_power:
            best_power = sp
            best_x = sx.copy()

    return best_x.reshape(-1, 2)


def main():
    """Load config, run optimization, write results."""
    # Load and merge configuration
    with open('/app/config.yaml') as f:
        config = yaml.safe_load(f)
    turbine_path = os.path.join('/app', config['turbine_file'])
    with open(turbine_path) as f:
        config['turbine'] = yaml.safe_load(f)

    # Create initial 4x2 regular grid with 2D margin from farm edges
    fb = config['optimization']['farm_bounds']
    D = float(config['turbine']['diameter'])
    xs = np.linspace(fb['x_min'] + 2 * D, fb['x_max'] - 2 * D, 4)
    ys = np.linspace(fb['y_min'] + 2 * D, fb['y_max'] - 2 * D, 2)
    initial = np.array([[x, y] for x in xs for y in ys])

    # Compute initial power
    init_power, _ = compute_array_power(initial, config)
    print(f"Initial layout power: {init_power / 1e6:.4f} MW")

    # Optimize layout
    optimized = optimize_layout(initial, config)
    opt_power, _ = compute_array_power(optimized, config)

    improvement = (opt_power - init_power) / init_power * 100.0
    print(f"Optimized layout power: {opt_power / 1e6:.4f} MW")
    print(f"Improvement: {improvement:.1f}%")

    # Write results JSON
    results = {
        'initial_power_watts': init_power,
        'optimized_power_watts': opt_power,
        'improvement_percent': improvement,
        'num_turbines': int(len(optimized)),
        'initial_positions': initial.tolist(),
        'optimized_positions': optimized.tolist(),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
