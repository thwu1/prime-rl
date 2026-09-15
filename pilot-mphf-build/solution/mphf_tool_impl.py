#!/usr/bin/env python3
"""
mphf_tool_impl.py — CLI front-end for libmphf.so (ctypes).

"""

import argparse
import ctypes
import sys

# ------------------------------------------------------------------ #
# Load the shared library and declare function signatures              #
# ------------------------------------------------------------------ #
_lib = ctypes.CDLL("/app/libmphf.so")

_lib.mphf_build.restype  = ctypes.c_void_p
_lib.mphf_build.argtypes = [
    ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
    ctypes.c_double, ctypes.c_double,
]

_lib.mphf_query.restype  = ctypes.c_uint64
_lib.mphf_query.argtypes = [ctypes.c_void_p, ctypes.c_uint64]

_lib.mphf_bits_per_key.restype  = ctypes.c_double
_lib.mphf_bits_per_key.argtypes = [ctypes.c_void_p]

_lib.mphf_save.restype  = ctypes.c_int
_lib.mphf_save.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

_lib.mphf_load.restype  = ctypes.c_void_p
_lib.mphf_load.argtypes = [ctypes.c_char_p]

_lib.mphf_free.restype  = None
_lib.mphf_free.argtypes = [ctypes.c_void_p]

_lib.mphf_key_count.restype  = ctypes.c_size_t
_lib.mphf_key_count.argtypes = [ctypes.c_void_p]

_lib.mphf_pilots_bytes.restype  = ctypes.c_size_t
_lib.mphf_pilots_bytes.argtypes = [ctypes.c_void_p]

_lib.mphf_remap_bytes.restype  = ctypes.c_size_t
_lib.mphf_remap_bytes.argtypes = [ctypes.c_void_p]

_lib.mphf_remap_count.restype  = ctypes.c_size_t
_lib.mphf_remap_count.argtypes = [ctypes.c_void_p]


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #
def _read_keys(path):
    with open(path) as fh:
        return [int(line) for line in fh if line.strip()]


# ------------------------------------------------------------------ #
# Sub-commands                                                         #
# ------------------------------------------------------------------ #
def cmd_build(args):
    keys = _read_keys(args.keyfile)
    n = len(keys)
    arr = (ctypes.c_uint64 * n)(*keys)
    mf = _lib.mphf_build(arr, n, args.alpha, args.lam)
    if not mf:
        print("error: MPHF construction failed", file=sys.stderr)
        sys.exit(1)
    rc = _lib.mphf_save(mf, args.output.encode())
    _lib.mphf_free(mf)
    if rc != 0:
        print("error: failed to write output file", file=sys.stderr)
        sys.exit(1)


def cmd_query(args):
    mf = _lib.mphf_load(args.mphf_file.encode())
    if not mf:
        print("error: failed to load MPHF", file=sys.stderr)
        sys.exit(1)
    keys = _read_keys(args.keyfile)
    out = []
    for k in keys:
        out.append(str(_lib.mphf_query(mf, k)))
    _lib.mphf_free(mf)
    sys.stdout.write("\n".join(out) + "\n")


def cmd_info(args):
    mf = _lib.mphf_load(args.mphf_file.encode())
    if not mf:
        print("error: failed to load MPHF", file=sys.stderr)
        sys.exit(1)
    n = _lib.mphf_key_count(mf)
    total_bpk = _lib.mphf_bits_per_key(mf)
    pilots_b = _lib.mphf_pilots_bytes(mf)
    remap_b = _lib.mphf_remap_bytes(mf)
    remap_c = _lib.mphf_remap_count(mf)
    _lib.mphf_free(mf)

    pilots_bpk = 8.0 * pilots_b / n if n > 0 else 0.0
    remap_bpk = 8.0 * remap_b / n if n > 0 else 0.0
    remap_frac = remap_c / n if n > 0 else 0.0

    print(f"total_bits_per_key={total_bpk:.6f}")
    print(f"pilots_bits_per_key={pilots_bpk:.6f}")
    print(f"remap_bits_per_key={remap_bpk:.6f}")
    print(f"remap_fraction={remap_frac:.6f}")


# ------------------------------------------------------------------ #
# Argument parsing                                                     #
# ------------------------------------------------------------------ #
def main():
    ap = argparse.ArgumentParser(description="MPHF CLI tool")
    sub = ap.add_subparsers(dest="cmd")

    p_build = sub.add_parser("build")
    p_build.add_argument("keyfile")
    p_build.add_argument("output")
    p_build.add_argument("--alpha", type=float, default=0.98)
    p_build.add_argument("--lambda", type=float, default=3.0, dest="lam")

    p_query = sub.add_parser("query")
    p_query.add_argument("mphf_file")
    p_query.add_argument("keyfile")

    p_info = sub.add_parser("info")
    p_info.add_argument("mphf_file")

    args = ap.parse_args()
    if args.cmd == "build":
        cmd_build(args)
    elif args.cmd == "query":
        cmd_query(args)
    elif args.cmd == "info":
        cmd_info(args)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
