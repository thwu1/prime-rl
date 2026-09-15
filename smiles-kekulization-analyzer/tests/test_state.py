#!/usr/bin/env python3
"""
Pytest tests for SMILES analyzer.
"""

import subprocess
import json
import pytest


def run_analyzer(smiles_list):
    """Run the SMILES analyzer on a list of SMILES strings."""
    input_text = "\n".join(smiles_list) + "\n"
    result = subprocess.run(
        ["python3", "/app/smiles_analyze.py"],
        input=input_text, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Analyzer failed: {result.stderr}"
    lines = result.stdout.strip().split("\n")
    results = [json.loads(line) for line in lines if line.strip()]
    assert len(results) == len(smiles_list), \
        f"Expected {len(smiles_list)} results, got {len(results)}"
    return results


# ====================================================================
# Basic parsing tests
# ====================================================================

class TestBasicParsing:
    def test_methane(self):
        r = run_analyzer(["C"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 1
        assert r["implicit_hydrogens"] == [4]
        assert r["molecular_formula"] == "CH4"

    def test_ethane(self):
        r = run_analyzer(["CC"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 2
        assert r["implicit_hydrogens"] == [3, 3]
        assert r["molecular_formula"] == "C2H6"

    def test_ethylene(self):
        r = run_analyzer(["C=C"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 2
        assert r["implicit_hydrogens"] == [2, 2]
        assert r["molecular_formula"] == "C2H4"

    def test_acetylene(self):
        r = run_analyzer(["C#C"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [1, 1]
        assert r["molecular_formula"] == "C2H2"

    def test_water(self):
        r = run_analyzer(["O"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 1
        assert r["implicit_hydrogens"] == [2]
        assert r["molecular_formula"] == "H2O"

    def test_ammonia(self):
        r = run_analyzer(["N"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [3]
        assert r["molecular_formula"] == "H3N"

    def test_hydrogen_sulfide(self):
        r = run_analyzer(["S"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [2]
        assert r["molecular_formula"] == "H2S"

    def test_hydrogen_fluoride(self):
        r = run_analyzer(["F"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [1]
        assert r["molecular_formula"] == "FH"

    def test_hcl(self):
        r = run_analyzer(["Cl"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [1]
        assert r["molecular_formula"] == "ClH"

    def test_hbr(self):
        r = run_analyzer(["Br"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [1]
        assert r["molecular_formula"] == "BrH"

    def test_hi(self):
        r = run_analyzer(["I"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [1]
        assert r["molecular_formula"] == "HI"


# ====================================================================
# Branching and ring tests
# ====================================================================

class TestStructure:
    def test_isobutane(self):
        r = run_analyzer(["CC(C)C"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 4
        assert r["implicit_hydrogens"] == [3, 1, 3, 3]
        assert r["molecular_formula"] == "C4H10"

    def test_formic_acid(self):
        r = run_analyzer(["C(=O)O"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 3
        assert r["implicit_hydrogens"] == [1, 0, 1]
        assert r["molecular_formula"] == "CH2O2"

    def test_acetic_acid(self):
        r = run_analyzer(["CC(=O)O"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 4
        assert r["implicit_hydrogens"] == [3, 0, 0, 1]
        assert r["molecular_formula"] == "C2H4O2"

    def test_cyclopropane(self):
        r = run_analyzer(["C1CC1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 3
        assert r["implicit_hydrogens"] == [2, 2, 2]
        assert r["molecular_formula"] == "C3H6"

    def test_cyclobutane(self):
        r = run_analyzer(["C1CCC1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 4
        assert r["implicit_hydrogens"] == [2, 2, 2, 2]
        assert r["molecular_formula"] == "C4H8"

    def test_disconnected_methanes(self):
        r = run_analyzer(["C.C"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 2
        assert r["implicit_hydrogens"] == [4, 4]
        assert r["molecular_formula"] == "C2H8"

    def test_chlorobenzene(self):
        r = run_analyzer(["c1ccccc1Cl"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 7
        assert r["molecular_formula"] == "C6H5Cl"
        assert r["kekulizable"] is True

    def test_double_bond_ring(self):
        """Ring with explicit double bond via ring closure."""
        r = run_analyzer(["C=1CCCCC1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 6
        # cyclohexene: double bond closes ring 0-5
        assert r["molecular_formula"] == "C6H10"


# ====================================================================
# Aromatic implicit hydrogen tests
# ====================================================================

class TestAromaticHydrogens:
    def test_benzene(self):
        r = run_analyzer(["c1ccccc1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 6
        assert r["implicit_hydrogens"] == [1, 1, 1, 1, 1, 1]
        assert r["molecular_formula"] == "C6H6"
        assert r["kekulizable"] is True

    def test_pyridine(self):
        """Pyridine: N has 0 implicit H (pyridine-type)."""
        r = run_analyzer(["c1ccncc1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 6
        assert r["implicit_hydrogens"] == [1, 1, 1, 0, 1, 1]
        assert r["molecular_formula"] == "C5H5N"
        assert r["kekulizable"] is True

    def test_pyrrole(self):
        """Pyrrole: [nH] has 1 explicit H."""
        r = run_analyzer(["c1cc[nH]c1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 5
        assert r["implicit_hydrogens"] == [1, 1, 1, 1, 1]
        assert r["molecular_formula"] == "C4H5N"
        assert r["kekulizable"] is True

    def test_furan(self):
        """Furan: aromatic O has 0 implicit H."""
        r = run_analyzer(["c1ccoc1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 5
        assert r["implicit_hydrogens"] == [1, 1, 1, 0, 1]
        assert r["molecular_formula"] == "C4H4O"
        assert r["kekulizable"] is True

    def test_thiophene(self):
        """Thiophene: aromatic S has 0 implicit H."""
        r = run_analyzer(["c1ccsc1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 5
        assert r["implicit_hydrogens"] == [1, 1, 1, 0, 1]
        assert r["molecular_formula"] == "C4H4S"
        assert r["kekulizable"] is True

    def test_naphthalene(self):
        """Naphthalene: bridgehead C atoms have 0 implicit H."""
        r = run_analyzer(["c1ccc2ccccc2c1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 10
        assert r["implicit_hydrogens"] == [1, 1, 1, 0, 1, 1, 1, 1, 0, 1]
        assert r["molecular_formula"] == "C10H8"
        assert r["kekulizable"] is True

    def test_imidazole(self):
        """Imidazole: c1c[nH]cn1 — two N, one with H."""
        r = run_analyzer(["c1c[nH]cn1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 5
        # c(1H), c(1H), [nH](1H), c(1H), n(0H)
        assert r["implicit_hydrogens"] == [1, 1, 1, 1, 0]
        assert r["molecular_formula"] == "C3H4N2"
        assert r["kekulizable"] is True

    def test_pyrimidine(self):
        """Pyrimidine: c1cncnc1 — two pyridine-type N."""
        r = run_analyzer(["c1cncnc1"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 6
        assert r["implicit_hydrogens"] == [1, 1, 0, 1, 0, 1]
        assert r["molecular_formula"] == "C4H4N2"
        assert r["kekulizable"] is True

    def test_toluene(self):
        """Toluene: methyl on benzene. Aromatic C bonded to CH3 has 0 H."""
        r = run_analyzer(["c1ccccc1C"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 7
        # c atoms: first 5 have 1H, c bonded to CH3 has 0H (3 bonds), CH3 has 3H
        assert r["implicit_hydrogens"] == [1, 1, 1, 1, 1, 0, 3]
        assert r["molecular_formula"] == "C7H8"


# ====================================================================
# Bracket atom tests
# ====================================================================

class TestBracketAtoms:
    def test_sodium(self):
        r = run_analyzer(["[Na]"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 1
        assert r["implicit_hydrogens"] == [0]
        assert r["molecular_formula"] == "Na"

    def test_ammonium(self):
        r = run_analyzer(["[NH4+]"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [4]
        assert r["molecular_formula"] == "H4N"

    def test_oxide_anion(self):
        r = run_analyzer(["[O-]"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [0]
        assert r["molecular_formula"] == "O"

    def test_chiral_carbon(self):
        r = run_analyzer(["[C@@H](Br)(Cl)F"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 4
        assert r["implicit_hydrogens"] == [1, 0, 0, 0]
        assert r["molecular_formula"] == "CHBrClF"

    def test_deuterium(self):
        r = run_analyzer(["[2H]"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 1
        assert r["implicit_hydrogens"] == [0]

    def test_iron(self):
        r = run_analyzer(["[Fe]"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 1
        assert r["implicit_hydrogens"] == [0]
        assert r["molecular_formula"] == "Fe"


# ====================================================================
# Syntax error tests
# ====================================================================

class TestSyntaxErrors:
    def test_unmatched_close_paren(self):
        r = run_analyzer([")"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "syntax"

    def test_unclosed_branch(self):
        r = run_analyzer(["C("])[0]
        assert r["valid"] is False
        assert r["error_type"] == "syntax"

    def test_unclosed_ring(self):
        r = run_analyzer(["C1CC"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "syntax"

    def test_unmatched_bracket(self):
        r = run_analyzer(["[C"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "syntax"

    def test_invalid_character(self):
        r = run_analyzer(["X"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "syntax"

    def test_trailing_bond(self):
        r = run_analyzer(["C="])[0]
        assert r["valid"] is False
        assert r["error_type"] == "syntax"

    def test_all_null_on_error(self):
        r = run_analyzer([")"])[0]
        assert r["num_heavy_atoms"] is None
        assert r["implicit_hydrogens"] is None
        assert r["molecular_formula"] is None
        assert r["kekulizable"] is None
        assert r["tautomer_hash"] is None


# ====================================================================
# Valence error tests
# ====================================================================

class TestValenceErrors:
    def test_pentavalent_carbon(self):
        r = run_analyzer(["C(C)(C)(C)(C)C"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "valence"

    def test_trivalent_oxygen(self):
        r = run_analyzer(["O(C)(C)C"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "valence"

    def test_divalent_fluorine(self):
        r = run_analyzer(["FCF"])[0]
        # F-C-F: C has bond_sum=2, h=2, fine. F has bond_sum=1, h=0, fine.
        # Actually this is valid! Let me reconsider...
        # F: bond to C, bond_sum=1, target=1, h=0. Valid.
        assert r["valid"] is True

    def test_trivalent_fluorine(self):
        r = run_analyzer(["F(C)C"])[0]
        # F bonded to two C atoms: bond_sum=2, max allowed=1
        assert r["valid"] is False
        assert r["error_type"] == "valence"


# ====================================================================
# Kekulization tests
# ====================================================================

class TestKekulization:
    def test_benzene_kekulizable(self):
        r = run_analyzer(["c1ccccc1"])[0]
        assert r["valid"] is True
        assert r["kekulizable"] is True

    def test_non_aromatic_has_null_kekulizable(self):
        r = run_analyzer(["CC"])[0]
        assert r["valid"] is True
        assert r["kekulizable"] is None

    def test_five_ring_no_donor_fails(self):
        """c1cncc1: 5-ring with pyridine-N, all atoms need double, odd count."""
        r = run_analyzer(["c1cncc1"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "kekulization"

    def test_six_ring_with_aromatic_oxygen_fails(self):
        """c1ccocc1: 6-ring with aromatic O, 5 C need double (odd)."""
        r = run_analyzer(["c1ccocc1"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "kekulization"

    def test_cyclobutadiene_kekulizable(self):
        """c1ccc1: 4-ring all aromatic C, 4 atoms, even, can match."""
        r = run_analyzer(["c1ccc1"])[0]
        assert r["valid"] is True
        assert r["kekulizable"] is True

    def test_naphthalene_kekulizable(self):
        r = run_analyzer(["c1ccc2ccccc2c1"])[0]
        assert r["valid"] is True
        assert r["kekulizable"] is True

    def test_three_ring_aromatic_fails(self):
        """c1cc1: 3-ring all aromatic C, odd → not kekulizable."""
        r = run_analyzer(["c1cc1"])[0]
        assert r["valid"] is False
        assert r["error_type"] == "kekulization"


# ====================================================================
# Tautomer hash tests
# ====================================================================

class TestTautomerHash:
    def test_amidine_tautomers_same_hash(self):
        """N=CN and NC=N are amidine tautomers: same hash."""
        results = run_analyzer(["N=CN", "NC=N"])
        assert results[0]["tautomer_hash"] == results[1]["tautomer_hash"]

    def test_glycine_forms_same_hash(self):
        """Zwitterionic and neutral glycine: same tautomer hash."""
        results = run_analyzer(["[NH3+]CC(=O)[O-]", "NCC(=O)O"])
        assert results[0]["tautomer_hash"] == results[1]["tautomer_hash"]

    def test_same_molecule_different_smiles_same_hash(self):
        """CCO and OCC are the same molecule: same hash."""
        results = run_analyzer(["CCO", "OCC"])
        assert results[0]["tautomer_hash"] == results[1]["tautomer_hash"]

    def test_different_molecules_different_hash(self):
        """Ethanol (CCO) and acetaldehyde (CC=O) are different: different hash."""
        results = run_analyzer(["CCO", "CC=O"])
        assert results[0]["tautomer_hash"] != results[1]["tautomer_hash"]

    def test_proto_h_value_amidine(self):
        """N=CN: non-C H = 1(N) + 2(N) = 3, charges = 0, proto_h = 3."""
        r = run_analyzer(["N=CN"])[0]
        assert r["tautomer_hash"].endswith("_3")

    def test_proto_h_value_ethanol(self):
        """CCO: non-C H = 1(O), charges = 0, proto_h = 1."""
        r = run_analyzer(["CCO"])[0]
        assert r["tautomer_hash"].endswith("_1")

    def test_proto_h_value_methane(self):
        """C: no non-C atoms, proto_h = 0."""
        r = run_analyzer(["C"])[0]
        assert r["tautomer_hash"].endswith("_0")

    def test_proto_h_value_zwitterion(self):
        """[NH3+]CC(=O)[O-]: non-C H = 3, charges = +1-1 = 0, proto_h = 3."""
        r = run_analyzer(["[NH3+]CC(=O)[O-]"])[0]
        assert r["tautomer_hash"].endswith("_3")

    def test_hash_format(self):
        """Hash should be 16 hex chars + underscore + integer."""
        r = run_analyzer(["C"])[0]
        h = r["tautomer_hash"]
        parts = h.rsplit("_", 1)
        assert len(parts) == 2
        assert len(parts[0]) == 16
        assert all(c in "0123456789abcdef" for c in parts[0])
        int(parts[1])  # should not raise


# ====================================================================
# Molecular formula tests
# ====================================================================

class TestMolecularFormula:
    def test_hill_order_with_carbon(self):
        """C first, H second, then alphabetical."""
        r = run_analyzer(["c1ccncc1"])[0]
        assert r["molecular_formula"] == "C5H5N"

    def test_hill_order_no_carbon(self):
        """Without C: all elements alphabetical."""
        r = run_analyzer(["N"])[0]
        assert r["molecular_formula"] == "H3N"

    def test_count_omitted_for_one(self):
        r = run_analyzer(["C"])[0]
        assert r["molecular_formula"] == "CH4"

    def test_complex_formula(self):
        r = run_analyzer(["c1ccc2ccccc2c1"])[0]
        assert r["molecular_formula"] == "C10H8"

    def test_halogenated(self):
        r = run_analyzer(["[C@@H](Br)(Cl)F"])[0]
        assert r["molecular_formula"] == "CHBrClF"

    def test_sulfur_compound(self):
        r = run_analyzer(["c1ccsc1"])[0]
        assert r["molecular_formula"] == "C4H4S"


# ====================================================================
# Edge cases and complex molecules
# ====================================================================

class TestEdgeCases:
    def test_multiple_ring_closures_on_atom(self):
        """C12(CC1)CC2 — atom 0 opens two rings."""
        r = run_analyzer(["C12(CC1)CC2"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 5

    def test_percent_ring_closure(self):
        """Ring closure with %nn notation."""
        r = run_analyzer(["C%10CCCCCCCCC%10"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 10
        assert r["molecular_formula"] == "C10H20"

    def test_stereo_bond_treated_as_single(self):
        """/ and \\ bonds treated as single."""
        r = run_analyzer(["F/C=C/F"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 4
        assert r["molecular_formula"] == "C2H2F2"

    def test_phosphorus(self):
        r = run_analyzer(["P"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [3]
        assert r["molecular_formula"] == "H3P"

    def test_boron(self):
        r = run_analyzer(["B"])[0]
        assert r["valid"] is True
        assert r["implicit_hydrogens"] == [3]
        assert r["molecular_formula"] == "BH3"

    def test_pentavalent_nitrogen_valid(self):
        """N with 5 bonds: valence 5 is allowed."""
        r = run_analyzer(["N(=O)(=O)C"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 4

    def test_hexavalent_sulfur_valid(self):
        """S with 6 bonds: valence 6 is allowed (sulfur hexafluoride-like)."""
        r = run_analyzer(["S(F)(F)(F)(F)(F)F"])[0]
        assert r["valid"] is True
        assert r["num_heavy_atoms"] == 7
        assert r["molecular_formula"] == "F6S"
