
"""
Powder diffraction peak indexing and lattice parameter refinement for
orthorhombic PbSO4 (Pnma) with impurity detection and zero-shift correction.

Strategy:
1. Use a distance-to-nearest-predicted cost function (no explicit assignment
   needed during optimization, avoiding combinatorial explosion)
2. Global search with differential evolution to find rough params
3. Refine with least_squares on explicit assignments
4. Identify impurity peaks by large residuals
"""

import json
import math
import numpy as np
from scipy.optimize import differential_evolution, least_squares


def load_inputs():
    with open("/app/observed_peaks.json") as f:
        peaks_data = json.load(f)
    with open("/app/structure_info.json") as f:
        struct_data = json.load(f)
    return peaks_data, struct_data


def is_allowed_pnma(h, k, l):
    if h == 0 and (k + l) % 2 != 0:
        return False
    if l == 0 and h % 2 != 0:
        return False
    if k == 0 and l == 0 and h % 2 != 0:
        return False
    if h == 0 and l == 0 and k % 2 != 0:
        return False
    if h == 0 and k == 0 and l % 2 != 0:
        return False
    return True


def generate_candidates(a_max, b_max, c_max, wavelength, two_theta_max):
    d_min = wavelength / (2.0 * math.sin(math.radians(two_theta_max / 2.0)))
    candidates = []
    for h in range(0, int(math.ceil(a_max / d_min)) + 2):
        for k in range(0, int(math.ceil(b_max / d_min)) + 2):
            for l in range(0, int(math.ceil(c_max / d_min)) + 2):
                if h == 0 and k == 0 and l == 0:
                    continue
                if not is_allowed_pnma(h, k, l):
                    continue
                candidates.append((h, k, l))
    return candidates


def calc_positions_np(candidates_arr, a, b, c, wavelength, zero_shift):
    """Vectorized 2theta calculation."""
    h, k, l = candidates_arr[:, 0], candidates_arr[:, 1], candidates_arr[:, 2]
    inv_d_sq = (h / a) ** 2 + (k / b) ** 2 + (l / c) ** 2
    d = 1.0 / np.sqrt(inv_d_sq)
    sin_theta = wavelength / (2.0 * d)
    valid = np.abs(sin_theta) <= 1.0
    tt = np.full(len(candidates_arr), 999.0)
    tt[valid] = 2.0 * np.degrees(np.arcsin(sin_theta[valid])) + zero_shift
    return tt


def nearest_pred_cost(params, obs_arr, cand_arr, wavelength):
    """
    Cost: for each observed peak, squared distance to nearest predicted peak.
    Uses Huber-like capping to be robust to impurities.
    """
    a, b, c, zs = params
    if a <= 0 or b <= 0 or c <= 0:
        return 1e10
    pred = calc_positions_np(cand_arr, a, b, c, wavelength, zs)
    pred_sorted = np.sort(pred[pred < 200])

    total = 0.0
    for obs_tt in obs_arr:
        idx = np.searchsorted(pred_sorted, obs_tt)
        dists = []
        if idx > 0:
            dists.append(abs(obs_tt - pred_sorted[idx - 1]))
        if idx < len(pred_sorted):
            dists.append(abs(obs_tt - pred_sorted[idx]))
        min_dist = min(dists) if dists else 10.0
        # Huber-like: cap contribution to avoid impurities dominating
        total += min(min_dist ** 2, 0.04)  # cap at 0.2 deg
    return total


def match_peaks_final(observed, pred_positions, candidates, threshold):
    """Greedy matching for final assignment."""
    pred = np.array(pred_positions)
    assignments = {}
    used_pred = set()

    for obs_idx in sorted(range(len(observed)), key=lambda i: observed[i]):
        obs_tt = observed[obs_idx]
        diffs = np.abs(pred - obs_tt)
        for pi in np.argsort(diffs):
            if diffs[pi] > threshold:
                break
            if pi in used_pred:
                continue
            assignments[obs_idx] = (int(pi), candidates[pi], float(pred[pi]))
            used_pred.add(pi)
            break

    return assignments


