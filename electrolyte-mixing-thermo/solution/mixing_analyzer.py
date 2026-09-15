#!/usr/bin/env python3

"""
Electrolyte solution mixing thermodynamics analyzer.

Uses pyEQL to model aqueous electrolyte solutions with the Pitzer activity
coefficient model (native engine), compute bulk and per-solute properties,
and analyse the thermodynamics of mixing (Gibbs energy, entropy, minimum
energy of separation).
"""

import argparse
import json
import warnings

import numpy as np
from pyEQL import Solution, ureg
from pyEQL.functions import gibbs_mix


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _create_solution(spec):
    """Create a pyEQL Solution from a JSON specification dict."""
    solutes = spec.get("solutes", {})
    vol = spec.get("volume", "1 L")
    pH = spec.get("pH", 7.0)
    temp = spec.get("temperature", "25 degC")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if solutes:
            return Solution(solutes=solutes, volume=vol, pH=pH,
                            temperature=temp, engine="native")
        return Solution(volume=vol, pH=pH, temperature=temp, engine="native")


_SKIP_SPECIES = frozenset({"H2O(aq)", "H[+1]", "OH[-1]"})


def _extract_properties(sol):
    """Return a dict of key thermodynamic properties."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            hardness_val = float(sol.hardness.to("mg/L").magnitude)
        except Exception:
            hardness_val = float(sol.hardness.magnitude) if hasattr(sol.hardness, "magnitude") else 0.0
        try:
            debye_val = float(sol.debye_length.to("nm").magnitude)
        except Exception:
            debye_val = float("inf")
        return {
            "ionic_strength_mol_kg": float(sol.ionic_strength.to("mol/kg").magnitude),
            "conductivity_S_m":      float(sol.conductivity.to("S/m").magnitude),
            "density_kg_L":          float(sol.density.to("kg/L").magnitude),
            "osmotic_pressure_Pa":   float(sol.osmotic_pressure.to("Pa").magnitude),
            "water_activity":        float(sol.get_water_activity()),
            "pH":                    float(sol.pH),
            "hardness_mg_L":         hardness_val,
            "debye_length_nm":       debye_val,
        }


def _extract_activity_coefficients(sol):
    """Return activity coefficients for solutes excluding H2O, H+, OH-."""
    coeffs = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for species in sol.components:
            if species in _SKIP_SPECIES:
                continue
            try:
                gamma = sol.get_activity_coefficient(species)
                coeffs[species] = float(gamma.magnitude)
            except Exception:
                pass
    return coeffs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Electrolyte solution mixing thermodynamics analyzer")
    parser.add_argument("--input", required=True, help="Path to input JSON")
    parser.add_argument("--output", required=True, help="Path to output JSON")
    args = parser.parse_args()

    with open(args.input) as fh:
        config = json.load(fh)

    sol_specs = config["solutions"]
    scan_steps = config.get("scan_steps", 11)

    # ---- Individual solutions ------------------------------------------------
    solutions = []
    individual = []
    for spec in sol_specs:
        sol = _create_solution(spec)
        solutions.append(sol)
        props = _extract_properties(sol)
        props["name"] = spec["name"]
        props["activity_coefficients"] = _extract_activity_coefficients(sol)
        individual.append(props)

    # ---- Blend ---------------------------------------------------------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        blended = solutions[0]
        for i in range(1, len(solutions)):
            blended = blended + solutions[i]

    blend_props = _extract_properties(blended)
    blend_props["activity_coefficients"] = _extract_activity_coefficients(blended)

    # ---- Thermodynamics ------------------------------------------------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if len(solutions) == 2:
            dg_real  = float(gibbs_mix(solutions[0], solutions[1],
                                       activity_correction=True).magnitude)
            dg_ideal = float(gibbs_mix(solutions[0], solutions[1],
                                       activity_correction=False).magnitude)
        else:
            # Sequential pairwise mixing for N > 2
            running = solutions[0]
            dg_real = dg_ideal = 0.0
            for i in range(1, len(solutions)):
                dg_real  += float(gibbs_mix(running, solutions[i],
                                            activity_correction=True).magnitude)
                dg_ideal += float(gibbs_mix(running, solutions[i],
                                            activity_correction=False).magnitude)
                running = running + solutions[i]

    # Entropy of mixing from the thermodynamic identity: dG_ideal = -T * dS
    # so dS = -dG_ideal / T
    T_K = float(blended.temperature.to("K").magnitude)
    ds = -dg_ideal / T_K

    nonideality = dg_real / dg_ideal if abs(dg_ideal) > 1e-10 else 1.0
    total_vol_L = float(blended.volume.to("L").magnitude)
    mes = abs(dg_real) / total_vol_L / 3600.0 if total_vol_L > 0 else 0.0

    thermo = {
        "gibbs_mix_J":                  dg_real,
        "gibbs_mix_ideal_J":            dg_ideal,
        "entropy_mix_J_K":              ds,
        "nonideality_factor":           nonideality,
        "min_energy_separation_kWh_m3": mes,
    }

    # ---- Scan ----------------------------------------------------------------
    scan_results = []
    if len(solutions) >= 2:
        spec_a, spec_b = sol_specs[0], sol_specs[1]
        vol_a = ureg.Quantity(spec_a.get("volume", "1 L")).to("L").magnitude
        vol_b = ureg.Quantity(spec_b.get("volume", "1 L")).to("L").magnitude
        total_v = vol_a + vol_b

        for j in range(scan_steps):
            frac = j / (scan_steps - 1) if scan_steps > 1 else 0.5
            if frac < 1e-10 or (1.0 - frac) < 1e-10:
                scan_results.append({"fraction_0": round(frac, 6),
                                     "gibbs_mix_J": 0.0})
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sa = _create_solution({**spec_a,
                                           "volume": f"{frac * total_v} L"})
                    sb = _create_solution({**spec_b,
                                           "volume": f"{(1 - frac) * total_v} L"})
                    dg = float(gibbs_mix(sa, sb,
                                         activity_correction=True).magnitude)
                scan_results.append({"fraction_0": round(frac, 6),
                                     "gibbs_mix_J": dg})

    # ---- Write output --------------------------------------------------------
    output = {
        "individual":     individual,
        "blend":          blend_props,
        "thermodynamics": thermo,
        "scan":           scan_results,
    }

    with open(args.output, "w") as fh:
        json.dump(output, fh, indent=2)


if __name__ == "__main__":
    main()
