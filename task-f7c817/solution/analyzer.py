#!/usr/bin/env python3

"""
MCNP Criticality Benchmark Analyzer
Parses MCNP input decks, computes material properties and geometric quantities,
cross-references with ICSBEP experimental data, and produces structured JSON output.
"""

import json
import math
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Physical constants and nuclear data
# ---------------------------------------------------------------------------

N_AVOGADRO = 6.02214076e23

# Atomic masses in g/mol (AME2020 / NUBASE2020)
ATOMIC_MASSES = {
    "U234": 234.040952,
    "U235": 235.043930,
    "U238": 238.050788,
    "Pu239": 239.052164,
    "Pu240": 240.053814,
    "Pu241": 241.056851,
    "Ga69": 68.925574,
    "Ga71": 70.924703,
    "N14": 14.003074,
    "O16": 15.994915,
}

# Map MCNP ZAID integer (ZZ*1000 + AAA) to element symbol+mass
ZAID_MAP = {
    92234: "U234", 92235: "U235", 92238: "U238",
    94239: "Pu239", 94240: "Pu240", 94241: "Pu241",
    31069: "Ga69", 31071: "Ga71",
    7014: "N14", 8016: "O16",
}

FISSILE_ISOTOPES = {"U235", "Pu239", "Pu241"}
URANIUM_ISOTOPES = {"U234", "U235", "U238"}


# ---------------------------------------------------------------------------
# MCNP Parsing
# ---------------------------------------------------------------------------

def parse_zaid(zaid_str):
    """Convert MCNP ZAID string like '92235.80c' to element name 'U235'."""
    zaid_num = int(zaid_str.split(".")[0])
    if zaid_num in ZAID_MAP:
        return ZAID_MAP[zaid_num]
    # Fallback: construct from Z and A
    z = zaid_num // 1000
    a = zaid_num % 1000
    return f"Z{z}A{a}"


def extract_benchmark_id(title):
    """Extract ICSBEP identifier from MCNP title card."""
    match = re.search(r"([A-Za-z0-9]+-[A-Za-z]+-[A-Za-z]+-\d+)", title)
    if match:
        return match.group(1).lower()
    return None


def extract_case(title):
    """Extract case number from title, return as 'case-N' or None."""
    match = re.search(r"case\s+(\d+)", title, re.IGNORECASE)
    if match:
        return f"case-{match.group(1)}"
    return None


def split_mcnp_sections(lines):
    """Split MCNP input (after title) into cell, surface, data sections."""
    sections = []
    current = []
    for line in lines:
        if line.strip() == "":
            if current:
                sections.append(current)
                current = []
        else:
            current.append(line)
    if current:
        sections.append(current)

    cell_lines = sections[0] if len(sections) > 0 else []
    surface_lines = sections[1] if len(sections) > 1 else []
    data_lines = []
    for s in sections[2:]:
        data_lines.extend(s)
    return cell_lines, surface_lines, data_lines


def parse_cell_card(line):
    """Parse a single MCNP cell card."""
    # Strip imp:n=... suffix
    cleaned = re.sub(r"\s+imp\s*:\s*n\s*=\s*\S+", "", line)
    tokens = cleaned.split()

    cell_id = int(tokens[0])
    mat_id = int(tokens[1])

    if mat_id == 0:
        density = 0.0
        region = " ".join(tokens[2:])
    else:
        density = float(tokens[2])
        region = " ".join(tokens[3:])

    return {
        "id": cell_id,
        "material_id": mat_id,
        "density": density,
        "region": region.strip(),
    }


def parse_surface_card(line):
    """Parse a single MCNP surface card. Only handles 'so' (sphere at origin)."""
    tokens = line.split()
    surf_id = int(tokens[0])
    surf_type = tokens[1].lower()

    if surf_type == "so":
        radius = float(tokens[2])
        return surf_id, {"type": "sphere_origin", "radius": radius}
    else:
        raise ValueError(f"Unsupported surface type: {surf_type}")


