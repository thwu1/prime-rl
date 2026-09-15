#!/usr/bin/env python3

"""
MCNP-to-OpenMC benchmark conversion and physics analysis pipeline.
Parses MCNP criticality safety input decks, translates them to OpenMC XML
format, validates XML output, and produces a physics analysis report.
"""

import json
import math
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# Physical constants and reference data
# ---------------------------------------------------------------------------

N_AVOGADRO = 6.02214076e23

ELEMENTS = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O",
    9: "F", 10: "Ne", 11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P",
    16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca", 21: "Sc", 22: "Ti",
    23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu",
    30: "Zn", 31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr",
    37: "Rb", 38: "Sr", 39: "Y", 40: "Zr", 41: "Nb", 42: "Mo", 43: "Tc",
    44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
    92: "U", 93: "Np", 94: "Pu", 95: "Am",
}

ATOMIC_MASSES = {
    "H1": 1.007825, "N14": 14.003074, "O16": 15.994915,
    "U234": 234.040952, "U235": 235.043930, "U238": 238.050788,
    "Pu239": 239.052164, "Pu240": 240.053814, "Pu241": 241.056851,
    "Ga69": 68.925574, "Ga71": 70.924703,
}

FISSILE_ISOTOPES = {"U235", "Pu239", "Pu241"}
URANIUM_ISOTOPES = {"U234", "U235", "U236", "U238"}


# ---------------------------------------------------------------------------
# MCNP Parsing
# ---------------------------------------------------------------------------

def zaid_to_name(zaid_str):
    """Convert MCNP ZAID like '92235.80c' to OpenMC name 'U235'."""
    zaid_num = int(zaid_str.split(".")[0])
    z = zaid_num // 1000
    a = zaid_num % 1000
    symbol = ELEMENTS.get(z, f"Z{z}")
    return f"{symbol}{a}"


def extract_benchmark_id(title):
    match = re.search(r"([A-Za-z0-9]+-[A-Za-z]+-[A-Za-z]+-\d+)", title)
    return match.group(1).lower() if match else None


def extract_case(title):
    match = re.search(r"case\s+(\d+)", title, re.IGNORECASE)
    return f"case-{match.group(1)}" if match else None


def split_mcnp_sections(lines):
    sections, current = [], []
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
    imp_match = re.search(r"imp\s*:\s*n\s*=\s*(\S+)", line)
    importance = float(imp_match.group(1)) if imp_match else 1.0
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
        "id": cell_id, "material_id": mat_id, "density": density,
        "region": region.strip(), "importance": importance,
    }


def parse_surface_card(line):
    tokens = line.split()
    surf_id = int(tokens[0])
    surf_type = tokens[1].lower()
    if surf_type == "so":
        return surf_id, {"type": "so", "radius": float(tokens[2])}
    raise ValueError(f"Unsupported surface type: {surf_type}")


def parse_data_section(lines):
    materials, kcode = {}, None
    current_mat_id = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("c ") or stripped.lower() == "c":
            current_mat_id = None
            continue
        if line[0] != " ":
            tokens = stripped.split()
            kw = tokens[0].lower()
            if kw.startswith("m") and kw[1:].isdigit():
                current_mat_id = int(kw[1:])
                materials[current_mat_id] = {}
                for i in range(1, len(tokens) - 1, 2):
                    materials[current_mat_id][zaid_to_name(tokens[i])] = float(tokens[i + 1])
            elif kw == "kcode":
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
            if current_mat_id is not None:
                tokens = stripped.split()
                for i in range(0, len(tokens) - 1, 2):
                    materials[current_mat_id][zaid_to_name(tokens[i])] = float(tokens[i + 1])
    return materials, kcode


def parse_mcnp_file(filepath):
    with open(filepath) as f:
        lines = [l.rstrip("\n") for l in f.readlines()]
    title = lines[0].strip()
    cell_lines, surface_lines, data_lines = split_mcnp_sections(lines[1:])
    cells = [parse_cell_card(l) for l in cell_lines]
    surfaces = {}
    for l in surface_lines:
        sid, sdata = parse_surface_card(l)
        surfaces[sid] = sdata
    materials, kcode = parse_data_section(data_lines)
    return {
        "title": title,
        "benchmark_id": extract_benchmark_id(title),
        "case": extract_case(title),
        "cells": cells, "surfaces": surfaces,
        "materials": materials, "kcode": kcode,
    }


