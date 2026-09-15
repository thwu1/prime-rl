#!/usr/bin/env python3
"""
2D Photonic Crystal TM Band Structure Solver.

Implements the plane-wave expansion (PWE) method to compute eigenfrequencies
of Maxwell's equations for 2D photonic crystals with circular dielectric rods.
Resolves material properties from /app/data/materials.json.
"""
import json
import sys
import numpy as np
from scipy.linalg import eigh
from scipy.special import j1


# -----------------------------------------------------------------------
# Material resolution
# -----------------------------------------------------------------------

MATERIALS_DB_PATH = "/app/data/materials.json"


def load_materials_db():
    """Load the material database from JSON."""
    with open(MATERIALS_DB_PATH) as f:
        data = json.load(f)
    db = {}
    for mat in data["materials"]:
        db[mat["id"]] = mat
    return db


def resolve_epsilon(material_name, materials_db):
    """Resolve a material name to its dielectric constant."""
    if material_name not in materials_db:
        raise ValueError(
            f"Unknown material '{material_name}'. "
            f"Available: {list(materials_db.keys())}"
        )
    return float(materials_db[material_name]["epsilon"])


# -----------------------------------------------------------------------
# Lattice setup
# -----------------------------------------------------------------------

def get_lattice(lattice_type):
    """Return (a1, a2, b1, b2, cell_area) for the given lattice type."""
    if lattice_type == "square":
        a1 = np.array([1.0, 0.0])
        a2 = np.array([0.0, 1.0])
    elif lattice_type == "triangular":
        a1 = np.array([1.0, 0.0])
        a2 = np.array([0.5, np.sqrt(3.0) / 2.0])
    else:
        raise ValueError(f"Unknown lattice type: {lattice_type}")

    det = a1[0] * a2[1] - a1[1] * a2[0]
    area = abs(det)
    b1 = (2.0 * np.pi / det) * np.array([a2[1], -a2[0]])
    b2 = (2.0 * np.pi / det) * np.array([-a1[1], a1[0]])

    return a1, a2, b1, b2, area


# -----------------------------------------------------------------------
# k-point path along IBZ boundary
# -----------------------------------------------------------------------

def get_ibz_kpoints(lattice_type, b1, b2, k_interp=4):
    """Generate k-points along the irreducible Brillouin zone boundary."""
    if lattice_type == "square":
        verts_frac = [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.0)]
    elif lattice_type == "triangular":
        verts_frac = [(0.0, 0.0), (0.5, 0.0), (2.0 / 3.0, 1.0 / 3.0), (0.0, 0.0)]
    else:
        raise ValueError(f"Unknown lattice type: {lattice_type}")

    verts = [f1 * b1 + f2 * b2 for f1, f2 in verts_frac]

    k_points = [verts[0].copy()]
    for i in range(len(verts) - 1):
        n_seg = k_interp + 1
        for j in range(1, n_seg + 1):
            t = j / n_seg
            k_points.append((1.0 - t) * verts[i] + t * verts[i + 1])

    return k_points


# -----------------------------------------------------------------------
# Reciprocal lattice vectors (plane waves)
# -----------------------------------------------------------------------

def build_g_vectors(N, b1, b2):
    """Generate G = n1*b1 + n2*b2 for |n1|, |n2| <= N."""
    ns = np.arange(-N, N + 1)
    n1, n2 = np.meshgrid(ns, ns, indexing="ij")
    n1 = n1.ravel()
    n2 = n2.ravel()
    gs = n1[:, np.newaxis] * b1[np.newaxis, :] + n2[:, np.newaxis] * b2[np.newaxis, :]
    return gs


# -----------------------------------------------------------------------
# Dielectric Fourier-coefficient matrix
# -----------------------------------------------------------------------

