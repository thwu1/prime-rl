
import json
import os
import sqlite3
import pytest

RESULT_PATH = "/app/audit_result.json"
TRF_PATH = "/app/tournament.trf"
DB_PATH = "/app/tournament.db"

EXPECTED = [
    {
        "candidate_index": 0,
        "c1": 0,
        "c3": 0,
        "colour_allocation_errors": 0,
        "c12": 2,
        "c13": 0,
        "c14": 1,
        "c15": 1,
        "legal": True,
        "quality_penalty": 4
    },
    {
        "candidate_index": 1,
        "c1": 4,
        "c3": 0,
        "colour_allocation_errors": 1,
        "c12": 4,
        "c13": 0,
        "c14": 3,
        "c15": 2,
        "legal": False,
        "quality_penalty": 9
    },
    {
        "candidate_index": 2,
        "c1": 0,
        "c3": 0,
        "colour_allocation_errors": 1,
        "c12": 2,
        "c13": 0,
        "c14": 1,
        "c15": 2,
        "legal": True,
        "quality_penalty": 5
    },
    {
        "candidate_index": 3,
        "c1": 0,
        "c3": 0,
        "colour_allocation_errors": 3,
        "c12": 8,
        "c13": 4,
        "c14": 1,
        "c15": 1,
        "legal": True,
        "quality_penalty": 14
    },
    {
        "candidate_index": 4,
        "c1": 2,
        "c3": 1,
        "colour_allocation_errors": 2,
        "c12": 6,
        "c13": 1,
        "c14": 2,
        "c15": 3,
        "legal": False,
        "quality_penalty": 12
    }
]


