#!/usr/bin/env python3
"""
Standalone Pitzer model engine for aqueous electrolyte solution thermodynamics.

Implements the Pitzer ion-interaction model for computing mean activity
coefficients, osmotic coefficients, water activity, and osmotic pressure
of binary and mixed electrolyte solutions at 25 degC.

References:
    Kim, H. & Frederick, W.F. Jr. (1988). J. Chem. Eng. Data, 33, 177-184.
    Pitzer, K.S. (1973). J. Phys. Chem., 77, 268-277.
    Mistry, K.H. et al. (2013). Desalination, 318, 34-47.

"""

import json
import math
import re
import sys

# ---------------------------------------------------------------------------
# Load parameter database
# ---------------------------------------------------------------------------

with open("/app/pitzer_params.json") as _f:
    _DB = json.load(_f)

_CONSTANTS = _DB["constants"]
_SALTS = _DB["salts"]

A_PHI = _CONSTANTS["A_phi"]
B_PITZER = _CONSTANTS["b"]
R_GAS = _CONSTANTS["R"]
M_W = _CONSTANTS["M_w"]
T_REF = _CONSTANTS["T_ref"]
V_W = _CONSTANTS["V_w"]

# ---------------------------------------------------------------------------
# Ion formula parser
# ---------------------------------------------------------------------------

_ION_RE = re.compile(r"^([A-Za-z0-9]+)([+-])(\d*)$")


def _parse_charge(ion: str) -> int:
    """Parse charge from ion formula like 'Na+', 'Cl-', 'Ba+2', 'SO4-2'."""
    m = _ION_RE.match(ion)
    if not m:
        raise ValueError(f"Cannot parse ion formula: {ion}")
    sign = 1 if m.group(2) == "+" else -1
    magnitude = int(m.group(3)) if m.group(3) else 1
    return sign * magnitude


# ---------------------------------------------------------------------------
# Ionic strength
# ---------------------------------------------------------------------------


def compute_ionic_strength(composition: dict) -> float:
    """Compute ionic strength I = 0.5 * sum(m_i * z_i^2).

    Args:
        composition: {ion_formula: molality_mol_per_kg}

    Returns:
        Ionic strength in mol/kg.
    """
    total = 0.0
    for ion, molality in composition.items():
        z = _parse_charge(ion)
        total += molality * z * z
    return 0.5 * total


# ---------------------------------------------------------------------------
# Salt matching
# ---------------------------------------------------------------------------


def _find_salt_for_ion(ion: str, composition: dict = None):
    """Find the best salt in the database that contains the given ion.

    If composition is provided, prefer salts whose BOTH ions are present
    in the composition.
    """
    fallback = None
    for name, params in _SALTS.items():
        if params["cation"] == ion or params["anion"] == ion:
            if composition is not None:
                # Check if the partner ion is also in the composition
                partner = params["anion"] if params["cation"] == ion else params["cation"]
                if partner in composition:
                    return params
            if fallback is None:
                fallback = params
    return fallback


def _find_salt_for_pair(cation: str, anion: str):
    """Find the salt matching this specific cation-anion pair."""
    for name, params in _SALTS.items():
        if params["cation"] == cation and params["anion"] == anion:
            return name, params
    return None, None


def _decompose_salts(composition: dict):
    """Decompose an ion mixture into constituent salts.

    Returns a list of (salt_params, actual_molality) tuples.
    """
    cations = {}
    anions = {}
    for ion, mol in composition.items():
        z = _parse_charge(ion)
        if z > 0:
            cations[ion] = mol
        elif z < 0:
            anions[ion] = mol

    salts_found = []
    # Copy so we can modify remaining amounts
    cat_remaining = dict(cations)
    an_remaining = dict(anions)

    # Greedy matching: try all pairs, pick those with parameters
    for cat in list(cations.keys()):
        for an in list(anions.keys()):
            name, params = _find_salt_for_pair(cat, an)
            if params is None:
                continue
            nu_cat = params["nu_cation"]
            nu_an = params["nu_anion"]
            # How much salt can be formed?
            max_from_cat = cat_remaining.get(cat, 0) / nu_cat
            max_from_an = an_remaining.get(an, 0) / nu_an
            salt_mol = min(max_from_cat, max_from_an)
            if salt_mol > 1e-15:
                salts_found.append((params, salt_mol))
                cat_remaining[cat] = cat_remaining.get(cat, 0) - salt_mol * nu_cat
                an_remaining[an] = an_remaining.get(an, 0) - salt_mol * nu_an

    return salts_found


