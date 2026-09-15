#!/usr/bin/env python3
"""Nuclear fuel depletion solver.

Parses OpenMC-inspired chain XML + TOML problem config,
solves the nuclide evolution, stores results in SQLite.

"""

import math
import sqlite3
import xml.etree.ElementTree as ET
import tomllib

import numpy as np

BARN_TO_CM2 = 1.0e-24


def parse_chain(path="/app/chain.xml"):
    """Parse OpenMC-inspired chain XML into nuclide data structures."""
    tree = ET.parse(path)
    root = tree.getroot()
    nuclides = []
    for nuc_elem in root.findall("nuclide"):
        name = nuc_elem.get("name")
        half_life = float(nuc_elem.get("half_life"))
        decay_constant = math.log(2) / half_life

        decay_modes = []
        for d in nuc_elem.findall("decay"):
            decay_modes.append({
                "target": d.get("target"),
                "branching_ratio": float(d.get("branching_ratio")),
            })

        reactions = []
        for r in nuc_elem.findall("reaction"):
            xs_barn = float(r.find("cross_section").get("barn"))
            fission_yields = []
            fy_elem = r.find("neutron_fission_yields/fission_yields")
            if fy_elem is not None:
                prods = fy_elem.find("products").text.split()
                vals = [float(x) for x in fy_elem.find("data").text.split()]
                fission_yields = list(zip(prods, vals))
            reactions.append({
                "type": r.get("type"),
                "target": r.get("target"),
                "xs_barn": xs_barn,
                "fission_yields": fission_yields,
            })

        nuclides.append({
            "name": name,
            "decay_constant": decay_constant,
            "decay_modes": decay_modes,
            "reactions": reactions,
        })
    return nuclides


def build_transmutation_matrix(nuclides, idx, flux):
    """Construct the transmutation matrix A for dN/dt = A*N."""
    n = len(nuclides)
    A = np.zeros((n, n))

    for i, nuc in enumerate(nuclides):
        lam = nuc["decay_constant"]

        # Radioactive decay: always remove from parent
        A[i, i] -= lam

        # Decay production in daughter (only if daughter is tracked)
        for mode in nuc["decay_modes"]:
            target = mode["target"]
            if target in idx:
                A[idx[target], i] += lam * mode["branching_ratio"]

        # Neutron reactions
        for rxn in nuc["reactions"]:
            sigma = rxn["xs_barn"] * BARN_TO_CM2
            rate = sigma * flux

            # Removal from parent (all reaction types)
            A[i, i] -= rate

            # Capture: production in daughter if tracked
            if rxn["type"] == "(n,gamma)":
                target = rxn["target"]
                if target and target in idx:
                    A[idx[target], i] += rate

            # Fission: production of fission products
            if rxn["type"] == "fission":
                for product, yld in rxn["fission_yields"]:
                    if product in idx:
                        A[idx[product], i] += yld * rate

    return A


def matrix_exponential(M):
    """Compute exp(M) via eigendecomposition.

    For the transmutation matrices in this problem (10x10, real,
    with well-separated eigenvalues), eigendecomposition is stable
    and exact up to floating point precision.
    """
    eigenvalues, V = np.linalg.eig(M)
    exp_diag = np.diag(np.exp(eigenvalues))
    result = V @ exp_diag @ np.linalg.inv(V)
    return result.real


def solve():
    # Parse input data
    nuclides = parse_chain("/app/chain.xml")
    idx = {nuc["name"]: i for i, nuc in enumerate(nuclides)}
    n = len(nuclides)
    names = [nuc["name"] for nuc in nuclides]

    with open("/app/problem.toml", "rb") as f:
        problem = tomllib.load(f)

    # Initial concentrations
    conc = np.zeros(n)
    for name, val in problem["inventory"].items():
        if name in idx:
            conc[idx[name]] = val

    # Read schema and create database
    with open("/app/schema.sql") as f:
        schema = f.read()

    conn = sqlite3.connect("/app/results.db")
    conn.executescript(schema)

    # Insert nuclide names
    for nuc in nuclides:
        conn.execute(
            "INSERT INTO nuclides (name) VALUES (?)", (nuc["name"],)
        )

    # Insert initial state (step 0)
    conn.execute(
        "INSERT INTO steps (step_number, cumulative_time_s, label) "
        "VALUES (?, ?, ?)",
        (0, 0.0, "initial"),
    )
    for nm in names:
        conn.execute(
            "INSERT INTO concentrations "
            "(step_number, nuclide, value_atoms_per_cm3) VALUES (?, ?, ?)",
            (0, nm, float(conc[idx[nm]])),
        )

    # Step through irradiation schedule
    cumtime = 0.0
    for step_idx, step in enumerate(problem["schedule"]):
        flux = step["flux_n_per_cm2_s"]
        dt = step["duration_s"]

        A = build_transmutation_matrix(nuclides, idx, flux)
        conc = matrix_exponential(A * dt) @ conc
        cumtime += dt

        step_num = step_idx + 1
        label = step.get("label", "")

        conn.execute(
            "INSERT INTO steps (step_number, cumulative_time_s, label) "
            "VALUES (?, ?, ?)",
            (step_num, cumtime, label),
        )
        for nm in names:
            conn.execute(
                "INSERT INTO concentrations "
                "(step_number, nuclide, value_atoms_per_cm3) "
                "VALUES (?, ?, ?)",
                (step_num, nm, float(conc[idx[nm]])),
            )

    conn.commit()
    conn.close()
    print("Results written to /app/results.db")


if __name__ == "__main__":
    solve()