@pytest.fixture
def results():
    assert os.path.exists(RESULT_PATH), f"Output file {RESULT_PATH} does not exist"
    with open(RESULT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "Result must be a JSON list"
    assert len(data) == 5, f"Expected 5 candidate results, got {len(data)}"
    return data


@pytest.fixture
def trf_lines():
    assert os.path.exists(TRF_PATH), f"TRF file {TRF_PATH} does not exist"
    with open(TRF_PATH) as f:
        return [line.rstrip("\n") for line in f.readlines()]


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ========== TRF File Structure Tests ==========

class TestTRFFileStructure:
    def test_trf_file_exists(self):
        assert os.path.exists(TRF_PATH), f"TRF file {TRF_PATH} does not exist"

    def test_trf_has_all_header_lines(self, trf_lines):
        required_codes = [
            "012", "022", "032", "042", "052", "062", "072",
            "082", "092", "102", "112", "122", "132", "XXR", "XXC"
        ]
        for code in required_codes:
            found = any(line.startswith(code) for line in trf_lines)
            assert found, f"TRF file missing required header line '{code}'"

    def test_trf_player_line_count(self, trf_lines):
        player_lines = [l for l in trf_lines if l.startswith("001")]
        assert len(player_lines) == 16, \
            f"Expected 16 player (001) lines, got {len(player_lines)}"

    def test_trf_xxr_matches_db(self, trf_lines, db_conn):
        db_rounds = db_conn.execute(
            "SELECT num_rounds FROM tournament_info"
        ).fetchone()[0]
        for line in trf_lines:
            if line.startswith("XXR"):
                trf_rounds = int(line[4:].strip())
                assert trf_rounds == db_rounds, \
                    f"XXR shows {trf_rounds} rounds but DB has {db_rounds}"
                return
        pytest.fail("No XXR line found in TRF")

    def test_trf_xxc_matches_db(self, trf_lines, db_conn):
        db_colour = db_conn.execute(
            "SELECT initial_colour FROM tournament_info"
        ).fetchone()[0]
        for line in trf_lines:
            if line.startswith("XXC"):
                trf_colour = line[4:].strip()
                assert trf_colour == db_colour, \
                    f"XXC shows '{trf_colour}' but DB has '{db_colour}'"
                return
        pytest.fail("No XXC line found in TRF")


class TestTRFPlayerData:
    """Verify TRF player lines match the SQLite database content."""

    def test_player_names_match_db(self, trf_lines, db_conn):
        players = {
            r["tpn"]: dict(r)
            for r in db_conn.execute("SELECT * FROM players")
        }
        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            trf_name = line[14:47].strip()
            assert tpn in players, f"TPN {tpn} in TRF but not in DB"
            assert trf_name == players[tpn]["name"], \
                f"TPN {tpn}: TRF name '{trf_name}' != DB '{players[tpn]['name']}'"

    def test_player_ratings_match_db(self, trf_lines, db_conn):
        players = {
            r["tpn"]: dict(r)
            for r in db_conn.execute("SELECT * FROM players")
        }
        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            trf_rating = int(line[48:52].strip())
            assert trf_rating == players[tpn]["rating"], \
                f"TPN {tpn}: TRF rating {trf_rating} != DB {players[tpn]['rating']}"

    def test_player_scores_match_db(self, trf_lines, db_conn):
        players = {
            r["tpn"]: dict(r)
            for r in db_conn.execute("SELECT * FROM players")
        }
        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            trf_score = float(line[80:84].strip())
            assert abs(trf_score - players[tpn]["score"]) < 0.01, \
                f"TPN {tpn}: TRF score {trf_score} != DB {players[tpn]['score']}"

    def test_player_ranks_match_db(self, trf_lines, db_conn):
        players = {
            r["tpn"]: dict(r)
            for r in db_conn.execute("SELECT * FROM players")
        }
        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            trf_rank = int(line[85:89].strip())
            assert trf_rank == players[tpn]["rank"], \
                f"TPN {tpn}: TRF rank {trf_rank} != DB {players[tpn]['rank']}"


class TestTRFRoundData:
    """Verify TRF round blocks match database round_results."""

    def test_round_opponents_match_db(self, trf_lines, db_conn):
        num_rounds = db_conn.execute(
            "SELECT num_rounds FROM tournament_info"
        ).fetchone()[0]
        expected = {}
        for row in db_conn.execute(
            "SELECT tpn, round_num, opponent_tpn FROM round_results"
        ):
            expected[(row[0], row[1])] = row[2]

        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            for rnd in range(num_rounds):
                start = 89 + rnd * 10
                block = line[start:start + 10] if start < len(line) else ""
                if len(block) >= 6 and block.strip():
                    opp = int(block[2:6].strip())
                    key = (tpn, rnd + 1)
                    assert key in expected, \
                        f"TPN {tpn} round {rnd+1} not in DB"
                    assert opp == expected[key], \
                        f"TPN {tpn} R{rnd+1}: TRF opponent {opp} != DB {expected[key]}"

    def test_round_colours_match_db(self, trf_lines, db_conn):
        num_rounds = db_conn.execute(
            "SELECT num_rounds FROM tournament_info"
        ).fetchone()[0]
        expected = {}
        for row in db_conn.execute(
            "SELECT tpn, round_num, colour FROM round_results"
        ):
            expected[(row[0], row[1])] = row[2].lower()

        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            for rnd in range(num_rounds):
                start = 89 + rnd * 10
                block = line[start:start + 10] if start < len(line) else ""
                if len(block) >= 8 and block.strip():
                    col = block[7].lower()
                    key = (tpn, rnd + 1)
                    assert col == expected[key], \
                        f"TPN {tpn} R{rnd+1}: TRF colour '{col}' != DB '{expected[key]}'"

    def test_round_results_match_db(self, trf_lines, db_conn):
        num_rounds = db_conn.execute(
            "SELECT num_rounds FROM tournament_info"
        ).fetchone()[0]
        expected = {}
        for row in db_conn.execute(
            "SELECT tpn, round_num, result FROM round_results"
        ):
            expected[(row[0], row[1])] = row[2]

        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            for rnd in range(num_rounds):
                start = 89 + rnd * 10
                block = line[start:start + 10] if start < len(line) else ""
                if len(block) >= 10 and block.strip():
                    res = block[9]
                    key = (tpn, rnd + 1)
                    assert res == expected[key], \
                        f"TPN {tpn} R{rnd+1}: TRF result '{res}' != DB '{expected[key]}'"

    def test_round_block_width(self, trf_lines, db_conn):
        """Each round block must be exactly 10 characters wide."""
        num_rounds = db_conn.execute(
            "SELECT num_rounds FROM tournament_info"
        ).fetchone()[0]
        for line in trf_lines:
            if not line.startswith("001"):
                continue
            tpn = int(line[4:8].strip())
            expected_min_len = 89 + num_rounds * 10
            assert len(line) >= expected_min_len - 1, \
                f"TPN {tpn}: line too short ({len(line)} chars), " \
                f"expected at least {expected_min_len} for {num_rounds} rounds"


# ========== Audit Output Structure Tests ==========

class TestOutputStructure:
    def test_result_file_exists(self, results):
        assert results is not None

    def test_all_fields_present(self, results):
        required = [
            "candidate_index", "c1", "c3", "colour_allocation_errors",
            "c12", "c13", "c14", "c15", "legal", "quality_penalty"
        ]
        for i, r in enumerate(results):
            for field in required:
                assert field in r, f"Candidate {i} missing field '{field}'"

    def test_candidate_indices(self, results):
        indices = sorted(r["candidate_index"] for r in results)
        assert indices == [0, 1, 2, 3, 4], \
            f"Expected indices [0,1,2,3,4], got {indices}"


# ========== Audit Result Correctness Tests ==========

class TestTRFParsing:
    """Verify correct opponent-history extraction via rematch detection."""

    def test_set0_no_rematches(self, results):
        r = next(x for x in results if x["candidate_index"] == 0)
        assert r["c1"] == 0, f"Set 0 should have 0 rematches, got {r['c1']}"

    def test_set1_four_rematches(self, results):
        r = next(x for x in results if x["candidate_index"] == 1)
        assert r["c1"] == 4, f"Set 1 should have 4 rematches, got {r['c1']}"

    def test_set4_two_rematches(self, results):
        r = next(x for x in results if x["candidate_index"] == 4)
        assert r["c1"] == 2, f"Set 4 should have 2 rematches, got {r['c1']}"


class TestAbsoluteCriteria:
    """C3: non-topscorers with same absolute colour preference."""

    def test_set0_no_c3(self, results):
        r = next(x for x in results if x["candidate_index"] == 0)
        assert r["c3"] == 0

    def test_set4_one_c3(self, results):
        r = next(x for x in results if x["candidate_index"] == 4)
        assert r["c3"] == 1, f"Set 4 should have 1 C3 violation, got {r['c3']}"

    def test_c3_zero_for_valid_sets(self, results):
        for idx in [0, 2, 3]:
            r = next(x for x in results if x["candidate_index"] == idx)
            assert r["c3"] == 0, f"Set {idx} should have 0 C3 violations"


class TestLegality:
    def test_set0_legal(self, results):
        r = next(x for x in results if x["candidate_index"] == 0)
        assert r["legal"] is True

    def test_set1_illegal(self, results):
        r = next(x for x in results if x["candidate_index"] == 1)
        assert r["legal"] is False

    def test_set2_legal(self, results):
        r = next(x for x in results if x["candidate_index"] == 2)
        assert r["legal"] is True

    def test_set3_legal(self, results):
        r = next(x for x in results if x["candidate_index"] == 3)
        assert r["legal"] is True

    def test_set4_illegal(self, results):
        r = next(x for x in results if x["candidate_index"] == 4)
        assert r["legal"] is False


class TestColourAllocation:
    """Verify correct application of the Article 5.2 colour allocation cascade."""

    def test_set0_colour_errors(self, results):
        r = next(x for x in results if x["candidate_index"] == 0)
        assert r["colour_allocation_errors"] == 0, \
            f"Set 0 expected 0 colour errors, got {r['colour_allocation_errors']}"

    def test_set1_colour_errors(self, results):
        r = next(x for x in results if x["candidate_index"] == 1)
        assert r["colour_allocation_errors"] == 1

    def test_set2_colour_errors(self, results):
        r = next(x for x in results if x["candidate_index"] == 2)
        assert r["colour_allocation_errors"] == 1

    def test_set3_colour_errors(self, results):
        r = next(x for x in results if x["candidate_index"] == 3)
        assert r["colour_allocation_errors"] == 3

    def test_set4_colour_errors(self, results):
        r = next(x for x in results if x["candidate_index"] == 4)
        assert r["colour_allocation_errors"] == 2


class TestColourPreferences:
    """C12: players not getting colour preference. C13: strong/absolute denials."""

    def test_c12_all_sets(self, results):
        expected = {0: 2, 1: 4, 2: 2, 3: 8, 4: 6}
        for idx, exp in expected.items():
            r = next(x for x in results if x["candidate_index"] == idx)
            assert r["c12"] == exp, \
                f"Set {idx}: expected c12={exp}, got {r['c12']}"

    def test_c13_all_sets(self, results):
        expected = {0: 0, 1: 0, 2: 0, 3: 4, 4: 1}
        for idx, exp in expected.items():
            r = next(x for x in results if x["candidate_index"] == idx)
            assert r["c13"] == exp, \
                f"Set {idx}: expected c13={exp}, got {r['c13']}"


class TestFloatCriteria:
    """C14: repeat downfloats. C15: repeat upfloat opponents."""

    def test_c14_all_sets(self, results):
        expected = {0: 1, 1: 3, 2: 1, 3: 1, 4: 2}
        for idx, exp in expected.items():
            r = next(x for x in results if x["candidate_index"] == idx)
            assert r["c14"] == exp, \
                f"Set {idx}: expected c14={exp}, got {r['c14']}"

    def test_c15_all_sets(self, results):
        expected = {0: 1, 1: 2, 2: 2, 3: 1, 4: 3}
        for idx, exp in expected.items():
            r = next(x for x in results if x["candidate_index"] == idx)
            assert r["c15"] == exp, \
                f"Set {idx}: expected c15={exp}, got {r['c15']}"


class TestQualityPenalty:
    def test_penalty_all_sets(self, results):
        expected = {0: 4, 1: 9, 2: 5, 3: 14, 4: 12}
        for idx, exp in expected.items():
            r = next(x for x in results if x["candidate_index"] == idx)
            assert r["quality_penalty"] == exp, \
                f"Set {idx}: expected penalty={exp}, got {r['quality_penalty']}"

    def test_penalty_is_sum(self, results):
        for r in results:
            expected = r["c12"] + r["c13"] + r["c14"] + r["c15"]
            assert r["quality_penalty"] == expected, \
                f"Set {r['candidate_index']}: quality_penalty should be c12+c13+c14+c15"

    def test_best_quality_is_set0(self, results):
        penalties = {r["candidate_index"]: r["quality_penalty"] for r in results}
        legal_penalties = {
            idx: p for idx, p in penalties.items()
            if next(x for x in results if x["candidate_index"] == idx)["legal"]
        }
        best_idx = min(legal_penalties, key=legal_penalties.get)
        assert best_idx == 0, \
            f"Set 0 should have lowest penalty among legal sets, but set {best_idx} does"
