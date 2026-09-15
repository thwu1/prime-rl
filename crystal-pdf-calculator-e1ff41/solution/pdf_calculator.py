#!/usr/bin/env python3
"""Compute the reduced pair distribution function G(r) for periodic crystal
structures in PDFfit .stru or CIF format.

"""

import argparse
import math
import os
import numpy as np


def parse_stru(filename):
    """Parse a PDFfit .stru file.

    Returns
    -------
    cell_params : list of 6 floats
        a, b, c (angstrom), alpha, beta, gamma (degrees)
    atoms : list of dicts
        Each with keys: element, frac (3-array), occ, uiso (float)
    """
    with open(filename) as fh:
        lines = fh.readlines()

    cell_params = None
    natoms = 0
    atoms = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("cell"):
            vals = stripped.split(None, 1)[1].replace(",", " ").split()
            cell_params = [float(v) for v in vals[:6]]
        elif stripped.startswith("ncell"):
            vals = stripped.split(None, 1)[1].replace(",", " ").split()
            natoms = int(vals[3])
        elif stripped == "atoms":
            i += 1
            for _ in range(natoms):
                parts = lines[i].split()
                elem = parts[0]
                fx, fy, fz = float(parts[1]), float(parts[2]), float(parts[3])
                occ = float(parts[4])
                i += 1
                # Line 2: dx dy dz biso (skip)
                i += 1
                # Line 3: U11 U22 U33
                uparts = lines[i].split()
                u11 = float(uparts[0])
                u22 = float(uparts[1])
                u33 = float(uparts[2])
                i += 1
                # Line 4: U12 U13 U23 (skip)
                i += 1
                # Lines 5-6: additional params (skip)
                i += 1
                i += 1
                uiso = (u11 + u22 + u33) / 3.0
                atoms.append({
                    "element": elem,
                    "frac": np.array([fx, fy, fz]),
                    "occ": occ,
                    "uiso": uiso,
                })
            break
        i += 1

    return cell_params, atoms


def parse_cif(filename):
    """Parse a CIF file using diffpy.structure for symmetry expansion.

    Returns
    -------
    cell_params : list of 6 floats
    atoms : list of dicts (same format as parse_stru)
    """
    from diffpy.structure import loadStructure
    stru = loadStructure(str(filename))
    lat = stru.lattice
    cell_params = [lat.a, lat.b, lat.c, lat.alpha, lat.beta, lat.gamma]
    atoms = []
    for atom in stru:
        uiso = float(atom.Uisoequiv)
        atoms.append({
            "element": atom.element,
            "frac": np.array(atom.xyz, dtype=float),
            "occ": float(atom.occupancy),
            "uiso": uiso,
        })
    return cell_params, atoms


def build_lattice(a, b, c, alpha_deg, beta_deg, gamma_deg):
    """Build the 3x3 matrix of lattice vectors (rows) from cell parameters.

    Uses the standard crystallographic Cartesian convention:
      a along x, b in the xy-plane.
    """
    ar = math.radians(alpha_deg)
    br = math.radians(beta_deg)
    gr = math.radians(gamma_deg)
    ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)
    sg = math.sin(gr)

    ax = a
    bx = b * cg
    by = b * sg
    cx = c * cb
    cy = c * (ca - cb * cg) / sg
    cz = c * math.sqrt(max(0.0, 1.0 - ca**2 - cb**2 - cg**2 + 2*ca*cb*cg)) / sg

    return np.array([
        [ax, 0.0, 0.0],
        [bx, by,  0.0],
        [cx, cy,  cz],
    ])


