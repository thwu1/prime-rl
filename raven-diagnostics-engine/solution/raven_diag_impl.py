#!/usr/bin/env python3
"""Raven diagnostic CLI - bridges config/data I/O to C shared library via ctypes."""


import argparse
import json
import csv
import ctypes
import sys


def load_data(path):
    obs, mod, wts = [], [], []
    hw = False
    with open(path) as f:
        for row in csv.reader(f):
            if not row:
                continue
            obs.append(float(row[1]))
            mod.append(float(row[2]))
            if len(row) >= 4:
                wts.append(float(row[3]))
                hw = True
            else:
                wts.append(1.0)
    return obs, mod, wts if hw else None, hw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    obs, mod, wts, has_wts = load_data(args.data)
    n = len(obs)

    sd = config.get("start_date", "2000-01-01")
    parts = sd.split("-")
    sy, sm, sday = int(parts[0]), int(parts[1]), int(parts[2])
    ts = config.get("timestep", 1.0)
    bv = config.get("blank_value", -1.2345)
    threshold = config.get("threshold", 0.0)
    comparison = config.get("comparison", "NONE")

    lib = ctypes.CDLL("/app/libdiag.so")
    lib.compute_baseweights.restype = None
    lib.compute_baseweights.argtypes = [
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int,
        ctypes.c_double, ctypes.c_double, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_double)
    ]
    lib.compute_metric.restype = ctypes.c_double
    lib.compute_metric.argtypes = [
        ctypes.c_char_p, ctypes.c_int,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double), ctypes.c_int,
        ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_double
    ]

    DA = ctypes.c_double * n
    c_obs = DA(*obs)
    c_mod = DA(*mod)
    c_wts = DA(*(wts if wts else [1.0] * n))
    c_bw = DA()

    lib.compute_baseweights(c_obs, c_mod, c_wts, 1 if has_wts else 0, n,
                            bv, threshold, comparison.encode(), c_bw)

    results = {}
    for met in config["metrics"]:
        name = met["name"]
        width = met.get("width", 0)
        val = lib.compute_metric(name.encode(), width, c_obs, c_mod, c_bw, n,
                                 ts, sy, sm, sday, bv)
        results[name] = val

    print(json.dumps(results))


if __name__ == "__main__":
    main()
