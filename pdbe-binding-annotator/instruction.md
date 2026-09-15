Build a Python CLI tool at `/app/binding_site_annotator.py` that queries the PDBe REST API (`https://www.ebi.ac.uk/pdbe/api/`) to produce a ligand binding site annotation report.

**Usage:** `python3 /app/binding_site_annotator.py <pdb_id> <chain_id> <ligand_author_residue_number>`

**Output:** `/app/report.json`

The tool must identify all standard amino acid residues interacting with the specified ligand and annotate each by cross-referencing multiple PDBe API data sources. The report must integrate per-residue annotations spanning sequence database cross-references, protein domain classifications, secondary structure context, and experimental validation quality.

**Output JSON schema:**

```json
{
  "pdb_id": "string",
  "ligand": {"chain_id": "str", "author_residue_number": "int", "chem_comp_id": "str"},
  "binding_residues": [
    {
      "chain_id": "str",
      "author_residue_number": "int",
      "chem_comp_id": "str",
      "uniprot_accession": "str|null",
      "uniprot_residue_number": "int|null",
      "interaction_types": ["str"],
      "min_distance_angstroms": "float",
      "ligand_atoms": ["str"],
      "pfam_id": "str|null",
      "cath_id": "str|null",
      "secondary_structure": "helix|strand|coil",
      "outlier_types": ["str"]
    }
  ],
  "summary": {
    "total_binding_residues": "int",
    "interaction_type_counts": {"type_name": "int"},
    "residues_with_outliers": "int",
    "secondary_structure_composition": {"helix": "int", "strand": "int", "coil": "int"},
    "pfam_domains": ["str"],
    "cath_superfamilies": ["str"],
    "unique_ligand_atoms_contacted": "int"
  }
}
```

**Constraints:**

- `binding_residues` sorted ascending by `author_residue_number`
- `interaction_types`, `outlier_types`, and `ligand_atoms` are alphabetically sorted, deduplicated
- `ligand_atoms` lists the ligand atom names this residue contacts across all atom-atom interactions
- `interaction_type_counts` counts distinct residues exhibiting each interaction type
- `pfam_domains` and `cath_superfamilies` are sorted, deduplicated
- `unique_ligand_atoms_contacted` is the total count of distinct ligand atom names involved in at least one amino acid contact across the entire binding site
- The ligand's `chem_comp_id` must come from the API response
- UniProt residue positions must be correctly derived from PDBe mapping data, not assumed to match PDB author numbering

**Verification:** Tested with PDB `1cbs`, chain `A`, ligand author residue number `200`.