def compute_pdf(stru_file, rmax, rstep, qdamp=0.0):
    """Compute reduced PDF G(r) for the structure in *stru_file*.

    Returns (r_grid, G_array) as numpy arrays.
    """
    ext = os.path.splitext(stru_file)[1].lower()
    if ext == ".cif":
        cell_params, atoms = parse_cif(stru_file)
    else:
        cell_params, atoms = parse_stru(stru_file)

    a, b, c, alpha, beta, gamma = cell_params
    lat = build_lattice(a, b, c, alpha, beta, gamma)

    # Volume and number density
    vol = abs(np.dot(lat[0], np.cross(lat[1], lat[2])))
    N = len(atoms)
    rho0 = N / vol

    # Cartesian atom positions
    cart = np.array([atom["frac"] @ lat for atom in atoms])

    # Perpendicular heights of the cell (for image range estimation)
    normals = [
        np.cross(lat[1], lat[2]),
        np.cross(lat[2], lat[0]),
        np.cross(lat[0], lat[1]),
    ]
    perp_d = [vol / np.linalg.norm(n) for n in normals]

    # Extend range to capture peak tails
    rmax_ext = rmax + 2.0
    nmax = [int(math.ceil(rmax_ext / d)) + 1 for d in perp_d]

    # Collect pair distances and Gaussian widths
    pair_dists = []
    pair_sigmas = []

    for i in range(N):
        uiso_i = atoms[i]["uiso"]
        for j in range(N):
            uiso_j = atoms[j]["uiso"]
            sigma_sq = uiso_i + uiso_j
            sigma = math.sqrt(sigma_sq) if sigma_sq > 1e-12 else 0.001
            for n1 in range(-nmax[0], nmax[0] + 1):
                for n2 in range(-nmax[1], nmax[1] + 1):
                    for n3 in range(-nmax[2], nmax[2] + 1):
                        if i == j and n1 == 0 and n2 == 0 and n3 == 0:
                            continue
                        shift = n1 * lat[0] + n2 * lat[1] + n3 * lat[2]
                        diff = cart[j] + shift - cart[i]
                        dist = math.sqrt(diff[0]**2 + diff[1]**2 + diff[2]**2)
                        if 0.5 < dist < rmax_ext:
                            pair_dists.append(dist)
                            pair_sigmas.append(sigma)

    pair_dists = np.array(pair_dists, dtype=np.float64)
    pair_sigmas = np.array(pair_sigmas, dtype=np.float64)

    # Build r-grid
    npts = int(round(rmax / rstep)) + 1
    r_grid = np.arange(npts) * rstep  # 0, rstep, ..., rmax

    # Compute G(r) via peak summation
    G = np.zeros(npts, dtype=np.float64)

    # Vectorised Gaussian accumulation (batch to control memory)
    BATCH = 5000
    for start in range(0, len(pair_dists), BATCH):
        end = min(start + BATCH, len(pair_dists))
        d_batch = pair_dists[start:end, np.newaxis]
        s_batch = pair_sigmas[start:end, np.newaxis]
        r_row = r_grid[np.newaxis, :]
        gauss = (1.0 / (s_batch * math.sqrt(2.0 * math.pi))) * np.exp(
            -0.5 * ((r_row - d_batch) / s_batch) ** 2
        )
        G += gauss.sum(axis=0)

    # Normalise: G(r) = (1 / (r * N)) * sum_peaks - 4*pi*r*rho0
    with np.errstate(divide="ignore", invalid="ignore"):
        G = G / (r_grid * N)
    G -= 4.0 * math.pi * r_grid * rho0

    # Apply Q-resolution damping envelope
    if qdamp > 0:
        envelope = np.exp(-0.5 * (qdamp * r_grid) ** 2)
        G *= envelope

    G[0] = 0.0  # G(r=0) = 0 by definition

    return r_grid, G


def main():
    parser = argparse.ArgumentParser(
        description="Compute reduced PDF G(r) from a crystal structure file."
    )
    parser.add_argument("structure", help="Path to .stru or .cif file")
    parser.add_argument("--rmax", type=float, default=10.0)
    parser.add_argument("--rstep", type=float, default=0.01)
    parser.add_argument("--qdamp", type=float, default=0.0,
                        help="Q-resolution damping factor (1/angstrom)")
    parser.add_argument("--output", required=True, help="Output file path")
    args = parser.parse_args()

    r, G = compute_pdf(args.structure, args.rmax, args.rstep, args.qdamp)

    with open(args.output, "w") as fh:
        for ri, gi in zip(r, G):
            fh.write(f"{ri:.6g} {gi:.6g}\n")


if __name__ == "__main__":
    main()
