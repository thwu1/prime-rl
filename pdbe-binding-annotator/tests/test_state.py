
import json
import os
import pytest


@pytest.fixture
def report():
    """Load the binding site annotation report."""
    report_path = "/app/report.json"
    assert os.path.exists(report_path), "report.json not found at /app/report.json"
    with open(report_path) as f:
        data = json.load(f)
    return data


@pytest.fixture
def resmap(report):
    """Build a lookup from author_residue_number to residue record."""
    return {r["author_residue_number"]: r for r in report["binding_residues"]}


class TestReportStructure:
    def test_top_level_keys(self, report):
        for key in ("pdb_id", "ligand", "binding_residues", "summary"):
            assert key in report, f"Missing top-level key: {key}"

    def test_pdb_id(self, report):
        assert report["pdb_id"] == "1cbs"

    def test_ligand_info(self, report):
        lig = report["ligand"]
        assert lig["chain_id"] == "A"
        assert lig["author_residue_number"] == 200
        assert lig["chem_comp_id"] == "REA"

    def test_binding_residue_keys(self, report):
        required = {
            "chain_id", "author_residue_number", "chem_comp_id",
            "uniprot_accession", "uniprot_residue_number",
            "interaction_types", "min_distance_angstroms",
            "ligand_atoms",
            "pfam_id", "cath_id", "secondary_structure", "outlier_types",
        }
        for res in report["binding_residues"]:
            missing = required - set(res.keys())
            assert not missing, f"Residue {res.get('author_residue_number')}: missing keys {missing}"


class TestBindingResidues:
    def test_total_count(self, report):
        """Exactly 18 protein binding residues (water excluded)."""
        assert len(report["binding_residues"]) == 18

    def test_no_water_molecules(self, report):
        for res in report["binding_residues"]:
            assert res["chem_comp_id"] != "HOH", \
                f"Water molecule found at residue {res['author_residue_number']}"

    def test_sorted_by_resnum(self, report):
        resnums = [r["author_residue_number"] for r in report["binding_residues"]]
        assert resnums == sorted(resnums), "binding_residues not sorted by author_residue_number"

    def test_expected_residue_numbers(self, report):
        expected = [15, 19, 24, 28, 31, 32, 35, 36, 39, 54, 56, 58, 59, 76, 121, 123, 132, 134]
        actual = [r["author_residue_number"] for r in report["binding_residues"]]
        assert actual == expected, f"Expected residue numbers {expected}, got {actual}"

    def test_expected_amino_acid_types(self, report):
        expected = {
            15: "PHE", 19: "LEU", 24: "VAL", 28: "LEU", 31: "ILE",
            32: "ALA", 35: "ALA", 36: "ALA", 39: "PRO", 54: "THR",
            56: "THR", 58: "VAL", 59: "ARG", 76: "VAL", 121: "LEU",
            123: "MET", 132: "ARG", 134: "TYR",
        }
        for res in report["binding_residues"]:
            rn = res["author_residue_number"]
            assert res["chem_comp_id"] == expected[rn], \
                f"Residue {rn}: expected {expected[rn]}, got {res['chem_comp_id']}"

    def test_all_chain_a(self, report):
        for res in report["binding_residues"]:
            assert res["chain_id"] == "A"


class TestUniProtMapping:
    def test_all_mapped_to_p29373(self, report):
        for res in report["binding_residues"]:
            assert res["uniprot_accession"] == "P29373", \
                f"Residue {res['author_residue_number']}: expected P29373"

    def test_uniprot_offset_is_plus_one(self, report):
        """For 1cbs, UniProt position = author_residue_number + 1."""
        for res in report["binding_residues"]:
            expected = res["author_residue_number"] + 1
            assert res["uniprot_residue_number"] == expected, \
                f"Residue {res['author_residue_number']}: expected UniProt {expected}, " \
                f"got {res['uniprot_residue_number']}"

    def test_specific_critical_mappings(self, resmap):
        checks = {15: 16, 54: 55, 76: 77, 121: 122, 132: 133, 134: 135}
        for pdb_rn, unp_rn in checks.items():
            assert resmap[pdb_rn]["uniprot_residue_number"] == unp_rn


