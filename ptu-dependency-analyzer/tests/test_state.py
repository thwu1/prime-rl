
import subprocess
import json
import pytest

ANALYZER = "/app/ptu_analyzer.py"
ALPHA = "/app/sessions/session_alpha.txt"
BETA = "/app/sessions/session_beta.txt"
GAMMA = "/app/sessions/session_gamma.txt"


def run_analyzer(session, command, arg=None):
    cmd = ["python3", ANALYZER, session, command]
    if arg is not None:
        cmd.append(str(arg))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"ptu_analyzer.py exited {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout.strip())


# ========== Session Alpha: deps ==========

class TestAlphaDeps:
    def test_deps_0(self):
        assert run_analyzer(ALPHA, "deps", 0) == {"deps": []}

    def test_deps_1(self):
        assert run_analyzer(ALPHA, "deps", 1) == {"deps": [0]}

    def test_deps_3(self):
        assert run_analyzer(ALPHA, "deps", 3) == {"deps": [0, 1, 2]}

    def test_deps_5(self):
        assert run_analyzer(ALPHA, "deps", 5) == {"deps": [1, 4]}

    def test_deps_7(self):
        assert run_analyzer(ALPHA, "deps", 7) == {"deps": [1, 5]}

    def test_deps_8(self):
        assert run_analyzer(ALPHA, "deps", 8) == {"deps": [1, 2, 3, 4]}


# ========== Session Alpha: rdeps ==========

class TestAlphaRdeps:
    def test_rdeps_0(self):
        assert run_analyzer(ALPHA, "rdeps", 0) == {"rdeps": [1, 2, 3]}

    def test_rdeps_1(self):
        assert run_analyzer(ALPHA, "rdeps", 1) == {"rdeps": [2, 3, 5, 6, 7, 8]}

    def test_rdeps_4(self):
        assert run_analyzer(ALPHA, "rdeps", 4) == {"rdeps": [5, 8]}

    def test_rdeps_8(self):
        assert run_analyzer(ALPHA, "rdeps", 8) == {"rdeps": []}


# ========== Session Alpha: undo-cascade ==========

class TestAlphaUndoCascade:
    def test_undo_0(self):
        assert run_analyzer(ALPHA, "undo-cascade", 0) == {
            "cascade": [1, 2, 3, 5, 6, 7, 8]
        }

    def test_undo_4(self):
        assert run_analyzer(ALPHA, "undo-cascade", 4) == {
            "cascade": [5, 7, 8]
        }

    def test_undo_6(self):
        assert run_analyzer(ALPHA, "undo-cascade", 6) == {"cascade": []}


# ========== Session Alpha: minimal-replay ==========

class TestAlphaMinimalReplay:
    def test_replay_8(self):
        assert run_analyzer(ALPHA, "minimal-replay", 8) == {
            "replay": [0, 1, 2, 3, 4, 8]
        }

    def test_replay_7(self):
        assert run_analyzer(ALPHA, "minimal-replay", 7) == {
            "replay": [0, 1, 4, 5, 7]
        }

    def test_replay_4(self):
        assert run_analyzer(ALPHA, "minimal-replay", 4) == {"replay": [4]}


# ========== Session Alpha: dead-ptus & critical-path ==========

class TestAlphaGraph:
    def test_dead_ptus(self):
        assert run_analyzer(ALPHA, "dead-ptus") == {"dead": [6, 7, 8]}

    def test_critical_path(self):
        assert run_analyzer(ALPHA, "critical-path") == {
            "path": [0, 1, 2, 3, 8],
            "length": 5,
        }


# ========== Session Beta: deps ==========

class TestBetaDeps:
    def test_deps_0(self):
        assert run_analyzer(BETA, "deps", 0) == {"deps": []}

    def test_deps_5(self):
        assert run_analyzer(BETA, "deps", 5) == {"deps": [3, 4]}

    def test_deps_6(self):
        assert run_analyzer(BETA, "deps", 6) == {"deps": [0, 1, 5]}

    def test_deps_7(self):
        assert run_analyzer(BETA, "deps", 7) == {"deps": [1, 2, 5, 6]}

    def test_deps_9(self):
        assert run_analyzer(BETA, "deps", 9) == {"deps": [7, 8]}


# ========== Session Beta: undo-cascade ==========

class TestBetaUndoCascade:
    def test_undo_3(self):
        assert run_analyzer(BETA, "undo-cascade", 3) == {
            "cascade": [5, 6, 7, 9]
        }

    def test_undo_0(self):
        assert run_analyzer(BETA, "undo-cascade", 0) == {
            "cascade": [1, 2, 6, 7, 8, 9]
        }


# ========== Session Beta: minimal-replay ==========