def build_epsilon_matrix(g_vecs, eps_rod, eps_bg, radius, cell_area):
    """Build the matrix of Fourier coefficients eps_hat(G_i - G_j)."""
    filling = np.pi * radius ** 2 / cell_area
    eps_avg = eps_bg + (eps_rod - eps_bg) * filling
    delta_eps = eps_rod - eps_bg

    dg = g_vecs[:, np.newaxis, :] - g_vecs[np.newaxis, :, :]
    dg_norm = np.linalg.norm(dg, axis=2)

    x = dg_norm * radius
    safe_x = np.where(dg_norm > 1e-12, x, 1.0)
    bessel_term = 2.0 * j1(safe_x) / safe_x

    eps_mat = np.where(dg_norm > 1e-12, delta_eps * filling * bessel_term, eps_avg)
    eps_mat = 0.5 * (eps_mat + eps_mat.T)

    return eps_mat


# -----------------------------------------------------------------------
# Eigenvalue solver at a single k-point
# -----------------------------------------------------------------------

def solve_tm_at_k(k, g_vecs, eps_mat, num_bands):
    """Solve the TM generalised eigenvalue problem at wavevector k."""
    kpg = k[np.newaxis, :] + g_vecs
    kpg_sq = np.sum(kpg ** 2, axis=1)
    K = np.diag(kpg_sq)

    n_g = len(g_vecs)
    n_compute = min(num_bands, n_g)

    try:
        eigenvalues = eigh(
            K, eps_mat, eigvals_only=True,
            subset_by_index=[0, n_compute - 1],
        )
    except Exception:
        eigenvalues = eigh(K, eps_mat, eigvals_only=True)
        eigenvalues = np.sort(eigenvalues)[:n_compute]

    eigenvalues = np.maximum(eigenvalues, 0.0)
    freqs = np.sqrt(eigenvalues) / (2.0 * np.pi)
    return freqs


# -----------------------------------------------------------------------
# Band-gap detection
# -----------------------------------------------------------------------

def find_gaps(bands_array, min_gap_pct=1.0):
    """Identify band gaps from the computed band structure."""
    n_bands = bands_array.shape[1]
    gaps = []
    for i in range(n_bands - 1):
        band_top = float(np.max(bands_array[:, i]))
        band_bot = float(np.min(bands_array[:, i + 1]))
        if band_bot > band_top and (band_bot + band_top) > 0:
            pct = 200.0 * (band_bot - band_top) / (band_bot + band_top)
            if pct > min_gap_pct:
                gaps.append({
                    "from_band": int(i + 1),
                    "to_band": int(i + 2),
                    "gap_min": band_top,
                    "gap_max": band_bot,
                    "gap_percent": pct,
                })
    return gaps


# -----------------------------------------------------------------------
# Main driver
# -----------------------------------------------------------------------

def compute_bands(config, materials_db=None):
    """Compute the TM band structure for the given configuration."""
    if materials_db is None:
        materials_db = load_materials_db()

    lattice_type = config["lattice_type"]

    # Resolve material names to epsilon values
    eps_rod = resolve_epsilon(config["rod_material"], materials_db)
    eps_bg = resolve_epsilon(config["background_material"], materials_db)

    radius = float(config["radius"])
    num_bands = int(config.get("num_bands", 8))
    resolution = int(config.get("resolution", 16))
    k_interp = int(config.get("k_interp", 4))

    N = max(resolution // 2, 4)

    _a1, _a2, b1, b2, area = get_lattice(lattice_type)
    g_vecs = build_g_vectors(N, b1, b2)
    eps_mat = build_epsilon_matrix(g_vecs, eps_rod, eps_bg, radius, area)
    k_points = get_ibz_kpoints(lattice_type, b1, b2, k_interp)

    all_bands = []
    k_coords = []
    for k in k_points:
        freqs = solve_tm_at_k(k, g_vecs, eps_mat, num_bands)
        all_bands.append(freqs.tolist())
        k_coords.append(k.tolist())

    bands_array = np.array(all_bands)
    gaps = find_gaps(bands_array)

    return {"bands": all_bands, "k_points": k_coords, "gaps": gaps}


# -----------------------------------------------------------------------
# CLI entry point
# -----------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 solve_bands.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)

    results = compute_bands(config)

    output_path = config.get("output", "/app/results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    for g in results["gaps"]:
        print(
            f"Gap: band {g['from_band']}->{g['to_band']}: "
            f"{g['gap_percent']:.2f}% ({g['gap_min']:.6f} to {g['gap_max']:.6f})"
        )
