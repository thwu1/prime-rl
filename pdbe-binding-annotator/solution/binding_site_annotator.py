#!/usr/bin/env python3
"""PDBe binding site annotator — integrates 6 API endpoints into a unified report."""

import sys
import json
import requests

BASE_URL = "https://www.ebi.ac.uk/pdbe/api"

# Standard amino acid 3-letter codes (including common modified variants)
AMINO_ACIDS = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "MSE", "SEC", "PYL",
}


def fetch_json(url):
    """Fetch JSON from a URL with error handling."""
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


def get_ligand_interactions(pdb_id, chain_id, seq_id):
    """Get atom-level interactions for a bound ligand."""
    url = f"{BASE_URL}/pdb/bound_ligand_interactions/{pdb_id}/{chain_id}/{seq_id}"
    data = fetch_json(url)
    return data[pdb_id]


def get_sifts_uniprot(pdb_id):
    """Get SIFTS UniProt mappings."""
    url = f"{BASE_URL}/mappings/uniprot/{pdb_id}"
    data = fetch_json(url)
    return data[pdb_id].get("UniProt", {})


def get_sifts_pfam(pdb_id):
    """Get SIFTS Pfam domain mappings."""
    url = f"{BASE_URL}/mappings/pfam/{pdb_id}"
    data = fetch_json(url)
    return data[pdb_id].get("Pfam", {})


def get_sifts_cath(pdb_id):
    """Get SIFTS CATH classification mappings."""
    url = f"{BASE_URL}/mappings/cath/{pdb_id}"
    data = fetch_json(url)
    return data[pdb_id].get("CATH", {})


def get_validation_outliers(pdb_id):
    """Get per-residue validation outlier summary."""
    url = f"{BASE_URL}/validation/residuewise_outlier_summary/entry/{pdb_id}"
    data = fetch_json(url)
    return data[pdb_id]


def get_secondary_structure(pdb_id):
    """Get secondary structure assignments."""
    url = f"{BASE_URL}/pdb/entry/secondary_structure/{pdb_id}"
    data = fetch_json(url)
    return data[pdb_id]


def map_to_uniprot(chain_id, author_resnum, uniprot_data):
    """Map PDB author_residue_number to UniProt accession and position.

    Uses SIFTS segment boundaries: for a segment mapping PDB start to UniProt unp_start,
    the UniProt position = unp_start + (author_residue_number - start.author_residue_number).
    This holds when author numbering is sequential within the segment.
    """
    for acc, info in uniprot_data.items():
        for mapping in info.get("mappings", []):
            if mapping["chain_id"] != chain_id:
                continue
            start_author = mapping["start"]["author_residue_number"]
            end_author = mapping["end"]["author_residue_number"]
            # Handle null end author residue number
            if end_author is None:
                # Fall back to residue_number-based bounds
                start_resnum = mapping["start"]["residue_number"]
                end_resnum = mapping["end"]["residue_number"]
                # Estimate author range from residue numbers
                author_offset = start_resnum - start_author
                estimated_end_author = end_resnum - author_offset
                if start_author <= author_resnum <= estimated_end_author:
                    unp_pos = mapping["unp_start"] + (author_resnum - start_author)
                    return acc, unp_pos
            elif start_author <= author_resnum <= end_author:
                unp_pos = mapping["unp_start"] + (author_resnum - start_author)
                return acc, unp_pos
    return None, None


def find_pfam(chain_id, author_resnum, pfam_data):
    """Find the Pfam domain covering a residue, if any."""
    for pfam_id, info in pfam_data.items():
        for mapping in info.get("mappings", []):
            if mapping["chain_id"] != chain_id:
                continue
            start = mapping["start"]["author_residue_number"]
            end = mapping["end"]["author_residue_number"]
            if start <= author_resnum <= end:
                return pfam_id
    return None


def find_cath(chain_id, author_resnum, cath_data):
    """Find the CATH superfamily covering a residue, if any."""
    for cath_id, info in cath_data.items():
        for mapping in info.get("mappings", []):
            if mapping["chain_id"] != chain_id:
                continue
            start = mapping["start"]["author_residue_number"]
            end = mapping["end"]["author_residue_number"]
            if start <= author_resnum <= end:
                return cath_id
    return None


def get_outliers_for_residue(chain_id, author_resnum, outlier_data):
    """Get sorted list of validation outlier types for a specific residue."""
    for mol in outlier_data.get("molecules", []):
        for chain in mol.get("chains", []):
            if chain.get("chain_id") != chain_id:
                continue
            for model in chain.get("models", []):
                for res in model.get("residues", []):
                    if res.get("author_residue_number") == author_resnum:
                        return sorted(res.get("outlier_types", []))
    return []