def parse_data_section(lines):
    """Parse the data section for materials and kcode."""
    materials = {}
    kcode = None
    current_mat_id = None

    for line in lines:
        stripped = line.strip()
        # Skip empty and comment lines
        if not stripped or stripped.lower().startswith("c ") or stripped.lower() == "c":
            current_mat_id = None  # Comments break continuation
            continue

        if line[0] != " ":
            # New data card
            tokens = stripped.split()
            keyword = tokens[0].lower()

            if keyword.startswith("m") and keyword[1:].isdigit():
                current_mat_id = int(keyword[1:])
                materials[current_mat_id] = {}
                # Parse nuclide entries on this line
                for i in range(1, len(tokens) - 1, 2):
                    name = parse_zaid(tokens[i])
                    density = float(tokens[i + 1])
                    materials[current_mat_id][name] = density
            elif keyword == "kcode":
                current_mat_id = None
                kcode = {
                    "particles": int(tokens[1]),
                    "initial_keff": float(tokens[2]),
                    "inactive_batches": int(tokens[3]),
                    "total_batches": int(tokens[4]),
                }
            else:
                current_mat_id = None
        else:
            # Continuation line
            if current_mat_id is not None:
                tokens = stripped.split()
                for i in range(0, len(tokens) - 1, 2):
                    name = parse_zaid(tokens[i])
                    density = float(tokens[i + 1])
                    materials[current_mat_id][name] = density

    return materials, kcode


def parse_mcnp_file(filepath):
    """Parse a complete MCNP input file."""
    with open(filepath) as f:
        lines = f.readlines()

    # Strip newlines
    lines = [l.rstrip("\n") for l in lines]

    title = lines[0].strip()
    benchmark_id = extract_benchmark_id(title)
    case = extract_case(title)

    cell_lines, surface_lines, data_lines = split_mcnp_sections(lines[1:])

    cells = [parse_cell_card(l) for l in cell_lines]
    surfaces = {}
    for l in surface_lines:
        sid, sdata = parse_surface_card(l)
        surfaces[sid] = sdata

    materials, kcode = parse_data_section(data_lines)

    return {
        "title": title,
        "benchmark_id": benchmark_id,
        "case": case,
        "cells": cells,
        "surfaces": surfaces,
        "materials": materials,
        "kcode": kcode,
    }


# ---------------------------------------------------------------------------
# Physics computations
# ---------------------------------------------------------------------------

def sphere_volume(radius):
    """Volume of a sphere with given radius."""
    return (4.0 / 3.0) * math.pi * radius ** 3


def compute_cell_volume(region_str, surfaces):
    """Compute geometric volume from CSG region for concentric spheres."""
    tokens = region_str.split()
    inner_radius = 0.0
    outer_radius = None

    for token in tokens:
        surf_id = abs(int(token))
        surf = surfaces[surf_id]
        if int(token) < 0:
            outer_radius = surf["radius"]
        else:
            inner_radius = surf["radius"]

    if outer_radius is None:
        return None  # Infinite (void)

    return sphere_volume(outer_radius) - sphere_volume(inner_radius)


def compute_weight_fractions(nuclides):
    """Compute mass fractions from atom densities using atomic masses."""
    mass_contributions = {}
    for name, n_density in nuclides.items():
        if name not in ATOMIC_MASSES:
            raise ValueError(f"No atomic mass for {name}")
        mass_contributions[name] = n_density * ATOMIC_MASSES[name]

    total_mass = sum(mass_contributions.values())
    weight_fractions = {}
    for name, mc in mass_contributions.items():
        weight_fractions[name] = mc / total_mass

    return weight_fractions


def compute_enrichment(nuclides):
    """Compute U-235 enrichment as weight percent of total uranium."""
    u_mass = {}
    for iso in URANIUM_ISOTOPES:
        if iso in nuclides:
            u_mass[iso] = nuclides[iso] * ATOMIC_MASSES[iso]

    total_u = sum(u_mass.values())
    if total_u == 0 or "U235" not in u_mass:
        return None

    return u_mass["U235"] / total_u * 100.0


def compute_isotope_mass_grams(n_density, volume_cm3, isotope_name):
    """Compute mass of an isotope in grams.

    n_density: atoms/barn-cm  (= 1e24 atoms/cm^3)
    volume_cm3: volume in cm^3
    Returns mass in grams.
    """
    A = ATOMIC_MASSES[isotope_name]
    return n_density * volume_cm3 * A * 1.0e24 / N_AVOGADRO


