
"""Robeson 2008 upper bound evaluation for polymeric membrane gas separation."""

import json


def load_robeson_params():
    with open("/app/data/robeson_parameters.json") as f:
        return json.load(f)


def load_polymer_database():
    with open("/app/data/polymer_database.json") as f:
        return json.load(f)


def _evaluate_polymer(polymer_data, gas_pair, robeson_params):
    """Evaluate a single polymer against the Robeson upper bound.

    Upper bound equation: P_A = k * alpha^(-n)
    where alpha = P_A / P_B (ideal selectivity).
    """
    gas_A, gas_B = gas_pair.split("/")
    P_A = polymer_data["permeabilities_barrer"][gas_A]
    P_B = polymer_data["permeabilities_barrer"][gas_B]
    alpha = P_A / P_B

    params = robeson_params["gas_pairs"][gas_pair]
    k = params["k"]
    n = params["n"]

    P_UB = k * alpha ** (-n)
    ratio = P_A / P_UB

    return {
        "polymer": polymer_data["abbreviation"],
        "P_A": round(P_A, 6),
        "alpha": round(alpha, 6),
        "P_upper_bound": round(P_UB, 6),
        "ratio": round(ratio, 8),
        "exceeds_bound": ratio > 1.0,
    }


def rank_polymers(gas_pair, polymer_abbrev=None):
    """Rank polymer(s) against the Robeson 2008 upper bound.

    Parameters
    ----------
    gas_pair : str, e.g. "CO2/CH4"
    polymer_abbrev : str or None. If None, rank all polymers.

    Returns
    -------
    list of dict, sorted by ratio descending
    """
    robeson_params = load_robeson_params()
    polymer_db = load_polymer_database()

    gas_A, gas_B = gas_pair.split("/")

    if polymer_abbrev:
        polymer = next(
            p for p in polymer_db["polymers"] if p["abbreviation"] == polymer_abbrev
        )
        return [_evaluate_polymer(polymer, gas_pair, robeson_params)]

    results = []
    for polymer in polymer_db["polymers"]:
        perms = polymer["permeabilities_barrer"]
        if gas_A in perms and gas_B in perms:
            results.append(_evaluate_polymer(polymer, gas_pair, robeson_params))

    results.sort(key=lambda x: x["ratio"], reverse=True)
    return results