def assign_secondary_structure(chain_id, author_resnum, ss_data):
    """Classify residue as helix, strand, or coil based on SS range annotations."""
    for mol in ss_data.get("molecules", []):
        for chain in mol.get("chains", []):
            if chain.get("chain_id") != chain_id:
                continue
            ss = chain.get("secondary_structure", {})
            for helix in ss.get("helices", []):
                h_start = helix["start"]["author_residue_number"]
                h_end = helix["end"]["author_residue_number"]
                if h_start <= author_resnum <= h_end:
                    return "helix"
            for strand in ss.get("strands", []):
                s_start = strand["start"]["author_residue_number"]
                s_end = strand["end"]["author_residue_number"]
                if s_start <= author_resnum <= s_end:
                    return "strand"
    return "coil"


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 binding_site_annotator.py <pdb_id> <chain_id> <ligand_author_residue_number>")
        sys.exit(1)

    pdb_id = sys.argv[1].lower()
    chain_id = sys.argv[2]
    ligand_resnum = int(sys.argv[3])

    print(f"Fetching data for {pdb_id} chain {chain_id} ligand {ligand_resnum}...")

    # Fetch data from all 6 endpoints
    interactions_list = get_ligand_interactions(pdb_id, chain_id, ligand_resnum)
    uniprot_data = get_sifts_uniprot(pdb_id)
    pfam_data = get_sifts_pfam(pdb_id)
    cath_data = get_sifts_cath(pdb_id)
    outlier_data = get_validation_outliers(pdb_id)
    ss_data = get_secondary_structure(pdb_id)

    # Extract ligand metadata from the API response
    ligand_info = interactions_list[0]["ligand"]
    chem_comp_id = ligand_info["chem_comp_id"]

    # Group atom-atom interactions by protein residue
    residue_interactions = {}
    for interaction in interactions_list[0]["interactions"]:
        end = interaction["end"]
        end_chain = end["chain_id"]
        end_resnum = end["author_residue_number"]
        end_comp = end["chem_comp_id"]

        # Exclude water and non-amino-acid residues
        if end_comp not in AMINO_ACIDS:
            continue

        key = (end_chain, end_resnum)
        if key not in residue_interactions:
            residue_interactions[key] = {
                "chain_id": end_chain,
                "author_residue_number": end_resnum,
                "chem_comp_id": end_comp,
                "interaction_types": set(),
                "ligand_atoms": set(),
                "min_distance": float("inf"),
            }

        # Collect all interaction detail types
        for detail in interaction.get("interaction_details", []):
            residue_interactions[key]["interaction_types"].add(detail)

        # Collect ligand atom names
        for atom_name in interaction.get("ligand_atoms", []):
            residue_interactions[key]["ligand_atoms"].add(atom_name)

        # Track minimum distance
        dist = interaction.get("distance")
        if dist is not None:
            residue_interactions[key]["min_distance"] = min(
                residue_interactions[key]["min_distance"], dist
            )

    # Build annotated binding residue records
    binding_residues = []
    all_ligand_atoms = set()
    for key in sorted(residue_interactions.keys(), key=lambda x: x[1]):
        res = residue_interactions[key]
        chain = res["chain_id"]
        author_resnum = res["author_residue_number"]

        unp_acc, unp_resnum = map_to_uniprot(chain, author_resnum, uniprot_data)
        pfam_id = find_pfam(chain, author_resnum, pfam_data)
        cath_id = find_cath(chain, author_resnum, cath_data)
        outliers = get_outliers_for_residue(chain, author_resnum, outlier_data)
        ss = assign_secondary_structure(chain, author_resnum, ss_data)

        all_ligand_atoms.update(res["ligand_atoms"])

        binding_residues.append({
            "chain_id": chain,
            "author_residue_number": author_resnum,
            "chem_comp_id": res["chem_comp_id"],
            "uniprot_accession": unp_acc,
            "uniprot_residue_number": unp_resnum,
            "interaction_types": sorted(res["interaction_types"]),
            "min_distance_angstroms": round(res["min_distance"], 2),
            "ligand_atoms": sorted(res["ligand_atoms"]),
            "pfam_id": pfam_id,
            "cath_id": cath_id,
            "secondary_structure": ss,
            "outlier_types": outliers,
        })

    # Compute summary statistics
    interaction_type_counts = {}
    for res in binding_residues:
        for itype in res["interaction_types"]:
            interaction_type_counts[itype] = interaction_type_counts.get(itype, 0) + 1

    residues_with_outliers = sum(1 for r in binding_residues if r["outlier_types"])

    ss_composition = {"helix": 0, "strand": 0, "coil": 0}
    for res in binding_residues:
        ss_composition[res["secondary_structure"]] += 1

    pfam_domains = sorted(set(r["pfam_id"] for r in binding_residues if r["pfam_id"]))
    cath_superfamilies = sorted(set(r["cath_id"] for r in binding_residues if r["cath_id"]))

    report = {
        "pdb_id": pdb_id,
        "ligand": {
            "chain_id": chain_id,
            "author_residue_number": ligand_resnum,
            "chem_comp_id": chem_comp_id,
        },
        "binding_residues": binding_residues,
        "summary": {
            "total_binding_residues": len(binding_residues),
            "interaction_type_counts": interaction_type_counts,
            "residues_with_outliers": residues_with_outliers,
            "secondary_structure_composition": ss_composition,
            "pfam_domains": pfam_domains,
            "cath_superfamilies": cath_superfamilies,
            "unique_ligand_atoms_contacted": len(all_ligand_atoms),
        },
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to /app/report.json")
    print(f"Found {len(binding_residues)} binding protein residues")


if __name__ == "__main__":
    main()
