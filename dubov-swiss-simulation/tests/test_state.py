"""
Verification tests for FIDE Dubov Swiss Tournament Simulation.

"""

import json
import csv
import math
import os
import re
import subprocess

import pytest

NUM_PLAYERS = 12


def get_engine():
    """Get path to the built engine binary."""
    engine = os.environ.get("DUBOV_ENGINE_PATH", "")
    if engine and os.path.exists(engine):
        return engine
    for path in [
        "/app/engine/build/CPPDubovSystem",
        "/app/engine/CPPDubovSystem",
    ]:
        if os.path.exists(path):
            return path
    pytest.skip("Engine binary not found")


def load_spec():
    """Load tournament specification."""
    with open("/app/tournament_spec.json", "r") as f:
        return json.load(f)


def parse_trf_players(trf_path):
    """
    Parse a TRF16 file and extract player data including round results.
    Matches the CPPDubovSystem parser layout (see trf.cpp parsePlayer):
      - rank at substr(4, 4)
      - rating at substr(48, 4)
      - points at substr(80, 4)
      - round data at stride-10 starting from position 92:
          opponent = substr(pos, 3)
          color    = substr(pos+4, 1)
          result   = substr(pos+6, 1)
    """
    players = {}

    with open(trf_path, "r") as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")
            if not line.startswith("001"):
                continue
            if len(line) < 89:
                continue

            rank_str = line[4:8].strip()
            if not rank_str:
                continue

            try:
                player_id = int(rank_str)
            except ValueError:
                continue

            rating_str = line[48:52].strip()
            try:
                rating = int(rating_str) if rating_str else 0
            except ValueError:
                rating = 0

            points_str = line[80:84].strip()
            try:
                points = float(points_str) if points_str else 0.0
            except ValueError:
                points = 0.0

            games = []
            pos = 92
            while pos + 6 < len(line):
                opp_raw = line[pos:pos + 3]
                opp_stripped = opp_raw.replace(" ", "")

                if not opp_stripped or opp_stripped in ("000", "0000"):
                    opp_id = 0
                else:
                    try:
                        opp_id = int(opp_stripped)
                    except ValueError:
                        pos += 10
                        continue

                color = line[pos + 4] if pos + 4 < len(line) else ""
                result = line[pos + 6] if pos + 6 < len(line) else ""

                games.append(
                    {"opponent": opp_id, "color": color, "result": result}
                )
                pos += 10

            players[player_id] = {
                "rating": rating,
                "points": points,
                "games": games,
            }

    return players


def compute_outcome(id1, id2):
    """Compute deterministic outcome between two players."""
    i = min(id1, id2)
    j = max(id1, id2)
    k = (3 * i + 7 * j) % 10
    if k <= 5:
        return i  # lower ID wins
    elif k <= 7:
        return 0  # draw
    else:
        return j  # higher ID wins


class TestEngineBuilt:
    """Verify the engine can be found."""

    def test_engine_exists(self):
        engine = get_engine()
        assert os.path.exists(engine), "Engine not found at {}".format(engine)