class TestBetaMinimalReplay:
    def test_replay_9(self):
        assert run_analyzer(BETA, "minimal-replay", 9) == {
            "replay": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        }

    def test_replay_7(self):
        assert run_analyzer(BETA, "minimal-replay", 7) == {
            "replay": [0, 1, 2, 3, 4, 5, 6, 7]
        }


# ========== Session Beta: dead-ptus & critical-path ==========

class TestBetaGraph:
    def test_dead_ptus(self):
        assert run_analyzer(BETA, "dead-ptus") == {"dead": [9]}

    def test_critical_path(self):
        assert run_analyzer(BETA, "critical-path") == {
            "path": [0, 1, 6, 7, 9],
            "length": 5,
        }


# ========== Session Gamma: deps ==========

class TestGammaDeps:
    def test_deps_0(self):
        assert run_analyzer(GAMMA, "deps", 0) == {"deps": []}

    def test_deps_1(self):
        assert run_analyzer(GAMMA, "deps", 1) == {"deps": []}

    def test_deps_2(self):
        assert run_analyzer(GAMMA, "deps", 2) == {"deps": [1]}

    def test_deps_6(self):
        assert run_analyzer(GAMMA, "deps", 6) == {"deps": [2, 5]}

    def test_deps_8(self):
        assert run_analyzer(GAMMA, "deps", 8) == {"deps": [2, 3, 4, 5, 6, 7]}

    def test_deps_10(self):
        assert run_analyzer(GAMMA, "deps", 10) == {"deps": [0, 4, 6, 7, 9]}

    def test_deps_12(self):
        assert run_analyzer(GAMMA, "deps", 12) == {"deps": [2, 5, 7, 8, 9]}


# ========== Session Gamma: rdeps ==========

class TestGammaRdeps:
    def test_rdeps_0(self):
        assert run_analyzer(GAMMA, "rdeps", 0) == {"rdeps": [9, 10]}

    def test_rdeps_2(self):
        assert run_analyzer(GAMMA, "rdeps", 2) == {
            "rdeps": [3, 4, 5, 6, 8, 11, 12]
        }

    def test_rdeps_7(self):
        assert run_analyzer(GAMMA, "rdeps", 7) == {"rdeps": [8, 10, 12]}

    def test_rdeps_12(self):
        assert run_analyzer(GAMMA, "rdeps", 12) == {"rdeps": []}


# ========== Session Gamma: undo-cascade ==========

class TestGammaUndoCascade:
    def test_undo_1(self):
        assert run_analyzer(GAMMA, "undo-cascade", 1) == {
            "cascade": [2, 3, 4, 5, 6, 7, 8, 10, 11, 12]
        }

    def test_undo_5(self):
        assert run_analyzer(GAMMA, "undo-cascade", 5) == {
            "cascade": [6, 7, 8, 10, 11, 12]
        }

    def test_undo_9(self):
        assert run_analyzer(GAMMA, "undo-cascade", 9) == {
            "cascade": [10, 12]
        }

    def test_undo_11(self):
        assert run_analyzer(GAMMA, "undo-cascade", 11) == {"cascade": []}


# ========== Session Gamma: minimal-replay ==========

class TestGammaMinimalReplay:
    def test_replay_8(self):
        assert run_analyzer(GAMMA, "minimal-replay", 8) == {
            "replay": [1, 2, 3, 4, 5, 6, 7, 8]
        }

    def test_replay_10(self):
        assert run_analyzer(GAMMA, "minimal-replay", 10) == {
            "replay": [0, 1, 2, 4, 5, 6, 7, 9, 10]
        }

    def test_replay_12(self):
        assert run_analyzer(GAMMA, "minimal-replay", 12) == {
            "replay": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12]
        }


# ========== Session Gamma: dead-ptus & critical-path ==========

class TestGammaGraph:
    def test_dead_ptus(self):
        assert run_analyzer(GAMMA, "dead-ptus") == {"dead": [10, 11, 12]}

    def test_critical_path(self):
        assert run_analyzer(GAMMA, "critical-path") == {
            "path": [1, 2, 5, 6, 7, 8, 12],
            "length": 7,
        }


# ========== Compilation Tiers (all sessions) ==========

class TestCompilationTiers:
    def test_alpha_tiers(self):
        assert run_analyzer(ALPHA, "compilation-tiers") == {
            "tiers": [[0, 4], [1], [2, 5, 6], [3, 7], [8]]
        }

    def test_beta_tiers(self):
        assert run_analyzer(BETA, "compilation-tiers") == {
            "tiers": [[0, 3, 4], [1, 2, 5, 8], [6], [7], [9]]
        }

    def test_gamma_tiers(self):
        assert run_analyzer(GAMMA, "compilation-tiers") == {
            "tiers": [
                [0, 1],
                [2, 9],
                [3, 4, 5],
                [6],
                [7, 11],
                [8, 10],
                [12],
            ]
        }
