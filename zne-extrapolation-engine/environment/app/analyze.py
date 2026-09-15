"""ZNE analysis pipeline.


Loads noisy quantum circuit measurement data from /app/data/, applies
multiple extrapolation strategies, selects the best model per circuit,
and writes results to /app/results.json.
"""

import json
import os
import sys
import numpy as np

from zne_inference import (
    LinearFactory,
    RichardsonFactory,
    ExpFactory,
    PolyExpFactory,
)


FACTORIES = {
    "linear": LinearFactory,
    "richardson": RichardsonFactory,
    "exponential": ExpFactory,
    "poly_exponential": PolyExpFactory,
}


def load_circuit_data(data_dir):
    """Load all circuit measurement data from JSON files.

    Args:
        data_dir: Path to directory containing circuit_*.json files.

    Returns:
        dict mapping circuit_id -> data dict with keys:
            circuit_id, description, scale_factors, expectation_values
    """
    circuits = {}
    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".json"):
            fpath = os.path.join(data_dir, fname)
            with open(fpath) as f:
                data = json.load(f)
            circuits[data["circuit_id"]] = data
    return circuits


def select_best_factory(scale_factors, exp_values):
    """Select the best extrapolation factory for the given data.

    Must handle factory failures gracefully (skip factories that raise).
    If no factory succeeds, raise RuntimeError.

    Args:
        scale_factors: List of noise scale factors.
        exp_values: List of measured expectation values.

    Returns:
        tuple: (factory_name: str, extrapolated_value: float)
    """
    raise NotImplementedError("select_best_factory not implemented")


def run_pipeline():
    """Run the full ZNE analysis pipeline."""
    data_dir = "/app/data"
    circuits = load_circuit_data(data_dir)

    results = {}
    for cid, cdata in sorted(circuits.items()):
        sf = cdata["scale_factors"]
        ev = cdata["expectation_values"]

        factory_results = {}
        for fname, fcls in FACTORIES.items():
            try:
                val = fcls.extrapolate(sf, ev)
                factory_results[fname] = round(float(val), 10)
            except Exception:
                factory_results[fname] = None

        best_name, best_value = select_best_factory(sf, ev)

        results[cid] = {
            "factory_results": factory_results,
            "best_factory": best_name,
            "extrapolated_value": round(float(best_value), 10),
        }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    for cid, r in sorted(results.items()):
        print(
            f"  Circuit {cid}: best={r['best_factory']}, "
            f"E(0)={r['extrapolated_value']:.8f}"
        )


if __name__ == "__main__":
    run_pipeline()