# ---------------------------------------------------------------------------
# OpenMC XML Generation
# ---------------------------------------------------------------------------

def generate_geometry_xml(parsed, output_dir):
    root = ET.Element("geometry")

    # Find outermost surface (exterior void cell with imp:n=0)
    outer_sids = set()
    for cell in parsed["cells"]:
        if cell["material_id"] == 0 and cell["importance"] == 0:
            for tok in cell["region"].split():
                try:
                    outer_sids.add(abs(int(tok)))
                except ValueError:
                    pass

    for sid in sorted(parsed["surfaces"]):
        sd = parsed["surfaces"][sid]
        attribs = {
            "id": str(sid),
            "type": "sphere",
            "coeffs": f"0 0 0 {sd['radius']}",
        }
        if sid in outer_sids:
            attribs["boundary"] = "vacuum"
        ET.SubElement(root, "surface", attribs)

    for cell in parsed["cells"]:
        if cell["material_id"] == 0:
            continue
        ET.SubElement(root, "cell", {
            "id": str(cell["id"]),
            "material": str(cell["material_id"]),
            "region": cell["region"],
        })

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(os.path.join(output_dir, "geometry.xml"),
               xml_declaration=True, encoding="unicode")


def generate_materials_xml(parsed, output_dir):
    root = ET.Element("materials")
    for mat_id in sorted(parsed["materials"]):
        nuclides = parsed["materials"][mat_id]
        mat_el = ET.SubElement(root, "material", {"id": str(mat_id)})
        ET.SubElement(mat_el, "density", {"units": "sum"})
        for nuc_name, ao in nuclides.items():
            ET.SubElement(mat_el, "nuclide", {
                "name": nuc_name, "ao": f"{ao:.6e}",
            })
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(os.path.join(output_dir, "materials.xml"),
               xml_declaration=True, encoding="unicode")


def generate_settings_xml(parsed, output_dir):
    root = ET.Element("settings")
    kc = parsed["kcode"]
    ET.SubElement(root, "run_mode").text = "eigenvalue"
    ET.SubElement(root, "batches").text = str(kc["total_batches"])
    ET.SubElement(root, "inactive").text = str(kc["inactive_batches"])
    ET.SubElement(root, "particles").text = str(kc["particles"])
    source = ET.SubElement(root, "source")
    space = ET.SubElement(source, "space")
    ET.SubElement(space, "type").text = "box"
    ET.SubElement(space, "parameters").text = "-1 -1 -1  1  1  1"
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(os.path.join(output_dir, "settings.xml"),
               xml_declaration=True, encoding="unicode")


def generate_openmc_files(parsed, base_dir):
    bid = parsed["benchmark_id"]
    out = os.path.join(base_dir, bid)
    os.makedirs(out, exist_ok=True)
    generate_geometry_xml(parsed, out)
    generate_materials_xml(parsed, out)
    generate_settings_xml(parsed, out)
    return out


# ---------------------------------------------------------------------------
# XML Validation
# ---------------------------------------------------------------------------

def validate_xml(openmc_base, benchmark_ids, log_path):
    log = []
    for bid in benchmark_ids:
        d = os.path.join(openmc_base, bid)
        for xf in ["geometry.xml", "materials.xml", "settings.xml"]:
            fp = os.path.join(d, xf)
            try:
                r = subprocess.run(
                    ["xmlstarlet", "val", fp],
                    capture_output=True, text=True, timeout=30,
                )
                out = (r.stdout.strip() or r.stderr.strip())
                log.append(f"{bid}/{xf}: {out}")
            except Exception as e:
                log.append(f"{bid}/{xf}: ERROR - {e}")
    with open(log_path, "w") as f:
        f.write("\n".join(log) + "\n")


# ---------------------------------------------------------------------------
# Physics Computations
# ---------------------------------------------------------------------------

def sphere_volume(r):
    return (4.0 / 3.0) * math.pi * r ** 3


