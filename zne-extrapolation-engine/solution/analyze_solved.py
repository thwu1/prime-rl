"""Complete analyze.py with model selection.

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
    circuits = {}
    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".json"):
            fpath = os.path.join(data_dir, fname)
            with open(fpath) as f:
                data = json.load(f)
            circuits[data["circuit_id"]] = data
    return circuits


def select_best_factory(scale_factors, exp_values):
    sf = list(scale_factors)
    ev = list(exp_values)
    n = len(sf)

    best_name = None
    best_cv_error = float("inf")
    best_value = None

    for fname, fcls in FACTORIES.items():
        cv_errors = []
        failed = False

        for i in range(n):
            sf_train = sf[:i] + sf[i + 1 :]
            ev_train = ev[:i] + ev[i + 1 :]

            try:
                predicted = fcls.fit_and_predict(sf_train, ev_train, sf[i])
                cv_errors.append((predicted - ev[i]) ** 2)
            except Exception:
                failed = True
                break

        if failed or not cv_errors:
            continue

        mean_cv = sum(cv_errors) / len(cv_errors)

        if mean_cv < best_cv_error:
            best_cv_error = mean_cv
            best_name = fname
            try:
                best_value = fcls.extrapolate(sf, ev)
            except Exception:
                best_name = None
                best_cv_error = float("inf")

    if best_name is None:
        raise RuntimeError("All factories failed")

    return best_name, best_value


def run_pipeline():
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
