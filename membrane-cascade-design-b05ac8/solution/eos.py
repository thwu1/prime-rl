
"""Peng-Robinson Equation of State implementation for pure and mixed gases."""

import json
import math
import numpy as np

R = 8.314462  # J/(mol*K)


def load_gas_properties():
    with open("/app/data/gas_properties.json") as f:
        return json.load(f)


def _pr_pure_params(gas_data, T):
    """Compute PR-EOS a(T) and b for a pure component."""
    Tc = gas_data["Tc_K"]
    Pc = gas_data["Pc_bar"] * 1e5  # Pa
    omega = gas_data["omega"]

    a_c = 0.45724 * R ** 2 * Tc ** 2 / Pc
    b = 0.07780 * R * Tc / Pc

    kappa = 0.37464 + 1.54226 * omega - 0.26992 * omega ** 2
    Tr = T / Tc
    alpha = (1 + kappa * (1 - math.sqrt(Tr))) ** 2
    a = a_c * alpha

    return a, b


def _solve_pr_cubic(A, B):
    """Solve the PR-EOS cubic for Z.

    Z^3 - (1-B)*Z^2 + (A - 3B^2 - 2B)*Z - (AB - B^2 - B^3) = 0

    Returns all real roots sorted ascending.
    """
    coeffs = [
        1.0,
        -(1.0 - B),
        A - 3.0 * B ** 2 - 2.0 * B,
        -(A * B - B ** 2 - B ** 3),
    ]
    roots = np.roots(coeffs)
    real_roots = sorted([r.real for r in roots if abs(r.imag) < 1e-8 and r.real > 0])
    return real_roots


def pr_fugacity_pure(gas_name, T, P_bar, gas_props=None):
    """Compute Z, phi, fugacity for a pure gas using PR-EOS.

    Parameters
    ----------
    gas_name : str
    T : float, temperature in K
    P_bar : float, pressure in bar
    gas_props : dict or None

    Returns
    -------
    dict with keys: gas, T_K, P_bar, Z, phi, fugacity_bar
    """
    if gas_props is None:
        gas_props = load_gas_properties()

    P = P_bar * 1e5  # Pa
    gas_data = gas_props["gases"][gas_name]
    a, b = _pr_pure_params(gas_data, T)

    A = a * P / (R * T) ** 2
    B = b * P / (R * T)

    roots = _solve_pr_cubic(A, B)

    # Select vapor root (largest root > B)
    valid = [z for z in roots if z > B]
    if not valid:
        raise ValueError(
            f"No valid vapor root for {gas_name} at T={T} K, P={P_bar} bar"
        )
    Z = max(valid)

    # Fugacity coefficient
    sqrt2 = math.sqrt(2)
    arg_num = Z + (1 + sqrt2) * B
    arg_den = Z + (1 - sqrt2) * B
    if arg_den <= 0 or arg_num <= 0:
        raise ValueError("Invalid argument for log in fugacity calculation")

    ln_phi = (
        (Z - 1)
        - math.log(Z - B)
        - A / (2 * sqrt2 * B) * math.log(arg_num / arg_den)
    )
    phi = math.exp(ln_phi)

    return {
        "gas": gas_name,
        "T_K": T,
        "P_bar": P_bar,
        "Z": round(Z, 8),
        "phi": round(phi, 8),
        "fugacity_bar": round(P_bar * phi, 8),
    }


def pr_fugacity_mixture(components, mole_fracs, T, P_bar, gas_props=None):
    """Compute mixture Z and component fugacity coefficients using PR-EOS.

    Uses van der Waals one-fluid mixing rules:
        a_mix = sum_i sum_j x_i x_j a_ij
        b_mix = sum_i x_i b_i
        a_ij = (1 - k_ij) * sqrt(a_i * a_j)

    Parameters
    ----------
    components : list of str
    mole_fracs : list of float
    T : float, K
    P_bar : float, bar
    gas_props : dict or None

    Returns
    -------
    dict with keys: gases, composition, T_K, P_bar, Z_mix, phi, fugacity_bar
    """
    if gas_props is None:
        gas_props = load_gas_properties()

    P = P_bar * 1e5  # Pa
    n = len(components)
    x = list(mole_fracs)

    # Pure component parameters
    a_pure = []
    b_pure = []
    for comp in components:
        ai, bi = _pr_pure_params(gas_props["gases"][comp], T)
        a_pure.append(ai)
        b_pure.append(bi)

    # Binary interaction parameters
    kij_data = gas_props.get("binary_interaction_parameters", {})
    kij = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                key1 = f"{components[i]}/{components[j]}"
                key2 = f"{components[j]}/{components[i]}"
                if key1 in kij_data:
                    kij[i][j] = kij_data[key1]
                elif key2 in kij_data:
                    kij[i][j] = kij_data[key2]

    # Cross parameters
    a_ij = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            a_ij[i][j] = (1 - kij[i][j]) * math.sqrt(a_pure[i] * a_pure[j])

    # Mixing rules
    a_mix = sum(x[i] * x[j] * a_ij[i][j] for i in range(n) for j in range(n))
    b_mix = sum(x[i] * b_pure[i] for i in range(n))

    A_mix = a_mix * P / (R * T) ** 2
    B_mix = b_mix * P / (R * T)

    roots = _solve_pr_cubic(A_mix, B_mix)
    valid = [z for z in roots if z > B_mix]
    if not valid:
        raise ValueError("No valid vapor root for mixture")
    Z_mix = max(valid)

    # Component fugacity coefficients
    sqrt2 = math.sqrt(2)
    log_arg = (Z_mix + (1 + sqrt2) * B_mix) / (Z_mix + (1 - sqrt2) * B_mix)

    phi = {}
    fug = {}
    for i in range(n):
        sum_xa = sum(x[j] * a_ij[i][j] for j in range(n))
        bi_over_bmix = b_pure[i] / b_mix

        ln_phi_i = (
            bi_over_bmix * (Z_mix - 1)
            - math.log(Z_mix - B_mix)
            - A_mix
            / (2 * sqrt2 * B_mix)
            * (2 * sum_xa / a_mix - bi_over_bmix)
            * math.log(log_arg)
        )
        phi_i = math.exp(ln_phi_i)
        phi[components[i]] = round(phi_i, 8)
        fug[components[i]] = round(P_bar * x[i] * phi_i, 8)

    return {
        "gases": components,
        "composition": {components[i]: round(x[i], 8) for i in range(n)},
        "T_K": T,
        "P_bar": P_bar,
        "Z_mix": round(Z_mix, 8),
        "phi": phi,
        "fugacity_bar": fug,
    }
