"""Tests for TMT spike-in proteomics quantification assessment pipeline."""

import json
import os
import pytest


RESULTS_PATH = "/app/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestOutputStructure:
    """Verify the output JSON has all required keys and correct types."""

    def test_results_is_dict(self, results):
        assert isinstance(results, dict)

    def test_required_top_level_keys(self, results):
        required = [
            "project_accession", "project_title", "total_peptides",
            "total_proteins", "valid_tryptic_peptides", "invalid_tryptic_peptides",
            "tryptic_coverage_pct", "protein_classifications",
            "protein_ratios", "peptide_masses",
            "spike_expected_ratios", "ratio_rmsd", "per_protein_cv",
        ]
        for key in required:
            assert key in results, f"Missing required key: {key}"

    def test_classification_categories_present(self, results):
        expected_cats = [
            "erwinia", "enolase_spike", "bsa_spike",
            "phosb_spike", "cytc_spike", "unclassified",
        ]
        for cat in expected_cats:
            assert cat in results["protein_classifications"], \
                f"Missing classification category: {cat}"

    def test_classification_values_are_lists(self, results):
        for cat, accs in results["protein_classifications"].items():
            assert isinstance(accs, list), \
                f"Classification {cat} should be a list, got {type(accs)}"

    def test_protein_ratios_is_dict(self, results):
        assert isinstance(results["protein_ratios"], dict)

    def test_peptide_masses_is_dict(self, results):
        assert isinstance(results["peptide_masses"], dict)

    def test_spike_expected_ratios_is_dict(self, results):
        assert isinstance(results["spike_expected_ratios"], dict)

    def test_ratio_rmsd_is_dict(self, results):
        assert isinstance(results["ratio_rmsd"], dict)

    def test_per_protein_cv_is_dict(self, results):
        assert isinstance(results["per_protein_cv"], dict)


class TestProjectMetadata:
    """Verify PRIDE API data was retrieved correctly."""

    def test_accession_is_pxd000001(self, results):
        assert results["project_accession"] == "PXD000001"

    def test_title_contains_tmt(self, results):
        title = results["project_title"].upper()
        assert "TMT" in title, \
            f"Project title should mention TMT, got: {results['project_title']}"

    def test_title_nonempty(self, results):
        assert len(results["project_title"]) > 10


class TestPeptideAndProteinCounts:
    """Verify reasonable counts from mzTab parsing."""

    def test_total_peptides_at_least_100(self, results):
        assert results["total_peptides"] >= 100, \
            f"Expected >= 100 peptides, got {results['total_peptides']}"

    def test_total_proteins_at_least_5(self, results):
        assert results["total_proteins"] >= 5, \
            f"Expected >= 5 proteins, got {results['total_proteins']}"

    def test_total_peptides_positive(self, results):
        assert results["total_peptides"] > 0

    def test_total_proteins_positive(self, results):
        assert results["total_proteins"] > 0


class TestTrypticValidation:
    """Verify enzymatic digestion validation."""

    def test_valid_tryptic_positive(self, results):
        assert results["valid_tryptic_peptides"] > 0, \
            "Expected some valid tryptic peptides"

    def test_coverage_above_50_pct(self, results):
        assert results["tryptic_coverage_pct"] > 50.0, \
            f"Tryptic coverage {results['tryptic_coverage_pct']}% too low (expected >50%)"

    def test_coverage_at_most_100(self, results):
        assert results["tryptic_coverage_pct"] <= 100.0

    def test_valid_plus_invalid_equals_checked(self, results):
        total = results["valid_tryptic_peptides"] + results["invalid_tryptic_peptides"]
        assert total > 0, "No peptides were checked for tryptic validity"


class TestMonoisotopicMass:
    """Verify mass calculation with known peptide masses."""

    def test_dgvsvar_mass(self, results):
        expected = 702.3660
        assert "DGVSVAR" in results["peptide_masses"], \
            "DGVSVAR not found in peptide_masses"
        actual = results["peptide_masses"]["DGVSVAR"]
        assert abs(actual - expected) < 0.01, \
            f"DGVSVAR mass {actual} != expected ~{expected}"

    def test_nvvldk_mass(self, results):
        expected = 686.3963
        if "NVVLDK" in results["peptide_masses"]:
            actual = results["peptide_masses"]["NVVLDK"]
            assert abs(actual - expected) < 0.01, \
                f"NVVLDK mass {actual} != expected ~{expected}"

    def test_all_masses_positive(self, results):
        for seq, mass in results["peptide_masses"].items():
            assert mass > 0, f"Peptide {seq} has non-positive mass {mass}"

    def test_all_masses_in_reasonable_range(self, results):
        for seq, mass in results["peptide_masses"].items():
            assert 300 < mass < 8000, \
                f"Peptide {seq} mass {mass} out of reasonable range [300, 8000]"


