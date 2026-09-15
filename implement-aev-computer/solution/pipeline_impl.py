#!/usr/bin/env python3
"""
AEV Benchmark Pipeline.

Reads molecular conformations from JSON, computes Atomic Environment Vectors
following the ANI/NeuroChem/TorchANI convention, and writes results to both
HDF5 and SQLite output formats.
"""

import json
import sqlite3
import collections
import os

import numpy as np
import h5py


# ──────────────────────────────────────────────────────────────────────
# Parameter parsing
# ──────────────────────────────────────────────────────────────────────
def load_params(filepath):
    """Parse an ANI NeuroChem .params file."""
    params = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in ("Rcr", "Rca"):
                params[key] = float(value)
            elif key in ("EtaR", "ShfR", "Zeta", "ShfZ", "EtaA", "ShfA"):
                value = value.strip("[]")
                params[key] = np.array(
                    [float(x) for x in value.split(",")], dtype=np.float64
                )
            elif key == "Atyp":
                params[key] = [x.strip() for x in value.strip("[]").split(",")]
            elif key == "TM":
                params[key] = int(value)
    return params


# ──────────────────────────────────────────────────────────────────────
# AEV computation
# ──────────────────────────────────────────────────────────────────────
def _cutoff_cosine(distances, cutoff):
    """Cosine cutoff: fc(R) = 0.5 * cos(R * pi / Rc) + 0.5."""
    return 0.5 * np.cos(distances * (np.pi / cutoff)) + 0.5


def compute_aev(species, coordinates, params):
    """Compute AEVs for a non-periodic molecule.

    Implements radial and angular symmetry functions with NeuroChem conventions:
      - Radial: 0.25 * exp(-eta_R * (R_ij - R_s)^2) * fc(R_ij)
      - Angular: 2 * ((1+cos(theta-theta_s))/2)^zeta
                   * exp(-eta_A * ((R_ij+R_ik)/2 - R_s)^2) * fc(R_ij)*fc(R_ik)
      - Angle: theta = arccos(0.95 * cos_angle) for numerical stability

    Returns:
        np.ndarray of shape (n_atoms, aev_length).
    """
    species = np.asarray(species, dtype=np.int64)
    coords = np.asarray(coordinates, dtype=np.float64)
    n_atoms = len(species)

    Rcr = params["Rcr"]
    Rca = params["Rca"]
    EtaR = params["EtaR"]
    ShfR = params["ShfR"]
    EtaA = params["EtaA"]
    Zeta = params["Zeta"]
    ShfA = params["ShfA"]
    ShfZ = params["ShfZ"]
    num_species = len(params["Atyp"])

    radial_sublength = len(EtaR) * len(ShfR)
    radial_length = num_species * radial_sublength
    angular_sublength = len(EtaA) * len(Zeta) * len(ShfA) * len(ShfZ)
    num_species_pairs = num_species * (num_species + 1) // 2
    angular_length = num_species_pairs * angular_sublength
    aev_length = radial_length + angular_length

    # Upper-triangular species-pair index lookup
    triu_idx = np.zeros((num_species, num_species), dtype=np.int64)
    k = 0
    for i in range(num_species):
        for j in range(i, num_species):
            triu_idx[i, j] = k
            triu_idx[j, i] = k
            k += 1

    aev = np.zeros((n_atoms, aev_length), dtype=np.float64)

    if n_atoms < 2:
        return aev

    # Pairwise distances
    diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
    dists = np.linalg.norm(diff, axis=-1)

    # ── Radial sub-AEV ──
    for i in range(n_atoms):
        for j in range(n_atoms):
            if i == j:
                continue
            d = dists[i, j]
            if d > Rcr:
                continue
            fc = _cutoff_cosine(d, Rcr)
            radial_vals = (
                0.25
                * np.exp(-EtaR[:, np.newaxis] * (d - ShfR[np.newaxis, :]) ** 2)
                * fc
            )
            sj = species[j]
            offset = sj * radial_sublength
            aev[i, offset : offset + radial_sublength] += radial_vals.flatten()

    # ── Angular sub-AEV ──
    for center in range(n_atoms):
        neighbors = []
        vecs = []
        ndists = []
        for other in range(n_atoms):
            if other == center:
                continue
            d = dists[center, other]
            if d <= Rca:
                neighbors.append(other)
                vecs.append(coords[other] - coords[center])
                ndists.append(d)

        n_neigh = len(neighbors)
        if n_neigh < 2:
            continue

        for ni in range(n_neigh):
            for nj in range(ni + 1, n_neigh):
                v1, v2 = vecs[ni], vecs[nj]
                d1, d2 = ndists[ni], ndists[nj]

                cos_angle = np.dot(v1, v2) / (d1 * d2)
                angle = np.arccos(0.95 * cos_angle)

                fc1 = _cutoff_cosine(d1, Rca)
                fc2 = _cutoff_cosine(d2, Rca)
                avg_d = (d1 + d2) / 2.0

                ShfZ_4d = ShfZ.reshape(1, 1, 1, -1)
                Zeta_4d = Zeta.reshape(1, -1, 1, 1)
                EtaA_4d = EtaA.reshape(-1, 1, 1, 1)
                ShfA_4d = ShfA.reshape(1, 1, -1, 1)

                factor1 = ((1.0 + np.cos(angle - ShfZ_4d)) / 2.0) ** Zeta_4d
                factor2 = np.exp(-EtaA_4d * (avg_d - ShfA_4d) ** 2)
                angular_vals = 2.0 * factor1 * factor2 * fc1 * fc2

                s1 = species[neighbors[ni]]
                s2 = species[neighbors[nj]]
                pair_idx = triu_idx[s1, s2]
                offset = radial_length + pair_idx * angular_sublength
                aev[center, offset : offset + angular_sublength] += angular_vals.flatten()

    return aev