class TestInteractionTypes:
    def test_phe15_hydrophobic_only(self, resmap):
        assert resmap[15]["interaction_types"] == ["hydrophobic"]

    def test_leu19_hydrophobic_only(self, resmap):
        assert resmap[19]["interaction_types"] == ["hydrophobic"]

    def test_ala32_hydrophobic_only(self, resmap):
        assert resmap[32]["interaction_types"] == ["hydrophobic"]

    def test_thr54_mixed(self, resmap):
        types = set(resmap[54]["interaction_types"])
        assert "hydrophobic" in types
        assert "weak_hbond" in types
        assert len(types) == 2

    def test_val76_mixed(self, resmap):
        types = set(resmap[76]["interaction_types"])
        assert "hydrophobic" in types
        assert "weak_hbond" in types

    def test_leu121_vdw_weakpolar(self, resmap):
        types = set(resmap[121]["interaction_types"])
        assert "vdw" in types
        assert "weak_polar" in types

    def test_arg132_hbond_polar_clash(self, resmap):
        types = set(resmap[132]["interaction_types"])
        assert "hbond" in types
        assert "polar" in types
        assert "vdw_clash" in types

    def test_tyr134_hbond_polar_clash(self, resmap):
        types = set(resmap[134]["interaction_types"])
        assert "hbond" in types
        assert "polar" in types
        assert "vdw_clash" in types

    def test_interaction_types_are_sorted(self, report):
        for res in report["binding_residues"]:
            assert res["interaction_types"] == sorted(res["interaction_types"]), \
                f"Residue {res['author_residue_number']}: interaction_types not sorted"


class TestMinDistances:
    def test_tyr134_min_distance(self, resmap):
        assert abs(resmap[134]["min_distance_angstroms"] - 2.57) < 0.02

    def test_arg132_min_distance(self, resmap):
        assert abs(resmap[132]["min_distance_angstroms"] - 2.73) < 0.02

    def test_ala32_min_distance(self, resmap):
        assert abs(resmap[32]["min_distance_angstroms"] - 3.52) < 0.02

    def test_phe15_min_distance(self, resmap):
        assert abs(resmap[15]["min_distance_angstroms"] - 3.91) < 0.02

    def test_thr54_min_distance(self, resmap):
        assert abs(resmap[54]["min_distance_angstroms"] - 3.69) < 0.02

    def test_leu121_min_distance(self, resmap):
        assert abs(resmap[121]["min_distance_angstroms"] - 3.26) < 0.02

    def test_tyr134_is_closest_contact(self, report):
        """TYR 134 has the closest contact in the binding site."""
        min_dist = min(r["min_distance_angstroms"] for r in report["binding_residues"])
        assert abs(min_dist - 2.57) < 0.02


class TestLigandAtoms:
    def test_phe15_ligand_atoms(self, resmap):
        assert resmap[15]["ligand_atoms"] == ["C10", "C11", "C12"]

    def test_leu19_ligand_atoms(self, resmap):
        assert resmap[19]["ligand_atoms"] == ["C18"]

    def test_val24_ligand_atoms(self, resmap):
        assert resmap[24]["ligand_atoms"] == ["C18", "C4"]

    def test_leu28_ligand_atoms(self, resmap):
        assert resmap[28]["ligand_atoms"] == ["C2", "C3"]

    def test_ala32_ligand_atoms(self, resmap):
        assert resmap[32]["ligand_atoms"] == ["C17", "C18", "C5", "C6", "C7", "C8", "C9"]

    def test_ala36_ligand_atoms(self, resmap):
        assert resmap[36]["ligand_atoms"] == ["C11", "C12", "C19", "C20"]

    def test_thr54_ligand_atoms(self, resmap):
        assert resmap[54]["ligand_atoms"] == ["C13", "C14", "C20", "O2"]

    def test_val58_ligand_atoms(self, resmap):
        assert resmap[58]["ligand_atoms"] == ["C16", "C17", "C19", "C7"]

    def test_val76_ligand_atoms(self, resmap):
        assert resmap[76]["ligand_atoms"] == ["C10", "C18"]

    def test_leu121_ligand_atoms(self, resmap):
        assert resmap[121]["ligand_atoms"] == ["O2"]

    def test_arg132_ligand_atoms(self, resmap):
        assert resmap[132]["ligand_atoms"] == ["O1"]

    def test_tyr134_ligand_atoms(self, resmap):
        assert resmap[134]["ligand_atoms"] == ["O1", "O2"]

    def test_ligand_atoms_sorted(self, report):
        for res in report["binding_residues"]:
            assert res["ligand_atoms"] == sorted(res["ligand_atoms"]), \
                f"Residue {res['author_residue_number']}: ligand_atoms not sorted"

    def test_ligand_atoms_deduplicated(self, report):
        for res in report["binding_residues"]:
            assert len(res["ligand_atoms"]) == len(set(res["ligand_atoms"])), \
                f"Residue {res['author_residue_number']}: ligand_atoms has duplicates"


