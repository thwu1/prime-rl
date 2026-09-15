#!/usr/bin/env python3
"""Generate 3-channel DFG LUT and print diagnostics for validation."""
import json
import sys

from brdf import D_GGX, V_SmithGGXCorrelated, F_Schlick, D_Charlie, V_Neubelt
from sampling import importance_sample_GGX, importance_sample_Charlie
from dfg_generator import compute_dfg, compute_dfg_cloth, compute_dfg_multiscatter


def main():
    print("=== GGX BRDF Function Diagnostics ===")
    print(f"D_GGX(NoH=1.0, alpha=0.5)     = {D_GGX(1.0, 0.5):.6f}")
    print(f"D_GGX(NoH=0.5, alpha=0.5)     = {D_GGX(0.5, 0.5):.6f}")
    print(f"D_GGX(NoH=1.0, alpha=1.0)     = {D_GGX(1.0, 1.0):.6f}")
    print()
    print(f"V_Smith(0.5, 0.5, 0.5)        = {V_SmithGGXCorrelated(0.5, 0.5, 0.5):.6f}")
    print(f"V_Smith(1.0, 1.0, 0.5)        = {V_SmithGGXCorrelated(1.0, 1.0, 0.5):.6f}")
    print(f"V_Smith(0.8, 0.6, 0.3)        = {V_SmithGGXCorrelated(0.8, 0.6, 0.3):.6f}")
    print()
    print(f"F_Schlick(0.5, 0.04)           = {F_Schlick(0.5, 0.04):.6f}")
    print(f"F_Schlick(0.0, 0.04)           = {F_Schlick(0.0, 0.04):.6f}")
    print(f"F_Schlick(1.0, 0.04)           = {F_Schlick(1.0, 0.04):.6f}")

    print("\n=== Cloth BRDF Function Diagnostics ===")
    print(f"D_Charlie(NoH=0.8, rough=0.5)  = {D_Charlie(0.8, 0.5):.6f}")
    print(f"D_Charlie(NoH=0.5, rough=0.5)  = {D_Charlie(0.5, 0.5):.6f}")
    print(f"D_Charlie(NoH=1.0, rough=0.5)  = {D_Charlie(1.0, 0.5):.6f}")
    print()
    print(f"V_Neubelt(0.5, 0.7)            = {V_Neubelt(0.5, 0.7):.6f}")
    print(f"V_Neubelt(0.5, 0.5)            = {V_Neubelt(0.5, 0.5):.6f}")

    print("\n=== Importance Sampling Diagnostics ===")
    H = importance_sample_GGX(0.0, 0.5, 0.5)
    print(f"sample_GGX(0.0, 0.5, alpha=0.5)     = ({H[0]:.6f}, {H[1]:.6f}, {H[2]:.6f})")
    H = importance_sample_Charlie(0.0, 0.5, 0.5)
    print(f"sample_Charlie(0.0, 0.5, rough=0.5)  = ({H[0]:.6f}, {H[1]:.6f}, {H[2]:.6f})")

    print("\n=== DFG LUT Values ===")
    test_points = [
        (0.1, 0.1), (0.1, 0.5), (0.1, 0.9),
        (0.5, 0.1), (0.5, 0.5), (0.5, 0.9),
        (0.9, 0.1), (0.9, 0.5), (0.9, 0.9),
    ]

    results = {}
    for NoV, roughness in test_points:
        sx, sy = compute_dfg(NoV, roughness, num_samples=2048)
        cloth = compute_dfg_cloth(NoV, roughness, num_samples=2048)
        mx, my, e_avg = compute_dfg_multiscatter(NoV, roughness, num_samples=2048)
        key = f"NoV={NoV}, rough={roughness}"
        results[key] = {
            "standard": {"x": round(sx, 6), "y": round(sy, 6)},
            "cloth": round(cloth, 6),
            "multiscatter": {"x": round(mx, 6), "y": round(my, 6), "E_avg": round(e_avg, 6)},
        }
        print(f"  {key}:")
        print(f"    std=({sx:.4f}, {sy:.4f})  cloth={cloth:.4f}  ms=({mx:.4f}, {my:.4f})  E_avg={e_avg:.4f}")

    with open('/app/output_lut.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to /app/output_lut.json")


if __name__ == '__main__':
    main()
