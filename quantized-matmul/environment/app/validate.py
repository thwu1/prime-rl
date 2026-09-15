#!/usr/bin/env python3
"""Validate adaptive_quantized_matmul — runs each test in a subprocess to survive crashes."""


import subprocess
import sys
import os

RUNNER_SCRIPT = r'''
import ctypes, sys, random, json, os

lib = ctypes.CDLL("/app/libqmatmul.so")
lib.adaptive_quantized_matmul.restype = ctypes.c_int
lib.adaptive_quantized_matmul.argtypes = [
    ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(ctypes.c_float), ctypes.c_int,
    ctypes.POINTER(ctypes.c_float), ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
]
lib.reference_matmul.restype = None
lib.reference_matmul.argtypes = [
    ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(ctypes.c_float), ctypes.c_int,
    ctypes.POINTER(ctypes.c_float),
]
lib.quantized_matmul.restype = ctypes.c_int
lib.quantized_matmul.argtypes = [
    ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(ctypes.c_float), ctypes.c_int,
    ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int,
]

cfg = json.loads(os.environ["TEST_CFG"])
M, K, N = cfg["M"], cfg["K"], cfg["N"]
bs, rtol = cfg["bs"], cfg["rtol"]
lo, hi = cfg.get("lo"), cfg.get("hi")
check_beats_sym = cfg.get("check_beats_sym", False)

random.seed(cfg["seed_a"])
if lo is not None:
    A = (ctypes.c_float * (M * K))(*[random.uniform(lo, hi) for _ in range(M * K)])
else:
    A = (ctypes.c_float * (M * K))(*[random.gauss(0, 1) for _ in range(M * K)])

random.seed(cfg["seed_b"])
if lo is not None:
    B = (ctypes.c_float * (K * N))(*[random.uniform(lo, hi) for _ in range(K * N)])
else:
    B = (ctypes.c_float * (K * N))(*[random.gauss(0, 1) for _ in range(K * N)])

C_ref = (ctypes.c_float * (M * N))(*([0.0] * (M * N)))
C_q   = (ctypes.c_float * (M * N))(*([0.0] * (M * N)))
stats = (ctypes.c_int * 2)(0, 0)

lib.reference_matmul(A, M, K, B, N, C_ref)
ret = lib.adaptive_quantized_matmul(A, M, K, B, N, C_q, bs,
                                     ctypes.cast(stats, ctypes.POINTER(ctypes.c_int)))
if ret != 0:
    print("FAIL: returned %d (stub not implemented?)" % ret)
    sys.exit(1)

max_err = 0.0
ref_max = 0.0
for i in range(M * N):
    v = C_q[i]
    if v != v:
        print("FAIL: NaN in output")
        sys.exit(1)
    d = abs(C_ref[i] - v)
    if d > max_err: max_err = d
    r = abs(C_ref[i])
    if r > ref_max: ref_max = r

rel_err = max_err / (ref_max + 1e-10)
if rel_err >= rtol:
    print("FAIL: relative error %.6f >= %.4f" % (rel_err, rtol))
    sys.exit(1)

msg = "PASS: rel_err=%.6f, sym=%d, asym=%d" % (rel_err, stats[0], stats[1])

if check_beats_sym:
    C_sym = (ctypes.c_float * (M * N))(*([0.0] * (M * N)))
    lib.quantized_matmul(A, M, K, B, N, C_sym, bs, 0)
    sym_err = 0.0
    for i in range(M * N):
        d = abs(C_ref[i] - C_sym[i])
        if d > sym_err: sym_err = d
    sym_rel = sym_err / (ref_max + 1e-10)
    if rel_err >= sym_rel:
        print("FAIL: adaptive err %.6f >= symmetric err %.6f" % (rel_err, sym_rel))
        sys.exit(1)
    msg += " (beats sym %.6f)" % sym_rel

print(msg)
'''

CASES = [
    # (name,                      M,  K,  N, bs, seed_a, seed_b, rtol,  lo,    hi,   beats_sym)
    ("centered_8x8",              8,  8,  8,  4,  42,    142,   0.15,  None,  None, False),
    ("biased_16x16",             16, 16, 16,  8,  43,    143,   0.15,  10.0,  20.0, False),
    ("unaligned_17x11",          17,  9, 11,  4,  44,    144,   0.15,  None,  None, False),
    ("large_32x32",              32, 32, 32,  8,  45,    145,   0.15,  None,  None, False),
    ("biased_beats_symmetric",   32, 32, 32,  8,  46,    146,   0.15,  10.0,  20.0, True),
]


def main():
    so_path = "/app/libqmatmul.so"
    if not os.path.exists(so_path):
        print("ERROR: %s not found. Run 'make' in /app/ first." % so_path)
        sys.exit(1)

    print("Validating adaptive_quantized_matmul...\n")
    passed = 0
    total = len(CASES)

    for name, M, K, N, bs, seed_a, seed_b, rtol, lo, hi, beats_sym in CASES:
        import json as _json
        cfg = _json.dumps({
            "M": M, "K": K, "N": N, "bs": bs,
            "seed_a": seed_a, "seed_b": seed_b, "rtol": rtol,
            "lo": lo, "hi": hi, "check_beats_sym": beats_sym,
        })
        env = dict(os.environ)
        env["TEST_CFG"] = cfg

        try:
            result = subprocess.run(
                [sys.executable, "-c", RUNNER_SCRIPT],
                capture_output=True, text=True, timeout=30, env=env,
            )
            if result.returncode == 0:
                print("  %s: %s" % (name, result.stdout.strip()))
                passed += 1
            elif result.returncode < 0:
                import signal
                sig = -result.returncode
                try:
                    signame = signal.Signals(sig).name
                except (ValueError, AttributeError):
                    signame = "signal %d" % sig
                print("  %s: CRASH (%s)" % (name, signame))
            else:
                output = result.stdout.strip() or result.stderr.strip().split('\n')[-1]
                print("  %s: %s" % (name, output))
        except subprocess.TimeoutExpired:
            print("  %s: TIMEOUT" % name)

    print("\n%d/%d tests passed" % (passed, total))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
