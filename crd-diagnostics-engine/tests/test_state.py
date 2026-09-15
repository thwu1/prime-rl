
import subprocess
import json
import pytest
import os


def run_cli(panel: dict) -> dict:
    """Run the CRD engine CLI with the given panel and return parsed output."""
    result = subprocess.run(
        ["npx", "tsx", "src/cli.ts"],
        input=json.dumps(panel),
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=60,
    )
    assert result.returncode == 0, f"CLI failed (exit {result.returncode}):\n{result.stderr}"
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"CLI output is not valid JSON:\n{result.stdout[:500]}")


# ---------------------------------------------------------------------------
# CAP Banding
# ---------------------------------------------------------------------------
class TestCapBanding:
    """Verify CAP class banding at exact boundary values."""

    @pytest.mark.parametrize(
        "kua_l,expected_class",
        [
            (0.0, 0),
            (0.05, 0),
            (0.09, 0),
            (0.10, 0),       # equivocal → reported as 0
            (0.20, 0),
            (0.34, 0),
            (0.35, 1),
            (0.50, 1),
            (0.69, 1),
            (0.70, 2),       # boundary: must be class 2
            (1.50, 2),
            (3.49, 2),
            (3.50, 3),       # boundary: must be class 3
            (10.0, 3),
            (17.49, 3),
            (17.50, 4),      # boundary: must be class 4
            (25.0, 4),
            (49.99, 4),
            (50.00, 5),      # boundary: must be class 5
            (75.0, 5),
            (99.99, 5),
            (100.00, 6),     # boundary: must be class 6
            (150.0, 6),
            (500.0, 6),
        ],
    )
    def test_cap_classification(self, kua_l, expected_class):
        panel = {
            "patient_id": "CAP_TEST",
            "total_ige_kua_l": 1000,
            "results": [{"allergen_id": "g205", "sige_kua_l": kua_l}],
        }
        report = run_cli(panel)
        assert len(report["allergen_results"]) == 1
        actual = report["allergen_results"][0]["cap_class"]
        assert actual == expected_class, (
            f"kUA/L={kua_l}: expected class {expected_class}, got {actual}"
        )


