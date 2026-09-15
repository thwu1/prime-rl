#!/usr/bin/env python3
"""Run acrobot simulation and compute RealAI Score."""

import sys
import json

sys.path.insert(0, '/app')

from plant import DoublePendulumPlant
from simulator import simulate
from scoring import compute_realai_score


def main():
    with open('/app/params.json') as f:
        params = json.load(f)

    try:
        from controller import AcrobotController
    except ImportError as e:
        print(f"Error importing controller: {e}")
        print("Create /app/controller.py with class AcrobotController(plant, params)")
        print("  method: get_control_output(state, t) -> float")
        sys.exit(1)

    plant = DoublePendulumPlant(params)
    controller = AcrobotController(plant, params)

    print("Running 10s RK4 simulation (dt=0.002)...")
    trajectory = simulate(plant, controller, params)
    print(f"Simulation complete: {len(trajectory)} timesteps")

    score, details = compute_realai_score(trajectory, params)

    results = {'realai_score': score, 'details': details,
               'trajectory_length': len(trajectory)}

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nRealAI Score: {score:.4f}")
    for k, v in details.items():
        print(f"  {k}: {v}")

    target = params.get('min_realai_score', 0.3)
    if score >= target:
        print(f"\nPASSED: Score {score:.4f} >= {target}")
    else:
        print(f"\nFAILED: Score {score:.4f} < {target}")
        sys.exit(1)


if __name__ == '__main__':
    main()
