#!/usr/bin/env python3
"""
Sensitivity-guided mechanism reduction for methane/air combustion
using GRI-Mech 3.0.
"""

import cantera as ct
import numpy as np
import json
import csv
import math

ct.suppress_thermo_warnings()

CONDITIONS = [
    ("A", 1200, 1),
    ("B", 1400, 1),
    ("C", 1600, 1),
    ("D", 1200, 10),
    ("E", 1400, 10),
    ("F", 1600, 10),
]
PHIS = [0.5, 0.7, 0.9, 1.0, 1.2]
ESSENTIAL = {"N2", "AR", "CH4", "O2", "H2O", "OH", "H", "O", "CH3",
             "CO", "CO2", "H2", "HO2", "H2O2", "CH2O", "HCO"}


def compute_ignition_delay(gas, T, P, phi=1.0):
    """Time of max dT/dt in a constant-pressure reactor. Returns seconds."""
    gas.set_equivalence_ratio(phi, "CH4:1", "O2:1, N2:3.76")
    gas.TP = T, P * ct.one_atm
    reactor = ct.IdealGasConstPressureReactor(gas)
    sim = ct.ReactorNet([reactor])
    times, temps = [], []
    while sim.time < 2.0:
        sim.step()
        times.append(sim.time)
        temps.append(reactor.T)
        if reactor.T > max(T * 1.5, T + 1000):
            break
    times = np.array(times)
    temps = np.array(temps)
    if len(times) < 2:
        return float("inf")
    dTdt = np.diff(temps) / np.diff(times)
    return times[np.argmax(dTdt)]


# ══════════════════════════════════════════════════════════════════════
# Step 1 - Ignition delays
# ══════════════════════════════════════════════════════════════════════
print("Step 1: Computing ignition delays ...")
gas = ct.Solution("gri30.yaml")

ignition_delays = {}
for cond, T, P in CONDITIONS:
    tau = compute_ignition_delay(gas, T, P)
    ignition_delays[cond] = tau * 1e3  # milliseconds
    print(f"  {cond}: T={T}K P={P}atm tau={tau*1e3:.6f} ms")

with open("/app/ignition_delays.json", "w") as f:
    json.dump(ignition_delays, f, indent=2)


# ══════════════════════════════════════════════════════════════════════
# Step 2 - Adiabatic flame temperatures
# ══════════════════════════════════════════════════════════════════════
print("\nStep 2: Computing adiabatic flame temperatures ...")
gas = ct.Solution("gri30.yaml")

flame_temps = {}
for phi in PHIS:
    gas.TP = 300.0, ct.one_atm
    gas.set_equivalence_ratio(phi, "CH4:1", "O2:1, N2:3.76")
    gas.equilibrate("HP")
    flame_temps[str(phi)] = gas.T
    print(f"  phi={phi}: T_ad = {gas.T:.2f} K")

with open("/app/flame_temperatures.json", "w") as f:
    json.dump(flame_temps, f, indent=2)


# ══════════════════════════════════════════════════════════════════════
# Step 3 - Ignition sensitivity at condition E (1400 K, 10 atm)
# ══════════════════════════════════════════════════════════════════════
print("\nStep 3: Ignition sensitivity analysis at condition E ...")
gas = ct.Solution("gri30.yaml")
n_rxn = gas.n_reactions

tau_base = compute_ignition_delay(gas, 1400, 10)
print(f"  Baseline ignition delay: {tau_base*1e3:.6f} ms")

sensitivities = []
for i in range(n_rxn):
    gas.set_multiplier(1.0)
    gas.set_multiplier(2.0, i)
    tau_pert = compute_ignition_delay(gas, 1400, 10)
    if tau_pert > 0 and tau_base > 0 and np.isfinite(tau_pert):
        S_i = math.log(tau_pert / tau_base) / math.log(2.0)
    else:
        S_i = 0.0
    sensitivities.append({
        "reaction_index": i,
        "equation": gas.reaction(i).equation,
        "sensitivity_coefficient": S_i,
    })
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{n_rxn} reactions ...")

gas.set_multiplier(1.0)

sorted_sens = sorted(
    sensitivities,
    key=lambda x: abs(x["sensitivity_coefficient"]),
    reverse=True,
)