def main():
    peaks_data, struct_data = load_inputs()
    observed = peaks_data["observed_two_theta"]
    wavelength = peaks_data["wavelength_angstrom"]
    lp = struct_data["initial_lattice_parameters_angstrom"]

    a0, b0, c0 = lp["a"], lp["b"], lp["c"]
    obs_arr = np.array(observed)
    tt_max = max(observed) + 2.0

    # Generate candidates with generous bounds
    candidates = generate_candidates(
        max(a0, 9.0) * 1.05, max(b0, 6.0) * 1.05, max(c0, 7.5) * 1.05,
        wavelength, tt_max
    )
    cand_arr = np.array(candidates, dtype=float)

    # Stage 1: Global search with differential evolution
    bounds = [
        (a0 * 0.96, a0 * 1.02),
        (b0 * 0.96, b0 * 1.04),
        (c0 * 0.96, c0 * 1.02),
        (-0.5, 0.5),
    ]

    result = differential_evolution(
        nearest_pred_cost,
        bounds,
        args=(obs_arr, cand_arr, wavelength),
        seed=42,
        maxiter=500,
        tol=1e-10,
        atol=1e-12,
        popsize=25,
        mutation=(0.5, 1.5),
        recombination=0.9,
    )

    a, b, c, zs = result.x
    print(f"DE result: a={a:.4f}, b={b:.4f}, c={c:.4f}, z={zs:.4f}, cost={result.fun:.6f}")

    # Stage 2: Match peaks and refine with least_squares
    pred = calc_positions_np(cand_arr, a, b, c, wavelength, zs)
    valid_mask = pred < 200
    pred_valid = pred[valid_mask]
    cand_valid = [candidates[i] for i in range(len(candidates)) if valid_mask[i]]

    for refinement_round in range(3):
        thresh = [0.15, 0.08, 0.05][refinement_round]
        assignments = match_peaks_final(observed, pred_valid, cand_valid, thresh)

        if len(assignments) < 30:
            print(f"  Round {refinement_round}: only {len(assignments)} matches, keeping previous")
            continue

        # Refine with fixed assignments
        obs_indices = sorted(assignments.keys())
        obs_vals = np.array([observed[i] for i in obs_indices])
        hkl_list = [assignments[i][1] for i in obs_indices]
        hkl_arr = np.array(hkl_list, dtype=float)

        def residuals(params):
            aa, bb, cc, zzs = params
            p = calc_positions_np(hkl_arr, aa, bb, cc, wavelength, zzs)
            return obs_vals - p

        res = least_squares(
            residuals,
            x0=[a, b, c, zs],
            bounds=([5, 3, 4, -1], [12, 8, 10, 1]),
            method='trf',
            ftol=1e-14, xtol=1e-14, gtol=1e-14,
            max_nfev=10000,
        )
        a, b, c, zs = res.x

        # Recompute predictions
        pred = calc_positions_np(cand_arr, a, b, c, wavelength, zs)
        valid_mask = pred < 200
        pred_valid = pred[valid_mask]
        cand_valid = [candidates[i] for i in range(len(candidates)) if valid_mask[i]]

        # Check residuals and remove outliers
        assignments2 = match_peaks_final(observed, pred_valid, cand_valid, 0.1)
        resids = [abs(observed[oi] - assignments2[oi][2]) for oi in assignments2]
        rms = math.sqrt(sum(r**2 for r in resids) / max(len(resids), 1))
        print(f"  Round {refinement_round}: matches={len(assignments2)}, "
              f"a={a:.5f}, b={b:.5f}, c={c:.5f}, z={zs:.5f}, rms={rms:.6f}")

    # Stage 3: Final assignment with impurity detection
    pred_final = calc_positions_np(cand_arr, a, b, c, wavelength, zs)
    valid_mask_f = pred_final < 200
    pred_valid_f = pred_final[valid_mask_f].tolist()
    cand_valid_f = [candidates[i] for i in range(len(candidates)) if valid_mask_f[i]]

    # Use a generous threshold first
    all_assignments = match_peaks_final(observed, pred_valid_f, cand_valid_f, 0.1)

    # Compute per-peak residuals
    clean_assignments = {}
    for oi, (pi, hkl, pred_tt) in all_assignments.items():
        tt_calc = calc_positions_np(
            np.array([hkl], dtype=float), a, b, c, wavelength, zs
        )[0]
        res = abs(observed[oi] - tt_calc)
        if res < 0.04:  # tight threshold for clean assignment
            clean_assignments[oi] = (pi, hkl, float(tt_calc))

    # Final re-refinement with clean peaks only
    if len(clean_assignments) >= 50:
        obs_indices = sorted(clean_assignments.keys())
        obs_vals = np.array([observed[i] for i in obs_indices])
        hkl_arr = np.array([clean_assignments[i][1] for i in obs_indices], dtype=float)

        def residuals_final(params):
            aa, bb, cc, zzs = params
            p = calc_positions_np(hkl_arr, aa, bb, cc, wavelength, zzs)
            return obs_vals - p

        res = least_squares(
            residuals_final,
            x0=[a, b, c, zs],
            bounds=([5, 3, 4, -1], [12, 8, 10, 1]),
            method='trf',
            ftol=1e-15, xtol=1e-15, gtol=1e-15,
            max_nfev=10000,
        )
        a, b, c, zs = res.x

    # Final matching
    pred_final2 = calc_positions_np(cand_arr, a, b, c, wavelength, zs)
    valid_mask2 = pred_final2 < 200
    pred_valid2 = pred_final2[valid_mask2].tolist()
    cand_valid2 = [candidates[i] for i in range(len(candidates)) if valid_mask2[i]]
    final_assignments = match_peaks_final(observed, pred_valid2, cand_valid2, 0.05)

    # Build output
    peak_assignments = []
    n_indexed = 0
    n_impurity = 0
    indexed_sq_residuals = []

    for i in range(len(observed)):
        if i in final_assignments:
            _, hkl, _ = final_assignments[i]
            tt_calc = calc_positions_np(
                np.array([hkl], dtype=float), a, b, c, wavelength, zs
            )[0]
            res = observed[i] - tt_calc
            indexed_sq_residuals.append(res ** 2)
            peak_assignments.append({
                "peak_index": i,
                "two_theta_observed": round(observed[i], 4),
                "hkl": [int(x) for x in hkl],
                "two_theta_calculated": round(float(tt_calc), 4),
                "is_impurity": False,
            })
            n_indexed += 1
        else:
            peak_assignments.append({
                "peak_index": i,
                "two_theta_observed": round(observed[i], 4),
                "hkl": None,
                "two_theta_calculated": None,
                "is_impurity": True,
            })
            n_impurity += 1

    rms_final = math.sqrt(sum(indexed_sq_residuals) / max(len(indexed_sq_residuals), 1))

    results = {
        "refined_lattice_parameters_angstrom": {
            "a": round(float(a), 5),
            "b": round(float(b), 5),
            "c": round(float(c), 5),
        },
        "zero_shift_degrees": round(float(zs), 5),
        "peak_assignments": peak_assignments,
        "rms_residual_degrees": round(float(rms_final), 6),
        "n_indexed": n_indexed,
        "n_impurity": n_impurity,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nFinal: a={a:.5f}, b={b:.5f}, c={c:.5f}, zero={zs:.5f}")
    print(f"Indexed: {n_indexed}, Impurity: {n_impurity}, RMS: {rms_final:.6f}")


if __name__ == "__main__":
    main()
