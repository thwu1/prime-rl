#!/usr/bin/env python3
"""Tests for GtoPdb multi-source selectivity profiler with CSV cross-validation."""

import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict

REPORT_PATH = "/app/test_report.json"
REPORT_MT3_PATH = "/app/test_report_mt3.json"


def setup_module():
    """Run the profiler with known serotonin receptor targets before tests."""
    # Run 1: targets 1 (5-HT1A), 2 (5-HT1B), 3 (5-HT1D), min-targets 2
    result = subprocess.run(
        ["python3", "/app/profiler.py",
         "--targets", "1,2,3",
         "--species", "Human",
         "--affinity-type", "pKi",
         "--min-targets", "2",
         "--output", REPORT_PATH],
        capture_output=True, text=True, timeout=900
    )
    assert result.returncode == 0, (
        f"Profiler failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    assert os.path.exists(REPORT_PATH), "Output file not created"

    # Run 2: same targets, min-targets 3
    result2 = subprocess.run(
        ["python3", "/app/profiler.py",
         "--targets", "1,2,3",
         "--species", "Human",
         "--affinity-type", "pKi",
         "--min-targets", "3",
         "--output", REPORT_MT3_PATH],
        capture_output=True, text=True, timeout=900
    )
    assert result2.returncode == 0, (
        f"Profiler (mt3) failed (exit {result2.returncode}):\n"
        f"stderr: {result2.stderr[:500]}"
    )


def load_report(path=REPORT_PATH):
    with open(path) as f:
        return json.load(f)


# ──────────────────────────────────────────────
# Output structure and schema validation
# ──────────────────────────────────────────────

class TestOutputStructure:
    def test_top_level_keys(self):
        report = load_report()
        for key in ("query", "ligand_count", "ligands", "csv_verification"):
            assert key in report, f"Missing top-level key: {key}"
        assert isinstance(report["ligands"], list)
        assert report["ligand_count"] == len(report["ligands"])

    def test_query_reflects_parameters(self):
        report = load_report()
        q = report["query"]
        assert q["targets"] == [1, 2, 3]
        assert q["species"] == "Human"
        assert q["affinity_type"] == "pKi"
        assert q["min_targets"] == 2

    def test_ligand_count_positive(self):
        report = load_report()
        assert report["ligand_count"] > 0, (
            "Expected at least one ligand shared across 5-HT1A/1B/1D"
        )

    def test_csv_verification_structure(self):
        report = load_report()
        cv = report["csv_verification"]
        for key in ("rows_matched", "pairs_verified", "pairs_failed",
                     "concordance_rate"):
            assert key in cv, f"Missing csv_verification key: {key}"
        assert isinstance(cv["rows_matched"], int)
        assert isinstance(cv["pairs_verified"], int)
        assert isinstance(cv["pairs_failed"], int)
        assert isinstance(cv["concordance_rate"], (int, float))

    def test_csv_verification_consistency(self):
        """concordance_rate must equal verified/(verified+failed)."""
        report = load_report()
        cv = report["csv_verification"]
        total = cv["pairs_verified"] + cv["pairs_failed"]
        if total > 0:
            expected_rate = cv["pairs_verified"] / total
            assert abs(cv["concordance_rate"] - expected_rate) < 0.01, (
                f"concordance_rate {cv['concordance_rate']} != "
                f"verified/total {expected_rate:.4f}"
            )
        else:
            assert cv["concordance_rate"] == 1.0


# ──────────────────────────────────────────────
# Ligand record fields
# ──────────────────────────────────────────────

class TestLigandRecords:
    REQUIRED_KEYS = [
        "ligand_id", "ligand_name", "approved",
        "primary_target_id", "primary_target_name",
        "primary_affinity", "mean_affinity",
        "selectivity_window", "ki_selectivity_ratio",
        "selectivity_entropy",
        "affinities", "molecular_properties",
        "interaction_types", "target_coverage",
        "original_affinity_nm", "measurement_count",
        "pmids", "csv_concordance",
    ]

    def test_required_fields_present(self):
        report = load_report()
        for lig in report["ligands"]:
            for key in self.REQUIRED_KEYS:
                assert key in lig, (
                    f"Ligand {lig.get('ligand_id', '?')} missing '{key}'"
                )

    def test_field_types(self):
        report = load_report()
        for lig in report["ligands"]:
            assert isinstance(lig["ligand_id"], int)
            assert isinstance(lig["ligand_name"], str)
            assert isinstance(lig["approved"], bool)
            assert isinstance(lig["primary_target_id"], int)
            assert isinstance(lig["primary_target_name"], str)
            for fld in ("primary_affinity", "mean_affinity",
                        "selectivity_window", "selectivity_entropy"):
                assert isinstance(lig[fld], (int, float)), (
                    f"Ligand {lig['ligand_id']}: {fld} should be numeric"
                )
            kr = lig["ki_selectivity_ratio"]
            assert kr is None or isinstance(kr, (int, float))
            assert isinstance(lig["affinities"], dict)
            assert isinstance(lig["molecular_properties"], dict)
            assert isinstance(lig["original_affinity_nm"], dict)
            assert isinstance(lig["measurement_count"], dict)
            assert isinstance(lig["pmids"], list)
            assert isinstance(lig["csv_concordance"], (int, float))

    def test_affinities_dict_values(self):
        report = load_report()
        for lig in report["ligands"]:
            aff = lig["affinities"]
            assert len(aff) >= 2, (
                f"Ligand {lig['ligand_id']} has {len(aff)} targets, expected >= 2"
            )
            for tid, val in aff.items():
                assert isinstance(val, (int, float)), (
                    f"Affinity for target {tid} is not numeric"
                )
                assert 0 < val < 15, (
                    f"pKi value {val} out of reasonable range (0,15)"
                )

    def test_molecular_properties_structure(self):
        report = load_report()
        mp_keys = ["molecular_weight", "logp", "lipinski_violations",
                    "hbond_acceptors", "hbond_donors"]
        for lig in report["ligands"]:
            mp = lig["molecular_properties"]
            for key in mp_keys:
                assert key in mp, (
                    f"Ligand {lig['ligand_id']} missing molecular property: {key}"
                )


# ──────────────────────────────────────────────
# Selectivity computation correctness
# ──────────────────────────────────────────────

class TestSelectivityComputations:
    def test_primary_target_is_highest_affinity(self):
        report = load_report()
        for lig in report["ligands"]:
            affs = lig["affinities"]
            max_val = max(affs.values())
            assert abs(lig["primary_affinity"] - max_val) < 0.02, (
                f"Ligand {lig['ligand_id']}: primary_affinity "
                f"{lig['primary_affinity']} != max affinity {max_val}"
            )

    def test_primary_target_id_matches(self):
        report = load_report()
        for lig in report["ligands"]:
            affs = lig["affinities"]
            expected_tid = max(affs, key=affs.get)
            assert str(lig["primary_target_id"]) == expected_tid, (
                f"Ligand {lig['ligand_id']}: primary_target_id "
                f"{lig['primary_target_id']} doesn't match highest-affinity "
                f"target {expected_tid}"
            )

    def test_mean_affinity(self):
        report = load_report()
        for lig in report["ligands"]:
            vals = list(lig["affinities"].values())
            expected = sum(vals) / len(vals)
            assert abs(lig["mean_affinity"] - expected) < 0.02, (
                f"Ligand {lig['ligand_id']}: mean_affinity "
                f"{lig['mean_affinity']} != expected {expected:.4f}"
            )

    def test_selectivity_window(self):
        report = load_report()
        for lig in report["ligands"]:
            vals = list(lig["affinities"].values())
            expected = max(vals) - min(vals)
            assert abs(lig["selectivity_window"] - expected) < 0.02, (
                f"Ligand {lig['ligand_id']}: selectivity_window "
                f"{lig['selectivity_window']} != expected {expected:.4f}"
            )

    def test_ki_selectivity_ratio(self):
        report = load_report()
        for lig in report["ligands"]:
            vals = sorted(lig["affinities"].values(), reverse=True)
            if len(vals) >= 2:
                expected = 10 ** vals[0] / 10 ** vals[1]
                assert lig["ki_selectivity_ratio"] is not None, (
                    f"Ligand {lig['ligand_id']}: ratio should not be null "
                    f"with {len(vals)} targets"
                )
                rel_err = abs(lig["ki_selectivity_ratio"] - expected) / max(expected, 1e-10)
                assert rel_err < 0.02, (
                    f"Ligand {lig['ligand_id']}: ki_selectivity_ratio "
                    f"{lig['ki_selectivity_ratio']} != expected {expected:.4f}"
                )
            else:
                assert lig["ki_selectivity_ratio"] is None

    def test_selectivity_entropy(self):
        report = load_report()
        for lig in report["ligands"]:
            vals = list(lig["affinities"].values())
            linear = [10 ** v for v in vals]
            total = sum(linear)
            probs = [k / total for k in linear]
            expected_h = -sum(p * math.log2(p) for p in probs if p > 0)
            assert abs(lig["selectivity_entropy"] - expected_h) < 0.02, (
                f"Ligand {lig['ligand_id']}: selectivity_entropy "
                f"{lig['selectivity_entropy']} != expected {expected_h:.4f}"
            )

    def test_entropy_bounds(self):
        """Entropy must be in [0, log2(n)] for n targets."""
        report = load_report()
        for lig in report["ligands"]:
            n = len(lig["affinities"])
            assert lig["selectivity_entropy"] >= -0.001, (
                f"Entropy cannot be negative: {lig['selectivity_entropy']}"
            )
            assert lig["selectivity_entropy"] <= math.log2(n) + 0.001, (
                f"Entropy {lig['selectivity_entropy']} exceeds log2({n})="
                f"{math.log2(n):.4f}"
            )


# ──────────────────────────────────────────────
# Sorting
# ──────────────────────────────────────────────

class TestSorting:
    def test_sorted_by_selectivity_window_then_primary(self):
        report = load_report()
        ligands = report["ligands"]
        for i in range(len(ligands) - 1):
            sw_a = ligands[i]["selectivity_window"]
            sw_b = ligands[i + 1]["selectivity_window"]
            if abs(sw_a - sw_b) > 0.0001:
                assert sw_a > sw_b, (
                    f"Index {i}: selectivity_window {sw_a} should be > {sw_b}"
                )
            else:
                assert ligands[i]["primary_affinity"] >= ligands[i + 1]["primary_affinity"], (
                    f"Index {i}: tie in selectivity_window ({sw_a}), "
                    f"primary_affinity {ligands[i]['primary_affinity']} "
                    f"should be >= {ligands[i + 1]['primary_affinity']}"
                )


# ──────────────────────────────────────────────
# min-targets filtering
# ──────────────────────────────────────────────

class TestMinTargetsFilter:
    def test_mt3_has_fewer_or_equal_ligands(self):
        r2 = load_report()
        r3 = load_report(REPORT_MT3_PATH)
        assert r3["ligand_count"] <= r2["ligand_count"], (
            f"min_targets=3 ({r3['ligand_count']}) should yield <= ligands "
            f"than min_targets=2 ({r2['ligand_count']})"
        )

    def test_mt3_ligands_have_3_targets(self):
        r3 = load_report(REPORT_MT3_PATH)
        for lig in r3["ligands"]:
            assert len(lig["affinities"]) >= 3, (
                f"Ligand {lig['ligand_id']} has {len(lig['affinities'])} "
                f"targets, expected >= 3"
            )

    def test_mt3_query_reflects_min3(self):
        r3 = load_report(REPORT_MT3_PATH)
        assert r3["query"]["min_targets"] == 3

    def test_mt3_target_coverage_is_one(self):
        """All ligands with min_targets=3 and 3 queried targets
        must have target_coverage == 1.0."""
        r3 = load_report(REPORT_MT3_PATH)
        for lig in r3["ligands"]:
            assert abs(lig["target_coverage"] - 1.0) < 0.001, (
                f"Ligand {lig['ligand_id']}: target_coverage should be 1.0 "
                f"when min_targets equals number of queried targets, "
                f"got {lig['target_coverage']}"
            )

    def test_mt3_has_csv_verification(self):
        r3 = load_report(REPORT_MT3_PATH)
        assert "csv_verification" in r3
        cv = r3["csv_verification"]
        assert cv["rows_matched"] > 0, (
            "CSV should have matching rows for 5-HT targets in mt3 run"
        )


# ──────────────────────────────────────────────
# HTML stripping
# ──────────────────────────────────────────────

class TestHTMLStripping:
    def test_no_html_in_target_names(self):
        report = load_report()
        for lig in report["ligands"]:
            name = lig["primary_target_name"]
            assert not re.search(r'<[^>]+>', name), (
                f"HTML found in target name: {name}"
            )

    def test_no_html_in_ligand_names(self):
        report = load_report()
        for lig in report["ligands"]:
            name = lig["ligand_name"]
            assert not re.search(r'<[^>]+>', name), (
                f"HTML found in ligand name: {name}"
            )


# ──────────────────────────────────────────────
# Molecular properties integration
# ──────────────────────────────────────────────

class TestMolecularProperties:
    def test_some_ligands_have_molecular_weight(self):
        report = load_report()
        has_mw = any(
            lig["molecular_properties"]["molecular_weight"] is not None
            for lig in report["ligands"]
        )
        assert has_mw, "At least some ligands should have molecular_weight"

    def test_lipinski_violations_type(self):
        report = load_report()
        for lig in report["ligands"]:
            lv = lig["molecular_properties"]["lipinski_violations"]
            assert lv is None or isinstance(lv, int), (
                f"lipinski_violations should be int or null, "
                f"got {type(lv).__name__}: {lv}"
            )

    def test_hbond_values_type(self):
        report = load_report()
        for lig in report["ligands"]:
            mp = lig["molecular_properties"]
            for key in ("hbond_acceptors", "hbond_donors"):
                val = mp[key]
                assert val is None or isinstance(val, int), (
                    f"{key} should be int or null, got {type(val).__name__}"
                )


# ──────────────────────────────────────────────
# Interaction types
# ──────────────────────────────────────────────

class TestInteractionTypes:
    def test_interaction_types_is_list(self):
        report = load_report()
        for lig in report["ligands"]:
            assert isinstance(lig["interaction_types"], list), (
                f"Ligand {lig['ligand_id']}: interaction_types should be a list"
            )

    def test_interaction_types_nonempty(self):
        report = load_report()
        for lig in report["ligands"]:
            assert len(lig["interaction_types"]) > 0, (
                f"Ligand {lig['ligand_id']}: interaction_types should not be empty"
            )

    def test_interaction_types_are_strings(self):
        report = load_report()
        for lig in report["ligands"]:
            for t in lig["interaction_types"]:
                assert isinstance(t, str) and len(t) > 0

    def test_interaction_types_sorted(self):
        report = load_report()
        for lig in report["ligands"]:
            types = lig["interaction_types"]
            assert types == sorted(types), (
                f"Ligand {lig['ligand_id']}: interaction_types {types} "
                f"should be sorted alphabetically"
            )

    def test_interaction_types_unique(self):
        report = load_report()
        for lig in report["ligands"]:
            types = lig["interaction_types"]
            assert len(types) == len(set(types)), (
                f"Ligand {lig['ligand_id']}: interaction_types should be unique"
            )

    def test_serotonin_is_agonist(self):
        """Serotonin (5-HT, ligand 5) is an agonist at 5-HT subtypes."""
        report = load_report()
        serotonin = next(
            (l for l in report["ligands"] if l["ligand_id"] == 5), None
        )
        if serotonin is not None:
            assert "Agonist" in serotonin["interaction_types"], (
                f"Serotonin should be classified as Agonist, "
                f"got {serotonin['interaction_types']}"
            )

    def test_interaction_types_contain_known_values(self):
        """All interaction types should be recognized pharmacological types."""
        known_types = {
            "Agonist", "Antagonist", "Inhibitor", "Allosteric modulator",
            "Antibody", "Channel blocker", "Gating inhibitor",
            "Subunit-specific agonist", "Subunit-specific antagonist",
            "Pore blocker", "None",
        }
        report = load_report()
        all_types = set()
        for lig in report["ligands"]:
            all_types.update(lig["interaction_types"])
        assert len(all_types & known_types) > 0, (
            f"No recognized pharmacological types found. Got: {all_types}"
        )


# ──────────────────────────────────────────────
# Target coverage
# ──────────────────────────────────────────────

class TestTargetCoverage:
    def test_target_coverage_type(self):
        report = load_report()
        for lig in report["ligands"]:
            tc = lig["target_coverage"]
            assert isinstance(tc, (int, float))

    def test_target_coverage_range(self):
        report = load_report()
        for lig in report["ligands"]:
            tc = lig["target_coverage"]
            assert 0.0 < tc <= 1.0, (
                f"Ligand {lig['ligand_id']}: target_coverage {tc} out of (0, 1]"
            )

    def test_target_coverage_consistent_with_affinities(self):
        """target_coverage must equal len(affinities) / number_of_queried_targets."""
        report = load_report()
        n_targets = len(report["query"]["targets"])
        for lig in report["ligands"]:
            expected = len(lig["affinities"]) / n_targets
            assert abs(lig["target_coverage"] - expected) < 0.001, (
                f"Ligand {lig['ligand_id']}: target_coverage "
                f"{lig['target_coverage']} != expected "
                f"{len(lig['affinities'])}/{n_targets} = {expected:.4f}"
            )

    def test_min_targets_coverage_lower_bound(self):
        """With min_targets=2 and 3 queried targets, coverage >= 2/3."""
        report = load_report()
        for lig in report["ligands"]:
            assert lig["target_coverage"] >= 2.0 / 3.0 - 0.001, (
                f"Ligand {lig['ligand_id']}: target_coverage "
                f"{lig['target_coverage']} below 2/3 with min_targets=2"
            )


# ──────────────────────────────────────────────
# Known ligand checks
# ──────────────────────────────────────────────

class TestKnownLigands:
    def test_serotonin_present(self):
        """5-hydroxytryptamine (ligand 5) interacts with all 5-HT subtypes."""
        report = load_report()
        ids = [lig["ligand_id"] for lig in report["ligands"]]
        assert 5 in ids, (
            "Serotonin (ligand 5) should appear in multi-target results "
            "for 5-HT receptors 1A/1B/1D"
        )

    def test_serotonin_is_not_approved(self):
        """Serotonin is an endogenous metabolite, not an approved drug."""
        report = load_report()
        serotonin = next(
            (l for l in report["ligands"] if l["ligand_id"] == 5), None
        )
        if serotonin is not None:
            assert serotonin["approved"] is False, (
                "Serotonin should not be marked as approved"
            )

    def test_approved_field_boolean(self):
        report = load_report()
        for lig in report["ligands"]:
            assert isinstance(lig["approved"], bool), (
                f"Ligand {lig['ligand_id']}: approved should be bool"
            )


# ──────────────────────────────────────────────
# Original affinity in nM (pKi → molar conversion)
# ──────────────────────────────────────────────

class TestOriginalAffinityNM:
    def test_original_affinity_nm_structure(self):
        """original_affinity_nm must be a dict with same keys as affinities."""
        report = load_report()
        for lig in report["ligands"]:
            oa = lig["original_affinity_nm"]
            assert isinstance(oa, dict), (
                f"Ligand {lig['ligand_id']}: original_affinity_nm must be dict"
            )
            assert set(oa.keys()) == set(lig["affinities"].keys()), (
                f"Ligand {lig['ligand_id']}: original_affinity_nm keys "
                f"{set(oa.keys())} must match affinities keys "
                f"{set(lig['affinities'].keys())}"
            )

    def test_original_affinity_nm_values_numeric(self):
        report = load_report()
        for lig in report["ligands"]:
            for tid, val in lig["original_affinity_nm"].items():
                assert isinstance(val, (int, float)), (
                    f"Ligand {lig['ligand_id']} target {tid}: "
                    f"original_affinity_nm must be numeric"
                )
                assert val > 0, (
                    f"Ligand {lig['ligand_id']} target {tid}: "
                    f"nM value must be positive, got {val}"
                )

    def test_original_affinity_nm_conversion(self):
        """Verify nM = 10^(9 - pAffinity) for each per-target value."""
        report = load_report()
        for lig in report["ligands"]:
            for tid in lig["affinities"]:
                pki = lig["affinities"][tid]
                nm_reported = lig["original_affinity_nm"][tid]
                nm_expected = 10 ** (9 - pki)
                rel_err = abs(nm_reported - nm_expected) / max(nm_expected, 1e-15)
                assert rel_err < 0.02, (
                    f"Ligand {lig['ligand_id']} target {tid}: "
                    f"nM {nm_reported} != 10^(9 - {pki}) = {nm_expected:.4f}"
                )

    def test_high_affinity_gives_low_nm(self):
        """Higher pKi should yield lower nM (stronger binding)."""
        report = load_report()
        for lig in report["ligands"]:
            affs = lig["affinities"]
            nm = lig["original_affinity_nm"]
            if len(affs) >= 2:
                tids = list(affs.keys())
                for i in range(len(tids)):
                    for j in range(i + 1, len(tids)):
                        if affs[tids[i]] > affs[tids[j]]:
                            assert nm[tids[i]] < nm[tids[j]], (
                                f"Ligand {lig['ligand_id']}: higher pKi at "
                                f"target {tids[i]} should yield lower nM"
                            )


# ──────────────────────────────────────────────
# Measurement count
# ──────────────────────────────────────────────

class TestMeasurementCount:
    def test_measurement_count_structure(self):
        """measurement_count must be a dict with same keys as affinities."""
        report = load_report()
        for lig in report["ligands"]:
            mc = lig["measurement_count"]
            assert isinstance(mc, dict), (
                f"Ligand {lig['ligand_id']}: measurement_count must be dict"
            )
            assert set(mc.keys()) == set(lig["affinities"].keys()), (
                f"Ligand {lig['ligand_id']}: measurement_count keys must "
                f"match affinities keys"
            )

    def test_measurement_count_positive(self):
        """Every target must have at least one measurement."""
        report = load_report()
        for lig in report["ligands"]:
            for tid, count in lig["measurement_count"].items():
                assert isinstance(count, int), (
                    f"Ligand {lig['ligand_id']} target {tid}: "
                    f"measurement_count must be int"
                )
                assert count >= 1, (
                    f"Ligand {lig['ligand_id']} target {tid}: "
                    f"measurement_count must be >= 1, got {count}"
                )

    def test_some_ligands_have_multiple_measurements(self):
        """5-HT receptors have well-studied ligands with multiple measurements."""
        report = load_report()
        has_multi = False
        for lig in report["ligands"]:
            if any(c > 1 for c in lig["measurement_count"].values()):
                has_multi = True
                break
        assert has_multi, (
            "Expected at least one ligand-target pair with multiple measurements"
        )


# ──────────────────────────────────────────────
# PubMed IDs
# ──────────────────────────────────────────────

class TestPMIDs:
    def test_pmids_is_list(self):
        report = load_report()
        for lig in report["ligands"]:
            assert isinstance(lig["pmids"], list), (
                f"Ligand {lig['ligand_id']}: pmids must be list"
            )

    def test_pmids_are_integers(self):
        report = load_report()
        for lig in report["ligands"]:
            for pmid in lig["pmids"]:
                assert isinstance(pmid, int), (
                    f"Ligand {lig['ligand_id']}: PMID {pmid} must be int"
                )
                assert pmid > 0, (
                    f"Ligand {lig['ligand_id']}: PMID must be positive"
                )

    def test_pmids_sorted_ascending(self):
        report = load_report()
        for lig in report["ligands"]:
            pmids = lig["pmids"]
            assert pmids == sorted(pmids), (
                f"Ligand {lig['ligand_id']}: pmids must be sorted ascending"
            )

    def test_pmids_unique(self):
        report = load_report()
        for lig in report["ligands"]:
            pmids = lig["pmids"]
            assert len(pmids) == len(set(pmids)), (
                f"Ligand {lig['ligand_id']}: pmids must be unique"
            )

    def test_some_ligands_have_pmids(self):
        """Well-characterized 5-HT ligands should have literature references."""
        report = load_report()
        has_pmids = any(len(lig["pmids"]) > 0 for lig in report["ligands"])
        assert has_pmids, "At least some ligands should have PubMed IDs"

    def test_serotonin_has_pmids(self):
        """Serotonin is extensively studied and must have PMIDs."""
        report = load_report()
        serotonin = next(
            (l for l in report["ligands"] if l["ligand_id"] == 5), None
        )
        if serotonin is not None:
            assert len(serotonin["pmids"]) >= 2, (
                f"Serotonin should have multiple PMIDs, "
                f"got {len(serotonin['pmids'])}"
            )

    def test_pmids_are_plausible(self):
        """PMIDs should be in a reasonable range (1-99999999)."""
        report = load_report()
        for lig in report["ligands"]:
            for pmid in lig["pmids"]:
                assert 100000 < pmid < 99999999, (
                    f"Ligand {lig['ligand_id']}: PMID {pmid} looks implausible"
                )


# ──────────────────────────────────────────────
# CSV concordance per ligand
# ──────────────────────────────────────────────

class TestCSVConcordance:
    def test_csv_concordance_type(self):
        report = load_report()
        for lig in report["ligands"]:
            cc = lig["csv_concordance"]
            assert isinstance(cc, (int, float)), (
                f"Ligand {lig['ligand_id']}: csv_concordance must be numeric"
            )

    def test_csv_concordance_range(self):
        report = load_report()
        for lig in report["ligands"]:
            cc = lig["csv_concordance"]
            assert 0.0 <= cc <= 1.0, (
                f"Ligand {lig['ligand_id']}: csv_concordance {cc} out of [0, 1]"
            )

    def test_high_concordance_expected(self):
        """API and CSV come from the same database; concordance should be high."""
        report = load_report()
        concordances = [lig["csv_concordance"] for lig in report["ligands"]]
        if concordances:
            avg = sum(concordances) / len(concordances)
            assert avg > 0.5, (
                f"Average csv_concordance {avg:.2f} is suspiciously low"
            )


# ──────────────────────────────────────────────
# CSV cross-validation with independent download
# ──────────────────────────────────────────────

class TestCSVCrossValidation:
    def test_csv_rows_matched_positive(self):
        """The profiler must have downloaded and matched CSV rows."""
        report = load_report()
        cv = report["csv_verification"]
        assert cv["rows_matched"] > 0, (
            "CSV should have matching rows for 5-HT receptor targets. "
            "rows_matched=0 suggests CSV was not downloaded or parsed."
        )

    def test_csv_concordance_rate_plausible(self):
        """Concordance between API and CSV should be reasonably high."""
        report = load_report()
        cv = report["csv_verification"]
        total = cv["pairs_verified"] + cv["pairs_failed"]
        if total > 0:
            assert cv["concordance_rate"] > 0.5, (
                f"Concordance rate {cv['concordance_rate']} is suspiciously low"
            )

    def test_csv_pairs_compared_is_positive(self):
        """At least some pairs should be comparable between API and CSV."""
        report = load_report()
        cv = report["csv_verification"]
        total = cv["pairs_verified"] + cv["pairs_failed"]
        assert total > 0, (
            "No (ligand, target) pairs were compared between API and CSV. "
            "Cross-validation must compare at least some pairs."
        )

    def test_independent_csv_row_count(self):
        """Independently download CSV and verify rows_matched is plausible."""
        report = load_report()
        target_ids = set(report["query"]["targets"])
        species = report["query"]["species"]
        aff_type = report["query"]["affinity_type"]

        try:
            req = urllib.request.Request(
                "https://www.guidetopharmacology.org/DATA/interactions.csv"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
        except Exception:
            return  # Skip if download fails in test

        lines = raw.split('\n')
        header_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip().strip('"')
            if stripped.startswith('#') or not stripped:
                continue
            if 'Target' in stripped and 'Target ID' in line:
                header_idx = i
                break

        csv_content = '\n'.join(lines[header_idx:])
        reader = csv.DictReader(io.StringIO(csv_content))

        count = 0
        for row in reader:
            try:
                tid = int(row.get('Target ID', '').strip())
            except (ValueError, TypeError):
                continue
            tspecies = row.get('Target Species', '').strip()
            aff_units = row.get('Affinity Units', '').strip()
            if tid in target_ids and tspecies == species and aff_units == aff_type:
                count += 1

        cv = report["csv_verification"]
        # Allow some tolerance for data updates
        assert abs(cv["rows_matched"] - count) <= 10, (
            f"rows_matched {cv['rows_matched']} differs from "
            f"independent count {count}"
        )

    def test_independent_csv_median_spot_check(self):
        """Spot-check: independently compute CSV median for serotonin at target 1
        and verify it's close to the profiler's API-derived value."""
        report = load_report()
        serotonin = next(
            (l for l in report["ligands"] if l["ligand_id"] == 5), None
        )
        if serotonin is None or "1" not in serotonin["affinities"]:
            return

        try:
            req = urllib.request.Request(
                "https://www.guidetopharmacology.org/DATA/interactions.csv"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
        except Exception:
            return

        lines = raw.split('\n')
        header_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip().strip('"')
            if stripped.startswith('#') or not stripped:
                continue
            if 'Target' in stripped and 'Target ID' in line:
                header_idx = i
                break

        csv_content = '\n'.join(lines[header_idx:])
        reader = csv.DictReader(io.StringIO(csv_content))

        import statistics
        vals = []
        for row in reader:
            try:
                lid = int(row.get('Ligand ID', '').strip())
                tid = int(row.get('Target ID', '').strip())
            except (ValueError, TypeError):
                continue
            if lid != 5 or tid != 1:
                continue
            if row.get('Target Species', '').strip() != 'Human':
                continue
            if row.get('Affinity Units', '').strip() != 'pKi':
                continue
            aff_med = row.get('Affinity Median', '').strip()
            aff_hi = row.get('Affinity High', '').strip()
            aff_lo = row.get('Affinity Low', '').strip()
            val = None
            if aff_med:
                try:
                    val = float(aff_med)
                except ValueError:
                    pass
            elif aff_hi and aff_lo:
                try:
                    val = (float(aff_hi) + float(aff_lo)) / 2.0
                except ValueError:
                    pass
            if val is not None:
                vals.append(val)

        if len(vals) == 0:
            return

        csv_median = statistics.median(vals)
        api_val = serotonin["affinities"]["1"]
        # They should be very close since API and CSV come from the same DB
        assert abs(api_val - csv_median) < 0.3, (
            f"Serotonin target 1: API median {api_val} vs CSV median "
            f"{csv_median:.4f} differ by more than 0.3"
        )


# ──────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────

class TestEdgeCases:
    def test_impossible_min_targets_yields_empty(self):
        try:
            result = subprocess.run(
                ["python3", "/app/profiler.py",
                 "--targets", "1,2",
                 "--species", "Human",
                 "--affinity-type", "pKi",
                 "--min-targets", "99",
                 "--output", "/app/test_empty.json"],
                capture_output=True, text=True, timeout=300
            )
        except subprocess.TimeoutExpired:
            assert False, "Profiler timed out on impossible min-targets query"
        assert result.returncode == 0, (
            f"Should exit 0 even with empty results: {result.stderr[:300]}"
        )
        with open("/app/test_empty.json") as f:
            report = json.load(f)
        assert report["ligand_count"] == 0
        assert report["ligands"] == []
        assert "csv_verification" in report
        assert report["csv_verification"]["concordance_rate"] == 1.0


# ──────────────────────────────────────────────
# API consistency cross-check
# ──────────────────────────────────────────────

class TestAPIConsistency:
    def test_approved_status_matches_api(self):
        """Verify the approved field against a direct API query."""
        report = load_report()
        if not report["ligands"]:
            return

        lig = report["ligands"][0]
        lid = lig["ligand_id"]

        url = f"https://www.guidetopharmacology.org/services/ligands/{lid}"
        req = urllib.request.Request(
            url, headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                api_data = json.loads(resp.read().decode())
            expected_approved = bool(api_data.get("approved", False))
            assert lig["approved"] == expected_approved, (
                f"Ligand {lid}: report says approved={lig['approved']} "
                f"but API says {expected_approved}"
            )
        except Exception:
            pass

    def test_affinity_matches_api_for_known_target(self):
        """Verify affinity values are consistent with API for target 1."""
        report = load_report()
        if not report["ligands"]:
            return

        url = ("https://www.guidetopharmacology.org/services/targets/1/"
               "interactions?species=Human&affinityParameter=pKi")
        req = urllib.request.Request(
            url, headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                api_interactions = json.loads(resp.read().decode())
        except Exception:
            return

        import statistics as stats_mod
        pair_vals = defaultdict(list)
        for ix in api_interactions:
            aff_str = ix.get("affinity", "")
            if not aff_str or not aff_str.strip():
                continue
            s = aff_str.strip()
            if " - " in s:
                parts = s.split(" - ")
                try:
                    val = (float(parts[0]) + float(parts[1])) / 2.0
                except (ValueError, IndexError):
                    continue
            else:
                try:
                    val = float(s)
                except ValueError:
                    continue
            pair_vals[ix["ligandId"]].append(val)

        expected = {lid: stats_mod.median(vs) for lid, vs in pair_vals.items()}

        matches = 0
        for lig in report["ligands"]:
            lid = lig["ligand_id"]
            if lid in expected and "1" in lig["affinities"]:
                report_val = lig["affinities"]["1"]
                exp_val = expected[lid]
                if abs(report_val - exp_val) < 0.05:
                    matches += 1

        assert matches >= 2, (
            f"Only {matches} ligands match API affinity data for target 1"
        )

    def test_interaction_types_match_api(self):
        """Verify interaction_types against direct API query for target 1."""
        report = load_report()
        if not report["ligands"]:
            return

        url = ("https://www.guidetopharmacology.org/services/targets/1/"
               "interactions?species=Human&affinityParameter=pKi")
        req = urllib.request.Request(
            url, headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                api_interactions = json.loads(resp.read().decode())
        except Exception:
            return

        api_types = defaultdict(set)
        for ix in api_interactions:
            aff_str = ix.get("affinity", "")
            if not aff_str or not aff_str.strip():
                continue
            ix_type = ix.get("type", "")
            if ix_type:
                api_types[ix["ligandId"]].add(ix_type)

        matches = 0
        for lig in report["ligands"]:
            lid = lig["ligand_id"]
            if lid in api_types and "1" in lig["affinities"]:
                for t in api_types[lid]:
                    if t in lig["interaction_types"]:
                        matches += 1
                        break

        assert matches >= 2, (
            f"Only {matches} ligands have interaction_types matching API"
        )

    def test_measurement_count_matches_api(self):
        """Verify measurement_count for target 1 against direct API data."""
        report = load_report()
        if not report["ligands"]:
            return

        url = ("https://www.guidetopharmacology.org/services/targets/1/"
               "interactions?species=Human&affinityParameter=pKi")
        req = urllib.request.Request(
            url, headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                api_interactions = json.loads(resp.read().decode())
        except Exception:
            return

        api_counts = defaultdict(int)
        for ix in api_interactions:
            aff_str = ix.get("affinity", "")
            if not aff_str or not aff_str.strip():
                continue
            api_counts[ix["ligandId"]] += 1

        matches = 0
        for lig in report["ligands"]:
            lid = lig["ligand_id"]
            if lid in api_counts and "1" in lig["measurement_count"]:
                if lig["measurement_count"]["1"] == api_counts[lid]:
                    matches += 1

        assert matches >= 2, (
            f"Only {matches} ligands have matching measurement_count for target 1"
        )
