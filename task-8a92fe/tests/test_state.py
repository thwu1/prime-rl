
import json
import os
import subprocess
import math


def round_half_up(x):
    """Round to nearest int, rounding 0.5 up (FIDE convention)."""
    return math.floor(x + 0.5)


# Expected ARO values computed by hand from the TRF data.
# ARO = mean of ratings of OTB opponents only (forfeit +/- excluded).
EXPECTED_ARO = {
    "1": 1836, "2": 1749, "3": 1748, "4": 1725, "5": 1841,
    "6": 1783, "7": 1323, "8": 1480, "9": 1909, "10": 1371,
    "11": 1610, "12": 1784, "13": 1385, "14": 1888, "15": 1649,
    "16": 1803, "17": 1498, "18": 1083, "19": 1380, "20": 1501,
}

# Expected color balance (whites - blacks) counting OTB games only.
EXPECTED_COLOR_BALANCE = {
    "1": 0, "2": -1, "3": 1, "4": -1, "5": 1,
    "6": -1, "7": 0, "8": 1, "9": 0, "10": -1,
    "11": -1, "12": 1, "13": 0, "14": 1, "15": 0,
    "16": -1, "17": 0, "18": 0, "19": 0, "20": 1,
}

# Expected due colors.
EXPECTED_DUE_COLOR = {
    "1": "white", "2": "white", "3": "black", "4": "white", "5": "black",
    "6": "white", "7": "black", "8": "black", "9": "white", "10": "white",
    "11": "white", "12": "black", "13": "black", "14": "black", "15": "black",
    "16": "white", "17": "black", "18": "white", "19": "black", "20": "black",
}

# Buchholz Cut 1: sum of all opponents' scores minus the lowest.
EXPECTED_BUCHHOLZ_CUT1 = {
    "1": 13.0, "2": 12.0, "3": 12.0, "4": 12.0, "5": 10.5,
    "6": 9.5, "7": 12.5, "8": 12.5, "9": 12.5, "10": 8.0,
    "11": 10.0, "12": 11.5, "13": 10.0, "14": 13.0, "15": 12.5,
    "16": 13.5, "17": 12.5, "18": 10.0, "19": 10.0, "20": 10.0,
}

# Sonneborn-Berger: sum of (opponent_score * result_value) for all games.
EXPECTED_SONNEBORN_BERGER = {
    "1": 6.5, "2": 6.25, "3": 9.5, "4": 2.0, "5": 0.0,
    "6": 3.0, "7": 6.0, "8": 7.5, "9": 10.75, "10": 0.0,
    "11": 5.0, "12": 8.75, "13": 0.0, "14": 10.5, "15": 3.75,
    "16": 6.25, "17": 10.25, "18": 3.0, "19": 1.0, "20": 4.5,
}