class TestProteinClassification:
    """Verify proteins are classified into correct spike categories."""

    def test_erwinia_has_multiple_proteins(self, results):
        erwinia = results["protein_classifications"]["erwinia"]
        assert len(erwinia) >= 5, \
            f"Expected >= 5 Erwinia proteins, got {len(erwinia)}"

    def test_erwinia_proteins_have_eca_prefix(self, results):
        erwinia = results["protein_classifications"]["erwinia"]
        for acc in erwinia:
            assert acc.startswith("ECA"), \
                f"Non-ECA accession in erwinia category: {acc}"

    def test_phosb_is_classified(self, results):
        phosb = results["protein_classifications"]["phosb_spike"]
        assert len(phosb) >= 1, "PhosB not classified"
        assert any("PYGM_RABIT" in acc for acc in phosb), \
            f"PYGM_RABIT not found in phosb_spike: {phosb}"

    def test_enolase_is_classified(self, results):
        eno = results["protein_classifications"]["enolase_spike"]
        assert len(eno) >= 1, "Enolase not classified"
        assert any("ENO1_YEAST" in acc for acc in eno), \
            f"ENO1_YEAST not found in enolase_spike: {eno}"

    def test_bsa_is_classified(self, results):
        bsa = results["protein_classifications"]["bsa_spike"]
        assert len(bsa) >= 1, "BSA not classified"
        assert any("ALBU_BOVIN" in acc for acc in bsa), \
            f"ALBU_BOVIN not found in bsa_spike: {bsa}"

    def test_cytc_is_classified(self, results):
        cytc = results["protein_classifications"]["cytc_spike"]
        assert len(cytc) >= 1, "CytC not classified"
        assert any("CYC_BOVIN" in acc for acc in cytc), \
            f"CYC_BOVIN not found in cytc_spike: {cytc}"

    def test_classification_lists_are_sorted(self, results):
        for cat, accs in results["protein_classifications"].items():
            assert accs == sorted(accs), \
                f"Category '{cat}' is not sorted: {accs}"


class TestTMTRatios:
    """Verify TMT ratio computation and patterns."""

    def test_all_ratios_have_six_channels(self, results):
        for acc, ratios in results["protein_ratios"].items():
            assert len(ratios) == 6, \
                f"Protein {acc} has {len(ratios)} channels (expected 6)"

    def test_channel_1_is_one(self, results):
        for acc, ratios in results["protein_ratios"].items():
            assert abs(ratios[0] - 1.0) < 0.001, \
                f"Protein {acc} channel 1 = {ratios[0]} (expected 1.0)"

    def test_erwinia_ratios_near_uniform(self, results):
        """Erwinia background should be approximately 1:1:1:1:1:1."""
        erwinia_accs = results["protein_classifications"]["erwinia"]
        checked = 0
        for acc in erwinia_accs[:8]:
            if acc in results["protein_ratios"]:
                ratios = results["protein_ratios"][acc]
                for i, r in enumerate(ratios):
                    assert 0.5 < r < 2.0, \
                        f"Erwinia {acc} channel {i+1}={r} outside [0.5, 2.0]"
                checked += 1
        assert checked >= 3, "Could not verify enough Erwinia protein ratios"

    def test_phosb_ratio_pattern(self, results):
        """PhosB channels 5-6 should be notably lower than channels 1-4."""
        phosb_accs = results["protein_classifications"]["phosb_spike"]
        for acc in phosb_accs:
            if acc in results["protein_ratios"]:
                ratios = results["protein_ratios"][acc]
                avg_first4 = sum(ratios[:4]) / 4
                avg_last2 = sum(ratios[4:6]) / 2
                if avg_first4 > 0:
                    ratio_drop = avg_last2 / avg_first4
                    assert 0.25 < ratio_drop < 0.75, \
                        f"PhosB ratio drop={ratio_drop:.3f}, " \
                        f"expected ~0.5 (channels 5-6 half of 1-4)"

    def test_bsa_ratio_pattern(self, results):
        """BSA spike should show elevated ratios in middle channels."""
        bsa_accs = results["protein_classifications"]["bsa_spike"]
        for acc in bsa_accs:
            if acc in results["protein_ratios"]:
                ratios = results["protein_ratios"][acc]
                assert ratios[3] > 3.0, \
                    f"BSA {acc} channel 4 = {ratios[3]}, expected > 3.0"

    def test_enolase_ratio_pattern(self, results):
        """Enolase spike should show depressed channel 4."""
        eno_accs = results["protein_classifications"]["enolase_spike"]
        for acc in eno_accs:
            if acc in results["protein_ratios"]:
                ratios = results["protein_ratios"][acc]
                assert ratios[3] < 0.3, \
                    f"Enolase {acc} channel 4 = {ratios[3]}, expected < 0.3"

    def test_cytc_ratio_pattern(self, results):
        """CytC spike should show elevated channel 6."""
        cytc_accs = results["protein_classifications"]["cytc_spike"]
        for acc in cytc_accs:
            if acc in results["protein_ratios"]:
                ratios = results["protein_ratios"][acc]
                assert ratios[5] > 1.3, \
                    f"CytC {acc} channel 6 = {ratios[5]}, expected > 1.3"


