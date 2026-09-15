
import json
import os
import subprocess
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_exe():
    for p in ['/app/bbpPairings.exe', '/app/bbpPairings-src/bbpPairings.exe']:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def parse_trf_players(path):
    """Parse player data from a TRF file.

    Returns dict: pid -> {score, rounds: [{opponent, color, result}, ...]}
    """
    players = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip('\n')
            if not line.startswith('001') or len(line) < 89:
                continue
            try:
                pid = int(line[4:8].strip())
            except ValueError:
                continue
            try:
                score = float(line[80:84].strip())
            except ValueError:
                score = -1.0

            rounds = []
            pos = 89
            while pos + 9 <= len(line):
                opp_str = line[pos + 2:pos + 6].strip()
                if not opp_str or not opp_str.isdigit():
                    break
                opp = int(opp_str)
                color = line[pos + 7]
                result = line[pos + 9]
                rounds.append({
                    'opponent': opp,
                    'color': color,
                    'result': result,
                })
                pos += 10
            players[pid] = {'score': score, 'rounds': rounds}
    return players


def trf_has_header(path, prefix):
    with open(path) as f:
        for line in f:
            if line.startswith(prefix):
                return True
    return False


def compute_score_from_rounds(rounds):
    s = 0.0
    for rd in rounds:
        if rd['result'] == '1':
            s += 1.0
        elif rd['result'] == '=':
            s += 0.5
    return s


def load_ground_truth():
    path = '/app/.ground_truth.json'
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def exe_path():
    return find_exe()


@pytest.fixture
def repaired():
    return parse_trf_players('/app/tournament_repaired.trf')


@pytest.fixture
def complete():
    return parse_trf_players('/app/tournament_complete.trf')


@pytest.fixture
def ground_truth():
    return load_ground_truth()


# ---------------------------------------------------------------------------
# Repaired tournament tests
# ---------------------------------------------------------------------------

