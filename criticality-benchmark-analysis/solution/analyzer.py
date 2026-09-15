#!/usr/bin/env python3
"""
ICSBEP Benchmark Criticality Validation Analyzer.

"""

import csv
import json
import math
import re
import xml.etree.ElementTree as ET

import h5py
import numpy as np

# Standard atomic masses (AMU) from IUPAC
ATOMIC_MASSES = {
    "H1": 1.00782503,
    "H2": 2.01410178,
    "C0": 12.0000,
    "N14": 14.00307401,
    "O16": 15.99491462,
    "O17": 16.99913176,
    "Si28": 27.97692653,
    "Si29": 28.97649472,
    "Si30": 29.97377017,
    "P31": 30.97376200,
    "S32": 31.97207117,
    "S33": 32.97145891,
    "S34": 33.96786700,
    "S36": 35.96708071,
    "Cr50": 49.94604183,
    "Cr52": 51.94050623,
    "Cr53": 52.94064815,
    "Cr54": 53.93887916,
    "Mn55": 54.93804391,
    "Fe54": 53.93960899,
    "Fe56": 55.93493633,
    "Fe57": 56.93539284,
    "Fe58": 57.93327443,
    "Ni58": 57.93534241,
    "Ni60": 59.93078589,
    "Ni61": 60.93105557,
    "Ni62": 61.92834537,
    "Ni64": 63.92796682,
    "Mo92": 91.90681,
    "Mo94": 93.90509,
    "Mo95": 94.90584,
    "Mo96": 95.90468,
    "Mo97": 96.90602,
    "Mo98": 97.90541,
    "Mo100": 99.90748,
    "U234": 234.04095,
    "U235": 235.04393,
    "U236": 236.04557,
    "U238": 238.05079,
}

AVOGADRO = 6.02214076e23


def get_atomic_mass(name):
    if name in ATOMIC_MASSES:
        return ATOMIC_MASSES[name]
    match = re.match(r"([A-Z][a-z]*)(\d+)", name)
    if match:
        return float(match.group(2))
    raise ValueError(f"Unknown nuclide: {name}")


def compute_density_gcc(nuclides):
    """Mass density (g/cm3) from atom number densities in atoms/barn-cm."""
    rho = 0.0
    for name, ao in nuclides.items():
        n = ao * 1e24  # atoms/cm3
        a = get_atomic_mass(name)
        rho += n * a / AVOGADRO
    return rho


def compute_enrichment_wt_pct(nuclides):
    """U-235 weight fraction enrichment (%) from uranium isotope densities."""
    u_isotopes = {k: v for k, v in nuclides.items() if k.startswith("U2")}
    if not u_isotopes:
        return 0.0
    total_mass = sum(ao * get_atomic_mass(name) for name, ao in u_isotopes.items())
    u235_mass = u_isotopes.get("U235", 0) * get_atomic_mass("U235")
    return u235_mass / total_mass * 100.0


def sphere_volume(r):
    return (4.0 / 3.0) * math.pi * r ** 3


def cylinder_volume(r, h):
    return math.pi * r ** 2 * h


# ===== OpenMC XML Parsing =====


def parse_openmc_materials(filepath):
    tree = ET.parse(filepath)
    root = tree.getroot()
    materials = {}
    for mat_elem in root.findall("material"):
        mat_id = int(mat_elem.get("id"))
        nuclides = {}
        for nuc_elem in mat_elem.findall("nuclide"):
            name = nuc_elem.get("name")
            ao = float(nuc_elem.get("ao"))
            nuclides[name] = ao
        materials[mat_id] = nuclides
    return materials


def parse_openmc_geometry(filepath):
    tree = ET.parse(filepath)
    root = tree.getroot()
    surfaces = {}
    for surf_elem in root.findall("surface"):
        sid = int(surf_elem.get("id"))
        stype = surf_elem.get("type")
        coeffs = [float(x) for x in surf_elem.get("coeffs").split()]
        boundary = surf_elem.get("boundary", None)
        surfaces[sid] = {"type": stype, "coeffs": coeffs, "boundary": boundary}
    cells = {}
    for cell_elem in root.findall("cell"):
        cid = int(cell_elem.get("id"))
        mat = cell_elem.get("material")
        region = cell_elem.get("region", "")
        cells[cid] = {"material": mat, "region": region}
    return surfaces, cells


