
import subprocess
import json
import os
import tempfile
import pytest


def run_engine(panel_json: dict) -> dict:
    """Run the compiled CRD engine CLI with the given patient panel."""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False, dir='/tmp'
    ) as f:
        json.dump(panel_json, f)
        f.flush()
        input_path = f.name
    try:
        result = subprocess.run(
            ['node', 'dist/cli.js', input_path],
            capture_output=True, text=True, cwd='/app',
            timeout=30
        )
    finally:
        os.unlink(input_path)
    if result.returncode != 0:
        raise RuntimeError(
            f"Engine failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout)


class TestCapClassBoundaries:
    """Verify CAP class assignment at critical boundary values."""

    def test_boundary_035(self):
        """0.35 kUA/L must be CAP class 1 (Low), not class 0."""
        panel = {
            "patientId": "CAP-B1",
            "totalIgE": 500.0,
            "results": [{"allergenId": "e94", "sIgE": 0.35}]
        }
        report = run_engine(panel)
        c = report['classifications'][0]
        assert c['capClass'] == 1, (
            f"0.35 kUA/L should be CAP class 1 (Low), got class {c['capClass']} ({c['capLabel']})"
        )

    def test_boundary_034(self):
        """0.34 kUA/L must be CAP class 0 (Absent)."""
        panel = {
            "patientId": "CAP-B0",
            "totalIgE": 500.0,
            "results": [{"allergenId": "e94", "sIgE": 0.34}]
        }
        report = run_engine(panel)
        c = report['classifications'][0]
        assert c['capClass'] == 0, (
            f"0.34 kUA/L should be CAP class 0, got class {c['capClass']}"
        )

    def test_boundary_class5_class6(self):
        """50.0 must be class 5; 100.0 must be class 6."""
        panel = {
            "patientId": "CAP-56",
            "totalIgE": 500.0,
            "results": [
                {"allergenId": "g205", "sIgE": 50.0},
                {"allergenId": "d202", "sIgE": 100.0},
                {"allergenId": "e94", "sIgE": 99.99},
            ]
        }
        report = run_engine(panel)
        classes = {c['allergenId']: c['capClass'] for c in report['classifications']}
        assert classes['g205'] == 5, (
            f"50.0 kUA/L should be CAP class 5 (Ultra High), got {classes['g205']}"
        )
        assert classes['d202'] == 6, (
            f"100.0 kUA/L should be CAP class 6 (Extremely High), got {classes['d202']}"
        )
        assert classes['e94'] == 5, (
            f"99.99 kUA/L should be CAP class 5 (Ultra High), got {classes['e94']}"
        )

    def test_all_class_labels(self):
        """Each CAP class should have the correct label."""
        panel = {
            "patientId": "CAP-LABELS",
            "totalIgE": 1000.0,
            "results": [
                {"allergenId": "e94", "sIgE": 0.10},     # class 0
                {"allergenId": "g205", "sIgE": 0.50},    # class 1
                {"allergenId": "d202", "sIgE": 1.00},    # class 2
                {"allergenId": "t215", "sIgE": 5.00},    # class 3
                {"allergenId": "e101", "sIgE": 20.00},   # class 4
                {"allergenId": "m229", "sIgE": 75.00},   # class 5
                {"allergenId": "i208", "sIgE": 150.00},  # class 6
            ]
        }
        report = run_engine(panel)
        labels = {c['allergenId']: c['capLabel'] for c in report['classifications']}
        assert labels['e94'] == 'Absent'
        assert labels['g205'] == 'Low'
        assert labels['d202'] == 'Moderate'
        assert labels['t215'] == 'High'
        assert labels['e101'] == 'Very High'
        assert labels['m229'] == 'Ultra High'
        assert labels['i208'] == 'Extremely High'


class TestCrossReactivity:
    """Verify cross-reactivity clustering by molecular family."""

    def test_pr10_clustering_across_sources(self):
        """PR-10 allergens from different food/pollen sources must cluster together."""
        panel = {
            "patientId": "XR-PR10",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "t215", "sIgE": 45.0},   # rBet v 1 (Birch, TREE_POLLENS, PR10)
                {"allergenId": "f352", "sIgE": 2.1},    # rAra h 8 (Peanut, FOOD_PEANUT, PR10)
                {"allergenId": "f434", "sIgE": 1.5},    # rMal d 1 (Apple, FOOD_FRUITS_VEGETABLES, PR10)
            ]
        }
        report = run_engine(panel)
        clusters = report['crossReactivityClusters']
        pr10_cluster = next(
            (c for c in clusters if c['molecularFamily'] == 'PR10'), None
        )
        assert pr10_cluster is not None, (
            f"Should find a PR10 cluster. Got clusters: "
            f"{[c['molecularFamily'] for c in clusters]}"
        )
        assert len(pr10_cluster['members']) == 3, (
            f"PR10 cluster should have 3 members, got {len(pr10_cluster['members'])}"
        )
        assert pr10_cluster['primarySource'] == 'Birch', (
            f"Primary source should be 'Birch' (highest sIgE), got '{pr10_cluster['primarySource']}'"
        )

    def test_primary_sensitization_flags(self):
        """Highest sIgE in family is primary; others are not. No-family allergens are always primary."""
        panel = {
            "patientId": "XR-PRI",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "t215", "sIgE": 45.0},   # rBet v 1 (PR10) - primary
                {"allergenId": "f352", "sIgE": 2.1},    # rAra h 8 (PR10) - cross-reactive
                {"allergenId": "e94", "sIgE": 25.0},    # rFel d 1 (no family) - primary
            ]
        }
        report = run_engine(panel)
        flags = {
            c['allergenId']: c['isPrimarySensitization']
            for c in report['classifications']
        }
        assert flags['t215'] is True, "Bet v 1 should be primary (highest PR10)"
        assert flags['f352'] is False, "Ara h 8 should not be primary (lower PR10)"
        assert flags['e94'] is True, "Fel d 1 should be primary (no molecular family)"


