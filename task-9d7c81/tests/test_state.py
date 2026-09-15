"""
Verification tests for mutation subsumption analysis report.
"""

import json
import os
import re
import shutil
import subprocess
from collections import Counter

REPORT_PATH = "/app/analysis_report.json"
SOURCE_PATH = "/app/src/algorithms.py"
TEST_DIR = "/app/tests"


def _load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def _kill_sets_from_report():
    """Helper: extract {mid: frozenset(killing test IDs)} from report."""
    km = _load_report()["kill_matrix"]
    return {mid: frozenset(t for t, v in row.items() if v == 1)
            for mid, row in km.items()}


# ------------------------------------------------------------------ structure
class TestReportStructure:

    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "analysis_report.json not found"

    def test_top_level_keys(self):
        r = _load_report()
        for key in ("summary", "kill_matrix", "subsumption",
                     "dynamic_equivalences", "minimal_test_set",
                     "operator_stats", "mutants"):
            assert key in r, f"Missing top-level key: {key}"

    def test_summary_keys(self):
        s = _load_report()["summary"]
        for key in ("total_mutants", "killed", "survived", "mutation_score"):
            assert key in s, f"Missing summary key: {key}"

    def test_subsumption_keys(self):
        sub = _load_report()["subsumption"]
        for key in ("relations", "reduced_relations",
                     "minimal_subsuming_set", "subsuming_mutation_score"):
            assert key in sub, f"Missing subsumption key: {key}"

    def test_mutant_entry_keys(self):
        r = _load_report()
        assert len(r["mutants"]) > 0, "No mutants in report"
        m = r["mutants"][0]
        for key in ("id", "operator", "function", "line",
                     "original", "replacement", "status", "killed_by"):
            assert key in m, f"Missing mutant key: {key}"


# -------------------------------------------------------------- consistency
class TestConsistency:

    def test_killed_plus_survived(self):
        s = _load_report()["summary"]
        assert s["killed"] + s["survived"] == s["total_mutants"]

    def test_mutation_score(self):
        s = _load_report()["summary"]
        expected = s["killed"] / s["total_mutants"]
        assert abs(s["mutation_score"] - expected) < 0.001

    def test_total_matches_mutant_list(self):
        r = _load_report()
        assert r["summary"]["total_mutants"] == len(r["mutants"])

    def test_kill_matrix_binary(self):
        km = _load_report()["kill_matrix"]
        for mid, tests in km.items():
            for tid, val in tests.items():
                assert val in (0, 1), f"Non-binary value {val} at {mid},{tid}"

    def test_status_matches_kill_matrix(self):
        r = _load_report()
        km = r["kill_matrix"]
        for m in r["mutants"]:
            kills = sum(v for v in km[m["id"]].values())
            if m["status"] == "killed":
                assert kills > 0, f"{m['id']} marked killed but 0 kills"
            else:
                assert kills == 0, f"{m['id']} marked survived but {kills} kills"

    def test_kill_matrix_covers_all_mutants(self):
        r = _load_report()
        km_ids = set(r["kill_matrix"].keys())
        mutant_ids = {m["id"] for m in r["mutants"]}
        assert km_ids == mutant_ids

    def test_kill_matrix_tests_consistent(self):
        """All rows in the kill matrix use the same set of test IDs."""
        km = _load_report()["kill_matrix"]
        test_sets = [frozenset(row.keys()) for row in km.values()]
        assert len(set(test_sets)) == 1, "Inconsistent test IDs across rows"


# ------------------------------------------------------------ mutant counts
class TestMutantCounts:

    def test_total_in_range(self):
        r = _load_report()
        n = r["summary"]["total_mutants"]
        assert 30 <= n <= 100, f"Unexpected mutant count: {n}"

    def test_all_operators_present(self):
        ops = {m["operator"] for m in _load_report()["mutants"]}
        assert "AOR" in ops, "No AOR mutants"
        assert "ROR" in ops, "No ROR mutants"
        assert "CRP" in ops, "No CRP mutants"

    def test_survived_at_least_one(self):
        assert _load_report()["summary"]["survived"] >= 1

    def test_mutation_score_range(self):
        score = _load_report()["summary"]["mutation_score"]
        assert 0.80 <= score <= 1.0, f"Score {score} outside expected range"