# ---------------------------------------------------------------------------
# Pitzer model helper functions
# ---------------------------------------------------------------------------


def _f1(x: float) -> float:
    """Pitzer f1 function: f1(x) = 2[1-(1+x)exp(-x)] / x^2."""
    if abs(x) < 1e-10:
        return 0.0
    return 2.0 * (1.0 - (1.0 + x) * math.exp(-x)) / (x * x)


def _B_MX(I: float, params: dict) -> float:
    """Compute Pitzer B_MX coefficient."""
    alpha1 = params["alpha1"]
    alpha2 = params["alpha2"]
    x1 = alpha1 * math.sqrt(I)
    x2 = alpha2 * math.sqrt(I)
    return params["Beta0"] + params["Beta1"] * _f1(x1) + params["Beta2"] * _f1(x2)


def _B_phi(I: float, params: dict) -> float:
    """Compute Pitzer B^phi coefficient."""
    alpha1 = params["alpha1"]
    alpha2 = params["alpha2"]
    x1 = alpha1 * math.sqrt(I)
    x2 = alpha2 * math.sqrt(I)
    return (
        params["Beta0"]
        + params["Beta1"] * math.exp(-x1)
        + params["Beta2"] * math.exp(-x2)
    )


def _effective_molality(I: float, params: dict) -> float:
    """Effective molality for the effective Pitzer model.

    m_eff = 2I / (nu+ * z+^2 + nu- * z-^2)
    """
    nu_cat = params["nu_cation"]
    nu_an = params["nu_anion"]
    z_cat = params["z_cation"]
    z_an = params["z_anion"]
    denom = nu_cat * z_cat ** 2 + nu_an * z_an ** 2
    return 2.0 * I / denom


# ---------------------------------------------------------------------------
# Activity coefficient (Pitzer)
# ---------------------------------------------------------------------------


def _pitzer_ln_gamma(I: float, m: float, params: dict) -> float:
    """Compute ln(gamma_+-) via the Pitzer model for a binary electrolyte.

    ln(gamma) = -|z+z-| A^phi (sqrt(I)/(1+b*sqrt(I)) + 2/b ln(1+b*sqrt(I)))
                + m (2 nu+ nu-)/(nu+ + nu-) (B_MX + B^phi)
                + m^2 (3 (nu+ nu-)^1.5)/(nu+ + nu-) C^phi
    """
    z_cat = params["z_cation"]
    z_an = params["z_anion"]
    nu_cat = params["nu_cation"]
    nu_an = params["nu_anion"]
    C_phi = params["Cphi"]
    b = B_PITZER

    sqrt_I = math.sqrt(I)
    bmx = _B_MX(I, params)
    bphi = _B_phi(I, params)

    # Electrostatic (Debye-Huckel) term
    term1 = (
        -abs(z_cat * z_an)
        * A_PHI
        * (sqrt_I / (1.0 + b * sqrt_I) + 2.0 / b * math.log(1.0 + b * sqrt_I))
    )

    # Binary interaction term
    nu_sum = nu_cat + nu_an
    term2 = m * 2.0 * nu_cat * nu_an / nu_sum * (bmx + bphi)

    # Triple interaction term
    term3 = m * m * 3.0 * (nu_cat * nu_an) ** 1.5 / nu_sum * C_phi

    return term1 + term2 + term3


def compute_activity_coefficient(composition: dict, ion: str) -> float:
    """Compute the mean molal activity coefficient for the given ion.

    For single-salt solutions, applies the standard Pitzer model.
    For multi-electrolyte solutions, uses the effective molality approach.

    Args:
        composition: {ion_formula: molality_mol_per_kg}
        ion: Ion formula to get the activity coefficient for.

    Returns:
        Dimensionless mean molal activity coefficient.
    """
    I = compute_ionic_strength(composition)
    if I < 1e-12:
        return 1.0

    # Find a salt containing this ion (prefer salts with both ions present)
    params = _find_salt_for_ion(ion, composition)
    if params is None:
        return 1.0

    m_eff = _effective_molality(I, params)
    ln_gamma = _pitzer_ln_gamma(I, m_eff, params)
    return math.exp(ln_gamma)


