#!/usr/bin/env python3

"""
Rosenthal quasi-steady-state thermal model for LPBF multi-track melt pool prediction.

Implements the point source solution on a semi-infinite body with adiabatic surface:
    T(xi,y,z) = T0 + Q/(2*pi*k*R) * exp(-V*(xi+R)/(2*alpha))

Computes single-track melt pool geometry, multi-track pre-heat via Green's function
integration, effective melt pool depth with pre-heat, solidification cooling rate,
and primary dendrite arm spacing.
"""

import json
import numpy as np
from scipy.optimize import brentq, minimize_scalar
from scipy.integrate import quad


def load_config():
    with open('/app/config.json') as f:
        return json.load(f)


def rosenthal(xi, y, z, Q, k, alpha, V, T0):
    """Rosenthal quasi-steady-state solution for semi-infinite body with adiabatic surface."""
    R = np.sqrt(xi**2 + y**2 + z**2)
    if R < 1e-15:
        return float('inf')
    return T0 + Q / (2.0 * np.pi * k * R) * np.exp(-V * (xi + R) / (2.0 * alpha))


def max_temp_at_yz(y, z, Q, k, alpha, V, T0):
    """
    Find the maximum temperature at coordinates (y, z) by optimizing over xi.
    The maximum occurs at some xi < 0 (behind the heat source).
    """
    def neg_T(xi):
        R = np.sqrt(xi**2 + y**2 + z**2)
        if R < 1e-15:
            return -1e15
        return -(T0 + Q / (2.0 * np.pi * k * R) * np.exp(-V * (xi + R) / (2.0 * alpha)))

    r0 = np.sqrt(y**2 + z**2)
    # Search bracket: xi is negative, extends to several times the offset distance
    xi_lo = -max(20.0 * r0, 2e-3)
    xi_hi = -1e-10
    res = minimize_scalar(neg_T, bounds=(xi_lo, xi_hi), method='bounded',
                          options={'xatol': 1e-12})
    return -res.fun


def find_melt_pool_half_width(Q, k, alpha, V, T0, T_liq):
    """
    Find the maximum transverse extent of the liquidus isotherm at the surface (z=0).
    This is the largest y such that the peak temperature at (y, 0) >= T_liq.
    """
    def obj(y_val):
        return max_temp_at_yz(y_val, 0.0, Q, k, alpha, V, T0) - T_liq

    y_lo = 1e-8
    y_hi = 5e-4
    # Ensure upper bound is beyond the melt pool
    while obj(y_hi) > 0:
        y_hi *= 2
        if y_hi > 0.05:
            raise ValueError("Cannot bracket melt pool half-width")
    return brentq(obj, y_lo, y_hi, rtol=1e-8)


def find_melt_pool_depth(Q, k, alpha, V, T0, T_liq):
    """
    Find the maximum depth of the liquidus isotherm at y=0.
    """
    def obj(z_val):
        return max_temp_at_yz(0.0, z_val, Q, k, alpha, V, T0) - T_liq

    z_lo = 1e-8
    z_hi = 5e-4
    while obj(z_hi) > 0:
        z_hi *= 2
        if z_hi > 0.05:
            raise ValueError("Cannot bracket melt pool depth")
    return brentq(obj, z_lo, z_hi, rtol=1e-8)


def compute_trailing_length(Q, k, T0, T_liq):
    """
    Analytical trailing melt pool length on surface centerline (y=0, z=0).

    On this line, xi < 0 gives R = |xi| = -xi, so xi + R = 0
    and exp(0) = 1, yielding T = T0 + Q / (2*pi*k*|xi|).
    Solving for |xi| at T = T_liq gives the trailing length.
    """
    return Q / (2.0 * np.pi * k * (T_liq - T0))


def compute_preheat_from_tracks(x_eval, y_eval, t_eval, completed_tracks,
                                 Q, V, alpha, rho, Cp, track_length):
    """
    Compute the temperature rise at (x_eval, y_eval, z=0) at time t_eval
    from all completed tracks using the 3D instantaneous point source Green's
    function integrated along each track path.

    For a semi-infinite body with adiabatic surface, the factor of 2 (method
    of images) is applied.

    Each completed track is a tuple: (start_x, end_x, y_track, t_start)
    """
    T_rise = 0.0

    for (sx, ex, ty, ts) in completed_tracks:
        direction = 1.0 if ex > sx else -1.0
        t_track_end = ts + track_length / V

        # Skip if track hasn't finished yet
        if t_eval <= t_track_end + 1e-15:
            continue

        def integrand(s, _sx=sx, _dir=direction, _ty=ty, _ts=ts):
            # Position of source at distance s along track
            x_s = _sx + _dir * s
            # Time elapsed since source was at this position
            tau = t_eval - (_ts + s / V)
            if tau < 1e-15:
                return 0.0

            dx = x_eval - x_s
            dy = y_eval - _ty
            r2 = dx**2 + dy**2

            denom = (4.0 * np.pi * alpha * tau) ** 1.5
            if denom < 1e-300:
                return 0.0

            val = np.exp(-r2 / (4.0 * alpha * tau)) / denom
            return val if np.isfinite(val) else 0.0

        result, _ = quad(integrand, 0, track_length, limit=200,
                         epsrel=1e-6, epsabs=1e-30)
        # Factor 2 for image source, Q/V is energy per unit length
        T_rise += (2.0 * Q / (V * rho * Cp)) * result

    return T_rise


