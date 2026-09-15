#!/usr/bin/env python3
"""Diagnostic script for the NF4 quantization codec.

Checks each subsystem against reference data and reports pass/fail.
Run with: python3 /app/validate.py
"""

import sys
import os
import math
import struct

sys.path.insert(0, "/app")

from codec import (
    create_nf4_map,
    quantize_blockwise_nf4,
    dequantize_blockwise_nf4,
    double_quantize,
    double_dequantize,
    compute_memory_bits_per_param,
)

REFERENCE_NF4 = [
    -1.0, -0.6961928009986877, -0.5250730514526367, -0.39491748809814453,
    -0.28444138169288635, -0.18477343022823334, -0.09105003625154495, 0.0,
    0.07958029955625534, 0.16093020141124725, 0.24611230194568634, 0.33791524171829224,
    0.44070982933044434, 0.5626170039176941, 0.7229568362236023, 1.0,
]


def check_nf4_map():
    print("=== NF4 Quantization Map ===")
    try:
        nf4 = create_nf4_map()
    except Exception as e:
        print(f"FAIL: {e}")
        return False

    if len(nf4) != 16:
        print(f"FAIL: expected 16 values, got {len(nf4)}")
        return False

    max_diff = 0.0
    max_diff_idx = 0
    for i, (computed, ref) in enumerate(zip(nf4, REFERENCE_NF4)):
        diff = abs(computed - ref)
        if diff > max_diff:
            max_diff = diff
            max_diff_idx = i

    if max_diff < 1e-3:
        print("PASS")
        return True
    else:
        print(f"FAIL: max deviation from reference = {max_diff:.6f} at index {max_diff_idx}")
        print(f"  computed[{max_diff_idx}] = {nf4[max_diff_idx]:.10f}")
        print(f"  expected[{max_diff_idx}] = {REFERENCE_NF4[max_diff_idx]:.10f}")
        return False


def check_blockwise():
    print("\n=== Blockwise Quantization ===")
    ok = True
    try:
        # Test with all-negative block
        neg_data = [-4.0, -3.0, -2.0, -1.0]
        qstate = quantize_blockwise_nf4(neg_data, blocksize=4)

        if abs(qstate["absmax"][0] - 4.0) > 1e-6:
            print(f"  FAIL: absmax for all-negative block = {qstate['absmax'][0]} (expected 4.0)")
            ok = False

        recon = dequantize_blockwise_nf4(qstate)
        max_err = max(abs(o - r) for o, r in zip(neg_data, recon))
        if max_err > 1.0:
            print(f"  FAIL: all-negative block max error = {max_err:.4f} (threshold: 1.0)")
            ok = False

        # Test with mixed-sign block
        mixed_data = [0.5, -0.3, 0.2, -0.9]
        qstate_mix = quantize_blockwise_nf4(mixed_data, blocksize=4)
        if abs(qstate_mix["absmax"][0] - 0.9) > 1e-6:
            print(f"  FAIL: absmax for mixed block = {qstate_mix['absmax'][0]} (expected 0.9)")
            ok = False

    except Exception as e:
        print(f"  FAIL: {e}")
        return False

    if ok:
        print("PASS")
    else:
        print("FAIL")
    return ok


def check_double_quant():
    print("\n=== Double Quantization ===")
    try:
        absmax_values = [1.5, 2.3, 0.8, 1.1, 3.0, 0.5, 1.9, 2.7]
        dq_state = double_quantize(absmax_values, inner_blocksize=4)
        recovered = double_dequantize(dq_state)

        max_err = max(abs(o - r) for o, r in zip(absmax_values, recovered))
        signed_errors = [r - o for o, r in zip(absmax_values, recovered)]
        mean_bias = sum(signed_errors) / len(signed_errors)

        ok = True
        if max_err > 0.15:
            print(f"  FAIL: roundtrip max error = {max_err:.4f} (threshold: 0.15)")
            ok = False
        if abs(mean_bias) > 0.05:
            print(f"  FAIL: mean signed error = {mean_bias:.4f} (threshold: 0.05)")
            ok = False

        if ok:
            print("PASS")
        else:
            print("FAIL")
        return ok
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def check_nibble_packing():
    print("\n=== Nibble Packing ===")
    try:
        from codec import pack_nibbles, unpack_nibbles
        test_indices = [5, 10, 3, 7, 0, 15]
        packed = pack_nibbles(test_indices)
        unpacked = unpack_nibbles(packed, len(test_indices))
        if unpacked != test_indices:
            print(f"FAIL: roundtrip mismatch")
            print(f"  input:  {test_indices}")
            print(f"  output: {unpacked}")
            return False
        print("PASS")
        return True
    except NotImplementedError:
        print("FAIL: nibble pack/unpack not implemented")
        return False
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def check_checkpoint():
    print("\n=== Checkpoint I/O ===")
    ref_path = "/app/reference.nf4"
    if not os.path.exists(ref_path):
        print("SKIP: reference.nf4 not found")
        return True

    try:
        from codec import read_checkpoint
        qstate = read_checkpoint(ref_path)

        ok = True
        if qstate["num_elements"] != 32:
            print(f"  FAIL: num_elements = {qstate['num_elements']} (expected 32)")
            ok = False
        if qstate["blocksize"] != 16:
            print(f"  FAIL: blocksize = {qstate['blocksize']} (expected 16)")
            ok = False

        expected_indices = [
            15, 0, 12, 2, 7, 14, 0, 10, 11, 3, 9, 5, 13, 1, 8, 6,
            4, 15, 10, 7, 2, 12, 5, 9, 0, 14, 3, 11, 8, 1, 6, 13,
        ]
        if qstate["indices"] != expected_indices:
            mismatches = sum(1 for a, b in zip(expected_indices, qstate["indices"]) if a != b)
            print(f"  FAIL: {mismatches}/{len(expected_indices)} indices mismatched")
            ok = False

        if ok:
            print("PASS")
        else:
            print("FAIL")
        return ok
    except NotImplementedError:
        print("FAIL: checkpoint I/O not implemented")
        return False
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


def check_memory_formulas():
    print("\n=== Memory Footprint ===")
    tests = [
        (64, False, 256, 4.5),
        (32, False, 256, 5.0),
        (128, False, 256, 4.25),
        (64, True, 256, 4.0 + 8.0 / 64.0 + 32.0 / (64.0 * 256.0)),
    ]
    ok = True
    for bs, dq, ibs, expected in tests:
        got = compute_memory_bits_per_param(bs, dq, ibs)
        if abs(got - expected) > 1e-6:
            print(f"  FAIL: blocksize={bs}, dq={dq}: got {got:.6f}, expected {expected:.6f}")
            ok = False
    if ok:
        print("PASS")
    else:
        print("FAIL")
    return ok


if __name__ == "__main__":
    results = [
        check_nf4_map(),
        check_blockwise(),
        check_double_quant(),
        check_nibble_packing(),
        check_checkpoint(),
        check_memory_formulas(),
    ]

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} checks passed")

    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print("VALIDATION FAILED")
        sys.exit(1)
