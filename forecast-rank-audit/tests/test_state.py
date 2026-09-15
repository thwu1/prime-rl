#!/usr/bin/env python3
"""Tests for the prediction market scoring pipeline forensic audit."""

import json
import os
import sqlite3
import math
import pytest
from collections import defaultdict

RESULTS_DIR = "/app/results"
DB_PATH = "/app/data/platform.db"

# Known ground truth
LATE_FORECASTER = "oscar_oracle"
LATE_PROBLEM_IDS = {3, 7, 15, 22, 31, 38, 44, 48}
SYBIL_PAIR = {"foxtrot_fox", "shadow_fox"}
STALE_ODDS_PROBLEMS = {8, 17, 29, 36, 42}
BUGGY_FORECASTERS = {
    "kilo_keen", "lima_logic", "mike_maven", "november_node",
    "oscar_oracle", "shadow_fox", "papa_prime", "quebec_quant",
    "romeo_rank", "sierra_stats"
}
SKILLED_FORECASTERS = {"ace_alpha", "bravo_brain", "charlie_calc", "delta_data", "echo_edge"}


def load_result(filename):
    path = os.path.join(RESULTS_DIR, filename)
    assert os.path.exists(path), "Missing result file: {}".format(filename)
    with open(path) as f:
        return json.load(f)


def flatten_json(obj):
    """Recursively flatten a JSON structure into a lowercase string for keyword search."""
    if isinstance(obj, str):
        return obj.lower()
    if isinstance(obj, (int, float, bool)):
        return str(obj).lower()
    if isinstance(obj, list):
        return " ".join(flatten_json(item) for item in obj)
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            parts.append(k.lower())
            parts.append(flatten_json(v))
        return " ".join(parts)
    return ""


# ── File existence ───────────────────────────────────────────────────────

class TestFileExistence:
    @pytest.mark.parametrize("filename", [
        "data_issues.json",
        "corrected_rankings.json",
        "platform_bugs.json",
        "irt_analysis.json",
        "robustness.json",
    ])
    def test_file_exists(self, filename):
        path = os.path.join(RESULTS_DIR, filename)
        assert os.path.exists(path), "Missing: {}".format(filename)


# ── Data issues discovery ────────────────────────────────────────────────

class TestDataIssues:
    def test_is_nonempty_list(self):
        data = load_result("data_issues.json")
        assert isinstance(data, list), "data_issues.json must be a list"
        assert len(data) >= 3, "Expected at least 3 issues, got {}".format(len(data))

    def test_late_submissions_discovered(self):
        """Agent must discover predictions submitted after problem resolution."""
        data = load_result("data_issues.json")
        text = flatten_json(data)
        assert "oscar" in text, (
            "data_issues must mention oscar_oracle for late/post-resolution submissions"
        )
        late_keywords = [
            "late", "after", "timestamp", "post", "resolution",
            "cheat", "look-ahead", "lookahead", "submitted_at",
            "hindsight", "future", "invalid", "tainted", "before",
            "temporal", "time", "19:30",
        ]
        assert any(kw in text for kw in late_keywords), (
            "data_issues must describe the late submission issue"
        )

    def test_sybil_pair_discovered(self):
        """Agent must discover the sybil/duplicate account pair."""
        data = load_result("data_issues.json")
        text = flatten_json(data)
        assert "foxtrot_fox" in text or "shadow_fox" in text, (
            "data_issues must mention foxtrot_fox or shadow_fox"
        )
        sybil_keywords = [
            "sybil", "duplicate", "clone", "identical", "similar",
            "copy", "collu", "sock", "same", "correl", "cosine",
            "pair", "match", "near",
        ]
        assert any(kw in text for kw in sybil_keywords), (
            "data_issues must describe the sybil/duplicate detection"
        )

    def test_stale_odds_discovered(self):
        """Agent must discover stale market odds by cross-referencing Parquet feed."""
        data = load_result("data_issues.json")
        text = flatten_json(data)
        stale_keywords = [
            "stale", "cached", "outdated", "mismatch", "differ",
            "discrepan", "feed", "parquet", "market", "odds", "price",
            "tick", "closing", "exchange",
        ]
        assert any(kw in text for kw in stale_keywords), (
            "data_issues must describe the stale market odds discrepancy "
            "found by cross-referencing Parquet feed with SQLite"
        )

    def test_stale_problems_identified(self):
        """Agent should identify at least some of the stale-odds problem IDs."""
        data = load_result("data_issues.json")
        text = flatten_json(data)
        found = sum(1 for p in STALE_ODDS_PROBLEMS if str(p) in text)
        assert found >= 3, (
            "Expected >= 3 of stale problems {} identified, found {}".format(
                sorted(STALE_ODDS_PROBLEMS), found)
        )

    def test_late_count_reasonable(self):
        """Agent should find approximately 8 late submissions."""
        data = load_result("data_issues.json")
        text = flatten_json(data)
        assert "oscar" in text


