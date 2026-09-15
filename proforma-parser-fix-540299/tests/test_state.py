
import json
import pytest


@pytest.fixture(scope="session")
def results():
    with open("/app/output.json") as f:
        return json.load(f)


def get_result(results, input_str):
    """Find the result object matching the given input string."""
    for r in results:
        if r["input"] == input_str:
            return r
    pytest.fail(f"No result found for input: {input_str!r}")


# ============================================================
# Structural tests
# ============================================================

class TestStructure:
    def test_result_count(self, results):
        """There should be exactly 43 results (36 positive + 7 negative)."""
        assert len(results) == 43

    def test_all_have_input(self, results):
        for r in results:
            assert "input" in r
            assert "valid" in r


# ============================================================
# Positive: basic sequences (cases 1-2)
# ============================================================

class TestBasicSequences:
    def test_simple_dipeptide(self, results):
        r = get_result(results, "AA")
        assert r["valid"] is True
        assert r["sequence"] == "AA"
        assert r["chain_count"] == 1
        assert r["ion_count"] == 1
        assert r["charge"] is None
        assert len(r["modifications"]) == 0
        assert r["n_terminal"] == []
        assert r["c_terminal"] == []

    def test_longer_sequence(self, results):
        r = get_result(results, "AAHCFKUOT")
        assert r["valid"] is True
        assert r["sequence"] == "AAHCFKUOT"
        assert r["chain_count"] == 1


# ============================================================
# Positive: simple modifications (cases 3-6)
# ============================================================

class TestSimpleModifications:
    def test_named_mods(self, results):
        r = get_result(results, "EM[Oxidation]EVEES[Phospho]PEK")
        assert r["valid"] is True
        assert r["sequence"] == "EMEVEESPEK"
        assert len(r["modifications"]) == 2
        assert r["modifications"][0] == {"position": 2, "value": "Oxidation"}
        assert r["modifications"][1] == {"position": 7, "value": "Phospho"}

    def test_mass_mods(self, results):
        r = get_result(results, "EM[+15.9949]EVEES[+79.9663]PEK")
        assert r["valid"] is True
        assert r["sequence"] == "EMEVEESPEK"
        assert r["modifications"][0]["value"] == "+15.9949"
        assert r["modifications"][1]["value"] == "+79.9663"

    def test_accession_mods(self, results):
        r = get_result(results, "EM[MOD:00719]EVEES[MOD:00046]PEK")
        assert r["valid"] is True
        assert r["sequence"] == "EMEVEESPEK"
        assert r["modifications"][0]["value"] == "MOD:00719"

    def test_cv_prefix_mods(self, results):
        r = get_result(results, "EM[U:Oxidation]EVEES[U:Phospho]PEK")
        assert r["valid"] is True
        assert r["sequence"] == "EMEVEESPEK"
        assert r["modifications"][0]["value"] == "U:Oxidation"


# ============================================================
# Positive: terminal modifications (cases 7-9)
# ============================================================

class TestTerminalModifications:
    def test_n_terminal(self, results):
        r = get_result(results, "[iTRAQ4plex]-EM[Oxidation]EVNES[Phospho]PEK")
        assert r["valid"] is True
        assert r["n_terminal"] == ["iTRAQ4plex"]
        assert r["sequence"] == "EMEVNESPEK"

    def test_c_terminal(self, results):
        r = get_result(results, "PEPTIDEG-[Methyl]")
        assert r["valid"] is True
        assert r["c_terminal"] == ["Methyl"]
        assert r["sequence"] == "PEPTIDEG"

    def test_both_terminals(self, results):
        r = get_result(
            results,
            "[iTRAQ4plex]-EM[Oxidation]EVNES[Phospho]PEK[iTRAQ4plex]-[Methyl]",
        )
        assert r["valid"] is True
        assert r["n_terminal"] == ["iTRAQ4plex"]
        assert r["c_terminal"] == ["Methyl"]


# ============================================================
# Positive: nested brackets (cases 10, 12, 25)
# ============================================================

