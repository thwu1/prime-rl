
"""
Tests for pencil puzzle solution recovery pipeline.
Verifies results.json against pre-computed SHA-256 hashes of the correct
move sequences extracted from ppbench's encrypted bundled dataset.
"""

import hashlib
import json
import os

import pytest

RESULTS_PATH = "/app/results.json"
TARGETS_PATH = "/app/targets.json"

# SHA-256 hashes of json.dumps(moves, separators=(',', ':')) for each target
# puzzle's correct solution (moves_full from decrypted golden_30 dataset).
EXPECTED = {
    "http://puzz.link/p?akari/10/10/..g.lbh52bhbh.g6..g.o.6.h6..o6.67.j.j15.j.l.g0./": {
        "pid": "lightup",
        "num_moves": 68,
        "hash": "79f4e0575c200b41f4d5acd64e1b39a54ca99a7cf03b86bcc23f98ee560c20d2",
    },
    "http://puzz.link/p?akari/10/10/hcl.l.j.hb.hchbkclek.j.ha.hch.l.n.h": {
        "pid": "lightup",
        "num_moves": 82,
        "hash": "38ea045d093b743963ecf0bb29088e3a3637237858210230f8f270e2a7df273e",
    },
    "http://puzz.link/p?lits/10/10/00281g00000000304g0s0o0400vv00004030": {
        "pid": "lits",
        "num_moves": 100,
        "hash": "1c39ee7834750182269f5fba36387c5b6db17b86de6ce64ba33aa594ddc63996",
    },
    "http://puzz.link/p?lits/10/10/21274v3u7vnuv1s0i0fu7s3o0098082p7sfu": {
        "pid": "lits",
        "num_moves": 100,
        "hash": "53d4d316895e62c1d99a292dbf72e0ff2c70eb3f8ca654e8fa1f2116315e52ad",
    },
    "https://puzz.link/p?sashigane/5/5/n..k.v.k.l": {
        "pid": "sashigane",
        "num_moves": 40,
        "hash": "c035cd25a050e52ba7c16c47cfee942fecda29efb25ba4342f54878d7131aaec",
    },
    "https://puzz.link/p?sashigane/8/8/q.gm3m.l3.nhu..l..l4n.mhs": {
        "pid": "sashigane",
        "num_moves": 112,
        "hash": "5b6deadea0ea4206936e353b45added234bc95fffbd491e504b833ec8e20ae48",
    },
    "https://puzz.link/p?yajilin/7/7/c30m32a33k31a12m41a": {
        "pid": "yajilin",
        "num_moves": 83,
        "hash": "42d6137a4bf23060511ea43be1fbeb580a0ae3bc63ad80ded710ffb8869b1c3e",
    },
    "http://puzz.link/p?yajilin/8/8/42j23e22zi13j": {
        "pid": "yajilin",
        "num_moves": 126,
        "hash": "8d52d662b494692898835f3f35a29d8c252eacabe7c2ec73fee96746091dd889",
    },
}


def _compute_moves_hash(moves):
    """Compute SHA-256 hash of compact JSON serialization of moves list."""
    moves_str = json.dumps(moves, separators=(",", ":"))
    return hashlib.sha256(moves_str.encode()).hexdigest()


def _verify_result(result):
    """Check if a result entry's moves match the expected hash."""
    url = result.get("puzzlink_url", "")
    if url not in EXPECTED:
        return False
    if not result.get("moves"):
        return False
    return _compute_moves_hash(result["moves"]) == EXPECTED[url]["hash"]


@pytest.fixture(scope="module")
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def targets():
    with open(TARGETS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def verified(results):
    """Map of URL -> bool indicating whether moves match expected hash."""
    out = {}
    for r in results:
        out[r["puzzlink_url"]] = _verify_result(r)
    return out


# -- basic file / schema checks ----------------------------------------------


class TestResultsFile:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), (
            "results.json not found. Run the pipeline first: "
            "cd /app && python3 pipeline.py"
        )

    def test_results_valid_json(self, results):
        assert isinstance(results, list), "results.json must be a JSON array"
        assert len(results) >= 8, (
            f"results.json has {len(results)} entries, expected >= 8"
        )

    def test_all_targets_present(self, targets, results):
        result_urls = {r["puzzlink_url"] for r in results}
        for t in targets:
            assert t["puzzlink_url"] in result_urls, (
                f"Missing result for target: {t['puzzlink_url'][:60]}..."
            )

    def test_result_entry_schema(self, results):
        for r in results:
            assert isinstance(r.get("puzzlink_url"), str), "missing puzzlink_url"
            assert isinstance(r.get("puzzle_type"), str), "missing puzzle_type"
            assert isinstance(r.get("solved"), bool), "missing or non-bool solved"
            assert isinstance(r.get("moves"), list), "missing or non-list moves"


# -- solution verification ---------------------------------------------------


class TestSolutionVerification:
    def test_at_least_five_verified(self, verified):
        n = sum(1 for v in verified.values() if v)
        assert n >= 5, (
            f"Only {n} puzzle(s) have correct move sequences. "
            "Need at least 5 out of 8."
        )

    def test_at_least_three_types(self, results, verified):
        solved_types = set()
        for r in results:
            url = r["puzzlink_url"]
            if verified.get(url, False) and url in EXPECTED:
                solved_types.add(EXPECTED[url]["pid"])
        assert len(solved_types) >= 3, (
            f"Verified types: {solved_types}. Need at least 3 distinct types."
        )

    def test_no_false_claims(self, results, verified):
        """Every result claiming solved=True must have correct moves."""
        for r in results:
            url = r["puzzlink_url"]
            if r.get("solved") and url in EXPECTED:
                assert verified.get(url, False), (
                    f"Puzzle claims solved=True but move sequence hash "
                    f"does not match expected: {url[:50]}..."
                )


# -- move format sanity -------------------------------------------------------


class TestMoveFormat:
    def test_verified_puzzles_have_moves(self, results, verified):
        for r in results:
            if verified.get(r["puzzlink_url"], False):
                assert len(r["moves"]) > 0, (
                    f"Puzzle verified but has no moves"
                )

    def test_move_strings_are_valid(self, results, verified):
        for r in results:
            if verified.get(r["puzzlink_url"], False):
                for move in r["moves"]:
                    assert isinstance(move, str), f"Move is not a string: {move}"
                    assert move.startswith("mouse,") or move.startswith("key,"), (
                        f"Invalid move prefix: {move[:30]}"
                    )