# ---------------------------------------------------------------------------
# sIgE/tIgE ratio
# ---------------------------------------------------------------------------
class TestSigeTigeRatio:
    def test_basic_ratio(self):
        panel = {
            "patient_id": "RATIO_1",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "g205", "sige_kua_l": 25.0}],
        }
        report = run_cli(panel)
        ratio = report["allergen_results"][0]["sige_tige_ratio"]
        assert abs(ratio - 0.05) < 0.001

    def test_ratio_capped_at_one(self):
        panel = {
            "patient_id": "RATIO_CAP",
            "total_ige_kua_l": 10,
            "results": [{"allergen_id": "g205", "sige_kua_l": 50.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["sige_tige_ratio"] == 1.0

    def test_ratio_zero_total_ige(self):
        panel = {
            "patient_id": "RATIO_ZERO",
            "total_ige_kua_l": 0,
            "results": [{"allergen_id": "g205", "sige_kua_l": 5.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["sige_tige_ratio"] == 0


# ---------------------------------------------------------------------------
# Cross-reactivity resolution
# ---------------------------------------------------------------------------
class TestCrossReactivityResolution:
    def test_pr10_resolution_large_difference(self):
        """Bet v 1 (MAJOR, PROBABLE) should beat Ara h 8 (MINOR, HIGH)."""
        panel = {
            "patient_id": "CR_PR10",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "t215", "sige_kua_l": 25.0},
                {"allergen_id": "f352", "sige_kua_l": 12.0},
            ],
        }
        report = run_cli(panel)
        results = {r["allergen_id"]: r for r in report["allergen_results"]}
        assert results["t215"]["classification"] == "PRIMARY"
        assert results["f352"]["classification"] == "CROSS_REACTIVE"

    def test_specificity_weight_resolution(self):
        """When sIgE values are close, specificity weights must determine winner.

        Correct weights: PROBABLE=1.5, HIGH=1.0
        Bet v 1: 2.0 * 2.0(MAJOR) * 1.5(PROBABLE) = 6.0 → PRIMARY
        Ara h 8: 4.0 * 1.0(MINOR) * 1.0(HIGH)     = 4.0 → CROSS_REACTIVE

        With inverted weights (PROBABLE=2.5, HIGH=3.0):
        Bet v 1: 2.0 * 2.0 * 2.5 = 10.0
        Ara h 8: 4.0 * 1.0 * 3.0 = 12.0 → would wrongly win
        """
        panel = {
            "patient_id": "CR_SPEC_WEIGHT",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "t215", "sige_kua_l": 2.0},
                {"allergen_id": "f352", "sige_kua_l": 4.0},
            ],
        }
        report = run_cli(panel)
        results = {r["allergen_id"]: r for r in report["allergen_results"]}
        assert results["t215"]["classification"] == "PRIMARY"
        assert results["f352"]["classification"] == "CROSS_REACTIVE"

    def test_storage_proteins_resolution(self):
        """Ara h 2 > Ara h 1 in STORAGE_PROTEINS when Ara h 2 has higher sIgE."""
        panel = {
            "patient_id": "CR_STORAGE",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "f423", "sige_kua_l": 45.0},
                {"allergen_id": "f422", "sige_kua_l": 10.0},
            ],
        }
        report = run_cli(panel)
        results = {r["allergen_id"]: r for r in report["allergen_results"]}
        assert results["f423"]["classification"] == "PRIMARY"
        assert results["f422"]["classification"] == "CROSS_REACTIVE"

    def test_no_family_major_is_primary(self):
        """MAJOR allergen without molecular family → PRIMARY."""
        panel = {
            "patient_id": "CR_NOFAM_MAJ",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "e94", "sige_kua_l": 30.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["classification"] == "PRIMARY"

    def test_no_family_minor_low_class_undetermined(self):
        """MINOR allergen without family and class < 3 → UNDETERMINED."""
        panel = {
            "patient_id": "CR_NOFAM_MINOR",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "o214", "sige_kua_l": 0.50}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["classification"] == "UNDETERMINED"

    def test_no_family_minor_high_class_primary(self):
        """MINOR allergen without family but class >= 3 → PRIMARY."""
        panel = {
            "patient_id": "CR_NOFAM_MINOR_HIGH",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "o214", "sige_kua_l": 5.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["classification"] == "PRIMARY"

    def test_class_zero_always_undetermined(self):
        """Class 0 results are always UNDETERMINED."""
        panel = {
            "patient_id": "CR_ZERO",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "e94", "sige_kua_l": 0.05}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["classification"] == "UNDETERMINED"

    def test_sole_family_member_primary(self):
        """Sole member of a molecular family group → PRIMARY."""
        panel = {
            "patient_id": "CR_SOLE",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "f423", "sige_kua_l": 20.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["classification"] == "PRIMARY"


# ---------------------------------------------------------------------------
# Syndrome detection
# ---------------------------------------------------------------------------
class TestSyndromeDetection:
    def test_pollen_food_syndrome(self):
        """PR-10 pollen + PR-10 food = PFAS."""
        panel = {
            "patient_id": "SYN_PFAS",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "t215", "sige_kua_l": 25.0},
                {"allergen_id": "f352", "sige_kua_l": 12.0},
            ],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "Pollen-Food Allergy Syndrome" in names
        pfas = next(s for s in report["detected_syndromes"]
                     if s["name"] == "Pollen-Food Allergy Syndrome")
        assert "t215" in pfas["involved_allergens"]
        assert "f352" in pfas["involved_allergens"]

    def test_ltp_syndrome(self):
        """>=2 LTP allergens from different sources."""
        panel = {
            "patient_id": "SYN_LTP",
            "total_ige_kua_l": 200,
            "results": [
                {"allergen_id": "f420", "sige_kua_l": 8.0},
                {"allergen_id": "w233", "sige_kua_l": 4.5},
            ],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "LTP Syndrome" in names
        ltp = next(s for s in report["detected_syndromes"]
                    if s["name"] == "LTP Syndrome")
        assert "f420" in ltp["involved_allergens"]
        assert "w233" in ltp["involved_allergens"]

    def test_ltp_syndrome_three_sources(self):
        """LTP syndrome with 3 different sources."""
        panel = {
            "patient_id": "SYN_LTP3",
            "total_ige_kua_l": 300,
            "results": [
                {"allergen_id": "f420", "sige_kua_l": 8.0},
                {"allergen_id": "w233", "sige_kua_l": 4.5},
                {"allergen_id": "f427", "sige_kua_l": 2.1},
            ],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "LTP Syndrome" in names
        ltp = next(s for s in report["detected_syndromes"]
                    if s["name"] == "LTP Syndrome")
        assert len(ltp["involved_allergens"]) >= 3

    def test_pork_cat_syndrome(self):
        """Cat serum albumin + bovine serum albumin."""
        panel = {
            "patient_id": "SYN_PORKCAT",
            "total_ige_kua_l": 200,
            "results": [
                {"allergen_id": "e220", "sige_kua_l": 5.0},
                {"allergen_id": "e204", "sige_kua_l": 3.0},
            ],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "Pork-Cat Syndrome" in names
        pcs = next(s for s in report["detected_syndromes"]
                    if s["name"] == "Pork-Cat Syndrome")
        assert "e220" in pcs["involved_allergens"]
        assert "e204" in pcs["involved_allergens"]

    def test_bird_egg_syndrome(self):
        """Gal d 5 positive → Bird-Egg Syndrome."""
        panel = {
            "patient_id": "SYN_BIRDEGG",
            "total_ige_kua_l": 300,
            "results": [{"allergen_id": "f75", "sige_kua_l": 4.0}],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "Bird-Egg Syndrome" in names
        bes = next(s for s in report["detected_syndromes"]
                    if s["name"] == "Bird-Egg Syndrome")
        assert "f75" in bes["involved_allergens"]

    def test_alpha_gal_syndrome(self):
        """Alpha-Gal marker positive → Alpha-Gal Syndrome."""
        panel = {
            "patient_id": "SYN_ALPHAGAL",
            "total_ige_kua_l": 100,
            "results": [{"allergen_id": "o215", "sige_kua_l": 2.5}],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "Alpha-Gal Syndrome" in names
        ags = next(s for s in report["detected_syndromes"]
                    if s["name"] == "Alpha-Gal Syndrome")
        assert "o215" in ags["involved_allergens"]

    def test_mite_shrimp_crossreactivity(self):
        """Mite tropomyosin + shrimp tropomyosin."""
        panel = {
            "patient_id": "SYN_MITESHRIMP",
            "total_ige_kua_l": 300,
            "results": [
                {"allergen_id": "d205", "sige_kua_l": 5.0},
                {"allergen_id": "f351", "sige_kua_l": 8.0},
            ],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "Mite-Shrimp Cross-Reactivity" in names
        ms = next(s for s in report["detected_syndromes"]
                   if s["name"] == "Mite-Shrimp Cross-Reactivity")
        assert "d205" in ms["involved_allergens"]
        assert "f351" in ms["involved_allergens"]

    def test_latex_fruit_syndrome(self):
        """Hev b 6.02 positive + kiwi allergen positive."""
        panel = {
            "patient_id": "SYN_LATEXFRUIT",
            "total_ige_kua_l": 200,
            "results": [
                {"allergen_id": "k220", "sige_kua_l": 6.0},
                {"allergen_id": "actd1", "sige_kua_l": 3.5},
            ],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "Latex-Fruit Syndrome" in names
        lfs = next(s for s in report["detected_syndromes"]
                    if s["name"] == "Latex-Fruit Syndrome")
        assert "k220" in lfs["involved_allergens"]
        assert "actd1" in lfs["involved_allergens"]

    def test_no_false_syndrome_single_allergen(self):
        """Single standalone allergen should not trigger multi-allergen syndromes."""
        panel = {
            "patient_id": "SYN_NONE",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "g205", "sige_kua_l": 25.0}],
        }
        report = run_cli(panel)
        assert len(report["detected_syndromes"]) == 0

    def test_no_pfas_without_pollen(self):
        """PR-10 food allergen alone should NOT trigger PFAS."""
        panel = {
            "patient_id": "SYN_NO_PFAS",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "f352", "sige_kua_l": 12.0}],
        }
        report = run_cli(panel)
        names = [s["name"] for s in report["detected_syndromes"]]
        assert "Pollen-Food Allergy Syndrome" not in names

    def test_class_zero_does_not_trigger_syndrome(self):
        """Class 0 results should not participate in syndrome detection."""
        panel = {
            "patient_id": "SYN_ZERO",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "t215", "sige_kua_l": 0.05},
                {"allergen_id": "f352", "sige_kua_l": 0.05},
            ],
        }
        report = run_cli(panel)
        assert len(report["detected_syndromes"]) == 0


# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------
class TestRiskLevel:
    def test_negligible_class_zero(self):
        panel = {
            "patient_id": "RISK_NEG",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "g205", "sige_kua_l": 0.05}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["risk_level"] == "NEGLIGIBLE"

    def test_very_high_storage_protein_class3(self):
        """STORAGE_PROTEINS with class >= 3 → VERY_HIGH."""
        panel = {
            "patient_id": "RISK_VH",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "f423", "sige_kua_l": 45.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["risk_level"] == "VERY_HIGH"

    def test_very_high_storage_protein_at_boundary(self):
        """STORAGE_PROTEINS at exactly class 3 boundary (3.50) → VERY_HIGH."""
        panel = {
            "patient_id": "RISK_VH_BOUND",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "f423", "sige_kua_l": 3.50}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["risk_level"] == "VERY_HIGH"

    def test_storage_protein_class2_not_very_high(self):
        """STORAGE_PROTEINS with class 2 → HIGH (not VERY_HIGH)."""
        panel = {
            "patient_id": "RISK_SP_C2",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "f423", "sige_kua_l": 2.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["risk_level"] == "HIGH"

    def test_high_major_severe(self):
        """MAJOR with SEVERE symptom and class >= 2 → HIGH."""
        panel = {
            "patient_id": "RISK_HIGH",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "e94", "sige_kua_l": 5.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["risk_level"] == "HIGH"

    def test_moderate_major_no_severe(self):
        """MAJOR without SEVERE and class >= 2 → MODERATE."""
        panel = {
            "patient_id": "RISK_MOD",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "g205", "sige_kua_l": 5.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["risk_level"] == "MODERATE"

    def test_low_minor_allergen(self):
        """MINOR allergen → LOW."""
        panel = {
            "patient_id": "RISK_LOW",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "t216", "sige_kua_l": 2.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["risk_level"] == "LOW"


# ---------------------------------------------------------------------------
# AIT eligibility
# ---------------------------------------------------------------------------
class TestAitEligibility:
    def test_eligible_primary_major_not_high(self):
        """PRIMARY + MAJOR + class >= 2 + not HIGH cross-reactivity → eligible."""
        panel = {
            "patient_id": "AIT_YES",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "e94", "sige_kua_l": 5.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["ait_eligible"] is True

    def test_not_eligible_high_cross_reactivity(self):
        """PRIMARY + MAJOR but HIGH cross-reactivity → NOT eligible."""
        panel = {
            "patient_id": "AIT_NO_CR",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "f420", "sige_kua_l": 8.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["ait_eligible"] is False

    def test_not_eligible_minor(self):
        """MINOR type → NOT eligible regardless of other conditions."""
        panel = {
            "patient_id": "AIT_NO_MINOR",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "t216", "sige_kua_l": 5.0}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["ait_eligible"] is False

    def test_not_eligible_cross_reactive_classification(self):
        """CROSS_REACTIVE classification → NOT eligible."""
        panel = {
            "patient_id": "AIT_NO_CR_CLASS",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "t215", "sige_kua_l": 25.0},
                {"allergen_id": "f352", "sige_kua_l": 12.0},
            ],
        }
        report = run_cli(panel)
        results = {r["allergen_id"]: r for r in report["allergen_results"]}
        assert results["f352"]["ait_eligible"] is False

    def test_not_eligible_low_class(self):
        """Class < 2 → NOT eligible."""
        panel = {
            "patient_id": "AIT_NO_LOWCLASS",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "e94", "sige_kua_l": 0.50}],
        }
        report = run_cli(panel)
        assert report["allergen_results"][0]["ait_eligible"] is False


# ---------------------------------------------------------------------------
# Overall report
# ---------------------------------------------------------------------------
class TestOverallReport:
    def test_report_structure(self):
        panel = {
            "patient_id": "STRUCT_TEST",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "f423", "sige_kua_l": 45.0},
                {"allergen_id": "t215", "sige_kua_l": 25.0},
            ],
        }
        report = run_cli(panel)
        assert report["patient_id"] == "STRUCT_TEST"
        assert len(report["allergen_results"]) == 2
        assert "detected_syndromes" in report
        assert isinstance(report["detected_syndromes"], list)
        assert "overall_risk" in report

    def test_allergen_result_fields(self):
        panel = {
            "patient_id": "FIELDS_TEST",
            "total_ige_kua_l": 500,
            "results": [{"allergen_id": "e94", "sige_kua_l": 5.0}],
        }
        report = run_cli(panel)
        r = report["allergen_results"][0]
        required_fields = [
            "allergen_id", "allergen_name", "source",
            "cap_class", "sige_tige_ratio", "classification",
            "risk_level", "ait_eligible",
        ]
        for field in required_fields:
            assert field in r, f"Missing field: {field}"

    def test_overall_risk_is_maximum(self):
        """overall_risk = max across all allergen_results."""
        panel = {
            "patient_id": "OVERALL_TEST",
            "total_ige_kua_l": 500,
            "results": [
                {"allergen_id": "f423", "sige_kua_l": 45.0},  # VERY_HIGH
                {"allergen_id": "g205", "sige_kua_l": 5.0},   # MODERATE
            ],
        }
        report = run_cli(panel)
        assert report["overall_risk"] == "VERY_HIGH"

    def test_complex_panel(self):
        """End-to-end test with multiple families and syndromes."""
        panel = {
            "patient_id": "COMPLEX",
            "total_ige_kua_l": 800,
            "results": [
                {"allergen_id": "t215", "sige_kua_l": 35.0},   # Bet v 1 (PR-10, MAJOR, PROBABLE)
                {"allergen_id": "f352", "sige_kua_l": 8.0},    # Ara h 8 (PR-10, MINOR, HIGH)
                {"allergen_id": "f423", "sige_kua_l": 60.0},   # Ara h 2 (STORAGE, MAJOR, LOW)
                {"allergen_id": "f420", "sige_kua_l": 15.0},   # Pru p 3 (LTP, MAJOR, HIGH)
                {"allergen_id": "w233", "sige_kua_l": 5.0},    # Art v 3 (LTP, MINOR, HIGH)
                {"allergen_id": "e94", "sige_kua_l": 20.0},    # Fel d 1 (none, MAJOR, NONE)
            ],
        }
        report = run_cli(panel)
        results = {r["allergen_id"]: r for r in report["allergen_results"]}

        # PR-10: Bet v 1 score = 35*2*1.5=105, Ara h 8 score = 8*1*1=8
        assert results["t215"]["classification"] == "PRIMARY"
        assert results["f352"]["classification"] == "CROSS_REACTIVE"

        # STORAGE_PROTEINS: only Ara h 2 → PRIMARY
        assert results["f423"]["classification"] == "PRIMARY"

        # LTP: Pru p 3 = 15*2*1=30, Art v 3 = 5*1*1=5
        assert results["f420"]["classification"] == "PRIMARY"
        assert results["w233"]["classification"] == "CROSS_REACTIVE"

        # No family: Fel d 1 MAJOR → PRIMARY
        assert results["e94"]["classification"] == "PRIMARY"

        # Syndromes
        syndrome_names = [s["name"] for s in report["detected_syndromes"]]
        assert "Pollen-Food Allergy Syndrome" in syndrome_names
        assert "LTP Syndrome" in syndrome_names

        # Risk
        assert results["f423"]["risk_level"] == "VERY_HIGH"
        assert report["overall_risk"] == "VERY_HIGH"

        # AIT
        assert results["e94"]["ait_eligible"] is True     # NONE cross-reactivity
        assert results["t215"]["ait_eligible"] is True     # PROBABLE (not HIGH)
        assert results["f420"]["ait_eligible"] is False    # HIGH cross-reactivity
        assert results["f423"]["ait_eligible"] is True     # LOW cross-reactivity