# ── Corrected rankings ──────────────────────────────────────────────────

class TestCorrectedRankings:
    def test_structure(self):
        data = load_result("corrected_rankings.json")
        assert isinstance(data, list), "corrected_rankings must be a list"
        assert len(data) >= 10, "Expected >= 10 forecasters, got {}".format(len(data))
        for entry in data:
            assert "username" in entry, "Entry missing 'username'"
            assert "final_rank" in entry, "Entry missing 'final_rank'"

    def test_multiple_scoring_methods(self):
        """Agent must use at least 3 scoring/ranking methods (2 proper rules + IRT)."""
        data = load_result("corrected_rankings.json")
        assert len(data) > 0, "corrected_rankings is empty"
        entry = data[0]
        score_fields = [
            k for k, v in entry.items()
            if k not in ("username", "final_rank", "rank") and isinstance(v, (int, float))
        ]
        assert len(score_fields) >= 3, (
            "Expected >= 3 scoring fields (2 proper rules + IRT), found: {}".format(
                score_fields)
        )

    def test_skilled_forecasters_ranked_high(self):
        """Genuinely skilled forecasters should appear near the top."""
        data = load_result("corrected_rankings.json")
        top5 = {e["username"] for e in data if e["final_rank"] <= 5}
        overlap = top5 & SKILLED_FORECASTERS
        assert len(overlap) >= 2, (
            "Expected >= 2 skilled forecasters in top 5, got {}. Top 5: {}".format(
                overlap, top5)
        )

    def test_ranks_are_valid(self):
        data = load_result("corrected_rankings.json")
        ranks = sorted(e["final_rank"] for e in data)
        assert ranks[0] == 1, "Minimum rank should be 1"
        assert len(ranks) == len(set(ranks)), "Ranks must be unique"

    def test_weak_forecasters_ranked_low(self):
        """Weak forecasters should not appear in top 5."""
        data = load_result("corrected_rankings.json")
        top5 = {e["username"] for e in data if e["final_rank"] <= 5}
        weak = {"mike_maven", "november_node", "sierra_stats", "lima_logic"}
        overlap = top5 & weak
        assert len(overlap) == 0, (
            "Weak forecasters should not be in top 5, found: {}".format(overlap)
        )


# ── Platform bugs ────────────────────────────────────────────────────────

class TestPlatformBugs:
    def test_structure(self):
        data = load_result("platform_bugs.json")
        assert isinstance(data, list), "platform_bugs must be a list"
        assert len(data) >= 2, "Expected at least 2 platform bugs identified"

    def test_scoring_inconsistency_found(self):
        """Agent must identify the Brier scoring formula inconsistency."""
        data = load_result("platform_bugs.json")
        text = flatten_json(data)
        scoring_keywords = [
            "scor", "brier", "formula", "inconsisten", "different",
            "half", "class", "bug", "error", "incorrect", "wrong",
            "mismatch", "discrepan", "comput", "factor", "ratio",
            "single", "partial", "batch",
        ]
        assert any(kw in text for kw in scoring_keywords), (
            "platform_bugs must identify a scoring inconsistency"
        )

    def test_affected_forecasters_identified(self):
        """Agent should identify at least some affected forecasters."""
        data = load_result("platform_bugs.json")
        text = flatten_json(data)
        found = sum(1 for f in BUGGY_FORECASTERS if f in text)
        assert found >= 3, (
            "Expected >= 3 of {} mentioned in platform_bugs, found {}".format(
                BUGGY_FORECASTERS, found)
        )

    def test_irt_link_function_bug_found(self):
        """Agent must identify the IRT probit vs logit link function error."""
        data = load_result("platform_bugs.json")
        text = flatten_json(data)
        irt_keywords = [
            "irt", "probit", "logit", "link", "logistic", "normal",
            "item response", "2pl", "2-pl", "ability", "abilit",
            "compres", "scale", "distort",
        ]
        assert any(kw in text for kw in irt_keywords), (
            "platform_bugs must identify the IRT link function error "
            "(probit used instead of logit)"
        )

    def test_oscar_mentioned_in_bugs_or_issues(self):
        """oscar_oracle's tainted data should surface in bugs or issues."""
        bugs_text = flatten_json(load_result("platform_bugs.json"))
        issues_text = flatten_json(load_result("data_issues.json"))
        combined = bugs_text + " " + issues_text
        assert "oscar" in combined, (
            "oscar_oracle must be mentioned in platform_bugs or data_issues"
        )