# ===== MCNP Input Parsing =====


def zaid_to_nuclide(zaid_str):
    zaid = zaid_str.split(".")[0]
    z = int(zaid) // 1000
    a = int(zaid) % 1000
    element_map = {
        1: "H", 6: "C", 7: "N", 8: "O", 14: "Si", 15: "P",
        16: "S", 24: "Cr", 25: "Mn", 26: "Fe", 28: "Ni", 42: "Mo",
        92: "U", 94: "Pu", 95: "Am",
    }
    elem = element_map.get(z, f"Z{z}")
    return f"{elem}{a}"


def parse_mcnp_input(filepath):
    with open(filepath) as f:
        lines = f.readlines()

    sections = []
    current_section = []
    for i, line in enumerate(lines):
        if i == 0:
            continue
        stripped = line.rstrip()
        if stripped == "" or stripped == " ":
            if current_section:
                sections.append(current_section)
                current_section = []
        else:
            current_section.append(line.rstrip("\n"))
    if current_section:
        sections.append(current_section)

    cell_lines = sections[0] if len(sections) > 0 else []
    surface_lines = sections[1] if len(sections) > 1 else []
    data_lines = sections[2] if len(sections) > 2 else []

    cells = []
    for line in cell_lines:
        parts = line.split()
        if not parts or parts[0].lower() == "c":
            continue
        cell_id = int(parts[0])
        mat_id = int(parts[1])
        if mat_id == 0:
            cells.append({
                "id": cell_id, "material_id": 0,
                "density": 0.0, "region_str": " ".join(parts[2:])
            })
        else:
            density = float(parts[2])
            rest = " ".join(parts[3:])
            region_str = re.split(r"\s+imp:", rest, flags=re.IGNORECASE)[0]
            cells.append({
                "id": cell_id, "material_id": mat_id,
                "density": density, "region_str": region_str
            })

    surfaces = {}
    for line in surface_lines:
        parts = line.split()
        if not parts or parts[0].lower() == "c":
            continue
        sid = int(parts[0])
        stype = parts[1].lower()
        params = [float(x) for x in parts[2:]]
        surfaces[sid] = {"type": stype, "params": params}

    merged_data = []
    for line in data_lines:
        if line.startswith("     ") and merged_data:
            merged_data[-1] += " " + line.strip()
        else:
            merged_data.append(line)

    materials = {}
    for line in merged_data:
        line = line.strip()
        if not line or line.lower().startswith("c "):
            continue
        match = re.match(r"m(\d+)\s+(.*)", line, re.IGNORECASE)
        if match:
            mat_id = int(match.group(1))
            rest = match.group(2)
            nuclides = {}
            tokens = rest.split()
            idx = 0
            while idx < len(tokens) - 1:
                zaid = tokens[idx]
                if "." in zaid or zaid.isdigit():
                    ao = float(tokens[idx + 1])
                    name = zaid_to_nuclide(zaid)
                    nuclides[name] = ao
                    idx += 2
                else:
                    idx += 1
            materials[mat_id] = nuclides

    return cells, surfaces, materials


# ===== CSV Parsing =====


def parse_uncertainties(filepath):
    data = {}
    with open(filepath) as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 4:
                continue
            benchmark = row[0].strip()
            case = row[1].strip()
            keff = float(row[2].strip())
            unc = float(row[3].strip())
            data[(benchmark, case)] = (keff, unc)
    return data


# ===== HDF5 Statepoint Analysis =====


