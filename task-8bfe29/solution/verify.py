#!/usr/bin/env python3
"""Verify the LABS implementation against reference data."""
import sys
import sqlite3
import json

sys.path.insert(0, "/app")

from labs.energy import energy, autocorrelation, merit_factor
from labs.interactions import get_interactions, topology_overlaps
from labs.theta import compute_theta, compute_gamma1
from labs.symmetry import canonical_form, negate, reverse_seq
from labs.solver import solve

db = sqlite3.connect("/app/data/reference.db")

# Verify energy examples from database
print("Checking energy examples...")
for row in db.execute("SELECT sequence_json, energy FROM energy_examples"):
    s = json.loads(row[0])
    computed = energy(s)
    assert computed == row[1], f"Energy mismatch for {row[0]}: {computed} != {row[1]}"
print("  All energy examples passed.")

# Verify interaction counts from database
print("Checking interaction counts...")
for row in db.execute("SELECT N, g2_size, g4_size, gamma1 FROM interaction_counts"):
    N_val, exp_g2, exp_g4, exp_gamma1 = row
    G2, G4 = get_interactions(N_val)
    assert len(G2) == exp_g2, f"G2 size mismatch for N={N_val}: {len(G2)} != {exp_g2}"
    assert len(G4) == exp_g4, f"G4 size mismatch for N={N_val}: {len(G4)} != {exp_g4}"
    assert compute_gamma1(G2, G4) == exp_gamma1, f"Gamma1 mismatch for N={N_val}"
print("  All interaction counts passed.")

# Verify solver finds known optima
print("Checking solver...")
for N_val, expected_E in [(5, 2), (7, 3), (11, 5), (13, 6)]:
    s, E = solve(N_val)
    assert E == expected_E, f"Solver N={N_val}: got E={E}, expected {expected_E}"
    assert energy(s) == E, f"Solver N={N_val}: energy(s)={energy(s)} != returned E={E}"
    print(f"  N={N_val}: E={E} (optimal)")

s21, E21 = solve(21)
assert E21 <= 30, f"Solver N=21: E={E21} > 30"
print(f"  N=21: E={E21} <= 30")

print("\nAll verifications passed.")
db.close()
