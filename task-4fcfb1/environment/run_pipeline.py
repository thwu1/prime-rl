#!/usr/bin/env python3
"""
Driver for the Gaussian basis rotation pipeline.
Reads config.json, calls gauss_basis functions, writes results.json.

"""
import json
import sys
import numpy as np

sys.path.insert(0, '/app')

from gauss_basis import (
    cartesian_powers,
    overlap_matrix,
    cartesian_rotation_matrix,
    spherical_to_cartesian_matrix,
    spherical_rotation_matrix,
)


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    results = {}

    for l in config["angular_momenta"]:
        l_key = f"l_{l}"
        l_results = {}

        powers = cartesian_powers(l)
        l_results["n_cartesian"] = len(powers)
        l_results["n_spherical"] = 2 * l + 1
        l_results["powers"] = [list(p) for p in powers]

        S = overlap_matrix(l)
        l_results["overlap_matrix"] = S.tolist()

        c = spherical_to_cartesian_matrix(l)
        l_results["c_matrix"] = c.tolist()

        cScT = c @ S @ c.T
        l_results["cScT_is_identity"] = bool(
            np.allclose(cScT, np.eye(2 * l + 1), atol=1e-12)
        )

        c_inv = S @ c.T
        l_results["c_inverse"] = c_inv.tolist()

        for rot in config["rotations"]:
            R = np.array(rot["matrix"])
            rot_name = rot["name"]

            R_cart = cartesian_rotation_matrix(l, R)

            RtSR = R_cart.T @ S @ R_cart
            preserves_overlap = bool(np.allclose(RtSR, S, atol=1e-12))

            R_sph = spherical_rotation_matrix(l, R, c, S)

            RtR = R_sph.T @ R_sph
            is_orthogonal = bool(
                np.allclose(RtR, np.eye(2 * l + 1), atol=1e-12)
            )

            det_val = float(np.linalg.det(R_sph))

            l_results[rot_name] = {
                "cartesian_rotation": R_cart.tolist(),
                "preserves_overlap": preserves_overlap,
                "spherical_rotation": R_sph.tolist(),
                "is_orthogonal": is_orthogonal,
                "determinant": det_val,
            }

        results[l_key] = l_results

    # Group property test: R_z(30) composed twice should equal R_z(60)
    R30 = np.array(config["rotations"][0]["matrix"])
    cos60, sin60 = 0.5, 0.8660254037844387
    R60 = np.array([[cos60, -sin60, 0], [sin60, cos60, 0], [0, 0, 1]])

    group_results = {}
    for l in config["angular_momenta"]:
        c = spherical_to_cartesian_matrix(l)
        S = overlap_matrix(l)
        R_sph_30 = spherical_rotation_matrix(l, R30, c, S)
        R_sph_60 = spherical_rotation_matrix(l, R60, c, S)
        R_composed = R_sph_30 @ R_sph_30
        group_results[f"l_{l}"] = bool(
            np.allclose(R_composed, R_sph_60, atol=1e-10)
        )

    results["group_property"] = group_results

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Pipeline complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
