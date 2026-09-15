#!/usr/bin/env python3
"""
QEC Decoder Comparison Pipeline

Benchmarks the Tesseract (A*) and Simplex (ILP) quantum error correction
decoders.  Produces:
  - processed.dem          (merged DEM from configured circuit)
  - cross_validation.json  (Tesseract vs Simplex cost comparison)
  - error_rates.json       (logical error rates for a (d, p) sweep)
  - threshold.json         (pseudo-threshold estimate)
"""

import json
import os

import numpy as np
import stim
from tesseract_decoder import common, simplex, tesseract


# ── helpers ──────────────────────────────────────────────────────────────────


def load_config(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def build_circuit(cfg: dict) -> stim.Circuit:
    n = cfg["noise"]
    return stim.Circuit.generated(
        cfg["code"],
        distance=cfg["distance"],
        rounds=cfg["rounds"],
        after_clifford_depolarization=n["after_clifford_depolarization"],
        before_measure_flip_probability=n["before_measure_flip_probability"],
        before_round_data_depolarization=n["before_round_data_depolarization"],
        after_reset_flip_probability=n["after_reset_flip_probability"],
    )


def per_round_rate(R_shot: float, rounds: int) -> float:
    """Convert per-shot logical error rate to per-round rate."""
    if R_shot <= 0:
        return 0.0
    if R_shot >= 0.5:
        return 0.5
    return 0.5 * (1.0 - (1.0 - 2.0 * R_shot) ** (1.0 / rounds))


# ── Part 1: DEM processing ──────────────────────────────────────────────────


def part1_processed_dem(circuit: stim.Circuit, out_dir: str):
    dem = circuit.detector_error_model(decompose_errors=False)
    merged = common.merge_indistinguishable_errors(dem)
    cleaned = common.remove_zero_probability_errors(merged)
    path = os.path.join(out_dir, "processed.dem")
    with open(path, "w") as f:
        f.write(str(cleaned))
    print(f"  Wrote {path}")


# ── Part 2: cross-validation ────────────────────────────────────────────────


def part2_cross_validation(circuit: stim.Circuit, out_dir: str):
    dem = circuit.detector_error_model(decompose_errors=False)
    num_det = dem.num_detectors

    # Tesseract decoder
    t_cfg = tesseract.TesseractConfig(
        dem=dem, det_beam=10, beam_climbing=True
    )
    t_dec = tesseract.TesseractDecoder(t_cfg)

    # Simplex decoder
    s_cfg = simplex.SimplexConfig(dem=dem)
    s_dec = simplex.SimplexDecoder(s_cfg)
    s_dec.init_ilp()

    # Sample
    sampler = circuit.compile_detector_sampler(seed=42)
    det_events, obs_flips = sampler.sample(shots=500, separate_observables=True)

    cost_matches = 0
    cost_mismatches = 0
    logical_errors_t = 0
    logical_errors_s = 0

    for i in range(500):
        syn = det_events[i, :num_det].astype(bool)
        actual = obs_flips[i].astype(bool)

        # Tesseract
        t_obs = t_dec.decode(syn)
        if t_dec.low_confidence_flag:
            continue  # skip un-decodable shots

        t_cost = t_dec.cost_from_errors(list(t_dec.predicted_errors_buffer))

        # Simplex
        s_obs = s_dec.decode(syn)
        s_cost = s_dec.cost_from_errors(list(s_dec.predicted_errors_buffer))

        # cost comparison
        if abs(t_cost - s_cost) < 1e-6:
            cost_matches += 1
        else:
            cost_mismatches += 1

        # logical-error comparison
        if np.any(np.asarray(t_obs, dtype=bool) != actual):
            logical_errors_t += 1
        if np.any(np.asarray(s_obs, dtype=bool) != actual):
            logical_errors_s += 1

    result = {
        "total_shots": 500,
        "cost_matches": cost_matches,
        "cost_mismatches": cost_mismatches,
        "logical_errors_tesseract": logical_errors_t,
        "logical_errors_simplex": logical_errors_s,
    }
    path = os.path.join(out_dir, "cross_validation.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Matches={cost_matches}  Mismatches={cost_mismatches}")


# ── Part 3: error-rate sweep ─────────────────────────────────────────────────


def part3_error_rates(out_dir: str):
    distances = [3, 5, 7]
    phys_rates = [0.05, 0.15, 0.2]
    num_shots = 2000
    results = []

    for d in distances:
        for p in phys_rates:
            rounds = 3 * d
            circuit = stim.Circuit.generated(
                "repetition_code:memory",
                distance=d,
                rounds=rounds,
                after_clifford_depolarization=p,
            )
            dem = circuit.detector_error_model(decompose_errors=True)
            num_det = dem.num_detectors

            t_cfg = tesseract.TesseractConfig(dem=dem, det_beam=5)
            t_dec = tesseract.TesseractDecoder(t_cfg)

            sampler = circuit.compile_detector_sampler(seed=12345)
            det_events, obs_flips = sampler.sample(
                shots=num_shots, separate_observables=True
            )

            predictions = t_dec.decode_batch(
                det_events[:, :num_det].astype(bool)
            )

            errors = np.any(
                predictions.astype(bool) != obs_flips.astype(bool), axis=1
            )
            n_errors = int(np.sum(errors))

            R_shot = n_errors / num_shots
            R_round = per_round_rate(R_shot, rounds)

            results.append(
                {
                    "distance": d,
                    "physical_error_rate": p,
                    "logical_error_rate_per_shot": R_shot,
                    "logical_error_rate_per_round": R_round,
                    "num_shots": num_shots,
                    "num_rounds": rounds,
                    "num_errors": n_errors,
                }
            )
            print(
                f"  d={d}  p={p}  errors={n_errors}/{num_shots}  "
                f"R_shot={R_shot:.6f}  R_round={R_round:.8f}"
            )

    path = os.path.join(out_dir, "error_rates.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    return results


# ── Part 4: threshold estimation ─────────────────────────────────────────────


def part4_threshold(er_data: list, out_dir: str):
    d3 = sorted(
        [(e["physical_error_rate"], e["logical_error_rate_per_round"])
         for e in er_data if e["distance"] == 3]
    )
    d5 = sorted(
        [(e["physical_error_rate"], e["logical_error_rate_per_round"])
         for e in er_data if e["distance"] == 5]
    )

    threshold = None
    for i in range(len(d3) - 1):
        p1, r3_lo = d3[i]
        p2, r3_hi = d3[i + 1]
        r5_lo = d5[i][1]
        r5_hi = d5[i + 1][1]

        diff_lo = r3_lo - r5_lo
        diff_hi = r3_hi - r5_hi

        if diff_lo * diff_hi <= 0 and (abs(diff_lo) + abs(diff_hi) > 0):
            if diff_lo != diff_hi:
                alpha = diff_lo / (diff_lo - diff_hi)
                threshold = p1 + alpha * (p2 - p1)
            else:
                threshold = (p1 + p2) / 2.0
            break

    if threshold is None:
        # Use the last measured point as fallback estimate
        threshold = float(max(p for p, _ in d3))

    result = {"threshold_estimate": float(threshold)}
    path = os.path.join(out_dir, "threshold.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Threshold estimate: {threshold:.6f}")
    return result


# ── main ─────────────────────────────────────────────────────────────────────


def main():
    cfg = load_config("/app/data/circuit_config.json")
    out_dir = "/app/output"
    os.makedirs(out_dir, exist_ok=True)

    print("Building circuit from config ...")
    circuit = build_circuit(cfg)

    print("Part 1: Processing DEM ...")
    part1_processed_dem(circuit, out_dir)

    print("Part 2: Cross-validation (500 shots) ...")
    part2_cross_validation(circuit, out_dir)

    print("Part 3: Error-rate sweep ...")
    er = part3_error_rates(out_dir)

    print("Part 4: Threshold estimation ...")
    part4_threshold(er, out_dir)

    print("Pipeline complete.")


if __name__ == "__main__":
    main()
