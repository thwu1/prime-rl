#!/usr/bin/env python3
"""
Electrolyte solution engine: computes thermodynamic properties of aqueous
electrolyte solutions using ion-interaction parameters from a SQLite database.

"""

import json
import math
import re
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Load parameters from SQLite database
# ---------------------------------------------------------------------------

_DB_PATH = "/app/parameters.db"


def _load_from_db():
    conn = sqlite3.connect(_DB_PATH)
    constants = {}
    for row in conn.execute("SELECT key, value FROM constants"):
        constants[row[0]] = row[1]
    salts = {}
    cursor = conn.execute("SELECT * FROM salt_parameters")
    columns = [desc[0] for desc in cursor.description]
    for row in cursor:
        d = dict(zip(columns, row))
        salts[d["salt_name"]] = d
    conn.close()
    return constants, salts


try:
    _CONSTANTS, _SALTS = _load_from_db()
except Exception:
    _CONSTANTS, _SALTS = {}, {}

A_PHI = _CONSTANTS.get("A_phi", 0.3915)
B_PARAM = _CONSTANTS.get("b", 1.2)
R_GAS = _CONSTANTS.get("R", 8.314)
M_W = _CONSTANTS.get("M_w", 0.018015)
T_REF = _CONSTANTS.get("T_ref", 298.15)
V_W = _CONSTANTS.get("V_w", 1.8015e-05)

# ---------------------------------------------------------------------------
# Ion formula parser
# ---------------------------------------------------------------------------

_ION_RE = re.compile(r"^([A-Za-z0-9]+)([+-])(\d*)$")


def _parse_charge(ion: str) -> int:
    m = _ION_RE.match(ion)
    if not m:
        raise ValueError(f"Cannot parse ion formula: {ion}")
    sign = 1 if m.group(2) == "+" else -1
    magnitude = int(m.group(3)) if m.group(3) else 1
    return sign * magnitude


# ---------------------------------------------------------------------------
# Ionic strength with charge-balance validation
# ---------------------------------------------------------------------------


def compute_ionic_strength(composition: dict) -> float:
    """Compute ionic strength I = 0.5 * sum(m_i * z_i^2).

    Raises ValueError if charge imbalance exceeds 1% of total ion equivalents.
    """
    if not composition:
        return 0.0

    total_equivalents = 0.0
    charge_sum = 0.0
    ionic_strength = 0.0

    for ion, molality in composition.items():
        z = _parse_charge(ion)
        total_equivalents += abs(z * molality)
        charge_sum += z * molality
        ionic_strength += molality * z * z

    if total_equivalents > 0:
        imbalance_fraction = abs(charge_sum) / total_equivalents
        if imbalance_fraction > 0.01:
            raise ValueError(
                f"Charge imbalance {imbalance_fraction:.4f} exceeds 1% threshold"
            )

    return 0.5 * ionic_strength


# ---------------------------------------------------------------------------
# Salt matching
# ---------------------------------------------------------------------------


def _find_salt_for_ion(ion, composition=None):
    fallback = None
    for name, params in _SALTS.items():
        if params["cation"] == ion or params["anion"] == ion:
            if composition is not None:
                partner = (
                    params["anion"] if params["cation"] == ion else params["cation"]
                )
                if partner in composition:
                    return params
            if fallback is None:
                fallback = params
    return fallback


def _find_salt_for_pair(cation, anion):
    for name, params in _SALTS.items():
        if params["cation"] == cation and params["anion"] == anion:
            return name, params
    return None, None


def _decompose_salts(composition):
    cations = {}
    anions = {}
    for ion, mol in composition.items():
        z = _parse_charge(ion)
        if z > 0:
            cations[ion] = mol
        elif z < 0:
            anions[ion] = mol

    salts_found = []
    cat_remaining = dict(cations)
    an_remaining = dict(anions)

    for cat in list(cations.keys()):
        for an in list(anions.keys()):
            name, params = _find_salt_for_pair(cat, an)
            if params is None:
                continue
            nu_cat = params["nu_cation"]
            nu_an = params["nu_anion"]
            max_from_cat = cat_remaining.get(cat, 0) / nu_cat
            max_from_an = an_remaining.get(an, 0) / nu_an
            salt_mol = min(max_from_cat, max_from_an)
            if salt_mol > 1e-15:
                salts_found.append((params, salt_mol))
                cat_remaining[cat] -= salt_mol * nu_cat
                an_remaining[an] -= salt_mol * nu_an

    return salts_found


# ---------------------------------------------------------------------------
# Ion-interaction model functions
# ---------------------------------------------------------------------------


def _g_func(x):
    """g(x) = 2[1-(1+x)exp(-x)] / x^2."""
    if abs(x) < 1e-10:
        return 0.0
    return 2.0 * (1.0 - (1.0 + x) * math.exp(-x)) / (x * x)


def _B_MX(I, params):
    alpha1 = params["alpha1"]
    alpha2 = params["alpha2"]
    x1 = alpha1 * math.sqrt(I)
    x2 = alpha2 * math.sqrt(I)
    return params["Beta0"] + params["Beta1"] * _g_func(x1) + params["Beta2"] * _g_func(x2)


