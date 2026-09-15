#!/usr/bin/env python3
"""
Extract thermal conductivity from LAMMPS NEMD output and convert
from LJ reduced units to SI units for argon.

The LJ unit of thermal conductivity is derived from dimensional analysis:
  [kappa] = [energy] / ([time] * [length] * [temperature])
          = epsilon / (tau * sigma * epsilon/kB)
          = kB / (tau * sigma)
where tau = sigma * sqrt(m / epsilon) is the LJ time unit.

Substituting:
  [kappa] = kB / (sigma^2 * sqrt(m / epsilon))
          = kB * sqrt(epsilon / m) / sigma^2

So: kappa_SI = kappa_star * kB * sqrt(epsilon / m) / sigma^2
"""

import json
import math
import re
import sys


def extract_kappa_from_log(logfile):
    """Extract thermal conductivity printed at the end of a LAMMPS run."""
    with open(logfile) as f:
        content = f.read()

    match = re.search(
        r"Running average thermal conductivity:\s+([\d.eE+-]+)", content
    )
    if match:
        return float(match.group(1))

    raise ValueError(f"Could not find 'Running average thermal conductivity' in {logfile}")


def compute_conversion_factor(spec):
    """
    Derive the LJ -> SI conversion factor for thermal conductivity.

    kappa_SI = kappa* * kB * sqrt(epsilon / m) / sigma^2

    Parameters from spec['physical_mapping']:
      sigma_m       : LJ length parameter in meters
      epsilon_over_kB_K : LJ energy parameter as epsilon/kB in Kelvin
      mass_kg       : atomic mass in kg
      kB_J_per_K    : Boltzmann constant in J/K
    """
    phys = spec["physical_mapping"]
    kB = phys["kB_J_per_K"]
    sigma = phys["sigma_m"]
    eps_over_kB = phys["epsilon_over_kB_K"]
    mass = phys["mass_kg"]

    epsilon = eps_over_kB * kB  # J

    # [kappa] = kB * sqrt(epsilon / m) / sigma^2
    factor = kB * math.sqrt(epsilon / mass) / (sigma ** 2)
    return factor


def main():
    # Load specification
    with open("/app/specification.json") as f:
        spec = json.load(f)

    # Extract kappa* from both methods
    kappa_mp = extract_kappa_from_log("/app/log.mp")
    kappa_heat = extract_kappa_from_log("/app/log.heat")

    print(f"Muller-Plathe kappa* = {kappa_mp:.4f}")
    print(f"Fix-heat kappa*      = {kappa_heat:.4f}")

    # Derive conversion factor
    factor = compute_conversion_factor(spec)
    print(f"Conversion factor    = {factor:.6f} W/(m*K) per LJ unit")

    # Convert to SI
    kappa_si_mp = kappa_mp * factor
    kappa_si_heat = kappa_heat * factor

    print(f"Muller-Plathe kappa_SI = {kappa_si_mp:.6f} W/(m*K)")
    print(f"Fix-heat kappa_SI      = {kappa_si_heat:.6f} W/(m*K)")

    # Cross-validation ratio
    ratio = max(kappa_mp, kappa_heat) / min(kappa_mp, kappa_heat)
    print(f"Cross-validation ratio = {ratio:.4f}")

    # Write results
    results = {
        "kappa_star_mp": round(kappa_mp, 4),
        "kappa_star_heat": round(kappa_heat, 4),
        "kappa_si_mp": round(kappa_si_mp, 6),
        "kappa_si_heat": round(kappa_si_heat, 6),
        "cross_validation_ratio": round(ratio, 4),
        "conversion_factor_w_per_m_k": round(factor, 6),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