# ──────────────────────────────────────────────────────────────────────
# Hill-order formula
# ──────────────────────────────────────────────────────────────────────
def hill_formula(elements):
    """Compute molecular formula in Hill order."""
    counts = collections.Counter(elements)
    parts = []
    if "C" in counts:
        c = counts.pop("C")
        parts.append("C" + (str(c) if c > 1 else ""))
        if "H" in counts:
            h = counts.pop("H")
            parts.append("H" + (str(h) if h > 1 else ""))
    for elem in sorted(counts.keys()):
        n = counts[elem]
        parts.append(elem + (str(n) if n > 1 else ""))
    return "".join(parts)


# ──────────────────────────────────────────────────────────────────────
# HDF5 output
# ──────────────────────────────────────────────────────────────────────
def write_hdf5(molecules_data, params, output_path):
    """Write results to HDF5 file with required hierarchical structure."""
    with h5py.File(output_path, "w") as f:
        mol_grp = f.create_group("molecules")
        for name, data in molecules_data.items():
            g = mol_grp.create_group(name)
            g.create_dataset(
                "aev", data=data["aev"], dtype=np.float64, compression="gzip"
            )
            g.create_dataset("species", data=data["species"], dtype=np.int64)
            g.create_dataset(
                "coordinates", data=data["coordinates"], dtype=np.float64
            )
            g.attrs["n_atoms"] = int(len(data["species"]))
            g.attrs["aev_length"] = 384

        params_grp = f.create_group("params")
        params_grp.attrs["Rcr"] = params["Rcr"]
        params_grp.attrs["Rca"] = params["Rca"]
        params_grp.attrs["num_species"] = len(params["Atyp"])

        meta_grp = f.create_group("metadata")
        meta_grp.attrs["pipeline_version"] = "1.0"


# ──────────────────────────────────────────────────────────────────────
# SQLite output
# ──────────────────────────────────────────────────────────────────────
def write_sqlite(molecules_data, output_path):
    """Write statistics to SQLite database with required schema."""
    if os.path.exists(output_path):
        os.remove(output_path)

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("""
        CREATE TABLE molecules (
            name TEXT PRIMARY KEY,
            n_atoms INTEGER NOT NULL,
            formula TEXT NOT NULL,
            radial_norm_mean REAL NOT NULL,
            radial_norm_std REAL NOT NULL,
            angular_norm_mean REAL NOT NULL,
            angular_norm_std REAL NOT NULL,
            sparsity REAL NOT NULL,
            max_element REAL NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE atom_details (
            molecule_name TEXT NOT NULL,
            atom_index INTEGER NOT NULL,
            species INTEGER NOT NULL,
            radial_l2_norm REAL NOT NULL,
            angular_l2_norm REAL NOT NULL,
            PRIMARY KEY (molecule_name, atom_index),
            FOREIGN KEY (molecule_name) REFERENCES molecules(name)
        )
    """)

    for name, data in molecules_data.items():
        aev = data["aev"]
        n_atoms = len(data["species"])
        formula = data["formula"]

        radial_norms = np.linalg.norm(aev[:, :64], axis=1)
        angular_norms = np.linalg.norm(aev[:, 64:], axis=1)

        sparsity = float((aev == 0.0).sum()) / aev.size
        max_elem = float(aev.max())

        conn.execute(
            "INSERT INTO molecules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                n_atoms,
                formula,
                float(radial_norms.mean()),
                float(radial_norms.std()),
                float(angular_norms.mean()),
                float(angular_norms.std()),
                sparsity,
                max_elem,
            ),
        )

        for i in range(n_atoms):
            conn.execute(
                "INSERT INTO atom_details VALUES (?, ?, ?, ?, ?)",
                (
                    name,
                    i,
                    int(data["species"][i]),
                    float(np.linalg.norm(aev[i, :64])),
                    float(np.linalg.norm(aev[i, 64:])),
                ),
            )

    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────
def main():
    with open("/app/conformations.json") as f:
        input_data = json.load(f)

    species_map = input_data["species_map"]
    params = load_params("/app/params.txt")

    molecules_data = {}
    for name, mol in input_data["molecules"].items():
        elements = mol["elements"]
        coordinates = mol["coordinates"]
        species_indices = [species_map[e] for e in elements]

        aev = compute_aev(species_indices, coordinates, params)

        molecules_data[name] = {
            "aev": aev,
            "species": np.array(species_indices, dtype=np.int64),
            "coordinates": np.array(coordinates, dtype=np.float64),
            "formula": hill_formula(elements),
        }

    write_hdf5(molecules_data, params, "/app/aev_output.h5")
    write_sqlite(molecules_data, "/app/benchmark.db")
    print("Pipeline complete.")


if __name__ == "__main__":
    main()