class TestRepairedTournament:

    def test_repaired_trf_exists(self):
        assert os.path.isfile('/app/tournament_repaired.trf'), \
            "/app/tournament_repaired.trf not found"

    def test_repaired_has_xxr_header(self):
        assert trf_has_header('/app/tournament_repaired.trf', 'XXR'), \
            "Repaired TRF missing XXR header"

    def test_repaired_has_xxc_header(self):
        assert trf_has_header('/app/tournament_repaired.trf', 'XXC'), \
            "Repaired TRF missing XXC header"

    def test_repaired_has_20_players(self, repaired):
        assert len(repaired) == 20, \
            f"Expected 20 players, got {len(repaired)}"

    def test_repaired_all_players_have_5_rounds(self, repaired):
        for pid, data in repaired.items():
            assert len(data['rounds']) == 5, \
                f"Player {pid}: expected 5 rounds, got {len(data['rounds'])}"

    def test_repaired_passes_bbp_checker(self, exe_path):
        if exe_path is None:
            pytest.skip("bbpPairings binary not found")
        result = subprocess.run(
            [exe_path, '--dutch', '/app/tournament_repaired.trf', '-c'],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"bbpPairings checker failed (exit {result.returncode}):\n" \
            f"stderr: {result.stderr[:1000]}"

    def test_repaired_scores_consistent(self, repaired):
        for pid, data in repaired.items():
            computed = compute_score_from_rounds(data['rounds'])
            assert abs(data['score'] - computed) < 0.01, \
                f"Player {pid}: header score {data['score']} != " \
                f"computed {computed}"

    def test_repaired_results_symmetric(self, repaired):
        for pid, data in repaired.items():
            for rnd_idx, rd in enumerate(data['rounds']):
                opp = rd['opponent']
                opp_data = repaired.get(opp)
                if opp_data is None or rnd_idx >= len(opp_data['rounds']):
                    continue
                opp_rd = opp_data['rounds'][rnd_idx]
                if opp_rd['opponent'] != pid:
                    continue
                complement = {'1': '0', '0': '1', '=': '='}
                expected = complement.get(opp_rd['result'])
                assert rd['result'] == expected, \
                    f"Round {rnd_idx+1}: player {pid} shows " \
                    f"'{rd['result']}' vs {opp}, but {opp} shows " \
                    f"'{opp_rd['result']}' (expected complement '{expected}')"


# ---------------------------------------------------------------------------
# Completed tournament tests
# ---------------------------------------------------------------------------

class TestCompleteTournament:

    def test_complete_trf_exists(self):
        assert os.path.isfile('/app/tournament_complete.trf'), \
            "/app/tournament_complete.trf not found"

    def test_complete_passes_bbp_checker(self, exe_path):
        if exe_path is None:
            pytest.skip("bbpPairings binary not found")
        result = subprocess.run(
            [exe_path, '--dutch', '/app/tournament_complete.trf', '-c'],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"bbpPairings checker failed (exit {result.returncode}):\n" \
            f"stderr: {result.stderr[:1000]}"

    def test_complete_has_20_players(self, complete):
        assert len(complete) == 20, \
            f"Expected 20 players, got {len(complete)}"

    def test_all_players_have_9_rounds(self, complete):
        for pid, data in complete.items():
            assert len(data['rounds']) == 9, \
                f"Player {pid}: expected 9 rounds, got {len(data['rounds'])}"

    def test_complete_no_repeated_opponents(self, complete):
        for pid, data in complete.items():
            opponents = [rd['opponent'] for rd in data['rounds']]
            dupes = [o for o in opponents if opponents.count(o) > 1]
            assert len(set(dupes)) == 0, \
                f"Player {pid} has repeated opponents: {set(dupes)}"

    def test_complete_valid_player_ids(self, complete):
        valid = set(range(1, 21))
        for pid, data in complete.items():
            assert pid in valid, f"Invalid player ID {pid}"
            for rd in data['rounds']:
                assert rd['opponent'] in valid, \
                    f"Player {pid}: invalid opponent {rd['opponent']}"

    def test_complete_no_self_pairings(self, complete):
        for pid, data in complete.items():
            for rnd_idx, rd in enumerate(data['rounds']):
                assert rd['opponent'] != pid, \
                    f"Player {pid} paired with self in round {rnd_idx+1}"

    def test_complete_scores_consistent(self, complete):
        for pid, data in complete.items():
            computed = compute_score_from_rounds(data['rounds'])
            assert abs(data['score'] - computed) < 0.01, \
                f"Player {pid}: header score {data['score']} != " \
                f"computed {computed}"

    def test_complete_results_symmetric(self, complete):
        for pid, data in complete.items():
            for rnd_idx, rd in enumerate(data['rounds']):
                opp = rd['opponent']
                opp_data = complete.get(opp)
                if opp_data is None or rnd_idx >= len(opp_data['rounds']):
                    continue
                opp_rd = opp_data['rounds'][rnd_idx]
                if opp_rd['opponent'] != pid:
                    continue
                complement = {'1': '0', '0': '1', '=': '='}
                expected = complement.get(opp_rd['result'])
                assert rd['result'] == expected, \
                    f"Round {rnd_idx+1}: player {pid} result " \
                    f"'{rd['result']}' vs {opp}, but opponent shows " \
                    f"'{opp_rd['result']}' (expected '{expected}')"

    def test_all_players_paired_each_round(self, complete):
        all_ids = set(range(1, 21))
        for rnd_idx in range(9):
            paired = set()
            for pid, data in complete.items():
                if rnd_idx < len(data['rounds']):
                    paired.add(pid)
                    paired.add(data['rounds'][rnd_idx]['opponent'])
            assert paired == all_ids, \
                f"Round {rnd_idx+1}: not all players paired. " \
                f"Missing: {all_ids - paired}"

    def test_complete_matches_ground_truth(self, complete, ground_truth):
        if ground_truth is None:
            pytest.skip("Ground truth file not found")
        for rnd_str, expected_games in ground_truth.items():
            rnd = int(rnd_str)
            rnd_idx = rnd - 1
            for game in expected_games:
                w, b = game['white'], game['black']
                result = game['result']

                assert w in complete, f"Player {w} missing from TRF"
                assert b in complete, f"Player {b} missing from TRF"
                assert rnd_idx < len(complete[w]['rounds']), \
                    f"Player {w} missing round {rnd}"
                assert rnd_idx < len(complete[b]['rounds']), \
                    f"Player {b} missing round {rnd}"

                w_rd = complete[w]['rounds'][rnd_idx]
                b_rd = complete[b]['rounds'][rnd_idx]

                # Verify pairing
                assert w_rd['opponent'] == b, \
                    f"Round {rnd}: expected {w} vs {b}, got {w} vs " \
                    f"{w_rd['opponent']}"
                assert b_rd['opponent'] == w, \
                    f"Round {rnd}: expected {b} vs {w}, got {b} vs " \
                    f"{b_rd['opponent']}"

                # Verify colors
                assert w_rd['color'] == 'w', \
                    f"Round {rnd}: player {w} should be white"
                assert b_rd['color'] == 'b', \
                    f"Round {rnd}: player {b} should be black"

                # Verify results
                if result == '1-0':
                    assert w_rd['result'] == '1', \
                        f"Round {rnd}: {w} vs {b}: expected white win"
                    assert b_rd['result'] == '0', \
                        f"Round {rnd}: {w} vs {b}: expected black loss"
                elif result == '0-1':
                    assert w_rd['result'] == '0', \
                        f"Round {rnd}: {w} vs {b}: expected white loss"
                    assert b_rd['result'] == '1', \
                        f"Round {rnd}: {w} vs {b}: expected black win"
                else:
                    assert w_rd['result'] == '=', \
                        f"Round {rnd}: {w} vs {b}: expected draw (white)"
                    assert b_rd['result'] == '=', \
                        f"Round {rnd}: {w} vs {b}: expected draw (black)"


# ---------------------------------------------------------------------------
# Diagnosis tests
# ---------------------------------------------------------------------------

class TestDiagnosis:

    def test_diagnosis_exists(self):
        assert os.path.isfile('/app/diagnosis.json'), \
            "/app/diagnosis.json not found"

    def test_diagnosis_valid_json(self):
        with open('/app/diagnosis.json') as f:
            data = json.load(f)
        assert isinstance(data, dict), "diagnosis.json root must be an object"

    def test_diagnosis_has_issues_array(self):
        with open('/app/diagnosis.json') as f:
            data = json.load(f)
        assert 'issues' in data, "diagnosis.json must have 'issues' key"
        assert isinstance(data['issues'], list), "'issues' must be an array"

    def test_diagnosis_documents_multiple_issues(self):
        with open('/app/diagnosis.json') as f:
            data = json.load(f)
        issues = data.get('issues', [])
        assert len(issues) >= 3, \
            f"Expected at least 3 documented issues, found {len(issues)}"