# ── IRT analysis ─────────────────────────────────────────────────────────

class TestIRTAnalysis:
    def test_structure(self):
        data = load_result("irt_analysis.json")
        assert isinstance(data, dict), "irt_analysis.json must be a dict"
        assert "item_parameters" in data, "irt_analysis must contain 'item_parameters'"
        assert "abilities" in data, "irt_analysis must contain 'abilities'"

    def test_item_parameters(self):
        data = load_result("irt_analysis.json")
        items = data["item_parameters"]
        assert isinstance(items, list), "item_parameters must be a list"
        assert len(items) >= 40, "Expected >= 40 item parameters, got {}".format(len(items))
        for item in items:
            assert "problem_id" in item, "Item param missing 'problem_id'"
            assert "difficulty" in item, "Item param missing 'difficulty'"
            assert "discrimination" in item, "Item param missing 'discrimination'"

    def test_abilities(self):
        data = load_result("irt_analysis.json")
        abilities = data["abilities"]
        assert isinstance(abilities, list), "abilities must be a list"
        assert len(abilities) >= 15, "Expected >= 15 abilities, got {}".format(len(abilities))
        for ab in abilities:
            assert "username" in ab, "Ability entry missing 'username'"
            assert "ability" in ab, "Ability entry missing 'ability'"

    def test_abilities_wider_than_published(self):
        """Re-estimated abilities (logit) should have wider range than published (probit)."""
        data = load_result("irt_analysis.json")
        abilities = {a["username"]: a["ability"] for a in data["abilities"]}

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT f.username, ia.ability
            FROM irt_abilities ia
            JOIN forecasters f ON ia.forecaster_id = f.id
        """)
        published = dict(cur.fetchall())
        conn.close()

        common = set(abilities.keys()) & set(published.keys())
        if len(common) >= 5:
            agent_range = max(abilities[u] for u in common) - min(abilities[u] for u in common)
            pub_range = max(published[u] for u in common) - min(published[u] for u in common)
            assert agent_range > pub_range * 1.2, (
                "Re-estimated abilities should have wider range than probit estimates. "
                "Agent range: {:.3f}, Published range: {:.3f}".format(agent_range, pub_range)
            )

    def test_published_comparison_present(self):
        data = load_result("irt_analysis.json")
        assert "published_comparison" in data, (
            "irt_analysis must contain 'published_comparison' "
            "describing discrepancy with published values"
        )
        pc = data["published_comparison"]
        text = flatten_json(pc)
        assert len(text) > 20, "published_comparison should contain substantive description"


# ── Robustness analysis ─────────────────────────────────────────────────

class TestRobustness:
    def test_is_dict(self):
        data = load_result("robustness.json")
        assert isinstance(data, dict), "robustness.json must be a dict"

    def test_rank_variance_present(self):
        data = load_result("robustness.json")
        assert "rank_variance" in data, "robustness must contain 'rank_variance'"
        rv = data["rank_variance"]
        assert isinstance(rv, dict), "rank_variance must be a dict mapping username->variance"
        assert len(rv) >= 10, "rank_variance should cover >= 10 forecasters"

    def test_rank_variance_nonnegative(self):
        data = load_result("robustness.json")
        rv = data["rank_variance"]
        for u, v in rv.items():
            assert isinstance(v, (int, float)), "variance for {} must be numeric".format(u)
            assert v >= 0, "variance for {} must be non-negative, got {}".format(u, v)

    def test_sensitive_forecasters_present(self):
        data = load_result("robustness.json")
        assert "sensitive_forecasters" in data, "robustness must contain 'sensitive_forecasters'"
        sf = data["sensitive_forecasters"]
        assert isinstance(sf, list), "sensitive_forecasters must be a list"
        assert len(sf) >= 1, "Expected at least 1 sensitive forecaster"

    def test_sensitive_above_median(self):
        """Sensitive forecasters should have above-median rank variance."""
        data = load_result("robustness.json")
        rv = data["rank_variance"]
        sf = set(data["sensitive_forecasters"])
        if len(rv) < 2:
            return
        values = sorted(rv.values())
        median = values[len(values) // 2]
        for u in sf:
            if u in rv:
                assert rv[u] >= median * 0.9, (
                    "{} marked sensitive but variance {} < median {}".format(u, rv[u], median)
                )


# ── Cross-validation against independently computed scores ──────────────

class TestCrossValidation:
    @staticmethod
    def _compute_clean_brier():
        """Independently compute correct full Brier scores from clean data."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT f.username, p.probs, pr.correct_option_idx
            FROM predictions p
            JOIN forecasters f ON p.forecaster_id = f.id
            JOIN problems pr ON p.problem_id = pr.id
            WHERE p.submitted_at <= pr.resolved_at
        """)
        rows = cur.fetchall()
        conn.close()

        user_scores = defaultdict(list)
        for uname, probs_str, correct in rows:
            probs = json.loads(probs_str)
            brier = sum(
                (probs[j] - (1 if j == correct else 0)) ** 2
                for j in range(len(probs))
            )
            user_scores[uname].append(brier)

        return {u: sum(s) / len(s) for u, s in user_scores.items()}

    def test_top_match_independent_brier(self):
        """Agent's top 5 should overlap with independently computed Brier top 5."""
        clean_brier = self._compute_clean_brier()
        brier_ranked = sorted(clean_brier.items(), key=lambda x: x[1])
        expected_top5 = {u for u, _ in brier_ranked[:5]}

        data = load_result("corrected_rankings.json")
        agent_top5 = {e["username"] for e in data if e["final_rank"] <= 5}

        overlap = agent_top5 & expected_top5
        assert len(overlap) >= 2, (
            "Agent top 5 ({}) must overlap with Brier top 5 ({}) by >= 2".format(
                agent_top5, expected_top5)
        )

    def test_published_rankings_genuinely_buggy(self):
        """Sanity check: published rankings actually differ from correct computation."""
        clean_brier = self._compute_clean_brier()

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT f.username, f.id, p.probs, pr.correct_option_idx
            FROM predictions p
            JOIN forecasters f ON p.forecaster_id = f.id
            JOIN problems pr ON p.problem_id = pr.id
        """)
        rows = cur.fetchall()

        user_scores_all = defaultdict(list)
        for uname, fid, probs_str, correct in rows:
            probs = json.loads(probs_str)
            brier = sum(
                (probs[j] - (1 if j == correct else 0)) ** 2
                for j in range(len(probs))
            )
            user_scores_all[uname].append(brier)
        correct_all = {u: sum(s) / len(s) for u, s in user_scores_all.items()}

        cur.execute("SELECT username, score FROM published_rankings WHERE method = 'brier'")
        published = dict(cur.fetchall())
        conn.close()

        discrepancies = 0
        for u in correct_all:
            if u in published and abs(correct_all[u] - published[u]) > 0.01:
                discrepancies += 1

        assert discrepancies >= 5, (
            "Sanity: expected >= 5 forecasters with score discrepancies, found {}".format(
                discrepancies)
        )

    def test_bottom_forecasters_are_weak(self):
        """The lowest-ranked forecasters should be genuinely weak."""
        data = load_result("corrected_rankings.json")
        n = len(data)
        bottom3 = {e["username"] for e in data if e["final_rank"] >= n - 2}
        weak = {"mike_maven", "november_node", "omega_outsider", "sierra_stats",
                "lima_logic", "kilo_keen"}
        overlap = bottom3 & weak
        assert len(overlap) >= 1, (
            "At least 1 weak forecaster should be in bottom 3, got {}".format(bottom3)
        )

    def test_parquet_stale_odds_sanity(self):
        """Sanity: Parquet closing prices differ from SQLite for stale problems."""
        try:
            import pyarrow.parquet as pq
        except ImportError:
            pytest.skip("pyarrow not available")

        table = pq.read_table("/app/data/market_feed/market_ticks.parquet")
        feed = table.to_pydict()

        closing_prices = {}
        for i in range(len(feed["problem_id"])):
            if feed["hours_before_close"][i] == 0:
                closing_prices[feed["problem_id"][i]] = feed["mid_price"][i]

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, market_odds FROM problems")
        sqlite_odds = {}
        for pid, odds_str in cur.fetchall():
            sqlite_odds[pid] = json.loads(odds_str)[0]
        conn.close()

        discrepancies = 0
        for pid in STALE_ODDS_PROBLEMS:
            if pid in closing_prices and pid in sqlite_odds:
                if abs(closing_prices[pid] - sqlite_odds[pid]) > 0.05:
                    discrepancies += 1

        assert discrepancies >= 3, (
            "Expected >= 3 stale odds discrepancies in Parquet vs SQLite, found {}".format(
                discrepancies)
        )