def compute_cooling_rate(Q, k, V, T_sol, T0):
    """
    Analytical cooling rate at the solidus point on the trailing surface centerline.

    On the surface centerline (y=0, z=0, xi < 0):
        T = T0 + Q / (2*pi*k*|xi|)
        dT/dxi = Q / (2*pi*k*xi^2)    (positive, since T increases toward source)
        |dT/dt| = V * dT/dxi = V * Q / (2*pi*k * xi_sol^2)

    Where xi_sol = -Q / (2*pi*k*(T_sol - T0)), so:
        |dT/dt| = V * 2*pi*k * (T_sol - T0)^2 / Q
    """
    return V * 2.0 * np.pi * k * (T_sol - T0) ** 2 / Q


def main():
    cfg = load_config()

    # Material properties
    k = cfg['material']['thermal_conductivity_W_per_mK']
    rho = cfg['material']['density_kg_per_m3']
    Cp = cfg['material']['specific_heat_J_per_kgK']
    T_sol = cfg['material']['solidus_K']
    T_liq = cfg['material']['liquidus_K']
    T0 = cfg['material']['ambient_K']
    eta = cfg['material']['absorptivity']
    alpha = k / (rho * Cp)

    # Laser parameters
    P = cfg['laser']['power_W']
    V = cfg['laser']['scan_speed_m_per_s']
    Q = eta * P

    # Pad parameters
    L = cfg['pad']['track_length_m']
    h = cfg['pad']['hatch_spacing_m']
    n_tracks = cfg['pad']['num_tracks']
    t_turn = cfg['pad']['turnaround_time_s']

    # Solidification parameters
    A_pdas = cfg['solidification']['pdas_coefficient_um']
    n_pdas = cfg['solidification']['pdas_exponent']

    results = {}

    # ---- Single-track melt pool dimensions ----
    print("Computing single-track melt pool dimensions...")
    hw = find_melt_pool_half_width(Q, k, alpha, V, T0, T_liq)
    dp = find_melt_pool_depth(Q, k, alpha, V, T0, T_liq)
    tl = compute_trailing_length(Q, k, T0, T_liq)

    results['single_track_half_width_um'] = round(hw * 1e6, 2)
    results['single_track_depth_um'] = round(dp * 1e6, 2)
    results['single_track_length_um'] = round(tl * 1e6, 2)
    print(f"  Half-width: {results['single_track_half_width_um']} um")
    print(f"  Depth: {results['single_track_depth_um']} um")
    print(f"  Length: {results['single_track_length_um']} um")

    # ---- Build track timeline ----
    t_scan = L / V
    tracks = []
    t = 0.0
    for i in range(n_tracks):
        y_track = i * h
        if i % 2 == 0:
            start_x, end_x = 0.0, L
        else:
            start_x, end_x = L, 0.0
        tracks.append((start_x, end_x, y_track, t))
        t += t_scan + t_turn

    # ---- Pre-heat temperatures ----
    print("\nComputing pre-heat temperatures...")
    preheat = {}
    for tn in cfg['queries']['preheat_tracks']:
        idx = tn - 1
        sx = tracks[idx][0]
        yt = tracks[idx][2]
        ts = tracks[idx][3]
        completed = tracks[:idx]
        rise = compute_preheat_from_tracks(sx, yt, ts, completed,
                                            Q, V, alpha, rho, Cp, L)
        preheat[str(tn)] = round(T0 + rise, 2)
        print(f"  Track {tn}: T_preheat = {preheat[str(tn)]} K (rise = {rise:.2f} K)")
    results['preheat_K'] = preheat

    # ---- Melt pool depth with pre-heat ----
    print("\nComputing melt pool depths with pre-heat...")
    depth_pre = {}
    for tn in cfg['queries']['depth_tracks']:
        if tn == 1:
            T_pre = T0
        else:
            idx = tn - 1
            sx = tracks[idx][0]
            yt = tracks[idx][2]
            ts = tracks[idx][3]
            completed = tracks[:idx]
            rise = compute_preheat_from_tracks(sx, yt, ts, completed,
                                                Q, V, alpha, rho, Cp, L)
            T_pre = T0 + rise
        d_eff = find_melt_pool_depth(Q, k, alpha, V, T_pre, T_liq)
        depth_pre[str(tn)] = round(d_eff * 1e6, 2)
        print(f"  Track {tn}: depth = {depth_pre[str(tn)]} um (T_pre = {T_pre:.2f} K)")
    results['depth_with_preheat_um'] = depth_pre

    # ---- Cooling rate ----
    print("\nComputing solidification cooling rate...")
    cooling_rate = compute_cooling_rate(Q, k, V, T_sol, T0)
    results['cooling_rate_at_surface_K_per_s'] = round(cooling_rate)
    print(f"  Cooling rate: {results['cooling_rate_at_surface_K_per_s']} K/s")

    # ---- PDAS ----
    print("\nComputing primary dendrite arm spacing...")
    pdas = A_pdas * cooling_rate ** (-n_pdas)
    results['pdas_um'] = round(pdas, 2)
    print(f"  PDAS: {results['pdas_um']} um")

    # ---- Write results ----
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