class TestSyndromeDetection:
    """Verify syndrome detection logic."""

    def test_ltp_syndrome_detected(self):
        """LTP syndrome requires >= 2 positive LTPs from different sources."""
        panel = {
            "patientId": "SYN-LTP",
            "totalIgE": 200.0,
            "results": [
                {"allergenId": "f420", "sIgE": 8.5},    # rPru p 3 (Peach LTP)
                {"allergenId": "w233", "sIgE": 3.2},    # nArt v 3 (Mugwort LTP)
                {"allergenId": "f427", "sIgE": 1.8},    # rAra h 9 (Peanut LTP)
            ]
        }
        report = run_engine(panel)
        ltp = next(s for s in report['syndromes'] if s['syndrome'] == 'ltp-syndrome')
        assert ltp['detected'] is True, (
            "LTP syndrome should be detected with 3 positive LTPs from 3 different sources"
        )

    def test_ltp_syndrome_not_detected_single_source(self):
        """LTP syndrome should not fire with only 1 source."""
        panel = {
            "patientId": "SYN-LTP-NEG",
            "totalIgE": 200.0,
            "results": [
                {"allergenId": "f420", "sIgE": 8.5},    # rPru p 3 (Peach LTP) - only 1 source
            ]
        }
        report = run_engine(panel)
        ltp = next(s for s in report['syndromes'] if s['syndrome'] == 'ltp-syndrome')
        assert ltp['detected'] is False, (
            "LTP syndrome should NOT be detected with only 1 LTP source"
        )

    def test_pork_cat_syndrome(self):
        """Pork-cat syndrome requires Fel d 2 (e220) + meat/milk albumin."""
        panel = {
            "patientId": "SYN-PC",
            "totalIgE": 150.0,
            "results": [
                {"allergenId": "e94", "sIgE": 35.0},    # rFel d 1 (Cat major)
                {"allergenId": "e220", "sIgE": 5.0},    # rFel d 2 (Cat serum albumin)
                {"allergenId": "e204", "sIgE": 3.0},    # nBos d 6 (Cow serum albumin)
            ]
        }
        report = run_engine(panel)
        pc = next(s for s in report['syndromes'] if s['syndrome'] == 'pork-cat')
        assert pc['detected'] is True, (
            "Pork-cat syndrome should be detected with Fel d 2 + Bos d 6 positive"
        )

    def test_bird_egg_syndrome(self):
        """Bird-egg syndrome requires Gal d 5 (f75) positive."""
        panel = {
            "patientId": "SYN-BE",
            "totalIgE": 180.0,
            "results": [
                {"allergenId": "f75", "sIgE": 12.0},    # nGal d 5 (Egg yolk livetin)
            ]
        }
        report = run_engine(panel)
        be = next(s for s in report['syndromes'] if s['syndrome'] == 'bird-egg')
        assert be['detected'] is True, (
            "Bird-egg syndrome should be detected when Gal d 5 is positive"
        )

    def test_pollen_food_syndrome(self):
        """Pollen-food syndrome: pollen PR-10 at CAP>=3 + food PR-10 at CAP>=1."""
        panel = {
            "patientId": "SYN-PF",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "t215", "sIgE": 45.0},   # rBet v 1 (Birch PR-10, CAP 4)
                {"allergenId": "f352", "sIgE": 2.1},    # rAra h 8 (Peanut PR-10, CAP 2)
            ]
        }
        report = run_engine(panel)
        pf = next(s for s in report['syndromes'] if s['syndrome'] == 'pollen-food')
        assert pf['detected'] is True, (
            "Pollen-food syndrome should be detected"
        )