# Expected standings order: sorted by points desc, BC1 desc, SB desc.
EXPECTED_STANDINGS_ORDER = [
    "9", "3", "14", "17", "12", "8", "7", "11", "20",
    "16", "1", "2", "15", "4", "18", "19", "6", "5", "13", "10",
]


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), \
            "results.json not found at /app/results.json"

    def test_results_valid_json(self):
        with open("/app/results.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "results.json root must be a dict"


class TestResultsSchema:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_has_standings(self):
        data = self._load()
        assert "standings" in data, "Missing 'standings' key"
        assert isinstance(data["standings"], dict)
        assert len(data["standings"]) == 20, \
            f"Expected 20 players, got {len(data['standings'])}"

    def test_has_standings_order(self):
        data = self._load()
        assert "standings_order" in data, "Missing 'standings_order' key"
        assert isinstance(data["standings_order"], list)
        assert len(data["standings_order"]) == 20, \
            f"Expected 20 entries in standings_order, got {len(data['standings_order'])}"

    def test_has_tournament_params(self):
        data = self._load()
        assert "tournament_params" in data
        params = data["tournament_params"]
        assert params["total_rounds"] == 7
        assert params["completed_rounds"] == 5

    def test_has_pairings(self):
        data = self._load()
        assert "next_round_pairings" in data
        assert isinstance(data["next_round_pairings"], list)
        assert len(data["next_round_pairings"]) > 0, "Pairings list is empty"

    def test_player_fields(self):
        data = self._load()
        required = {
            "name", "rating", "points", "buchholz_cut1",
            "sonneborn_berger", "aro", "color_balance", "due_color",
        }
        for pid, pdata in data["standings"].items():
            assert isinstance(pdata, dict), f"Player {pid} data must be a dict"
            for field in required:
                assert field in pdata, \
                    f"Player {pid} missing field '{field}'"


class TestARO:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_aro_values(self):
        data = self._load()
        players = data["standings"]
        errors = []
        for pid, expected_aro in EXPECTED_ARO.items():
            if pid not in players:
                errors.append(f"Player {pid} not found in results")
                continue
            actual = players[pid].get("aro")
            if actual != expected_aro:
                errors.append(
                    f"Player {pid}: expected ARO={expected_aro}, got {actual}"
                )
        assert not errors, "ARO mismatches:\n" + "\n".join(errors)


class TestColorBalance:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_color_balance_values(self):
        data = self._load()
        players = data["standings"]
        errors = []
        for pid, expected in EXPECTED_COLOR_BALANCE.items():
            if pid not in players:
                errors.append(f"Player {pid} not found in results")
                continue
            actual = players[pid].get("color_balance")
            if actual != expected:
                errors.append(
                    f"Player {pid}: expected color_balance={expected}, "
                    f"got {actual}"
                )
        assert not errors, "Color balance mismatches:\n" + "\n".join(errors)


class TestDueColor:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_due_color_values(self):
        data = self._load()
        players = data["standings"]
        errors = []
        for pid, expected in EXPECTED_DUE_COLOR.items():
            if pid not in players:
                errors.append(f"Player {pid} not found in results")
                continue
            actual = players[pid].get("due_color")
            if actual != expected:
                errors.append(
                    f"Player {pid}: expected due_color={expected}, "
                    f"got {actual}"
                )
        assert not errors, "Due color mismatches:\n" + "\n".join(errors)


class TestBuchholzCut1:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_buchholz_cut1_values(self):
        data = self._load()
        players = data["standings"]
        errors = []
        for pid, expected in EXPECTED_BUCHHOLZ_CUT1.items():
            if pid not in players:
                errors.append(f"Player {pid} not found in results")
                continue
            actual = players[pid].get("buchholz_cut1")
            if actual is None:
                errors.append(f"Player {pid}: buchholz_cut1 is None")
                continue
            if abs(actual - expected) > 0.01:
                errors.append(
                    f"Player {pid}: expected BC1={expected}, got {actual}"
                )
        assert not errors, "Buchholz Cut 1 mismatches:\n" + "\n".join(errors)


class TestSonnebornBerger:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_sonneborn_berger_values(self):
        data = self._load()
        players = data["standings"]
        errors = []
        for pid, expected in EXPECTED_SONNEBORN_BERGER.items():
            if pid not in players:
                errors.append(f"Player {pid} not found in results")
                continue
            actual = players[pid].get("sonneborn_berger")
            if actual is None:
                errors.append(f"Player {pid}: sonneborn_berger is None")
                continue
            if abs(actual - expected) > 0.01:
                errors.append(
                    f"Player {pid}: expected SB={expected}, got {actual}"
                )
        assert not errors, "Sonneborn-Berger mismatches:\n" + "\n".join(errors)


class TestStandingsOrder:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_standings_order(self):
        data = self._load()
        actual = data["standings_order"]
        # Convert to strings for comparison
        actual_str = [str(x) for x in actual]
        assert actual_str == EXPECTED_STANDINGS_ORDER, (
            f"Standings order mismatch.\n"
            f"Expected: {EXPECTED_STANDINGS_ORDER}\n"
            f"Got:      {actual_str}"
        )


class TestPairings:
    def _load(self):
        with open("/app/results.json") as f:
            return json.load(f)

    def test_pairings_structure(self):
        data = self._load()
        pairings = data["next_round_pairings"]
        for i, pair in enumerate(pairings):
            assert isinstance(pair, dict), f"Pairing {i} must be a dict"
            assert "white" in pair, f"Pairing {i} missing 'white'"
            assert "black" in pair, f"Pairing {i} missing 'black'"
            assert isinstance(pair["white"], int), \
                f"Pairing {i} white must be int"
            assert isinstance(pair["black"], int), \
                f"Pairing {i} black must be int"

    def test_pairings_valid_ids(self):
        data = self._load()
        valid_ids = set(range(1, 21)) | {-1}
        pairings = data["next_round_pairings"]
        for i, pair in enumerate(pairings):
            assert pair["white"] in valid_ids, \
                f"Pairing {i}: invalid white ID {pair['white']}"
            assert pair["black"] in valid_ids, \
                f"Pairing {i}: invalid black ID {pair['black']}"

    def test_pairings_count(self):
        """20 players -> 10 pairings (even count, no bye needed)."""
        data = self._load()
        pairings = data["next_round_pairings"]
        assert len(pairings) == 10, \
            f"Expected 10 pairings for 20 players, got {len(pairings)}"

    def test_no_self_pairing(self):
        data = self._load()
        for i, pair in enumerate(data["next_round_pairings"]):
            if pair["black"] != -1:
                assert pair["white"] != pair["black"], \
                    f"Pairing {i}: self-pairing {pair['white']}"


class TestEngineBinary:
    def test_engine_exists(self):
        """The built engine binary should exist somewhere under /app."""
        found = False
        for root, dirs, files in os.walk("/app"):
            if "CPPDubovSystem" in files:
                found = True
                break
        assert found, "CPPDubovSystem binary not found under /app/"

    def test_engine_runs(self):
        """The engine should respond to --version."""
        binary = None
        for root, dirs, files in os.walk("/app"):
            if "CPPDubovSystem" in files:
                candidate = os.path.join(root, "CPPDubovSystem")
                if os.access(candidate, os.X_OK):
                    binary = candidate
                    break
        assert binary is not None, "No executable CPPDubovSystem found"
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, \
            f"Engine --version failed: {result.stderr}"


class TestCrossValidation:
    """Cross-validate agent's pairings against engine output."""

    def test_pairings_match_engine(self):
        binary = None
        for root, dirs, files in os.walk("/app"):
            if "CPPDubovSystem" in files:
                candidate = os.path.join(root, "CPPDubovSystem")
                if os.access(candidate, os.X_OK):
                    binary = candidate
                    break
        if binary is None:
            build_dir = "/app/CPPDubovSystem/build_test"
            os.makedirs(build_dir, exist_ok=True)
            subprocess.run(
                ["cmake", ".."],
                cwd=build_dir, capture_output=True, timeout=30
            )
            subprocess.run(
                ["make", "-j2"],
                cwd=build_dir, capture_output=True, timeout=120
            )
            candidate = os.path.join(build_dir, "CPPDubovSystem")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                binary = candidate

        assert binary is not None, \
            "Cannot find or build CPPDubovSystem for cross-validation"

        csv_path = "/tmp/test_pairings.csv"
        result = subprocess.run(
            [binary, "--pairings", "/app/tournament.trf",
             "--output", csv_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Engine pairing generation failed: {result.stderr}"
        assert os.path.isfile(csv_path), "Engine did not produce CSV output"

        engine_pairings = set()
        with open(csv_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("White"):
                    continue
                parts = line.split(",")
                if len(parts) == 2:
                    w, b = int(parts[0]), int(parts[1])
                    engine_pairings.add((w, b))

        with open("/app/results.json") as f:
            data = json.load(f)
        agent_pairings = set()
        for pair in data["next_round_pairings"]:
            agent_pairings.add((pair["white"], pair["black"]))

        assert engine_pairings == agent_pairings, (
            f"Pairings mismatch.\n"
            f"Engine: {sorted(engine_pairings)}\n"
            f"Agent:  {sorted(agent_pairings)}"
        )