class TestNestedBrackets:
    def test_cation_nested_brackets(self, results):
        r = get_result(
            results, "EM[Oxidation]EVE[Cation:Mg[II]]ES[Phospho]PEK"
        )
        assert r["valid"] is True
        assert r["sequence"] == "EMEVEESPEK"
        mod_values = [m["value"] for m in r["modifications"]]
        assert "Cation:Mg[II]" in mod_values
        assert "Oxidation" in mod_values
        assert "Phospho" in mod_values

    def test_formula_with_isotope_brackets(self, results):
        r = get_result(results, "SEQUEN[Formula:[13C2]C-2H2N]CE")
        assert r["valid"] is True
        assert r["sequence"] == "SEQUENCE"
        assert r["modifications"][0]["value"] == "Formula:[13C2]C-2H2N"
        assert "formula" in r["features"]

    def test_info_with_nested_brackets(self, results):
        inp = "ELVIS[Phospho|INFO:newly discovered|INFO:really awesome [new-to-science] #cool]K"
        r = get_result(results, inp)
        assert r["valid"] is True
        assert r["sequence"] == "ELVISK"
        assert "info" in r["features"]
        mod_val = r["modifications"][0]["value"]
        assert "Phospho" in mod_val
        assert "[new-to-science]" in mod_val


# ============================================================
# Positive: formula & glycan (cases 11, 13)
# ============================================================

class TestFormulaGlycan:
    def test_simple_formula(self, results):
        r = get_result(results, "SEQUEN[Formula:C12H20O2]CE")
        assert r["valid"] is True
        assert r["sequence"] == "SEQUENCE"
        assert "formula" in r["features"]

    def test_glycan(self, results):
        r = get_result(results, "SEQUEN[Glycan:HexNAc1Hex2]CE")
        assert r["valid"] is True
        assert r["sequence"] == "SEQUENCE"
        assert "glycan" in r["features"]


# ============================================================
# Positive: info tag (case 14)
# ============================================================

class TestInfoTag:
    def test_info(self, results):
        r = get_result(results, "ELVIS[Phospho|INFO:newly discovered]K")
        assert r["valid"] is True
        assert r["sequence"] == "ELVISK"
        assert "info" in r["features"]
        assert r["modifications"][0]["value"] == "Phospho|INFO:newly discovered"


# ============================================================
# Positive: charge states (cases 15-16)
# ============================================================

class TestCharge:
    def test_integer_charge(self, results):
        r = get_result(results, "EMEVEESPEK/2")
        assert r["valid"] is True
        assert r["charge"] == 2
        assert "charge" in r["features"]

    def test_adduct_charge(self, results):
        r = get_result(results, "PEPTIDE/[Na:z+1]")
        assert r["valid"] is True
        assert r["charge"] == 1
        assert "charge" in r["features"]


# ============================================================
# Positive: cross-link (case 17)
# ============================================================

class TestCrossLink:
    def test_cross_link_two_chains(self, results):
        r = get_result(
            results, "SEK[XLMOD:02001#XL1]UENCE//EMEVTK[#XL1]SESPEK"
        )
        assert r["valid"] is True
        assert r["chain_count"] == 2
        assert r["sequence"] == "SEKUENCE"
        assert "cross_link" in r["features"]
        assert "label" in r["features"]


# ============================================================
# Positive: chimeric spectra (case 18)
# ============================================================

class TestChimeric:
    def test_chimeric_two_ions(self, results):
        r = get_result(results, "EMEVEESPEK+ELVISLIVER")
        assert r["valid"] is True
        assert r["ion_count"] == 2
        assert r["sequence"] == "EMEVEESPEK"
        assert "chimeric" in r["features"]


# ============================================================
# Positive: global modifications (cases 19-20)
# ============================================================

class TestGlobalModifications:
    def test_global_isotope(self, results):
        r = get_result(results, "<13C>ATPEILTVNSIGQLK")
        assert r["valid"] is True
        assert r["sequence"] == "ATPEILTVNSIGQLK"
        assert "global_isotope" in r["features"]

    def test_global_fixed(self, results):
        r = get_result(results, "<[Oxidation]@C,M>MTPEILTCNSIGCLK")
        assert r["valid"] is True
        assert r["sequence"] == "MTPEILTCNSIGCLK"
        assert "global_fixed" in r["features"]
        assert "global_isotope" not in r["features"]


