"""
QCM-D Multi-Harmonic Viscoelastic Film Analysis Engine

Implements the acoustic impedance transfer matrix method for computing
complex frequency shifts of a quartz crystal microbalance loaded with
multi-layer viscoelastic films, and a bounded nonlinear least-squares
inverse solver for extracting film properties from measured data.

Physics:
  - Power law rheological model: |G*|rho_n = |G*|rho_3 * (n/3)^(phi/90)
  - Complex modulus: G*rho = |G*|rho * exp(i*phi)
  - Acoustic impedance: Z = sqrt(G*rho)
  - Transfer matrix propagation through multi-layer stacks
  - Small load approximation: delfstar = f1 * i * ZL / (pi * Zq)
"""


import numpy as np
from scipy.optimize import least_squares
from copy import deepcopy

ZQ_DEFAULT = 8.84e6   # Shear acoustic impedance of AT-cut quartz (kg/m^2/s)
F1_DEFAULT = 5e6      # Fundamental resonant frequency (Hz)


def _grho_n(n, grho3, phi):
    """Power law: |G*|rho at harmonic n from value at n=3."""
    if grho3 == 0:
        return 0.0
    return grho3 * (n / 3.0) ** (phi / 90.0)


def _gstar_rho_n(n, grho3, phi):
    """Complex G*rho at harmonic n."""
    mag = _grho_n(n, grho3, phi)
    return mag * np.exp(1j * np.radians(phi))


def _zstar(n, grho3, phi):
    """Complex acoustic impedance Z = sqrt(G*rho) at harmonic n."""
    gstar = _gstar_rho_n(n, grho3, phi)
    return np.sqrt(gstar)


def _calc_D(n, drho, grho3, phi, f1):
    """Complex phase parameter D = 2*pi*n*f1*drho / Z."""
    Z = _zstar(n, grho3, phi)
    if abs(Z) == 0:
        return 0.0 + 0.0j
    return 2.0 * np.pi * n * f1 * drho / Z


def _calc_ZL(n, layers, f1):
    """
    Complex load impedance via transfer matrix method.

    layers: dict mapping layer number (1 = closest to crystal, ascending
            outward) to {'grho3': float, 'phi': float, 'drho': float}.
    """
    layer_nums = sorted(layers.keys())
    layer_min = min(layer_nums)
    layer_max = max(layer_nums)
    N = len(layers)

    # --- Terminal impedance from outermost layer ---
    p_max = layers[layer_max]
    grho3_max = p_max['grho3']
    phi_max = p_max['phi']
    drho_max = p_max['drho']

    if drho_max == float('inf') or np.isinf(drho_max):
        if grho3_max == 0:
            Zf = 0.0 + 0.0j        # vacuum / air
        else:
            Zf = _zstar(n, grho3_max, phi_max)  # semi-infinite bulk
    else:
        Z_max = _zstar(n, grho3_max, phi_max)
        D_max = _calc_D(n, drho_max, grho3_max, phi_max, f1)
        Zf = 1j * Z_max * np.tan(D_max)

    # Single layer: we are done
    if N == 1:
        return Zf

    # --- Compute impedance and phase for all inner layers ---
    Z = {}
    Dvals = {}
    for i in range(layer_min, layer_max):
        p = layers[i]
        Z[i] = _zstar(n, p['grho3'], p['phi'])
        Dvals[i] = _calc_D(n, p['drho'], p['grho3'], p['phi'], f1)

    # --- Terminal matrix (references impedance of layer adjacent to bulk) ---
    Z_ref = Z[layer_max - 1]
    Tn = np.array([
        [1.0 + Zf / Z_ref, 0.0],
        [0.0, 1.0 - Zf / Z_ref],
    ], dtype=complex)

    # Phase propagation through layer_max - 1
    D_val = Dvals[layer_max - 1]
    L = np.array([
        [np.exp(1j * D_val), 0.0],
        [0.0, np.exp(-1j * D_val)],
    ], dtype=complex)

    uvec = L @ Tn @ np.array([[1.0], [1.0]], dtype=complex)

    # --- Cascade inward through remaining layers ---
    for i in range(layer_max - 2, layer_min - 1, -1):
        S = np.array([
            [1.0 + Z[i + 1] / Z[i], 1.0 - Z[i + 1] / Z[i]],
            [1.0 - Z[i + 1] / Z[i], 1.0 + Z[i + 1] / Z[i]],
        ], dtype=complex)

        D_val = Dvals[i]
        L = np.array([
            [np.exp(1j * D_val), 0.0],
            [0.0, np.exp(-1j * D_val)],
        ], dtype=complex)

        uvec = L @ S @ uvec

    # --- Load impedance at the crystal surface ---
    rstar = uvec[1, 0] / uvec[0, 0]
    ZL = Z[layer_min] * (1.0 - rstar) / (1.0 + rstar)
    return ZL