def cell_volume(region_str, surfaces):
    inner_r, outer_r = 0.0, None
    for tok in region_str.split():
        sid = abs(int(tok))
        r = surfaces[sid]["radius"]
        if int(tok) < 0:
            outer_r = r
        else:
            inner_r = r
    return (sphere_volume(outer_r) - sphere_volume(inner_r)) if outer_r else None


def weight_fractions(nuclides):
    mc = {n: d * ATOMIC_MASSES[n] for n, d in nuclides.items()}
    total = sum(mc.values())
    return {n: v / total for n, v in mc.items()}


def enrichment_u235(nuclides):
    um = {i: nuclides[i] * ATOMIC_MASSES[i] for i in URANIUM_ISOTOPES if i in nuclides}
    total = sum(um.values())
    if total == 0 or "U235" not in um:
        return None
    return um["U235"] / total * 100.0


def fissile_mass_kg(cells, materials, surfaces):
    total_g = 0.0
    for c in cells:
        mid = c["material_id"]
        if mid == 0:
            continue
        vol = cell_volume(c["region"], surfaces)
        if not vol or vol <= 0:
            continue
        mat = materials[mid]
        for iso, nd in mat.items():
            if iso in FISSILE_ISOTOPES:
                total_g += nd * vol * ATOMIC_MASSES[iso] * 1e24 / N_AVOGADRO
    return total_g / 1000.0


# ---------------------------------------------------------------------------
# Uncertainties CSV
# ---------------------------------------------------------------------------

def load_uncertainties(csv_path):
    entries = []
    with open(csv_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                entries.append({
                    "benchmark": parts[0], "case": parts[1],
                    "keff": float(parts[2]), "uncertainty": float(parts[3]),
                })
    return entries


def find_experimental(entries, bid, case_str):
    for match_case in ([case_str] if case_str else []) + ["case-1", ""]:
        for e in entries:
            if e["benchmark"] == bid and e["case"] == match_case:
                return e["keff"], e["uncertainty"]
    for e in entries:
        if e["benchmark"] == bid:
            return e["keff"], e["uncertainty"]
    return None, None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(filepath, uncertainties):
    p = parse_mcnp_file(filepath)

    mats_out = {}
    for mid, nucs in p["materials"].items():
        total = sum(nucs.values())
        wf = weight_fractions(nucs)
        enr = enrichment_u235(nucs)
        mats_out[str(mid)] = {
            "nuclides": dict(nucs),
            "total_atom_density": total,
            "weight_fractions": wf,
            "enrichment_u235_wpct": enr,
        }

    cells_out = []
    for c in p["cells"]:
        if c["material_id"] == 0:
            continue
        vol = cell_volume(c["region"], p["surfaces"])
        cells_out.append({
            "id": c["id"], "material_id": c["material_id"],
            "volume_cm3": vol,
        })

    fm = fissile_mass_kg(p["cells"], p["materials"], p["surfaces"])
    keff, unc = find_experimental(uncertainties, p["benchmark_id"], p["case"])

    report = {
        "id": p["benchmark_id"], "title": p["title"],
        "materials": mats_out, "cells": cells_out,
        "total_fissile_mass_kg": fm,
        "experimental_keff": keff, "experimental_uncertainty": unc,
        "kcode": p["kcode"],
    }
    return p, report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    bench_dir = Path("/app/benchmarks")
    csv_path = Path("/app/data/uncertainties.csv")
    output_json = Path("/app/output/results.json")
    openmc_base = Path("/app/output/openmc")
    val_log = Path("/app/output/validation.log")

    uncertainties = load_uncertainties(csv_path)
    results, bids = [], []

    for fp in sorted(bench_dir.glob("*.i")):
        print(f"Processing {fp.name}...")
        parsed, report = analyze(fp, uncertainties)
        results.append(report)
        generate_openmc_files(parsed, str(openmc_base))
        bids.append(parsed["benchmark_id"])

    validate_xml(str(openmc_base), bids, str(val_log))

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w") as f:
        json.dump({"benchmarks": results}, f, indent=2)

    print(f"Done: {len(results)} benchmarks processed")
    print(f"  OpenMC XML: {openmc_base}")
    print(f"  Validation: {val_log}")
    print(f"  Report: {output_json}")


if __name__ == "__main__":
    main()