# ---------------------------------------------------------------------------
# Osmotic coefficient (Pitzer)
# ---------------------------------------------------------------------------


def _pitzer_osmotic(I: float, m: float, params: dict) -> float:
    """Compute molal osmotic coefficient via the Pitzer model.

    phi = 1 - A^phi |z+z-| sqrt(I)/(1+b sqrt(I))
          + m (2 nu+ nu-)/(nu+ + nu-) B^phi
          + m^2 (2 (nu+ nu-)^1.5)/(nu+ + nu-) C^phi
    """
    z_cat = params["z_cation"]
    z_an = params["z_anion"]
    nu_cat = params["nu_cation"]
    nu_an = params["nu_anion"]
    C_phi = params["Cphi"]
    b = B_PITZER

    sqrt_I = math.sqrt(I)
    bphi = _B_phi(I, params)

    nu_sum = nu_cat + nu_an
    term1 = 1.0 - A_PHI * abs(z_cat * z_an) * sqrt_I / (1.0 + b * sqrt_I)
    term2 = m * 2.0 * nu_cat * nu_an / nu_sum * bphi
    term3 = m * m * 2.0 * (nu_cat * nu_an) ** 1.5 / nu_sum * C_phi

    return term1 + term2 + term3


def compute_osmotic_coefficient(composition: dict) -> float:
    """Compute the molal osmotic coefficient.

    For mixed electrolytes, returns the concentration-weighted average
    of individual salt osmotic coefficients (effective Pitzer model).

    Args:
        composition: {ion_formula: molality_mol_per_kg}

    Returns:
        Dimensionless molal osmotic coefficient.
    """
    I = compute_ionic_strength(composition)
    if I < 1e-12:
        return 1.0

    salts = _decompose_salts(composition)
    if not salts:
        return 1.0

    weighted_sum = 0.0
    total_weight = 0.0

    for params, salt_mol in salts:
        m_eff = _effective_molality(I, params)
        phi = _pitzer_osmotic(I, m_eff, params)
        weighted_sum += salt_mol * phi
        total_weight += salt_mol

    if total_weight < 1e-15:
        return 1.0

    return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# Water activity
# ---------------------------------------------------------------------------


def compute_water_activity(composition: dict) -> float:
    """Compute water activity from osmotic coefficient.

    ln(a_w) = -phi * M_w * sum(m_i)

    Args:
        composition: {ion_formula: molality_mol_per_kg}

    Returns:
        Water activity (dimensionless, between 0 and 1).
    """
    phi = compute_osmotic_coefficient(composition)
    total_molality = sum(composition.values())
    ln_aw = -phi * M_W * total_molality
    return math.exp(ln_aw)


# ---------------------------------------------------------------------------
# Osmotic pressure
# ---------------------------------------------------------------------------


def compute_osmotic_pressure(
    composition: dict, temperature_K: float = 298.15
) -> float:
    """Compute osmotic pressure in bar.

    pi = -RT / V_w * ln(a_w)

    Args:
        composition: {ion_formula: molality_mol_per_kg}
        temperature_K: Temperature in Kelvin (default 298.15).

    Returns:
        Osmotic pressure in bar.
    """
    aw = compute_water_activity(composition)
    # pi in Pa, then convert to bar
    pi_pa = -R_GAS * temperature_K / V_W * math.log(aw)
    return pi_pa / 1.0e5


# ---------------------------------------------------------------------------
# Main: process solutions.json -> results.json
# ---------------------------------------------------------------------------


def main():
    with open("/app/solutions.json") as f:
        data = json.load(f)

    results = {"solutions": []}

    for sol in data["solutions"]:
        comp = sol["composition"]
        I = compute_ionic_strength(comp)

        # Find the first cation to report its activity coefficient
        first_cation = None
        for ion in comp:
            if _parse_charge(ion) > 0:
                first_cation = ion
                break

        gamma = (
            compute_activity_coefficient(comp, first_cation)
            if first_cation
            else 1.0
        )
        phi = compute_osmotic_coefficient(comp)
        aw = compute_water_activity(comp)
        pi = compute_osmotic_pressure(comp)

        results["solutions"].append(
            {
                "id": sol["id"],
                "ionic_strength": round(I, 6),
                "activity_coefficient": round(gamma, 6),
                "osmotic_coefficient": round(phi, 6),
                "water_activity": round(aw, 6),
                "osmotic_pressure_bar": round(pi, 4),
            }
        )

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
