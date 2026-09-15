#!/usr/bin/env python3
"""Tests for ISPD 2026 scoring pipeline leaderboard."""

import json
import os
import pytest

LEADERBOARD = "/app/leaderboard.json"

# Pre-computed expected scores (see scoring methodology in docs)
EXPECTED_RANKING = ["team_alpha", "team_beta", "team_gamma", "team_delta"]

# Expected per-design scores (rounded to 2 dp)
# team_alpha: aes=39.22, jpeg=32.94, total=72.16
# team_beta: aes=34.63, jpeg=0.00 (equiv fail), total=34.63
# team_gamma: aes=0.00 (placement fail), jpeg=30.89, total=30.89
# team_delta: aes=3.87, jpeg=6.50, total=10.37
EXPECTED = {
    "team_alpha": {"aes_cipher_top": 39.22, "jpeg_encoder": 32.94, "total": 72.16},
    "team_beta": {"aes_cipher_top": 34.63, "jpeg_encoder": 0.00, "total": 34.63},
    "team_gamma": {"aes_cipher_top": 0.00, "jpeg_encoder": 30.89, "total": 30.89},
    "team_delta": {"aes_cipher_top": 3.87, "jpeg_encoder": 6.50, "total": 10.37},
}

SCORE_TOLERANCE = 0.5


class TestLeaderboardExists:
    def test_file_exists(self):
        assert os.path.exists(LEADERBOARD), f"Leaderboard not found at {LEADERBOARD}"

    def test_valid_json(self):
        with open(LEADERBOARD) as f:
            data = json.load(f)
        assert "rankings" in data, "Missing 'rankings' key in leaderboard JSON"

    def test_rankings_is_list(self):
        with open(LEADERBOARD) as f:
            data = json.load(f)
        assert isinstance(data["rankings"], list), "'rankings' must be a list"


class TestLeaderboardStructure:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(LEADERBOARD) as f:
            self.data = json.load(f)
        self.rankings = self.data["rankings"]

    def test_four_teams(self):
        assert len(self.rankings) == 4, f"Expected 4 teams, got {len(self.rankings)}"

    def test_required_fields(self):
        for entry in self.rankings:
            for field in ["rank", "team", "total_score", "aes_cipher_top", "jpeg_encoder"]:
                assert field in entry, f"Missing field '{field}' in ranking entry {entry}"

    def test_ranks_sequential(self):
        ranks = [r["rank"] for r in self.rankings]
        assert ranks == [1, 2, 3, 4], f"Ranks should be [1,2,3,4], got {ranks}"

    def test_all_teams_present(self):
        teams = sorted([r["team"] for r in self.rankings])
        expected = sorted(EXPECTED_RANKING)
        assert teams == expected, f"Expected teams {expected}, got {teams}"


class TestRankingOrder:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(LEADERBOARD) as f:
            self.data = json.load(f)
        self.rankings = self.data["rankings"]
        self.by_team = {r["team"]: r for r in self.rankings}

    def test_ranking_order(self):
        team_order = [r["team"] for r in self.rankings]
        assert team_order == EXPECTED_RANKING, (
            f"Expected ranking order {EXPECTED_RANKING}, got {team_order}"
        )

    def test_scores_descending(self):
        scores = [r["total_score"] for r in self.rankings]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Scores not descending: {scores[i]} < {scores[i+1]} "
                f"at positions {i} and {i+1}"
            )