def forward_calc(layers, harmonics, f1=F1_DEFAULT, Zq=ZQ_DEFAULT):
    """
    Compute complex frequency shifts for a stack of viscoelastic layers.

    Parameters
    ----------
    layers : dict
        Maps layer number (int, 1 = closest to crystal) to property dict
        with keys 'grho3', 'phi', 'drho'.
    harmonics : list of int
        Odd harmonic numbers.
    f1 : float
        Fundamental resonant frequency (Hz).
    Zq : float
        Acoustic impedance of quartz (kg/m^2/s).

    Returns
    -------
    dict : {n: {'delf': float, 'delg': float}} for each harmonic n.
    """
    results = {}
    for n in harmonics:
        ZL = _calc_ZL(n, layers, f1)
        delfstar = f1 * 1j * ZL / (np.pi * Zq)
        results[n] = {
            'delf': float(delfstar.real),
            'delg': float(delfstar.imag),
        }
    return results


def inverse_calc(measurements, harmonics_f, harmonics_g, unknowns,
                 layers_init, f1=F1_DEFAULT, Zq=ZQ_DEFAULT, bounds=None):
    """
    Solve for unknown layer properties from measured shifts.

    Parameters
    ----------
    measurements : dict
        {n: {'delf': float, 'delg': float}} measured data.
    harmonics_f : list of int
        Harmonics to fit against frequency shift.
    harmonics_g : list of int
        Harmonics to fit against half-bandwidth shift.
    unknowns : list of str
        Properties to solve for, e.g. ['grho3_1', 'phi_1', 'drho_1'].
    layers_init : dict
        Initial guess and fixed layer properties.
    f1 : float
        Fundamental resonant frequency (Hz).
    Zq : float
        Acoustic impedance of quartz (kg/m^2/s).
    bounds : dict or None
        Maps unknown names to (lower, upper) tuples.

    Returns
    -------
    dict : {unknown_name: solved_value} for each unknown.
    """
    default_bounds = {
        'grho3': (1e4, 1e13),
        'phi': (0.0, 90.0),
        'drho': (0.0, 3e-2),
    }

    if bounds is None:
        bounds = {}

    # Parse unknowns into (property, layer, full_name) tuples
    parsed = []
    for u in unknowns:
        parts = u.split('_')
        prop = parts[0]
        layer = int(parts[1]) if len(parts) > 1 else 1
        parsed.append((prop, layer, u))

    # All harmonics we need for the forward model
    all_harmonics = sorted(set(harmonics_f + harmonics_g))

    # Build initial guess and bound arrays
    x0 = []
    lb = []
    ub = []
    for prop, layer, name in parsed:
        x0.append(layers_init[layer][prop])
        if name in bounds:
            lb.append(bounds[name][0])
            ub.append(bounds[name][1])
        elif prop in default_bounds:
            lb.append(default_bounds[prop][0])
            ub.append(default_bounds[prop][1])
        else:
            lb.append(-np.inf)
            ub.append(np.inf)

    x0 = np.array(x0, dtype=float)

    def residual(x):
        layers = deepcopy(layers_init)
        for i, (prop, layer, _) in enumerate(parsed):
            layers[layer][prop] = float(x[i])

        computed = forward_calc(layers, all_harmonics, f1, Zq)

        resid = []
        for n_h in harmonics_f:
            resid.append(computed[n_h]['delf'] - measurements[n_h]['delf'])
        for n_h in harmonics_g:
            resid.append(computed[n_h]['delg'] - measurements[n_h]['delg'])
        return resid

    sol = least_squares(
        residual, x0,
        bounds=(lb, ub),
        x_scale='jac',
        ftol=1e-12,
        xtol=1e-12,
        max_nfev=10000,
    )

    result = {}
    for i, (_, _, name) in enumerate(parsed):
        result[name] = float(sol.x[i])
    return result