class TestRiskAssessment:
    """Verify risk assessment logic."""

    def test_anaphylaxis_false_positive(self):
        """SEVERE symptom without ANAPHYLAXIS pathology must NOT trigger anaphylaxis risk."""
        panel = {
            "patientId": "RISK-FP",
            "totalIgE": 200.0,
            "results": [
                {"allergenId": "m229", "sIgE": 25.0},
                # rAlt a 1: symptoms=[SEVERE], pathologies=[ASTHMA, SEVERE_ASTHMA] — no ANAPHYLAXIS
            ]
        }
        report = run_engine(panel)
        ra = report['riskAssessment']
        assert ra['anaphylaxisRisk'] is False, (
            "rAlt a 1 has SEVERE symptom but NOT ANAPHYLAXIS pathology — "
            "anaphylaxisRisk should be false"
        )
        assert ra['overallRisk'] == 'high', (
            f"CAP 4 + SEVERE symptom but no anaphylaxis → 'high', got '{ra['overallRisk']}'"
        )

    def test_anaphylaxis_true(self):
        """Allergen with ANAPHYLAXIS pathology must trigger anaphylaxis risk."""
        panel = {
            "patientId": "RISK-TRUE",
            "totalIgE": 400.0,
            "results": [
                {"allergenId": "f423", "sIgE": 25.0},
                # rAra h 2: pathologies=[ANAPHYLAXIS, FOOD_ALLERGY]
            ]
        }
        report = run_engine(panel)
        assert report['riskAssessment']['anaphylaxisRisk'] is True, (
            "rAra h 2 has ANAPHYLAXIS pathology — anaphylaxisRisk should be true"
        )

    def test_ait_eligibility(self):
        """MAJOR allergens at CAP >= 2 in pollen/mite categories → AIT eligible."""
        panel = {
            "patientId": "AIT-TEST",
            "totalIgE": 200.0,
            "results": [
                {"allergenId": "t215", "sIgE": 15.0},   # rBet v 1, MAJOR, TREE_POLLENS, CAP 3
                {"allergenId": "d202", "sIgE": 8.0},    # rDer p 1, MAJOR, MITES, CAP 3
            ]
        }
        report = run_engine(panel)
        ra = report['riskAssessment']
        assert ra['aitEligible'] is True, (
            "AIT should be eligible for major pollen/mite allergens at CAP >= 2"
        )
        assert 'Birch' in ra['aitRecommendations'], (
            f"Birch should be in AIT recommendations, got {ra['aitRecommendations']}"
        )
        assert 'House dust mite (D. pteronyssinus)' in ra['aitRecommendations'], (
            f"HDM should be in AIT recommendations, got {ra['aitRecommendations']}"
        )


class TestSigeRatio:
    """Verify sIgE/tIgE ratio is numeric and correct."""

    def test_ratio_is_numeric(self):
        """sigeToTigeRatio must be a number, not a string."""
        panel = {
            "patientId": "RATIO-TYPE",
            "totalIgE": 200.0,
            "results": [{"allergenId": "e94", "sIgE": 20.0}]
        }
        report = run_engine(panel)
        ratio = report['classifications'][0]['sigeToTigeRatio']
        assert isinstance(ratio, (int, float)), (
            f"sigeToTigeRatio should be a number, got {type(ratio).__name__}: {ratio}"
        )

    def test_ratio_value(self):
        """Ratio = sIgE / totalIgE = 20.0 / 200.0 = 0.1."""
        panel = {
            "patientId": "RATIO-VAL",
            "totalIgE": 200.0,
            "results": [{"allergenId": "e94", "sIgE": 20.0}]
        }
        report = run_engine(panel)
        ratio = report['classifications'][0]['sigeToTigeRatio']
        assert abs(ratio - 0.1) < 0.001, f"Ratio should be 0.1, got {ratio}"

    def test_ratio_zero_total(self):
        """When totalIgE is 0, ratio should be 0."""
        panel = {
            "patientId": "RATIO-ZERO",
            "totalIgE": 0.0,
            "results": [{"allergenId": "e94", "sIgE": 5.0}]
        }
        report = run_engine(panel)
        ratio = report['classifications'][0]['sigeToTigeRatio']
        assert ratio == 0, f"Ratio should be 0 when totalIgE is 0, got {ratio}"