def _B_phi(I, params):
    alpha1 = params["alpha1"]
    alpha2 = params["alpha2"]
    x1 = alpha1 * math.sqrt(I)
    x2 = alpha2 * math.sqrt(I)
    return (
        params["Beta0"]
        + params["Beta1"] * math.exp(-x1)
        + params["Beta2"] * math.exp(-x2)
    )


def _effective_molality(I, params):
    nu_cat = params["nu_cation"]
    nu_an = params["nu_anion"]
    z_cat = params["z_cation"]
    z_an = params["z_anion"]
    denom = nu_cat * z_cat**2 + nu_an * z_an**2
    return 2.0 * I / denom


# ---------------------------------------------------------------------------
# Activity coefficient
# ---------------------------------------------------------------------------


def _ln_gamma(I, m, params):
    z_cat = params["z_cation"]
    z_an = params["z_anion"]
    nu_cat = params["nu_cation"]
    nu_an = params["nu_anion"]
    C_phi = params["Cphi"]
    b = B_PARAM

    sqrt_I = math.sqrt(I)
    bmx = _B_MX(I, params)
    bphi = _B_phi(I, params)

    term1 = -abs(z_cat * z_an) * A_PHI * (
        sqrt_I / (1.0 + b * sqrt_I) + 2.0 / b * math.log(1.0 + b * sqrt_I)
    )

    nu_sum = nu_cat + nu_an
    term2 = m * 2.0 * nu_cat * nu_an / nu_sum * (bmx + bphi)
    term3 = m * m * 3.0 * (nu_cat * nu_an) ** 1.5 / nu_sum * C_phi

    return term1 + term2 + term3


def compute_activity_coefficient(composition: dict, ion: str) -> float:
    """Compute the mean molal activity coefficient for the given ion."""
    I = compute_ionic_strength(composition)
    if I < 1e-12:
        return 1.0

    params = _find_salt_for_ion(ion, composition)
    if params is None:
        return 1.0

    m_eff = _effective_molality(I, params)
    return math.exp(_ln_gamma(I, m_eff, params))


# ---------------------------------------------------------------------------
# Osmotic coefficient
# ---------------------------------------------------------------------------


def _osmotic_single(I, m, params):
    z_cat = params["z_cation"]
    z_an = params["z_anion"]
    nu_cat = params["nu_cation"]
    nu_an = params["nu_anion"]
    C_phi = params["Cphi"]
    b = B_PARAM

    sqrt_I = math.sqrt(I)
    bphi = _B_phi(I, params)

    nu_sum = nu_cat + nu_an
    term1 = 1.0 - A_PHI * abs(z_cat * z_an) * sqrt_I / (1.0 + b * sqrt_I)
    term2 = m * 2.0 * nu_cat * nu_an / nu_sum * bphi
    term3 = m * m * 2.0 * (nu_cat * nu_an) ** 1.5 / nu_sum * C_phi

    return term1 + term2 + term3


def compute_osmotic_coefficient(composition: dict) -> float:
    """Compute the molal osmotic coefficient."""
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
        phi = _osmotic_single(I, m_eff, params)
        weighted_sum += salt_mol * phi
        total_weight += salt_mol

    if total_weight < 1e-15:
        return 1.0

    return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# Water activity
# ---------------------------------------------------------------------------


def compute_water_activity(composition: dict) -> float:
    """Compute water activity from osmotic coefficient."""
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
    """Compute osmotic pressure in bar."""
    aw = compute_water_activity(composition)
    pi_pa = -R_GAS * temperature_K / V_W * math.log(aw)
    return pi_pa / 1.0e5


# ---------------------------------------------------------------------------
# Main: process solutions.json -> results.json + results.db
# ---------------------------------------------------------------------------


def main():
    with open("/app/solutions.json") as f:
        data = json.load(f)

    results = {"solutions": []}
    db_rows = []

    for sol in data["solutions"]:
        comp = sol["composition"]
        I = compute_ionic_strength(comp)

        first_cation = None
        for ion in comp:
            if _parse_charge(ion) > 0:
                first_cation = ion
                break

        gamma = (
            compute_activity_coefficient(comp, first_cation) if first_cation else 1.0
        )
        phi = compute_osmotic_coefficient(comp)
        aw = compute_water_activity(comp)
        pi = compute_osmotic_pressure(comp)

        entry = {
            "id": sol["id"],
            "ionic_strength": round(I, 6),
            "activity_coefficient": round(gamma, 6),
            "osmotic_coefficient": round(phi, 6),
            "water_activity": round(aw, 6),
            "osmotic_pressure_bar": round(pi, 4),
        }
        results["solutions"].append(entry)
        db_rows.append(entry)

    # Write JSON output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Write SQLite output
    conn = sqlite3.connect("/app/results.db")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS results (
            solution_id TEXT PRIMARY KEY,
            ionic_strength REAL,
            activity_coefficient REAL,
            osmotic_coefficient REAL,
            water_activity REAL,
            osmotic_pressure_bar REAL
        )"""
    )
    conn.execute("DELETE FROM results")
    for row in db_rows:
        conn.execute(
            "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["ionic_strength"],
                row["activity_coefficient"],
                row["osmotic_coefficient"],
                row["water_activity"],
                row["osmotic_pressure_bar"],
            ),
        )
    conn.commit()
    conn.close()

    print("Results written to /app/results.json and /app/results.db")


if __name__ == "__main__":
    main()