# ------------------------------------------------------------ subsumption
class TestSubsumption:

    def test_relations_valid(self):
        """For each (M1,M2) in relations, kill_set(M1) ⊊ kill_set(M2)."""
        r = _load_report()
        km = r["kill_matrix"]
        for m1, m2 in r["subsumption"]["relations"]:
            ks1 = {t for t, v in km[m1].items() if v == 1}
            ks2 = {t for t, v in km[m2].items() if v == 1}
            assert ks1 < ks2, (
                f"Invalid subsumption {m1}->{m2}: "
                f"|ks1|={len(ks1)}, |ks2|={len(ks2)}, "
                f"ks1⊂ks2={ks1 < ks2}"
            )

    def test_minimal_set_no_mutual_subsumption(self):
        """No mutant in the minimal subsuming set is subsumed by another."""
        r = _load_report()
        km = r["kill_matrix"]
        minimal = r["subsumption"]["minimal_subsuming_set"]
        for m1 in minimal:
            ks1 = {t for t, v in km[m1].items() if v == 1}
            for m2 in minimal:
                if m1 != m2:
                    ks2 = {t for t, v in km[m2].items() if v == 1}
                    assert not (ks2 < ks1), (
                        f"{m2} subsumes {m1} but both in minimal set"
                    )

    def test_minimal_set_killable(self):
        """Every mutant in the minimal subsuming set must be killable."""
        r = _load_report()
        km = r["kill_matrix"]
        for mid in r["subsumption"]["minimal_subsuming_set"]:
            assert any(v == 1 for v in km[mid].values()), (
                f"{mid} in subsuming set but not killable"
            )

    def test_minimal_set_complete(self):
        """Every killable mutant not in the set must be subsumed by one in it."""
        r = _load_report()
        km = r["kill_matrix"]
        minimal = set(r["subsumption"]["minimal_subsuming_set"])
        killable = {mid for mid, row in km.items()
                    if any(v == 1 for v in row.values())}
        for mid in killable - minimal:
            ks_mid = {t for t, v in km[mid].items() if v == 1}
            found_subsumer = False
            for sub_mid in killable:
                if sub_mid == mid:
                    continue
                ks_sub = {t for t, v in km[sub_mid].items() if v == 1}
                if ks_sub < ks_mid:
                    found_subsumer = True
                    break
            assert found_subsumer, (
                f"Killable mutant {mid} not in minimal set and not subsumed"
            )

    def test_subsuming_score_correct(self):
        """subsuming_mutation_score = |minimal_subsuming_set| / total_mutants."""
        r = _load_report()
        minimal_size = len(r["subsumption"]["minimal_subsuming_set"])
        total = r["summary"]["total_mutants"]
        expected = round(minimal_size / total, 4)
        assert abs(r["subsumption"]["subsuming_mutation_score"] - expected) < 0.002


# ----------------------------------------------- reduced relations (Hasse)
class TestReducedRelations:

    def test_reduced_is_subset_of_full(self):
        """Every reduced relation must also appear in the full relations."""
        r = _load_report()
        full = {tuple(x) for x in r["subsumption"]["relations"]}
        reduced = {tuple(x) for x in r["subsumption"]["reduced_relations"]}
        assert reduced <= full, (
            f"{len(reduced - full)} reduced relations not in full set"
        )

    def test_reduced_relations_valid(self):
        """Each reduced relation has no intermediate mutant."""
        r = _load_report()
        ks = _kill_sets_from_report()
        killable = {m for m, s in ks.items() if s}
        for m1, m2 in r["subsumption"]["reduced_relations"]:
            assert ks[m1] < ks[m2], (
                f"Reduced relation {m1}->{m2} is not a valid subsumption"
            )
            for m3 in killable:
                if m3 != m1 and m3 != m2:
                    assert not (ks[m1] < ks[m3] < ks[m2]), (
                        f"Reduced relation {m1}->{m2} has intermediate {m3}"
                    )

    def test_reduced_relations_complete(self):
        """Every immediate subsumption must appear in reduced_relations."""
        r = _load_report()
        ks = _kill_sets_from_report()
        killable = {m for m, s in ks.items() if s}
        reduced_set = {(a, b) for a, b in r["subsumption"]["reduced_relations"]}

        for m1 in sorted(killable):
            for m2 in sorted(killable):
                if m1 != m2 and ks[m1] < ks[m2]:
                    has_intermediate = any(
                        ks[m1] < ks[m3] < ks[m2]
                        for m3 in killable if m3 != m1 and m3 != m2
                    )
                    if not has_intermediate:
                        assert (m1, m2) in reduced_set, (
                            f"Missing Hasse edge {m1}->{m2}"
                        )

    def test_reduced_strictly_smaller(self):
        """The reduced set must be <= the full set in size."""
        r = _load_report()
        full_n = len(r["subsumption"]["relations"])
        reduced_n = len(r["subsumption"]["reduced_relations"])
        assert reduced_n <= full_n


# ------------------------------------------------------ dynamic equivalence
class TestDynamicEquivalence:

    def test_pairs_have_identical_kill_vectors(self):
        r = _load_report()
        km = r["kill_matrix"]
        test_ids = sorted(next(iter(km.values())).keys())
        for m1, m2 in r["dynamic_equivalences"]:
            v1 = tuple(km[m1][t] for t in test_ids)
            v2 = tuple(km[m2][t] for t in test_ids)
            assert v1 == v2, f"Dyn-equiv {m1},{m2} differ"

    def test_pairs_are_killable(self):
        r = _load_report()
        km = r["kill_matrix"]
        for m1, m2 in r["dynamic_equivalences"]:
            assert any(v == 1 for v in km[m1].values()), f"{m1} not killable"
            assert any(v == 1 for v in km[m2].values()), f"{m2} not killable"