class TestQualityControl:
    """Verify quality control pipeline: validation, deduplication, CCD detection."""

    def test_duplicate_handling(self):
        """Duplicate allergenIds: keep highest sIgE, flag DUPLICATE_ENTRY."""
        panel = {
            "patientId": "QC-DUP",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "t215", "sIgE": 10.0},
                {"allergenId": "t215", "sIgE": 45.0},
                {"allergenId": "e94", "sIgE": 5.0},
            ]
        }
        report = run_engine(panel)
        assert len(report['classifications']) == 2, (
            f"Should have 2 classifications after dedup, got {len(report['classifications'])}"
        )
        t215 = next(c for c in report['classifications'] if c['allergenId'] == 't215')
        assert t215['sIgE'] == 45.0, (
            f"Should keep highest sIgE (45.0), got {t215['sIgE']}"
        )
        dup_flags = [f for f in report['qualityFlags'] if f['code'] == 'DUPLICATE_ENTRY']
        assert len(dup_flags) == 1, (
            f"Should have 1 DUPLICATE_ENTRY flag, got {len(dup_flags)}"
        )

    def test_unknown_allergen(self):
        """Unknown allergenId: excluded and UNKNOWN_ALLERGEN flag."""
        panel = {
            "patientId": "QC-UNK",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "NONEXISTENT_XYZ", "sIgE": 50.0},
                {"allergenId": "e94", "sIgE": 5.0},
            ]
        }
        report = run_engine(panel)
        assert len(report['classifications']) == 1, (
            f"Should have 1 classification (unknown excluded), got {len(report['classifications'])}"
        )
        assert report['classifications'][0]['allergenId'] == 'e94'
        unk_flags = [f for f in report['qualityFlags'] if f['code'] == 'UNKNOWN_ALLERGEN']
        assert len(unk_flags) == 1, (
            f"Should have 1 UNKNOWN_ALLERGEN flag, got {len(unk_flags)}"
        )

    def test_negative_sige(self):
        """Negative sIgE: excluded and NEGATIVE_SIGE flag."""
        panel = {
            "patientId": "QC-NEG",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "t215", "sIgE": -2.5},
                {"allergenId": "e94", "sIgE": 5.0},
            ]
        }
        report = run_engine(panel)
        assert len(report['classifications']) == 1, (
            f"Should have 1 classification (negative excluded), got {len(report['classifications'])}"
        )
        assert report['classifications'][0]['allergenId'] == 'e94'
        neg_flags = [f for f in report['qualityFlags'] if f['code'] == 'NEGATIVE_SIGE']
        assert len(neg_flags) == 1, (
            f"Should have 1 NEGATIVE_SIGE flag, got {len(neg_flags)}"
        )

    def test_ccd_interference(self):
        """CCD marker positive: CCD_INTERFERENCE flag, no exclusion."""
        panel = {
            "patientId": "QC-CCD",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "o214", "sIgE": 2.5},
                {"allergenId": "e94", "sIgE": 5.0},
            ]
        }
        report = run_engine(panel)
        assert len(report['classifications']) == 2, (
            "CCD marker should NOT be excluded — both results should be classified"
        )
        ccd_flags = [f for f in report['qualityFlags'] if f['code'] == 'CCD_INTERFERENCE']
        assert len(ccd_flags) == 1, (
            f"Should have 1 CCD_INTERFERENCE flag, got {len(ccd_flags)}"
        )

    def test_qc_clean_input(self):
        """Clean input: qualityFlags is empty list."""
        panel = {
            "patientId": "QC-CLEAN",
            "totalIgE": 300.0,
            "results": [{"allergenId": "e94", "sIgE": 5.0}]
        }
        report = run_engine(panel)
        assert 'qualityFlags' in report, "Report must include qualityFlags field"
        assert report['qualityFlags'] == [], (
            f"Clean input should have no flags, got {report['qualityFlags']}"
        )

    def test_qc_combined(self):
        """Multiple QC issues in one panel."""
        panel = {
            "patientId": "QC-COMBO",
            "totalIgE": 300.0,
            "results": [
                {"allergenId": "t215", "sIgE": 10.0},
                {"allergenId": "t215", "sIgE": 45.0},
                {"allergenId": "FAKE_ID", "sIgE": 50.0},
                {"allergenId": "e94", "sIgE": -1.0},
                {"allergenId": "o214", "sIgE": 2.5},
                {"allergenId": "g205", "sIgE": 3.0},
            ]
        }
        report = run_engine(panel)
        class_ids = {c['allergenId'] for c in report['classifications']}
        assert class_ids == {'t215', 'o214', 'g205'}, (
            f"Should classify t215, o214, g205 only. Got {class_ids}"
        )
        codes = [f['code'] for f in report['qualityFlags']]
        assert 'DUPLICATE_ENTRY' in codes, "Missing DUPLICATE_ENTRY flag"
        assert 'UNKNOWN_ALLERGEN' in codes, "Missing UNKNOWN_ALLERGEN flag"
        assert 'NEGATIVE_SIGE' in codes, "Missing NEGATIVE_SIGE flag"
        assert 'CCD_INTERFERENCE' in codes, "Missing CCD_INTERFERENCE flag"

    def test_duplicate_affects_clustering(self):
        """Duplicate entries must be deduplicated before clustering."""
        panel = {
            "patientId": "QC-CLUST",
            "totalIgE": 200.0,
            "results": [
                {"allergenId": "t215", "sIgE": 45.0},   # rBet v 1 (Birch, PR10)
                {"allergenId": "t215", "sIgE": 10.0},   # Duplicate
                {"allergenId": "f352", "sIgE": 2.1},    # rAra h 8 (Peanut, PR10)
            ]
        }
        report = run_engine(panel)
        dup_flags = [f for f in report['qualityFlags'] if f['code'] == 'DUPLICATE_ENTRY']
        assert len(dup_flags) == 1, "Should flag the duplicate t215 entry"
        pr10 = next(
            (c for c in report['crossReactivityClusters']
             if c['molecularFamily'] == 'PR10'), None
        )
        assert pr10 is not None, "PR10 cluster should exist"
        assert len(pr10['members']) == 2, (
            f"PR10 cluster should have 2 unique members (not 3 from duplicate), "
            f"got {len(pr10['members'])}"
        )