# ============================================================
# Positive: labile modifications (case 21)
# ============================================================

class TestLabileMods:
    def test_labile(self, results):
        r = get_result(results, "{Glycan:Hex}EM[Oxidation]EVNESPEK")
        assert r["valid"] is True
        assert r["sequence"] == "EMEVNESPEK"
        assert "labile" in r["features"]


# ============================================================
# Positive: unlocalised modifications (case 22)
# ============================================================

class TestUnlocalisedMods:
    def test_unlocalised(self, results):
        r = get_result(results, "[Phospho]?EM[Oxidation]EVTSESPEK")
        assert r["valid"] is True
        assert r["sequence"] == "EMEVTSESPEK"
        assert "unlocalised" in r["features"]


# ============================================================
# Positive: ambiguous amino acids (case 23)
# ============================================================

class TestAmbiguousAA:
    def test_ambiguous(self, results):
        r = get_result(
            results,
            "(?DQ)NGTWEM[Oxidation]ESNENFEGYM[Oxidation]K",
        )
        assert r["valid"] is True
        assert "ambiguous_aa" in r["features"]
        assert r["sequence"].startswith("DQ")
        assert r["sequence"] == "DQNGTWEMESNENFEGYMK"


# ============================================================
# Positive: modification ranges (case 24)
# ============================================================

class TestRange:
    def test_range(self, results):
        r = get_result(results, "PRT(ESFRMS)[+19.0523]ISK")
        assert r["valid"] is True
        assert "range" in r["features"]
        assert r["sequence"] == "PRTESFRMSISK"
        mod_values = [m["value"] for m in r["modifications"]]
        assert "+19.0523" in mod_values


# ============================================================
# Positive: labels with scores (case 26)
# ============================================================

class TestLabels:
    def test_labels_with_scores(self, results):
        r = get_result(
            results,
            "EM[Oxidation]EVT[#g1(0.01)]S[#g1(0.09)]ES[Phospho#g1(0.90)]PEK",
        )
        assert r["valid"] is True
        assert "label" in r["features"]
        assert r["sequence"] == "EMEVTSESPEK"
        assert len(r["modifications"]) == 4


# ============================================================
# Positive: combined features (cases 27-31)
# ============================================================

class TestCombinedFeatures:
    def test_chimeric_with_charges(self, results):
        r = get_result(results, "EMEVEESPEK/2+ELVISLIVER/3")
        assert r["valid"] is True
        assert r["ion_count"] == 2
        assert r["charge"] == 2
        assert "chimeric" in r["features"]
        assert "charge" in r["features"]

    def test_multiple_global_isotopes(self, results):
        r = get_result(results, "<13C><15N>ATPEILTVNSIGQLK")
        assert r["valid"] is True
        assert r["sequence"] == "ATPEILTVNSIGQLK"
        assert "global_isotope" in r["features"]

    def test_multiple_labile(self, results):
        r = get_result(results, "{Glycan:Hex}{Glycan:NeuAc}EMEVNESPEK")
        assert r["valid"] is True
        assert r["sequence"] == "EMEVNESPEK"
        assert "labile" in r["features"]

    def test_unlocalised_with_occurrence_and_nterm(self, results):
        r = get_result(
            results, "[Phospho]^2?[Acetyl]-EM[Oxidation]EVTSESPEK"
        )
        assert r["valid"] is True
        assert r["sequence"] == "EMEVTSESPEK"
        assert "unlocalised" in r["features"]
        assert r["n_terminal"] == ["Acetyl"]

    def test_single_chain_crosslink_labels(self, results):
        r = get_result(results, "EVTSEKC[X:Disulfide#XL1]LEMSC[#XL1]EFD")
        assert r["valid"] is True
        assert r["sequence"] == "EVTSEKCLEMSCEFD"
        assert "label" in r["features"]
        assert r["chain_count"] == 1


# ============================================================
# Positive: multi-adduct charge (case 32)
# ============================================================