class TestHardConstraints:
    """Verify that hard constraint violations produce score 0."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open(LEADERBOARD) as f:
            self.data = json.load(f)
        self.by_team = {r["team"]: r for r in self.data["rankings"]}

    def test_team_beta_jpeg_zero(self):
        """team_beta jpeg_encoder should be 0 due to equivalence failure."""
        score = self.by_team["team_beta"]["jpeg_encoder"]
        assert abs(score) < 0.1, (
            f"team_beta jpeg_encoder should be 0 (equiv fail), got {score}"
        )

    def test_team_gamma_aes_zero(self):
        """team_gamma aes_cipher_top should be 0 due to placement illegality."""
        score = self.by_team["team_gamma"]["aes_cipher_top"]
        assert abs(score) < 0.1, (
            f"team_gamma aes_cipher_top should be 0 (placement fail), got {score}"
        )

    def test_team_alpha_aes_nonzero(self):
        """team_alpha aes should have a positive score (no constraint violations)."""
        score = self.by_team["team_alpha"]["aes_cipher_top"]
        assert score > 10.0, (
            f"team_alpha aes_cipher_top should be >10, got {score}"
        )


class TestPerDesignScores:
    """Verify individual design scores are correct."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open(LEADERBOARD) as f:
            self.data = json.load(f)
        self.by_team = {r["team"]: r for r in self.data["rankings"]}

    def test_team_alpha_aes(self):
        actual = self.by_team["team_alpha"]["aes_cipher_top"]
        expected = EXPECTED["team_alpha"]["aes_cipher_top"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_alpha aes: expected ~{expected}, got {actual}"
        )

    def test_team_alpha_jpeg(self):
        actual = self.by_team["team_alpha"]["jpeg_encoder"]
        expected = EXPECTED["team_alpha"]["jpeg_encoder"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_alpha jpeg: expected ~{expected}, got {actual}"
        )

    def test_team_beta_aes(self):
        actual = self.by_team["team_beta"]["aes_cipher_top"]
        expected = EXPECTED["team_beta"]["aes_cipher_top"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_beta aes: expected ~{expected}, got {actual}"
        )

    def test_team_gamma_jpeg(self):
        actual = self.by_team["team_gamma"]["jpeg_encoder"]
        expected = EXPECTED["team_gamma"]["jpeg_encoder"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_gamma jpeg: expected ~{expected}, got {actual}"
        )

    def test_team_delta_aes(self):
        actual = self.by_team["team_delta"]["aes_cipher_top"]
        expected = EXPECTED["team_delta"]["aes_cipher_top"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_delta aes: expected ~{expected}, got {actual}"
        )

    def test_team_delta_jpeg(self):
        actual = self.by_team["team_delta"]["jpeg_encoder"]
        expected = EXPECTED["team_delta"]["jpeg_encoder"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_delta jpeg: expected ~{expected}, got {actual}"
        )


class TestTotalScores:
    """Verify total scores are correct sums."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open(LEADERBOARD) as f:
            self.data = json.load(f)
        self.by_team = {r["team"]: r for r in self.data["rankings"]}

    def test_team_alpha_total(self):
        actual = self.by_team["team_alpha"]["total_score"]
        expected = EXPECTED["team_alpha"]["total"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_alpha total: expected ~{expected}, got {actual}"
        )

    def test_team_beta_total(self):
        actual = self.by_team["team_beta"]["total_score"]
        expected = EXPECTED["team_beta"]["total"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_beta total: expected ~{expected}, got {actual}"
        )

    def test_team_gamma_total(self):
        actual = self.by_team["team_gamma"]["total_score"]
        expected = EXPECTED["team_gamma"]["total"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_gamma total: expected ~{expected}, got {actual}"
        )

    def test_team_delta_total(self):
        actual = self.by_team["team_delta"]["total_score"]
        expected = EXPECTED["team_delta"]["total"]
        assert abs(actual - expected) < SCORE_TOLERANCE, (
            f"team_delta total: expected ~{expected}, got {actual}"
        )

    def test_totals_are_sums(self):
        """Total score should be sum of per-design scores."""
        for entry in self.data["rankings"]:
            total = entry["total_score"]
            design_sum = entry["aes_cipher_top"] + entry["jpeg_encoder"]
            assert abs(total - design_sum) < 0.05, (
                f"{entry['team']}: total_score ({total}) != "
                f"aes ({entry['aes_cipher_top']}) + jpeg ({entry['jpeg_encoder']}) "
                f"= {design_sum}"
            )