with open("/app/ignition_sensitivity.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["rank", "reaction_index", "equation", "sensitivity_coefficient"])
    for rank, s in enumerate(sorted_sens[:30], 1):
        w.writerow([
            rank,
            s["reaction_index"],
            s["equation"],
            f"{s['sensitivity_coefficient']:.8f}",
        ])

print("\n  Top-10 sensitive reactions:")
for s in sorted_sens[:10]:
    print(f"    Rxn {s['reaction_index']:>3}: "
          f"S={s['sensitivity_coefficient']:+.6f}  {s['equation']}")


# ══════════════════════════════════════════════════════════════════════
# Step 4 - Build reduced mechanism
# ══════════════════════════════════════════════════════════════════════
print("\nStep 4: Building reduced mechanism ...")
gas_full = ct.Solution("gri30.yaml")

# Find maximum n_take giving <25 species (greedy, keeps most reactions)
n_take = len(sorted_sens)
while n_take > 0:
    species_names = set(ESSENTIAL)
    for s in sorted_sens[:n_take]:
        rxn = gas_full.reaction(s["reaction_index"])
        species_names.update(rxn.reactants.keys())
        species_names.update(rxn.products.keys())
    if len(species_names) < 25:
        break
    n_take -= 1

print(f"  Using top-{n_take} sensitive reactions")
print(f"  {len(species_names)} species: {sorted(species_names)}")

# Build species list preserving original order
all_species = ct.Species.list_from_file("gri30.yaml")
species_list = [sp for sp in all_species if sp.name in species_names]

# Filter reactions: keep only those with all reactants/products in species set
ref_phase = ct.Solution(thermo="ideal-gas", kinetics="gas", species=all_species)
all_reactions = ct.Reaction.list_from_file("gri30.yaml", ref_phase)

reactions_list = [
    rxn for rxn in all_reactions
    if (all(r in species_names for r in rxn.reactants)
        and all(p in species_names for p in rxn.products))
]

print(f"  Reduced: {len(species_list)} species, {len(reactions_list)} reactions")

gas_reduced = ct.Solution(
    thermo="ideal-gas",
    kinetics="gas",
    transport_model="mixture-averaged",
    species=species_list,
    reactions=reactions_list,
)

gas_reduced.write_yaml("/app/reduced_mechanism.yaml")

with open("/app/reduced_stats.json", "w") as f:
    json.dump({
        "n_species": gas_reduced.n_species,
        "n_reactions": gas_reduced.n_reactions,
    }, f, indent=2)


# ══════════════════════════════════════════════════════════════════════
# Step 5 - Validation
# ══════════════════════════════════════════════════════════════════════
print("\nStep 5: Validating reduced mechanism ...")

# 5a - Ignition delays
gas_red = ct.Solution("/app/reduced_mechanism.yaml")

with open("/app/validation_ignition.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["condition", "full_delay_ms", "reduced_delay_ms",
                "relative_error_percent"])
    for cond, T, P in CONDITIONS:
        tau_full = ignition_delays[cond]
        tau_red = compute_ignition_delay(gas_red, T, P) * 1e3
        rel_err = abs(tau_red - tau_full) / tau_full * 100
        w.writerow([cond, f"{tau_full:.6f}", f"{tau_red:.6f}", f"{rel_err:.2f}"])
        print(f"  Ign {cond}: full={tau_full:.4f}  red={tau_red:.4f} ms"
              f"  err={rel_err:.1f}%")

# 5b - Adiabatic flame temperatures
gas_red_t = ct.Solution("/app/reduced_mechanism.yaml")

with open("/app/validation_flame.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["equivalence_ratio", "full_temp_K", "reduced_temp_K",
                "absolute_error_K"])
    for phi in PHIS:
        T_full = flame_temps[str(phi)]
        gas_red_t.TP = 300.0, ct.one_atm
        gas_red_t.set_equivalence_ratio(phi, "CH4:1", "O2:1, N2:3.76")
        gas_red_t.equilibrate("HP")
        T_red = gas_red_t.T
        abs_err = abs(T_red - T_full)
        w.writerow([phi, f"{T_full:.4f}", f"{T_red:.4f}", f"{abs_err:.4f}"])
        print(f"  Flame phi={phi}: full={T_full:.2f}  red={T_red:.2f} K"
              f"  err={abs_err:.1f} K")

print("\nDone.")