class TestMultiAdduct:
    def test_multi_adduct_with_occurrence(self, results):
        r = get_result(results, "PEPTIDE/[Na:z+1,H:z+1^2]")
        assert r["valid"] is True
        assert r["sequence"] == "PEPTIDE"
        assert r["charge"] == 3
        assert "charge" in r["features"]
        assert r["chain_count"] == 1
        assert r["ion_count"] == 1


# ============================================================
# Positive: cross-link with charge (case 33)
# ============================================================

class TestCrossLinkCharge:
    def test_cross_link_with_charge(self, results):
        r = get_result(
            results,
            "SEK[XLMOD:02001#XL1]UENCE//EMEVTK[#XL1]SESPEK/2",
        )
        assert r["valid"] is True
        assert r["chain_count"] == 2
        assert r["charge"] == 2
        assert r["sequence"] == "SEKUENCE"
        assert "cross_link" in r["features"]
        assert "charge" in r["features"]
        assert "label" in r["features"]
        assert r["modifications"][0] == {"position": 3, "value": "XLMOD:02001#XL1"}


# ============================================================
# Positive: global + unlocalised + labile (case 34)
# ============================================================

class TestTripleCombined:
    def test_global_unlocalised_labile(self, results):
        r = get_result(results, "<13C>[Phospho]?{Glycan:Hex}ACDEFGHIK")
        assert r["valid"] is True
        assert r["sequence"] == "ACDEFGHIK"
        assert "global_isotope" in r["features"]
        assert "labile" in r["features"]
        assert "unlocalised" in r["features"]
        assert len(r["modifications"]) == 0
        assert r["n_terminal"] == []


# ============================================================
# Positive: ambiguous + range combined (case 35)
# ============================================================

class TestAmbiguousRange:
    def test_ambiguous_then_range(self, results):
        r = get_result(results, "(?DQ)(NGTWEM)[Oxidation]K")
        assert r["valid"] is True
        assert r["sequence"] == "DQNGTWEMK"
        assert "ambiguous_aa" in r["features"]
        assert "range" in r["features"]
        assert len(r["modifications"]) == 1
        assert r["modifications"][0] == {"position": 8, "value": "Oxidation"}


# ============================================================
# Positive: multi-global-fixed + charge (case 36)
# ============================================================

class TestMultiGlobalFixed:
    def test_multi_global_fixed_with_inline_mod_and_charge(self, results):
        r = get_result(
            results,
            "<[Carbamidomethyl]@C><[Oxidation]@M>AC[+42.0106]MPEK/+2",
        )
        assert r["valid"] is True
        assert r["sequence"] == "ACMPEK"
        assert r["charge"] == 2
        assert "global_fixed" in r["features"]
        assert "charge" in r["features"]
        assert "global_isotope" not in r["features"]
        assert len(r["modifications"]) == 1
        assert r["modifications"][0] == {"position": 2, "value": "+42.0106"}


# ============================================================
# Negative test cases (cases 37-43) — should all be invalid
# ============================================================

class TestNegativeCases:
    def test_missing_cterm_mod(self, results):
        r = get_result(results, "A[+1]-")
        assert r["valid"] is False
        assert "error" in r

    def test_empty_range(self, results):
        r = get_result(results, "()[Dehydro]S")
        assert r["valid"] is False
        assert "error" in r

    def test_unpaired_bracket(self, results):
        r = get_result(results, "ELVIS[Phospho|INFO:newly]discovered]K")
        assert r["valid"] is False
        assert "error" in r

    def test_nested_ranges(self, results):
        r = get_result(
            results, "P(RT(ESFRMS)[+19.0523]IS)[+19.0523]K"
        )
        assert r["valid"] is False
        assert "error" in r

    def test_bare_slash(self, results):
        r = get_result(results, "/")
        assert r["valid"] is False
        assert "error" in r

    def test_empty_global(self, results):
        r = get_result(results, "<>PEPTIDE")
        assert r["valid"] is False
        assert "error" in r

    def test_empty_chain_after_separator(self, results):
        r = get_result(results, "PEPTIDE//")
        assert r["valid"] is False
        assert "error" in r