def analyze_statepoint(filepath):
    """Extract k-eff statistics and convergence diagnostics from HDF5 statepoint."""
    with h5py.File(filepath, "r") as f:
        keff_all = f["results/k_effective"][:]
        n_inactive = int(f["settings/n_inactive"][()])
        entropy = f["diagnostics/entropy"][:]

    active_keff = keff_all[n_inactive:]
    n_active = len(active_keff)
    keff_mean = float(np.mean(active_keff))
    keff_stderr = float(np.std(active_keff, ddof=1) / np.sqrt(n_active))

    # Entropy convergence: coefficient of variation of latter half
    last_half = entropy[len(entropy) // 2:]
    entropy_cv = float(np.std(last_half) / np.mean(last_half))
    entropy_converged = entropy_cv < 0.02

    return {
        "simulated_keff": keff_mean,
        "simulated_keff_stderr": keff_stderr,
        "n_active_batches": n_active,
        "entropy_converged": entropy_converged,
    }


# ===== Benchmark Material Analysis =====


def analyze_hmf001(benchmarks_dir):
    materials = parse_openmc_materials(f"{benchmarks_dir}/hmf001/materials.xml")
    surfaces, cells = parse_openmc_geometry(f"{benchmarks_dir}/hmf001/geometry.xml")

    radii = {}
    for sid, sdata in surfaces.items():
        if sdata["type"] == "sphere":
            radii[sid] = sdata["coeffs"][3]

    shell_densities = []
    total_fissile_mass_kg = 0.0
    total_u235_weight = 0.0
    total_u_weight = 0.0

    for cid in sorted(cells.keys()):
        cell = cells[cid]
        mat_str = cell["material"]
        if mat_str == "void" or mat_str == "7":
            continue
        mat_id = int(mat_str)
        nuclides = materials[mat_id]

        region = cell["region"].strip()
        parts = region.split()
        inner_r = 0.0
        outer_r = 0.0
        for part in parts:
            part = part.strip()
            if part.startswith("-"):
                sid = int(part[1:])
                outer_r = radii[sid]
            else:
                sid = int(part)
                inner_r = radii[sid]

        vol = sphere_volume(outer_r) - sphere_volume(inner_r)
        density = compute_density_gcc(nuclides)
        mass_kg = density * vol / 1000.0

        shell_densities.append(density)
        total_fissile_mass_kg += mass_kg

        for name, ao in nuclides.items():
            if name.startswith("U2"):
                weight = ao * get_atomic_mass(name) * vol
                total_u_weight += weight
                if name == "U235":
                    total_u235_weight += weight

    avg_enrichment = total_u235_weight / total_u_weight * 100.0

    return {
        "total_fissile_mass_kg": round(total_fissile_mass_kg, 6),
        "avg_enrichment_wt_pct": round(avg_enrichment, 6),
        "shell_densities_gcc": [round(d, 6) for d in shell_densities],
    }


def analyze_hmf003(benchmarks_dir):
    cells, surfaces, materials = parse_mcnp_input(
        f"{benchmarks_dir}/hmf003/mcnp_input.txt"
    )
    r_core = surfaces[1]["params"][0]
    r_outer = surfaces[2]["params"][0]

    core_vol = sphere_volume(r_core)
    refl_vol = sphere_volume(r_outer) - sphere_volume(r_core)

    core_nuclides = materials[1]
    refl_nuclides = materials[2]

    core_density = compute_density_gcc(core_nuclides)
    refl_density = compute_density_gcc(refl_nuclides)

    return {
        "core_mass_kg": round(core_density * core_vol / 1000.0, 6),
        "core_enrichment_wt_pct": round(compute_enrichment_wt_pct(core_nuclides), 6),
        "reflector_mass_kg": round(refl_density * refl_vol / 1000.0, 6),
        "reflector_enrichment_wt_pct": round(
            compute_enrichment_wt_pct(refl_nuclides), 6
        ),
        "core_density_gcc": round(core_density, 6),
        "reflector_density_gcc": round(refl_density, 6),
    }


def analyze_hst001(benchmarks_dir):
    materials = parse_openmc_materials(f"{benchmarks_dir}/hst001/materials.xml")
    surfaces, cells = parse_openmc_geometry(f"{benchmarks_dir}/hst001/geometry.xml")

    sol_nuclides = materials[1]
    sol_density = compute_density_gcc(sol_nuclides)
    enrichment = compute_enrichment_wt_pct(sol_nuclides)

    h_density = sol_nuclides.get("H1", 0.0)
    u235_density = sol_nuclides.get("U235", 0.0)
    hx_ratio = h_density / u235_density if u235_density > 0 else 0.0

    r_cyl = surfaces[1]["coeffs"][2]
    z_bottom = surfaces[4]["coeffs"][0]
    z_top = surfaces[5]["coeffs"][0]
    height = z_top - z_bottom
    sol_vol = cylinder_volume(r_cyl, height)

    u235_n = u235_density * 1e24
    u235_mass_g = u235_n * get_atomic_mass("U235") / AVOGADRO * sol_vol

    return {
        "solution_density_gcc": round(sol_density, 6),
        "enrichment_wt_pct": round(enrichment, 6),
        "hx_ratio": round(hx_ratio, 4),
        "solution_volume_cm3": round(sol_vol, 4),
        "u235_mass_g": round(u235_mass_g, 4),
    }


# ===== C/E Validation =====


def compute_ce_analysis(sim_keff, sim_stderr, exp_keff, exp_unc):
    """Compute C/E ratio with propagated uncertainty."""
    ce = sim_keff / exp_keff
    ce_unc = ce * math.sqrt(
        (sim_stderr / sim_keff) ** 2 + (exp_unc / exp_keff) ** 2
    )
    validation_pass = abs(ce - 1.0) < 2.0 * ce_unc
    return {
        "c_over_e": round(ce, 8),
        "c_over_e_unc": round(ce_unc, 8),
        "validation_pass": validation_pass,
    }


# ===== Main =====


def main():
    benchmarks_dir = "/app/benchmarks"
    statepoints_dir = "/app/statepoints"
    output_path = "/app/validation_report.json"

    uncertainties = parse_uncertainties(f"{benchmarks_dir}/uncertainties.csv")

    # Material analysis
    hmf001_mat = analyze_hmf001(benchmarks_dir)
    hmf003_mat = analyze_hmf003(benchmarks_dir)
    hst001_mat = analyze_hst001(benchmarks_dir)

    # Statepoint analysis
    hmf001_sim = analyze_statepoint(f"{statepoints_dir}/hmf001_statepoint.h5")
    hmf003_sim = analyze_statepoint(f"{statepoints_dir}/hmf003_statepoint.h5")
    hst001_sim = analyze_statepoint(f"{statepoints_dir}/hst001_statepoint.h5")

    # Experimental data lookup
    hmf001_exp = uncertainties[("heu-met-fast-001", "case-1")]
    hmf003_exp = uncertainties[("heu-met-fast-003", "case-1")]
    hst001_exp = uncertainties[("heu-sol-therm-001", "case-1")]

    # C/E validation
    hmf001_ce = compute_ce_analysis(
        hmf001_sim["simulated_keff"], hmf001_sim["simulated_keff_stderr"],
        *hmf001_exp
    )
    hmf003_ce = compute_ce_analysis(
        hmf003_sim["simulated_keff"], hmf003_sim["simulated_keff_stderr"],
        *hmf003_exp
    )
    hst001_ce = compute_ce_analysis(
        hst001_sim["simulated_keff"], hst001_sim["simulated_keff_stderr"],
        *hst001_exp
    )

    results = {
        "hmf001": {
            **hmf001_mat, **hmf001_sim,
            "experimental_keff": hmf001_exp[0],
            "experimental_uncertainty": hmf001_exp[1],
            **hmf001_ce,
        },
        "hmf003": {
            **hmf003_mat, **hmf003_sim,
            "experimental_keff": hmf003_exp[0],
            "experimental_uncertainty": hmf003_exp[1],
            **hmf003_ce,
        },
        "hst001": {
            **hst001_mat, **hst001_sim,
            "experimental_keff": hst001_exp[0],
            "experimental_uncertainty": hst001_exp[1],
            **hst001_ce,
        },
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