class TestSpikeExpectedRatios:
    """Verify expected ratios were correctly extracted from project description."""

    def test_all_spike_categories_present(self, results):
        expected_cats = ["erwinia", "enolase_spike", "bsa_spike",
                         "phosb_spike", "cytc_spike"]
        for cat in expected_cats:
            assert cat in results["spike_expected_ratios"], \
                f"Missing expected ratio category: {cat}"

    def test_all_expected_ratios_have_six_channels(self, results):
        for cat, ratios in results["spike_expected_ratios"].items():
            assert len(ratios) == 6, \
                f"Expected ratios for {cat} have {len(ratios)} channels"

    def test_all_channel_1_normalized_to_one(self, results):
        for cat, ratios in results["spike_expected_ratios"].items():
            assert abs(ratios[0] - 1.0) < 0.001, \
                f"Expected ratio {cat} channel 1 = {ratios[0]}, should be 1.0"

    def test_erwinia_expected_uniform(self, results):
        """Erwinia background should be 1:1:1:1:1:1."""
        ratios = results["spike_expected_ratios"]["erwinia"]
        for i, r in enumerate(ratios):
            assert abs(r - 1.0) < 0.001, \
                f"Erwinia expected ch{i+1}={r}, should be 1.0"

    def test_enolase_expected_v_shape(self, results):
        """Enolase expected: 10:5:2.5:1:2.5:10 -> normalized ch4 = 0.1."""
        ratios = results["spike_expected_ratios"]["enolase_spike"]
        assert abs(ratios[3] - 0.1) < 0.001, \
            f"Enolase expected ch4={ratios[3]}, should be 0.1"
        assert abs(ratios[1] - 0.5) < 0.001, \
            f"Enolase expected ch2={ratios[1]}, should be 0.5"

    def test_bsa_expected_peak(self, results):
        """BSA expected: 1:2.5:5:10:5:1 -> normalized ch4 = 10.0."""
        ratios = results["spike_expected_ratios"]["bsa_spike"]
        assert abs(ratios[3] - 10.0) < 0.001, \
            f"BSA expected ch4={ratios[3]}, should be 10.0"
        assert abs(ratios[2] - 5.0) < 0.001, \
            f"BSA expected ch3={ratios[2]}, should be 5.0"

    def test_phosb_expected_drop(self, results):
        """PhosB expected: 2:2:2:2:1:1 -> normalized ch5,ch6 = 0.5."""
        ratios = results["spike_expected_ratios"]["phosb_spike"]
        assert abs(ratios[4] - 0.5) < 0.001, \
            f"PhosB expected ch5={ratios[4]}, should be 0.5"
        assert abs(ratios[5] - 0.5) < 0.001, \
            f"PhosB expected ch6={ratios[5]}, should be 0.5"

    def test_cytc_expected_channel6(self, results):
        """CytC expected: 1:1:1:1:1:2 -> normalized ch6 = 2.0."""
        ratios = results["spike_expected_ratios"]["cytc_spike"]
        assert abs(ratios[5] - 2.0) < 0.001, \
            f"CytC expected ch6={ratios[5]}, should be 2.0"