class TestSecondaryStructure:
    def test_helix_residues(self, resmap):
        helix_expected = [15, 19, 28, 31, 32, 35, 36]
        for rn in helix_expected:
            assert resmap[rn]["secondary_structure"] == "helix", \
                f"Residue {rn} should be helix, got {resmap[rn]['secondary_structure']}"

    def test_strand_residues(self, resmap):
        strand_expected = [54, 121, 123, 132, 134]
        for rn in strand_expected:
            assert resmap[rn]["secondary_structure"] == "strand", \
                f"Residue {rn} should be strand, got {resmap[rn]['secondary_structure']}"

    def test_coil_residues(self, resmap):
        coil_expected = [24, 39, 56, 58, 59, 76]
        for rn in coil_expected:
            assert resmap[rn]["secondary_structure"] == "coil", \
                f"Residue {rn} should be coil, got {resmap[rn]['secondary_structure']}"


class TestDomainAnnotation:
    def test_all_residues_in_pfam_pf00061(self, report):
        for res in report["binding_residues"]:
            assert res["pfam_id"] == "PF00061", \
                f"Residue {res['author_residue_number']}: expected Pfam PF00061, got {res['pfam_id']}"

    def test_all_residues_in_cath_2_40_128_20(self, report):
        for res in report["binding_residues"]:
            assert res["cath_id"] == "2.40.128.20", \
                f"Residue {res['author_residue_number']}: expected CATH 2.40.128.20, got {res['cath_id']}"


class TestValidationOutliers:
    def test_val76_has_clashes(self, resmap):
        assert len(resmap[76]["outlier_types"]) > 0, "VAL 76 should have validation outliers"
        assert "clashes" in resmap[76]["outlier_types"]

    def test_clean_residues_have_no_outliers(self, resmap):
        clean_residues = [15, 19, 24, 28, 31, 32, 35, 36, 39, 54, 56, 58, 59, 121, 123, 132, 134]
        for rn in clean_residues:
            assert resmap[rn]["outlier_types"] == [], \
                f"Residue {rn} should have no outliers, got {resmap[rn]['outlier_types']}"


class TestSummary:
    def test_total_binding_residues(self, report):
        assert report["summary"]["total_binding_residues"] == 18

    def test_total_matches_list_length(self, report):
        assert report["summary"]["total_binding_residues"] == len(report["binding_residues"])

    def test_residues_with_outliers(self, report):
        assert report["summary"]["residues_with_outliers"] == 1

    def test_ss_composition_helix(self, report):
        assert report["summary"]["secondary_structure_composition"]["helix"] == 7

    def test_ss_composition_strand(self, report):
        assert report["summary"]["secondary_structure_composition"]["strand"] == 5

    def test_ss_composition_coil(self, report):
        assert report["summary"]["secondary_structure_composition"]["coil"] == 6

    def test_ss_composition_sums_to_total(self, report):
        ss = report["summary"]["secondary_structure_composition"]
        assert ss["helix"] + ss["strand"] + ss["coil"] == 18

    def test_pfam_domains(self, report):
        assert "PF00061" in report["summary"]["pfam_domains"]
        assert len(report["summary"]["pfam_domains"]) == 1

    def test_cath_superfamilies(self, report):
        assert "2.40.128.20" in report["summary"]["cath_superfamilies"]
        assert len(report["summary"]["cath_superfamilies"]) == 1

    def test_interaction_type_hydrophobic_count(self, report):
        counts = report["summary"]["interaction_type_counts"]
        assert counts.get("hydrophobic", 0) == 15

    def test_interaction_type_hbond_count(self, report):
        counts = report["summary"]["interaction_type_counts"]
        assert counts.get("hbond", 0) == 2

    def test_interaction_type_polar_count(self, report):
        counts = report["summary"]["interaction_type_counts"]
        assert counts.get("polar", 0) == 2

    def test_interaction_type_vdw_clash_count(self, report):
        counts = report["summary"]["interaction_type_counts"]
        assert counts.get("vdw_clash", 0) == 2

    def test_interaction_type_weak_hbond_count(self, report):
        counts = report["summary"]["interaction_type_counts"]
        assert counts.get("weak_hbond", 0) == 2

    def test_interaction_type_vdw_count(self, report):
        counts = report["summary"]["interaction_type_counts"]
        assert counts.get("vdw", 0) == 1

    def test_interaction_type_weak_polar_count(self, report):
        counts = report["summary"]["interaction_type_counts"]
        assert counts.get("weak_polar", 0) == 1

    def test_unique_ligand_atoms_contacted(self, report):
        assert report["summary"]["unique_ligand_atoms_contacted"] == 20

    def test_unique_ligand_atoms_consistent(self, report):
        """Verify unique_ligand_atoms_contacted matches union of all per-residue ligand_atoms."""
        all_atoms = set()
        for res in report["binding_residues"]:
            all_atoms.update(res["ligand_atoms"])
        assert report["summary"]["unique_ligand_atoms_contacted"] == len(all_atoms)
