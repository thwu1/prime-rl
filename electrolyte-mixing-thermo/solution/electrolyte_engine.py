#!/usr/bin/env python3

"""Multi-scale electrolyte solution thermodynamic analysis engine."""

import argparse
import json
import math
import re
import warnings

import numpy as np
from pyEQL import Solution, ureg
from pyEQL.functions import gibbs_mix

SKIP_SPECIES = frozenset({"H2O(aq)", "H[+1]", "OH[-1]"})


def parse_charge(formula):
    """Parse ionic charge from formula like 'Na+', 'Ca+2', 'Cl-', 'SO4-2'."""
    m = re.search(r'([+-])(\d*)$', formula)
    if not m:
        return 0
    sign = 1 if m.group(1) == '+' else -1
    mag = int(m.group(2)) if m.group(2) else 1
    return sign * mag


def std_charge(std_formula):
    """Parse charge from pyEQL standardized formula like 'Na[+1]', 'Cl[-1]'."""
    m = re.search(r'\[([+-])(\d+)\]', std_formula)
    if m:
        sign = 1 if m.group(1) == '+' else -1
        return sign * int(m.group(2))
    return 0


def create_solution(spec):
    """Create a pyEQL Solution from a JSON spec."""
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


def extract_properties(sol):
    """Extract key thermodynamic properties from a Solution."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            hardness_val = float(sol.hardness.to("mg/L").magnitude)
        except Exception:
            hardness_val = float(getattr(sol.hardness, "magnitude", 0))
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


def extract_activity_coefficients(sol):
    """Extract activity coefficients for solutes excluding water, H+, OH-."""
    coeffs = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for species in sol.components:
            if species in SKIP_SPECIES:
                continue
            try:
                coeffs[species] = float(sol.get_activity_coefficient(species).magnitude)
            except Exception:
                pass
    return coeffs


def compute_concentration_profile(cp_config):
    """Sweep salt concentration and compute mean activity coefficients."""
    cation = cp_config["salt_cation"]
    anion = cp_config["salt_anion"]
    min_m = cp_config["min_molal"]
    max_m = cp_config["max_molal"]
    steps = cp_config["steps"]

    # Determine stoichiometric coefficients from charge balance
    z_cat = abs(parse_charge(cation))
    z_an = abs(parse_charge(anion))
    g = math.gcd(z_cat, z_an)
    nu_cat = z_an // g
    nu_an = z_cat // g
    nu_total = nu_cat + nu_an

    molalities = np.linspace(min_m, max_m, steps)
    points = []

    for m in molalities:
        m_cat = m * nu_cat
        m_an = m * nu_an
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sol = Solution(
                solutes={cation: f"{m_cat} mol/kg", anion: f"{m_an} mol/kg"},
                temperature="25 degC", engine="native"
            )
            # Get activity coefficients, separate cation/anion by charge
            coeffs = extract_activity_coefficients(sol)
            gamma_cat = gamma_an = 1.0
            for sp, gv in coeffs.items():
                c = std_charge(sp)
                if c > 0:
                    gamma_cat = gv
                elif c < 0:
                    gamma_an = gv

            # Mean activity coefficient: (gamma_+^nu_+ * gamma_-^nu_-)^(1/nu_total)
            gamma_mean = (gamma_cat ** nu_cat * gamma_an ** nu_an) ** (1.0 / nu_total)
            try:
                dl = float(sol.debye_length.to("nm").magnitude)
            except Exception:
                dl = float("inf")

        points.append({
            "molality": round(float(m), 6),
            "gamma_mean": float(gamma_mean),
            "debye_length_nm": float(dl)
        })

    # Find minimum gamma_mean
    gammas = [p["gamma_mean"] for p in points]
    min_idx = int(np.argmin(gammas))
    gamma_minimum = {
        "molality": points[min_idx]["molality"],
        "value": points[min_idx]["gamma_mean"]
    }

    # Find unity crossing above minimum
    unity_crossing = None
    for p in points[min_idx + 1:]:
        if p["gamma_mean"] >= 1.0:
            unity_crossing = p["molality"]
            break

    return {
        "points": points,
        "gamma_minimum": gamma_minimum,
        "gamma_unity_crossing_molality": unity_crossing
    }


def compute_dilution(blend, target_aw, temperature):
    """Binary search for dilution volume achieving target water activity."""
    current_aw = float(blend.get_water_activity())
    blend_is = float(blend.ionic_strength.to("mol/kg").magnitude)

    if current_aw >= target_aw - 0.001:
        return {
            "dilution_volume_L": 0.0,
            "achieved_water_activity": current_aw,
            "diluted_ionic_strength_mol_kg": blend_is
        }

    blend_vol = float(blend.volume.to("L").magnitude)

    # Find upper bound where water activity exceeds target
    lower = 0.0
    upper = blend_vol
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(25):
            water = Solution(volume=f"{upper} L", temperature=temperature,
                             engine="native")
            diluted = blend + water
            aw = float(diluted.get_water_activity())
            if aw >= target_aw:
                break
            upper *= 2

        # Binary search
        mid = upper
        for _ in range(60):
            mid = (lower + upper) / 2
            if mid < 1e-12:
                break
            water = Solution(volume=f"{mid} L", temperature=temperature,
                             engine="native")
            diluted = blend + water
            aw = float(diluted.get_water_activity())
            if abs(aw - target_aw) < 0.0003:
                break
            if aw < target_aw:
                lower = mid
            else:
                upper = mid

    final_vol = (lower + upper) / 2
    if final_vol > 1e-12:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            water = Solution(volume=f"{final_vol} L", temperature=temperature,
                             engine="native")
            diluted = blend + water
    else:
        diluted = blend
        final_vol = 0.0

    return {
        "dilution_volume_L": float(final_vol),
        "achieved_water_activity": float(diluted.get_water_activity()),
        "diluted_ionic_strength_mol_kg": float(
            diluted.ionic_strength.to("mol/kg").magnitude)
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input) as f:
        config = json.load(f)

    sol_specs = config["solutions"]
    scan_steps = config.get("scan_steps", 11)

    # ---- Individual solutions -------------------------------------------
    solutions = []
    individual = []
    for spec in sol_specs:
        sol = create_solution(spec)
        solutions.append(sol)
        props = extract_properties(sol)
        props["name"] = spec["name"]
        props["activity_coefficients"] = extract_activity_coefficients(sol)
        individual.append(props)

    # ---- Blend ----------------------------------------------------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        blended = solutions[0]
        for i in range(1, len(solutions)):
            blended = blended + solutions[i]

    blend_props = extract_properties(blended)
    blend_props["activity_coefficients"] = extract_activity_coefficients(blended)

    # ---- Excess volume --------------------------------------------------
    sum_indiv_vol_mL = sum(
        float(s.volume.to("mL").magnitude) for s in solutions
    )
    blend_vol_mL = float(blended.volume.to("mL").magnitude)
    excess_volume_mL = blend_vol_mL - sum_indiv_vol_mL

    # ---- Thermodynamics -------------------------------------------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if len(solutions) == 2:
            dg_real = float(gibbs_mix(solutions[0], solutions[1],
                                       activity_correction=True).magnitude)
            dg_ideal = float(gibbs_mix(solutions[0], solutions[1],
                                        activity_correction=False).magnitude)
        else:
            # Sequential pairwise mixing for N > 2
            running = solutions[0]
            dg_real = dg_ideal = 0.0
            for i in range(1, len(solutions)):
                dg_real += float(gibbs_mix(running, solutions[i],
                                            activity_correction=True).magnitude)
                dg_ideal += float(gibbs_mix(running, solutions[i],
                                             activity_correction=False).magnitude)
                running = running + solutions[i]

    # Entropy from thermodynamic identity: dS = -dG_ideal / T
    T_K = float(blended.temperature.to("K").magnitude)
    ds = -dg_ideal / T_K

    nonideality = dg_real / dg_ideal if abs(dg_ideal) > 1e-10 else 1.0
    total_vol_L = float(blended.volume.to("L").magnitude)
    mes = abs(dg_real) / total_vol_L / 3600.0 if total_vol_L > 0 else 0.0
    excess_gibbs = dg_real - dg_ideal

    thermo = {
        "gibbs_mix_J":                  dg_real,
        "gibbs_mix_ideal_J":            dg_ideal,
        "entropy_mix_J_K":              ds,
        "nonideality_factor":           nonideality,
        "min_energy_separation_kWh_m3": mes,
        "excess_volume_mL":             excess_volume_mL,
        "excess_gibbs_J":               excess_gibbs,
    }

    # ---- Scan -----------------------------------------------------------
    scan_results = []
    if len(solutions) >= 2:
        spec_a, spec_b = sol_specs[0], sol_specs[1]
        vol_a = ureg.Quantity(spec_a.get("volume", "1 L")).to("L").magnitude
        vol_b = ureg.Quantity(spec_b.get("volume", "1 L")).to("L").magnitude
        total_v = vol_a + vol_b

        for j in range(scan_steps):
            frac = j / (scan_steps - 1) if scan_steps > 1 else 0.5
            if frac < 1e-10 or (1.0 - frac) < 1e-10:
                scan_results.append({
                    "fraction_0": round(frac, 6),
                    "gibbs_mix_J": 0.0,
                    "optimal": False
                })
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sa = create_solution({**spec_a,
                                           "volume": f"{frac * total_v} L"})
                    sb = create_solution({**spec_b,
                                           "volume": f"{(1 - frac) * total_v} L"})
                    dg = float(gibbs_mix(sa, sb,
                                         activity_correction=True).magnitude)
                scan_results.append({
                    "fraction_0": round(frac, 6),
                    "gibbs_mix_J": dg,
                    "optimal": False
                })

        # Mark the scan point with the most negative Gibbs energy
        min_gibbs = min(pt["gibbs_mix_J"] for pt in scan_results)
        for pt in scan_results:
            if pt["gibbs_mix_J"] == min_gibbs and pt["gibbs_mix_J"] < 0:
                pt["optimal"] = True
                break

    # ---- Assemble output ------------------------------------------------
    output = {
        "individual":     individual,
        "blend":          blend_props,
        "thermodynamics": thermo,
        "scan":           scan_results,
    }

    if "concentration_profile" in config:
        output["concentration_profile"] = compute_concentration_profile(
            config["concentration_profile"])

    if "target_water_activity" in config:
        temp_str = sol_specs[0].get("temperature", "25 degC")
        output["dilution"] = compute_dilution(
            blended, config["target_water_activity"], temp_str)

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
