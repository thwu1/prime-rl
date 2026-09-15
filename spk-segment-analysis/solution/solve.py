#!/usr/bin/env python3

"""
Solution: SPK Segment Forensics and Interpolation Accuracy Benchmark

Performs five analyses on the DE432s planetary ephemeris:
1. Extracts Type 2 segment metadata via DAF API
2. Manually evaluates Chebyshev polynomials using Clenshaw recurrence
3. Cross-validates manual evaluation against spkgeo
4. Benchmarks Chebyshev least-squares fitting at various degrees
5. Creates a Type 13 Hermite SPK and measures interpolation error
"""

import json
import sys

import numpy as np
import spiceypy as spice


# ---------------------------------------------------------------------------
# Clenshaw recurrence for Chebyshev polynomial evaluation
# ---------------------------------------------------------------------------

def clenshaw_chebyshev(coeffs, x):
    """Evaluate sum_{i=0}^{n-1} c_i T_i(x) using Clenshaw recurrence.

    Parameters
    ----------
    coeffs : array-like  — Chebyshev coefficients [c0, c1, ..., c_{n-1}]
    x      : float       — evaluation point in [-1, 1]

    Returns
    -------
    float — value of the Chebyshev series at x
    """
    n = len(coeffs)
    if n == 0:
        return 0.0
    if n == 1:
        return float(coeffs[0])

    bk2 = 0.0
    bk1 = 0.0
    for i in range(n - 1, 0, -1):
        bk = 2.0 * x * bk1 - bk2 + float(coeffs[i])
        bk2 = bk1
        bk1 = bk
    return x * bk1 - bk2 + float(coeffs[0])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    spice.furnsh("/app/data/naif0012.tls")
    spice.furnsh("/app/data/de432s.bsp")

    # ===================================================================
    # STEP 1 — Extract Type 2 segment metadata for EMB (body 3, center 0)
    # ===================================================================
    print("=== Step 1: Segment metadata extraction ===")

    handle = spice.dafopr("/app/data/de432s.bsp")
    spice.dafbfs(handle)

    seg_found = False
    begin_addr = end_addr = 0

    while spice.daffna():
        summary = spice.dafgs(n=128)
        dc, ic = spice.dafus(summary, 2, 6)

        body_id   = int(ic[0])
        center_id = int(ic[1])
        data_type = int(ic[3])

        if body_id == 3 and center_id == 0 and data_type == 2:
            seg_found = True
            begin_addr = int(ic[4])
            end_addr   = int(ic[5])
            print(f"  Segment found — DAF addresses [{begin_addr}, {end_addr}]")
            break

    if not seg_found:
        print("ERROR: EMB Type 2 segment not found in DE432s")
        sys.exit(1)

    # Read the 4-value footer: INIT, INTLEN, RSIZE, N
    footer = spice.dafgda(handle, end_addr - 3, end_addr)
    init_epoch = footer[0]
    intlen     = footer[1]
    rsize      = int(footer[2])
    n_records  = int(footer[3])

    n_coeffs   = (rsize - 2) // 3
    poly_degree = n_coeffs - 1

    metadata = {
        "poly_degree": poly_degree,
        "n_coeffs_per_component": n_coeffs,
        "rsize": rsize,
        "intlen_seconds": intlen,
        "n_records": n_records,
        "init_epoch_et": init_epoch,
    }
    with open("/app/segment_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  poly_degree={poly_degree}, rsize={rsize}, "
          f"intlen={intlen:.1f}s, n_records={n_records}")

    # ===================================================================
    # STEP 2 — Manual Chebyshev evaluation at 2020-JAN-01 12:00:00 TDB
    # ===================================================================
    print("\n=== Step 2: Manual Chebyshev evaluation ===")

    eval_et = spice.str2et("2020-JAN-01 12:00:00 TDB")
    print(f"  Target ET = {eval_et:.6f}")

    # Locate the record
    rec_idx = int((eval_et - init_epoch) / intlen)
    assert 0 <= rec_idx < n_records, f"Record index {rec_idx} out of range"

    rec_start = begin_addr + rec_idx * rsize
    rec_end   = rec_start + rsize - 1
    record    = spice.dafgda(handle, rec_start, rec_end)

    mid    = record[0]
    radius = record[1]
    x_coeffs = record[2            : 2 + n_coeffs]
    y_coeffs = record[2 + n_coeffs  : 2 + 2 * n_coeffs]
    z_coeffs = record[2 + 2*n_coeffs: 2 + 3 * n_coeffs]

    # Normalize epoch to [-1, 1]
    s = (eval_et - mid) / radius
    print(f"  Record MID={mid:.6f}, RADIUS={radius:.1f}, s={s:.10f}")

    x_pos = clenshaw_chebyshev(x_coeffs, s)
    y_pos = clenshaw_chebyshev(y_coeffs, s)
    z_pos = clenshaw_chebyshev(z_coeffs, s)

    manual_pos = {"x_km": x_pos, "y_km": y_pos, "z_km": z_pos}
    with open("/app/manual_position.json", "w") as f:
        json.dump(manual_pos, f, indent=2)

    print(f"  Position: [{x_pos:.6f}, {y_pos:.6f}, {z_pos:.6f}] km")

    spice.dafcls(handle)

    # ===================================================================
    # STEP 3 — Verification against spkgeo
    # ===================================================================
    print("\n=== Step 3: Verification ===")

    state, _ = spice.spkgeo(3, eval_et, "J2000", 0)
    spice_pos = state[:3]

    diff_vec = np.array([x_pos - spice_pos[0],
                         y_pos - spice_pos[1],
                         z_pos - spice_pos[2]])
    verif_error = float(np.linalg.norm(diff_vec))

    with open("/app/verification_error.txt", "w") as f:
        f.write(f"{verif_error:.15e}\n")

    print(f"  |manual - spkgeo| = {verif_error:.2e} km")

    # ===================================================================
    # STEP 4 — Chebyshev fitting accuracy study
    # ===================================================================
    print("\n=== Step 4: Chebyshev fitting accuracy ===")

    et_start = spice.str2et("2020-JAN-01 00:00:00 TDB")
    et_end   = spice.str2et("2020-JUL-01 00:00:00 TDB")

    # 50 sample positions
    n_samples = 50
    sample_ets = np.linspace(et_start, et_end, n_samples)
    sample_pos = np.zeros((n_samples, 3))
    for i, et in enumerate(sample_ets):
        st, _ = spice.spkgeo(3, float(et), "J2000", 0)
        sample_pos[i] = st[:3]

    # 5000 test positions
    n_test = 5000
    test_ets = np.linspace(et_start, et_end, n_test)
    test_pos = np.zeros((n_test, 3))
    for i, et in enumerate(test_ets):
        st, _ = spice.spkgeo(3, float(et), "J2000", 0)
        test_pos[i] = st[:3]

    # Normalize times to [-1, 1]
    span = et_end - et_start
    t_s = 2.0 * (sample_ets - et_start) / span - 1.0
    t_t = 2.0 * (test_ets   - et_start) / span - 1.0

    accuracy = {}
    for degree in [5, 10, 15, 20, 25]:
        max_comp_err = 0.0
        for dim in range(3):
            c = np.polynomial.chebyshev.chebfit(t_s, sample_pos[:, dim], degree)
            fitted = np.polynomial.chebyshev.chebval(t_t, c)
            max_comp_err = max(max_comp_err,
                               float(np.max(np.abs(fitted - test_pos[:, dim]))))
        accuracy[str(degree)] = max_comp_err
        print(f"  Degree {degree:2d}: max error = {max_comp_err:.6e} km")

    with open("/app/chebyshev_accuracy.json", "w") as f:
        json.dump(accuracy, f, indent=2)

    # ===================================================================
    # STEP 5 — Hermite Type 13 SPK creation and accuracy measurement
    # ===================================================================
    print("\n=== Step 5: Hermite SPK construction ===")

    # Sample states at 1-day intervals
    n_days = int((et_end - et_start) / 86400.0)
    hermite_ets = np.array([et_start + i * 86400.0 for i in range(n_days + 1)])
    # Clip to coverage
    hermite_ets = hermite_ets[hermite_ets <= et_end + 1.0]

    hermite_states = np.zeros((len(hermite_ets), 6))
    for i, et in enumerate(hermite_ets):
        st, _ = spice.spkgeo(3, float(et), "J2000", 0)
        hermite_states[i] = st

    print(f"  {len(hermite_ets)} states sampled (days 0..{n_days})")

    # Filter test data to hermite coverage
    mask = (test_ets >= hermite_ets[0]) & (test_ets <= hermite_ets[-1])
    valid_test_ets = test_ets[mask]
    valid_test_pos = test_pos[mask]

    # Write Type 13 SPK
    spk_handle = spice.spkopn("/app/hermite_emb.bsp",
                              "Hermite EMB Ephemeris", 512)
    spice.spkw13(
        spk_handle,
        3,                      # body
        0,                      # center
        "J2000",                # frame
        hermite_ets[0],         # first epoch
        hermite_ets[-1],        # last epoch
        "EMB_HERMITE_TYPE13",   # segment id
        7,                      # polynomial degree
        len(hermite_ets),       # number of states
        hermite_states,
        hermite_ets,
    )
    spice.spkcls(spk_handle)
    print("  Written /app/hermite_emb.bsp")

    # Evaluate max error vs DE432s
    spice.kclear()
    spice.furnsh("/app/data/naif0012.tls")
    spice.furnsh("/app/hermite_emb.bsp")

    hermite_test_pos = np.zeros((len(valid_test_ets), 3))
    for i, et in enumerate(valid_test_ets):
        st, _ = spice.spkgeo(3, float(et), "J2000", 0)
        hermite_test_pos[i] = st[:3]

    pos_errors = np.linalg.norm(valid_test_pos - hermite_test_pos, axis=1)
    hermite_max_error = float(np.max(pos_errors))

    with open("/app/hermite_max_error.txt", "w") as f:
        f.write(f"{hermite_max_error:.15e}\n")

    print(f"  Hermite max position error: {hermite_max_error:.6e} km")
    print("\n=== All steps completed successfully ===")


if __name__ == "__main__":
    main()