# --------------------------------------------------------- minimal test set
class TestMinimalTestSet:

    def test_covers_all_killable(self):
        r = _load_report()
        km = r["kill_matrix"]
        min_tests = r["minimal_test_set"]
        killable = {mid for mid, row in km.items()
                    if any(v == 1 for v in row.values())}
        covered = set()
        for t in min_tests:
            for mid in killable:
                if km[mid].get(t, 0) == 1:
                    covered.add(mid)
        assert covered == killable, (
            f"Minimal test set misses {len(killable - covered)} mutants"
        )

    def test_irredundant(self):
        """Removing any single test must leave at least one mutant uncovered."""
        r = _load_report()
        km = r["kill_matrix"]
        min_tests = r["minimal_test_set"]
        killable = {mid for mid, row in km.items()
                    if any(v == 1 for v in row.values())}
        for drop in min_tests:
            reduced = [t for t in min_tests if t != drop]
            covered = set()
            for t in reduced:
                for mid in killable:
                    if km[mid].get(t, 0) == 1:
                        covered.add(mid)
            assert covered != killable, f"Test {drop} is redundant"


# ---------------------------------------------------------- operator stats
class TestOperatorStats:

    def test_counts_match_mutant_list(self):
        r = _load_report()
        counts = Counter(m["operator"] for m in r["mutants"])
        stats = r["operator_stats"]
        for op, cnt in counts.items():
            assert op in stats, f"Operator {op} missing from stats"
            assert stats[op]["count"] == cnt, (
                f"{op}: count {stats[op]['count']} != {cnt}"
            )

    def test_killed_survived_sum(self):
        stats = _load_report()["operator_stats"]
        for op, s in stats.items():
            assert s["killed"] + s["survived"] == s["count"], (
                f"{op}: killed+survived != count"
            )

    def test_score_correct(self):
        stats = _load_report()["operator_stats"]
        for op, s in stats.items():
            expected = s["killed"] / s["count"] if s["count"] > 0 else 0.0
            assert abs(s["score"] - expected) < 0.002, (
                f"{op}: score {s['score']} != {expected}"
            )


# ------------------------------------------------------------ spot checks
class TestSpotChecks:

    def test_aor_plus_to_minus_in_bsearch_killed(self):
        """AOR: + -> - in binary_search must be killed."""
        r = _load_report()
        found = any(
            m["operator"] == "AOR"
            and m["function"] == "binary_search"
            and m["original"] == "+"
            and m["replacement"] == "-"
            and m["status"] == "killed"
            for m in r["mutants"]
        )
        assert found, "No killed AOR +->- mutant in binary_search"

    def test_ror_neq_to_eq_in_gcd_killed(self):
        """ROR: != -> == in gcd must be killed."""
        r = _load_report()
        found = any(
            m["operator"] == "ROR"
            and m["function"] == "gcd"
            and m["original"] == "!="
            and m["replacement"] == "=="
            and m["status"] == "killed"
            for m in r["mutants"]
        )
        assert found, "No killed ROR !=->== mutant in gcd"

    def test_equivalent_mutant_survives(self):
        """
        The ROR mutant replacing < with <= in binary_search's
        'elif arr[mid] < target' is equivalent and must survive.
        Verify independently by running the mutant.
        """
        with open(SOURCE_PATH) as f:
            source = f.read()

        lines = source.split('\n')
        mutated_lines = []
        applied = False
        for line in lines:
            if ('elif' in line and 'arr[mid] < target' in line
                    and not applied):
                mutated_lines.append(
                    line.replace('< target', '<= target', 1))
                applied = True
            else:
                mutated_lines.append(line)
        assert applied, "Could not locate elif line to mutate"

        mutated_source = '\n'.join(mutated_lines)
        backup = SOURCE_PATH + ".spotbak"
        shutil.copy2(SOURCE_PATH, backup)
        try:
            with open(SOURCE_PATH, 'w') as f:
                f.write(mutated_source)
            result = subprocess.run(
                ["python3", "-m", "pytest", TEST_DIR, "--tb=no", "-q"],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                cwd="/app",
            )
            assert result.returncode == 0, (
                "Equivalent mutant (< -> <= in elif) should survive"
            )
        finally:
            shutil.copy2(backup, SOURCE_PATH)
            os.remove(backup)

    def test_source_file_intact(self):
        """Original source must not be corrupted by the analyzer."""
        with open(SOURCE_PATH) as f:
            src = f.read()
        assert "def binary_search" in src
        assert "def gcd" in src
        assert "def is_prime" in src
        assert "def nth_fibonacci" in src
