
"""
Verification tests for the election cryptosystem audit & remediation task.
Checks tally, individual votes, and patch security verdicts.
"""

import json
import os
import pytest


EXPECTED_TALLY = {
    "Aster": 7,
    "Bloom": 9,
    "Cedar": 6,
    "Dahlia": 8,
}

EXPECTED_VOTES = {
    "V001": "Bloom",
    "V002": "Dahlia",
    "V003": "Aster",
    "V004": "Cedar",
    "V005": "Bloom",
    "V006": "Dahlia",
    "V007": "Aster",
    "V008": "Bloom",
    "V009": "Cedar",
    "V010": "Dahlia",
    "V011": "Bloom",
    "V012": "Aster",
    "V013": "Cedar",
    "V014": "Dahlia",
    "V015": "Bloom",
    "V016": "Aster",
    "V017": "Bloom",
    "V018": "Cedar",
    "V019": "Dahlia",
    "V020": "Aster",
    "V021": "Cedar",
    "V022": "Bloom",
    "V023": "Dahlia",
    "V024": "Aster",
    "V025": "Bloom",
    "V026": "Bloom",
    "V027": "Dahlia",
    "V028": "Cedar",
    "V029": "Aster",
    "V030": "Dahlia",
}

EXPECTED_PATCH_VERDICTS = {
    "A": "SECURE",
    "B": "VULNERABLE",
    "C": "SECURE",
    "D": "SECURE",
    "E": "VULNERABLE",
}


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), \
            "results.json not found at /app/results.json"

    def test_results_valid_json(self):
        data = load_results()
        assert isinstance(data, dict), "results.json must be a JSON object"

    def test_has_tally_key(self):
        data = load_results()
        assert "tally" in data, "results.json must contain a 'tally' key"

    def test_has_votes_key(self):
        data = load_results()
        assert "votes" in data, "results.json must contain a 'votes' key"

    def test_has_patch_assessment_key(self):
        data = load_results()
        assert "patch_assessment" in data, \
            "results.json must contain a 'patch_assessment' key"


class TestTally:
    def test_tally_candidate_count(self):
        tally = load_results()["tally"]
        assert len(tally) == 4, f"Expected 4 candidates in tally, got {len(tally)}"

    def test_total_votes(self):
        tally = load_results()["tally"]
        total = sum(tally.values())
        assert total == 30, f"Total votes should be 30, got {total}"

    @pytest.mark.parametrize("candidate,expected_count",
                             list(EXPECTED_TALLY.items()))
    def test_candidate_tally(self, candidate, expected_count):
        tally = load_results()["tally"]
        actual = tally.get(candidate)
        assert actual == expected_count, \
            f"Tally for {candidate}: expected {expected_count}, got {actual}"


class TestIndividualVotes:
    def test_all_voters_present(self):
        votes = load_results()["votes"]
        for vid in EXPECTED_VOTES:
            assert vid in votes, f"Missing vote for voter {vid}"

    def test_no_extra_voters(self):
        votes = load_results()["votes"]
        extra = set(votes.keys()) - set(EXPECTED_VOTES.keys())
        assert len(extra) == 0, f"Unexpected voters in results: {extra}"

    @pytest.mark.parametrize("voter_id,expected_candidate",
                             list(EXPECTED_VOTES.items()))
    def test_individual_vote(self, voter_id, expected_candidate):
        votes = load_results()["votes"]
        actual = votes.get(voter_id)
        assert actual == expected_candidate, \
            f"Vote for {voter_id}: expected '{expected_candidate}', got '{actual}'"


class TestBatchCorrectness:
    def test_batch_alpha_all_correct(self):
        """Verify all 10 votes from batch alpha (shared-factor keys)."""
        votes = load_results()["votes"]
        for i in range(1, 11):
            vid = f"V{i:03d}"
            assert votes.get(vid) == EXPECTED_VOTES[vid], \
                f"Batch alpha {vid}: expected {EXPECTED_VOTES[vid]}, " \
                f"got {votes.get(vid)}"

    def test_batch_beta_all_correct(self):
        """Verify all 10 votes from batch beta (seeded-PRNG keys)."""
        votes = load_results()["votes"]
        for i in range(11, 21):
            vid = f"V{i:03d}"
            assert votes.get(vid) == EXPECTED_VOTES[vid], \
                f"Batch beta {vid}: expected {EXPECTED_VOTES[vid]}, " \
                f"got {votes.get(vid)}"

    def test_batch_gamma_all_correct(self):
        """Verify all 10 votes from batch gamma (adjacent-prime keys)."""
        votes = load_results()["votes"]
        for i in range(21, 31):
            vid = f"V{i:03d}"
            assert votes.get(vid) == EXPECTED_VOTES[vid], \
                f"Batch gamma {vid}: expected {EXPECTED_VOTES[vid]}, " \
                f"got {votes.get(vid)}"


class TestPatchAssessment:
    def test_all_patches_present(self):
        pa = load_results()["patch_assessment"]
        for name in EXPECTED_PATCH_VERDICTS:
            assert name in pa, f"Missing assessment for patch {name}"

    def test_no_extra_patches(self):
        pa = load_results()["patch_assessment"]
        extra = set(pa.keys()) - set(EXPECTED_PATCH_VERDICTS.keys())
        assert len(extra) == 0, f"Unexpected patches in assessment: {extra}"

    @pytest.mark.parametrize("patch,expected_verdict",
                             list(EXPECTED_PATCH_VERDICTS.items()))
    def test_patch_verdict(self, patch, expected_verdict):
        pa = load_results()["patch_assessment"]
        actual = pa.get(patch)
        assert actual == expected_verdict, \
            f"Patch {patch}: expected '{expected_verdict}', got '{actual}'"
