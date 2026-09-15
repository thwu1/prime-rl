#!/usr/bin/env python3
"""
BRDF Evaluation Driver

Loads the compiled C shared library via ctypes, reads evaluation configurations
from config.json, and writes computed results to output.json.

"""

import ctypes
import json
import os
import sys


# ---------- ctypes struct definitions (must match brdf.h) ----------

class Material(ctypes.Structure):
    _fields_ = [
        ("baseColor", ctypes.c_float * 3),
        ("metallic", ctypes.c_float),
        ("roughness", ctypes.c_float),
        ("reflectance", ctypes.c_float),
        ("clearCoat", ctypes.c_float),
        ("clearCoatRoughness", ctypes.c_float),
    ]


class BRDFResult(ctypes.Structure):
    _fields_ = [
        ("specular", ctypes.c_float * 3),
        ("diffuse", ctypes.c_float * 3),
        ("total", ctypes.c_float * 3),
        ("clearcoat_specular", ctypes.c_float),
    ]


class DFGResult(ctypes.Structure):
    _fields_ = [
        ("dfg1", ctypes.c_float),
        ("dfg2", ctypes.c_float),
    ]


class EnergyCompResult(ctypes.Structure):
    _fields_ = [
        ("E", ctypes.c_float),
        ("compensation", ctypes.c_float * 3),
    ]


# ---------- Library loading ----------

def load_library():
    base = os.path.dirname(os.path.abspath(__file__))
    lib_path = os.path.join(base, "build", "libbrdf.so")
    if not os.path.exists(lib_path):
        print(f"Error: Shared library not found at {lib_path}", file=sys.stderr)
        print("Build first: cd /app && mkdir -p build && cd build && cmake .. && make",
              file=sys.stderr)
        sys.exit(1)

    lib = ctypes.CDLL(lib_path)

    lib.compute_dfg.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_int]
    lib.compute_dfg.restype = DFGResult

    lib.evaluate_standard_brdf.argtypes = [
        ctypes.c_float, ctypes.c_float, ctypes.c_float, Material
    ]
    lib.evaluate_standard_brdf.restype = BRDFResult

    lib.evaluate_clearcoat_brdf.argtypes = [
        ctypes.c_float, ctypes.c_float, ctypes.c_float, Material
    ]
    lib.evaluate_clearcoat_brdf.restype = BRDFResult

    lib.compute_energy_compensation.argtypes = [
        ctypes.c_float, ctypes.c_float, ctypes.c_float * 3, ctypes.c_int
    ]
    lib.compute_energy_compensation.restype = EnergyCompResult

    return lib


def make_material(m):
    """Create a Material struct from a config dictionary."""
    mat = Material()
    bc = (ctypes.c_float * 3)(*m["baseColor"])
    mat.baseColor = bc
    mat.roughness = m["roughness"]
    mat.metallic = m["metallic"]
    mat.reflectance = m["reflectance"]
    mat.clearCoat = m.get("clearCoat", 0.0)
    mat.clearCoatRoughness = m.get("clearCoatRoughness", 0.0)
    return mat


def main():
    lib = load_library()

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "config.json")
    with open(config_path) as f:
        config = json.load(f)

    results = {}

    # DFG evaluations
    for ev in config["dfg_evaluations"]:
        r = lib.compute_dfg(ev["NoV"], ev["perceptual_roughness"],
                            ev["num_samples"])
        results[ev["id"]] = {
            "dfg1": round(float(r.dfg1), 6),
            "dfg2": round(float(r.dfg2), 6),
        }

    # Standard BRDF evaluations
    for ev in config["brdf_evaluations"]:
        mat = make_material(ev["material"])
        r = lib.evaluate_standard_brdf(ev["theta_v"], ev["theta_l"],
                                       ev["phi_l"], mat)
        results[ev["id"]] = {
            "specular": [round(float(r.specular[i]), 6) for i in range(3)],
            "diffuse":  [round(float(r.diffuse[i]), 6)  for i in range(3)],
            "total":    [round(float(r.total[i]), 6)    for i in range(3)],
        }

    # Clear coat evaluations
    for ev in config["clear_coat_evaluations"]:
        mat = make_material(ev["material"])
        r = lib.evaluate_clearcoat_brdf(ev["theta_v"], ev["theta_l"],
                                        ev["phi_l"], mat)
        results[ev["id"]] = {
            "specular": [round(float(r.specular[i]), 6) for i in range(3)],
            "diffuse":  [round(float(r.diffuse[i]), 6)  for i in range(3)],
            "clearcoat_specular": round(float(r.clearcoat_specular), 6),
            "total":    [round(float(r.total[i]), 6)    for i in range(3)],
        }

    # Energy compensation
    for ev in config["energy_compensation"]:
        f0_arr = (ctypes.c_float * 3)(*ev["f0"])
        r = lib.compute_energy_compensation(
            ev["NoV"], ev["perceptual_roughness"], f0_arr, 1024
        )
        results[ev["id"]] = {
            "E": round(float(r.E), 6),
            "compensation": [round(float(r.compensation[i]), 6)
                             for i in range(3)],
        }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "output.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