class TestTRFFile:
    """Verify the TRF file is valid and complete."""

    def test_trf_exists(self):
        assert os.path.exists("/app/tournament.trf"), "tournament.trf not found"

    def test_trf_has_all_players(self):
        players = parse_trf_players("/app/tournament.trf")
        assert len(players) == NUM_PLAYERS, (
            "Expected {} players, found {}".format(NUM_PLAYERS, len(players))
        )
        for pid in range(1, NUM_PLAYERS + 1):
            assert pid in players, "Player {} missing from TRF".format(pid)

    def test_trf_has_five_rounds(self):
        players = parse_trf_players("/app/tournament.trf")
        for pid, pdata in players.items():
            assert len(pdata["games"]) == 5, (
                "Player {} has {} rounds, expected 5".format(
                    pid, len(pdata["games"])
                )
            )

    def test_trf_parseable_by_engine(self):
        """Engine should parse the TRF and generate round 6 pairings."""
        engine = get_engine()
        result = subprocess.run(
            [
                engine,
                "--pairings",
                "/app/tournament.trf",
                "--output",
                "/tmp/test_verify_r6.csv",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            "Engine failed to parse TRF: return={}, "
            "stderr={}, stdout={}".format(
                result.returncode,
                result.stderr[:500],
                result.stdout[:500],
            )
        )

    def test_tnr_code_present(self):
        with open("/app/tournament.trf", "r") as f:
            content = f.read()
        assert "TNR" in content or "XXR" in content, (
            "TRF file missing TNR/XXR code for total rounds"
        )

    def test_points_consistency(self):
        """Verify that stated points match sum of game results."""
        players = parse_trf_players("/app/tournament.trf")
        for pid, pdata in players.items():
            computed_pts = 0.0
            for game in pdata["games"]:
                r = game["result"]
                if r in ("1", "+", "w", "f", "u"):
                    computed_pts += 1.0
                elif r in ("=", "d", "h"):
                    computed_pts += 0.5
            assert abs(pdata["points"] - computed_pts) < 0.01, (
                "Player {}: stated points {} != computed {}".format(
                    pid, pdata["points"], computed_pts
                )
            )


class TestFPC:
    """Verify all rounds pass the Free Pairings Checker."""

    @pytest.mark.parametrize("round_num", [1, 2, 3, 4, 5])
    def test_fpc_round(self, round_num):
        engine = get_engine()
        result = subprocess.run(
            [
                engine,
                "--fpc",
                "/app/tournament.trf",
                "--fpc_rounds",
                str(round_num),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr

        # Check for error count
        err_match = re.search(
            r"ERRORS TOTAL DETECTED IN TOURNAMENT PAIRINGS:\s*(\d+)", output
        )
        assert err_match, (
            "Could not find error count in FPC output for round {}. "
            "returncode={}, output={}".format(
                round_num, result.returncode, output[:500]
            )
        )
        errors = int(err_match.group(1))
        assert errors == 0, (
            "FPC found {} errors in round {}".format(errors, round_num)
        )

        # Check no unmatched pairings
        nm_match = re.search(
            r"TOTAL GAMES NOT_MATCHED/TOTAL:\s*(\d+)/(\d+)", output
        )
        assert nm_match, (
            "Could not find match ratio in FPC output for round {}".format(
                round_num
            )
        )
        not_matched = int(nm_match.group(1))
        assert not_matched == 0, (
            "FPC: {} pairings unmatched in round {}".format(
                not_matched, round_num
            )
        )


class TestRound6Pairings:
    """Verify round 6 pairings match engine output."""

    def test_round6_csv_exists(self):
        assert os.path.exists("/app/round6_pairings.csv")

    def test_round6_matches_engine(self):
        engine = get_engine()
        result = subprocess.run(
            [
                engine,
                "--pairings",
                "/app/tournament.trf",
                "--output",
                "/tmp/test_r6_engine.csv",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            "Engine failed: {}".format(result.stderr[:500])
        )

        # Parse engine pairings
        engine_pairs = set()
        with open("/tmp/test_r6_engine.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                engine_pairs.add(
                    (int(row["White"]), int(row["Black"]))
                )

        # Parse agent pairings
        agent_pairs = set()
        with open("/app/round6_pairings.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                agent_pairs.add(
                    (int(row["White"]), int(row["Black"]))
                )

        assert engine_pairs == agent_pairs, (
            "Round 6 pairings mismatch.\n"
            "Engine: {}\n"
            "Agent:  {}".format(sorted(engine_pairs), sorted(agent_pairs))
        )


class TestAnalysis:
    """Verify analysis.json contents."""

    @pytest.fixture
    def analysis(self):
        assert os.path.exists("/app/analysis.json"), "analysis.json not found"
        with open("/app/analysis.json", "r") as f:
            return json.load(f)

    @pytest.fixture
    def trf_data(self):
        return parse_trf_players("/app/tournament.trf")

    @pytest.fixture
    def spec(self):
        return load_spec()

    def test_has_required_keys(self, analysis):
        for key in [
            "aro", "color_diff", "scoregroups",
            "round6_pairings",
        ]:
            assert key in analysis, "Missing key '{}' in analysis.json".format(key)

    def test_aro_values(self, analysis, trf_data, spec):
        """Independently compute ARO from TRF data and compare."""
        ratings = {p["id"]: p["rating"] for p in spec["players"]}
        for pid in range(1, NUM_PLAYERS + 1):
            pdata = trf_data[pid]
            otb_ratings = []
            for game in pdata["games"]:
                if game["result"] in ("1", "0", "="):
                    opp = game["opponent"]
                    if opp in ratings:
                        otb_ratings.append(ratings[opp])
            if otb_ratings:
                expected = math.floor(
                    sum(otb_ratings) / len(otb_ratings) + 0.5
                )
            else:
                expected = 0
            agent_val = analysis["aro"].get(str(pid))
            assert agent_val is not None, (
                "ARO for player {} missing".format(pid)
            )
            assert agent_val == expected, (
                "ARO mismatch for player {}: "
                "expected {}, got {}. "
                "OTB opponents: {}".format(
                    pid,
                    expected,
                    agent_val,
                    [
                        g["opponent"]
                        for g in pdata["games"]
                        if g["result"] in ("1", "0", "=")
                    ],
                )
            )

    def test_color_diff_values(self, analysis, trf_data):
        """Independently compute color differences from TRF data."""
        for pid in range(1, NUM_PLAYERS + 1):
            pdata = trf_data[pid]
            diff = 0
            for game in pdata["games"]:
                if game["color"] == "w":
                    diff += 1
                elif game["color"] == "b":
                    diff -= 1
            agent_val = analysis["color_diff"].get(str(pid))
            assert agent_val is not None, (
                "color_diff for player {} missing".format(pid)
            )
            assert agent_val == diff, (
                "color_diff mismatch for player {}: "
                "expected {}, got {}. "
                "Colors: {}".format(
                    pid,
                    diff,
                    agent_val,
                    [g["color"] for g in pdata["games"]],
                )
            )

    def test_scoregroups(self, analysis, trf_data):
        """Verify scoregroups match player points in TRF."""
        expected_groups = {}
        for pid, pdata in trf_data.items():
            score_key = "{:.1f}".format(pdata["points"])
            if score_key not in expected_groups:
                expected_groups[score_key] = []
            expected_groups[score_key].append(pid)
        for key in expected_groups:
            expected_groups[key].sort()

        agent_groups = analysis["scoregroups"]
        normalized = {}
        for k, v in agent_groups.items():
            nk = "{:.1f}".format(float(k))
            normalized[nk] = sorted(v)

        assert normalized == expected_groups, (
            "Scoregroups mismatch.\n"
            "Expected: {}\n"
            "Got:      {}".format(expected_groups, normalized)
        )

    def test_round6_pairings_in_analysis(self, analysis):
        """Round 6 pairings in analysis should match the CSV file."""
        if not os.path.exists("/app/round6_pairings.csv"):
            pytest.skip("round6_pairings.csv not found")

        csv_pairs = []
        with open("/app/round6_pairings.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                csv_pairs.append([int(row["White"]), int(row["Black"])])

        assert analysis["round6_pairings"] == csv_pairs, (
            "round6_pairings in analysis.json doesn't match CSV.\n"
            "CSV: {}\n"
            "JSON: {}".format(csv_pairs, analysis["round6_pairings"])
        )

    def test_outcome_consistency(self, trf_data):
        """
        Verify that game results in the TRF are consistent with the
        deterministic outcome rule from the specification.
        """
        for pid, pdata in trf_data.items():
            for round_idx, game in enumerate(pdata["games"]):
                opp = game["opponent"]
                if opp == 0:
                    continue  # PAB
                result = game["result"]
                if result in ("+", "-", "h", "f", "u", "z"):
                    continue  # forfeit or other special result

                winner = compute_outcome(pid, opp)
                if winner == 0:
                    assert result == "=", (
                        "Player {} vs {} (round {}): "
                        "expected draw, got result '{}'".format(
                            pid, opp, round_idx + 1, result
                        )
                    )
                elif winner == pid:
                    assert result == "1", (
                        "Player {} vs {} (round {}): "
                        "expected {} to win, got result '{}'".format(
                            pid, opp, round_idx + 1, pid, result
                        )
                    )
                else:
                    assert result == "0", (
                        "Player {} vs {} (round {}): "
                        "expected {} to lose, got result '{}'".format(
                            pid, opp, round_idx + 1, pid, result
                        )
                    )

    def test_all_games_otb(self, trf_data):
        """With even players, all games should be over-the-board (no byes)."""
        for pid, pdata in trf_data.items():
            for round_idx, game in enumerate(pdata["games"]):
                assert game["opponent"] != 0, (
                    "Player {} round {}: unexpected bye with even player count".format(
                        pid, round_idx + 1
                    )
                )
                assert game["color"] in ("w", "b"), (
                    "Player {} round {}: unexpected color '{}'".format(
                        pid, round_idx + 1, game["color"]
                    )
                )
                assert game["result"] in ("1", "0", "="), (
                    "Player {} round {}: unexpected result '{}'".format(
                        pid, round_idx + 1, game["result"]
                    )
                )

    def test_game_symmetry(self, trf_data):
        """Verify that if A played B in round r, then B played A in round r."""
        for pid, pdata in trf_data.items():
            for round_idx, game in enumerate(pdata["games"]):
                opp = game["opponent"]
                if opp == 0:
                    continue
                opp_data = trf_data.get(opp)
                assert opp_data is not None, (
                    "Player {}'s opponent {} not found in TRF".format(pid, opp)
                )
                assert round_idx < len(opp_data["games"]), (
                    "Opponent {} doesn't have round {} data".format(
                        opp, round_idx + 1
                    )
                )
                opp_game = opp_data["games"][round_idx]
                assert opp_game["opponent"] == pid, (
                    "Asymmetric pairing: player {} played {} in round {}, "
                    "but {} played {} in that round".format(
                        pid, opp, round_idx + 1, opp, opp_game["opponent"]
                    )
                )