class TestRatioRMSD:
    """Verify RMSD between observed and expected ratios."""

    def test_rmsd_categories_match_expected(self, results):
        for cat in results["spike_expected_ratios"]:
            assert cat in results["ratio_rmsd"], \
                f"RMSD missing for category: {cat}"

    def test_all_rmsd_non_negative(self, results):
        for cat, rmsd in results["ratio_rmsd"].items():
            assert rmsd >= 0.0, f"RMSD for {cat} is negative: {rmsd}"

    def test_erwinia_rmsd_low(self, results):
        """Erwinia (1:1:1:1:1:1 expected) should have low RMSD."""
        assert results["ratio_rmsd"]["erwinia"] < 0.5, \
            f"Erwinia RMSD={results['ratio_rmsd']['erwinia']}, expected < 0.5"

    def test_all_rmsd_reasonable(self, results):
        """No category should have wildly divergent ratios."""
        for cat, rmsd in results["ratio_rmsd"].items():
            assert rmsd < 5.0, \
                f"RMSD for {cat} = {rmsd}, unreasonably high (> 5.0)"

    def test_rmsd_computation_nontrivial(self, results):
        """At least one category should have RMSD > 0."""
        rmsds = list(results["ratio_rmsd"].values())
        assert any(r > 0.01 for r in rmsds), \
            "All RMSD values are near zero, suggesting trivial computation"


class TestPerProteinCV:
    """Verify per-protein coefficient of variation computation."""

    def test_at_least_three_proteins_have_cv(self, results):
        assert len(results["per_protein_cv"]) >= 3, \
            f"Expected >= 3 proteins with CV, got {len(results['per_protein_cv'])}"

    def test_cv_count_at_most_total_proteins(self, results):
        assert len(results["per_protein_cv"]) <= results["total_proteins"], \
            "More CVs than total proteins"

    def test_all_cv_non_negative(self, results):
        for acc, cv in results["per_protein_cv"].items():
            assert cv >= 0.0, f"CV for {acc} is negative: {cv}"

    def test_all_cv_reasonable(self, results):
        for acc, cv in results["per_protein_cv"].items():
            assert cv < 2.0, f"CV for {acc} = {cv}, unreasonably high (> 2.0)"

    def test_erwinia_proteins_low_cv(self, results):
        """Erwinia background proteins should have relatively low CV."""
        erwinia_accs = results["protein_classifications"]["erwinia"]
        checked = 0
        for acc in erwinia_accs[:5]:
            if acc in results["per_protein_cv"]:
                assert results["per_protein_cv"][acc] < 0.5, \
                    f"Erwinia {acc} CV={results['per_protein_cv'][acc]}, expected < 0.5"
                checked += 1
        assert checked >= 2, "Could not verify enough Erwinia protein CVs"

    def test_cv_proteins_have_ratios(self, results):
        """Every protein with a CV should also have ratios."""
        for acc in results["per_protein_cv"]:
            assert acc in results["protein_ratios"], \
                f"Protein {acc} has CV but no ratios"


class TestDataIntegrity:
    """Cross-validation between output sections."""

    def test_classified_proteins_have_ratios(self, results):
        all_classified = []
        for cat, accs in results["protein_classifications"].items():
            all_classified.extend(accs)
        for acc in all_classified:
            assert acc in results["protein_ratios"], \
                f"Classified protein {acc} missing from protein_ratios"

    def test_total_proteins_matches_ratios(self, results):
        assert results["total_proteins"] == len(results["protein_ratios"]), \
            f"total_proteins ({results['total_proteins']}) != " \
            f"len(protein_ratios) ({len(results['protein_ratios'])})"

    def test_all_ratios_channels_positive(self, results):
        for acc, ratios in results["protein_ratios"].items():
            for i, r in enumerate(ratios):
                assert r > 0, \
                    f"Protein {acc} channel {i+1} ratio is non-positive: {r}"

    def test_expected_ratios_consistent_with_classifications(self, results):
        """Each category with expected ratios should have classified proteins."""
        for cat in results["spike_expected_ratios"]:
            if cat in results["protein_classifications"]:
                assert len(results["protein_classifications"][cat]) >= 1, \
                    f"Category {cat} has expected ratios but no classified proteins"

    def test_rmsd_consistent_with_expected_ratios(self, results):
        """RMSD should exist for exactly the same categories as expected ratios."""
        assert set(results["ratio_rmsd"].keys()) == \
            set(results["spike_expected_ratios"].keys()), \
            "RMSD categories don't match expected ratio categories"
