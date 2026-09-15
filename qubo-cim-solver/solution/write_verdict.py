#!/usr/bin/env python3
"""Write the solver evaluation verdict to /app/verdict.json."""
import json

verdict = {
    "alpha": {
        "has_defects": True,
        "defect_categories": ["energy_computation"],
        "impact": (
            "ising_energy() computes s @ J @ s + h @ s instead of 0.5 * s @ J @ s + h @ s. "
            "With symmetric J, s @ J @ s double-counts each coupling pair, producing energies "
            "roughly twice the coupling contribution. This causes reported Ising energies to be "
            "incorrect (failing self-consistency checks) and corrupts the cross-run best-solution "
            "selection since different runs accumulate different tracking offsets."
        ),
    },
    "beta": {
        "has_defects": True,
        "defect_categories": ["local_search"],
        "impact": (
            "local_search() never sets improved = True inside the spin-flip loop. "
            "The convergence check 'if not improved: break' always triggers after the "
            "first pass, so the descent terminates after a single sweep regardless of "
            "whether improvements were found. Solutions are not fully locally optimized, "
            "leading to suboptimal energies especially on frustrated and dense instances."
        ),
    },
    "gamma": {
        "has_defects": True,
        "defect_categories": ["dynamics_parameters"],
        "impact": (
            "solve() clamps pump_max to min(cfg['pump_max'], 0.5), overriding the "
            "configured value of 3.0. CIM bifurcation requires pump > 1.0; with "
            "p_max = 0.5 the oscillators never bifurcate and remain near zero throughout "
            "the simulation. The resulting spin assignments are effectively random, and "
            "only local search from random starts provides any optimization."
        ),
    },
}

with open("/app/verdict.json", "w") as f:
    json.dump(verdict, f, indent=2)

print("Wrote /app/verdict.json")