def compute_fissile_mass_kg(cells, materials, surfaces):
    """Compute total fissile mass across all cells in kg."""
    total_mass_g = 0.0

    for cell in cells:
        mat_id = cell["material_id"]
        if mat_id == 0:
            continue

        volume = compute_cell_volume(cell["region"], surfaces)
        if volume is None or volume <= 0:
            continue

        mat = materials[mat_id]
        for iso_name, n_density in mat.items():
            if iso_name in FISSILE_ISOTOPES:
                total_mass_g += compute_isotope_mass_grams(
                    n_density, volume, iso_name
                )

    return total_mass_g / 1000.0


# ---------------------------------------------------------------------------
# Uncertainties CSV
# ---------------------------------------------------------------------------

def load_uncertainties(csv_path):
    """Load the headerless ICSBEP uncertainties CSV."""
    entries = []
    with open(csv_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            entries.append({
                "benchmark": parts[0],
                "case": parts[1],
                "keff": float(parts[2]),
                "uncertainty": float(parts[3]),
            })
    return entries


def find_experimental_data(entries, benchmark_id, case_str):
    """Find matching experimental keff and uncertainty."""
    # Try exact case match first
    if case_str:
        for e in entries:
            if e["benchmark"] == benchmark_id and e["case"] == case_str:
                return e["keff"], e["uncertainty"]

    # Try case-1 as default
    for e in entries:
        if e["benchmark"] == benchmark_id and e["case"] == "case-1":
            return e["keff"], e["uncertainty"]

    # Try empty case (single-case benchmark)
    for e in entries:
        if e["benchmark"] == benchmark_id and e["case"] == "":
            return e["keff"], e["uncertainty"]

    # Last resort: first match
    for e in entries:
        if e["benchmark"] == benchmark_id:
            return e["keff"], e["uncertainty"]

    return None, None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def analyze_benchmark(filepath, uncertainties):
    """Analyze a single MCNP benchmark file."""
    parsed = parse_mcnp_file(filepath)

    # Build material analysis
    materials_out = {}
    for mat_id, nuclides in parsed["materials"].items():
        total_density = sum(nuclides.values())
        wf = compute_weight_fractions(nuclides)
        enrichment = compute_enrichment(nuclides)

        materials_out[str(mat_id)] = {
            "nuclides": dict(nuclides),
            "total_atom_density": total_density,
            "weight_fractions": wf,
            "enrichment_u235_wpct": enrichment,
        }

    # Build cell analysis (exclude void cells)
    cells_out = []
    for cell in parsed["cells"]:
        if cell["material_id"] == 0:
            continue
        volume = compute_cell_volume(cell["region"], parsed["surfaces"])
        cells_out.append({
            "id": cell["id"],
            "material_id": cell["material_id"],
            "volume_cm3": volume,
        })

    # Fissile mass
    fissile_mass = compute_fissile_mass_kg(
        parsed["cells"], parsed["materials"], parsed["surfaces"]
    )

    # Experimental data
    keff, unc = find_experimental_data(
        uncertainties, parsed["benchmark_id"], parsed["case"]
    )

    return {
        "id": parsed["benchmark_id"],
        "title": parsed["title"],
        "materials": materials_out,
        "cells": cells_out,
        "total_fissile_mass_kg": fissile_mass,
        "experimental_keff": keff,
        "experimental_uncertainty": unc,
        "kcode": parsed["kcode"],
    }


def main():
    benchmarks_dir = Path("/app/benchmarks")
    csv_path = Path("/app/data/uncertainties.csv")
    output_path = Path("/app/output/results.json")

    # Load uncertainties
    uncertainties = load_uncertainties(csv_path)

    # Analyze all benchmark files
    results = []
    for fpath in sorted(benchmarks_dir.glob("*.i")):
        print(f"Analyzing {fpath.name}...")
        result = analyze_benchmark(fpath, uncertainties)
        results.append(result)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"benchmarks": results}, f, indent=2)

    print(f"Results written to {output_path}")
    print(f"Analyzed {len(results)} benchmarks")


if __name__ == "__main__":
    main()