class TestFullPipeline:
    """End-to-end test with a complex multi-allergen patient panel."""

    def test_complex_panel(self):
        """Complex panel testing multiple features simultaneously."""
        panel = {
            "patientId": "FULL-001",
            "totalIgE": 350.0,
            "results": [
                {"allergenId": "t215", "sIgE": 42.0},   # Bet v 1 (PR10, Birch)
                {"allergenId": "f352", "sIgE": 3.0},    # Ara h 8 (PR10, Peanut)
                {"allergenId": "f428", "sIgE": 1.8},    # Cor a 1 (PR10, Hazelnut)
                {"allergenId": "f420", "sIgE": 9.5},    # Pru p 3 (LTP, Peach)
                {"allergenId": "w233", "sIgE": 4.1},    # Art v 3 (LTP, Mugwort)
                {"allergenId": "d202", "sIgE": 12.0},   # Der p 1 (Mite major)
                {"allergenId": "f423", "sIgE": 0.8},    # Ara h 2 (Storage, Peanut) - CAP 2
            ]
        }
        report = run_engine(panel)

        # qualityFlags present and clean
        assert 'qualityFlags' in report, "Report must include qualityFlags"
        assert report['qualityFlags'] == [], "Clean input should have no QC flags"

        # PR10 cluster with 3 members from 3 different sources
        clusters = report['crossReactivityClusters']
        pr10 = next((c for c in clusters if c['molecularFamily'] == 'PR10'), None)
        assert pr10 is not None, "PR10 cluster must be present"
        member_ids = [m['allergenId'] for m in pr10['members']]
        assert set(member_ids) == {'t215', 'f352', 'f428'}, (
            f"PR10 cluster should contain t215, f352, f428. Got: {member_ids}"
        )

        # LTP cluster
        ltp = next((c for c in clusters if c['molecularFamily'] == 'LTP'), None)
        assert ltp is not None, "LTP cluster must be present"
        assert len(ltp['members']) == 2

        # Syndromes
        syndromes = {s['syndrome']: s['detected'] for s in report['syndromes']}
        assert syndromes['pollen-food'] is True, "Pollen-food syndrome should fire"
        assert syndromes['ltp-syndrome'] is True, "LTP syndrome should fire"

        # Risk: Ara h 2 has ANAPHYLAXIS pathology, but at CAP 2.
        # Max CAP is 4 (Bet v 1 at 42.0). anaphylaxisRisk should be true.
        ra = report['riskAssessment']
        assert ra['anaphylaxisRisk'] is True
        assert ra['overallRisk'] == 'very-high', (
            f"CAP 4 + anaphylaxis → very-high, got '{ra['overallRisk']}'"
        )
        assert ra['aitEligible'] is True
