
import subprocess
import os
import re
import json
import pytest

SPEC_PATH = "/app/VotingProtocol.tla"
CFG_PATH = "/app/VotingProtocol.cfg"
TLA2TOOLS = "/usr/local/lib/tla2tools.jar"


def run_tlc(timeout=180):
    """Run TLC model checker on the specification with deadlock checking disabled."""
    cmd = [
        "java", "-jar", TLA2TOOLS,
        SPEC_PATH,
        "-config", CFG_PATH,
        "-deadlock",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd="/app",
    )
    return result.returncode, result.stdout, result.stderr


def run_explorer(*args, timeout=120):
    """Run the Python state space explorer with given arguments."""
    cmd = ["python3", "/app/explorer.py"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── File existence checks ────────────────────────────────────────────

class TestSpecFileExists:
    def test_spec_exists(self):
        assert os.path.exists(SPEC_PATH), f"{SPEC_PATH} not found"

    def test_cfg_exists(self):
        assert os.path.exists(CFG_PATH), f"{CFG_PATH} not found"

    def test_tla2tools_exists(self):
        assert os.path.exists(TLA2TOOLS), f"{TLA2TOOLS} not found"


# ── Structural anti-cheat checks on the TLA+ spec ───────────────────

class TestSpecStructure:
    def setup_method(self):
        with open(SPEC_PATH) as f:
            self.content = f.read()

    def test_has_propose_action(self):
        assert "Propose" in self.content, "Spec must contain Propose action"

    def test_has_castvote_action(self):
        assert "CastVote" in self.content, "Spec must contain CastVote action"

    def test_has_decide_action(self):
        assert "Decide" in self.content, "Spec must contain Decide action"

    def test_has_agreement_invariant(self):
        assert "Agreement" in self.content, "Spec must define Agreement invariant"

    def test_has_required_variables(self):
        for var in ["proposed", "votes", "decided", "hasVotedFor"]:
            assert var in self.content, f"Variable '{var}' missing from spec"

    def test_has_quorum_concept(self):
        assert any(kw in self.content for kw in ["Quorum", "Majority", "div"]), \
            "Spec must reference a quorum or majority concept"

    def test_config_checks_agreement(self):
        with open(CFG_PATH) as f:
            cfg = f.read()
        assert "Agreement" in cfg, "TLC config must check the Agreement invariant"


# ── TLC model checking ──────────────────────────────────────────────

class TestTLCPasses:
    def test_no_invariant_violation(self):
        rc, stdout, stderr = run_tlc()
        combined = stdout + "\n" + stderr
        assert "Model checking completed. No error has been found." in combined, (
            f"TLC did not complete successfully. Output (last 3000 chars):\n"
            f"{combined[-3000:]}"
        )

    def test_nontrivial_state_space(self):
        rc, stdout, stderr = run_tlc()
        combined = stdout + "\n" + stderr
        match = re.search(r"(\d+)\s+distinct states found", combined)
        assert match is not None, (
            f"Could not find distinct state count in TLC output:\n"
            f"{combined[-3000:]}"
        )
        assert int(match.group(1)) >= 50, (
            f"State space too small ({match.group(1)} distinct states). "
            f"Spec may have been trivially simplified."
        )


# ── Bug report ───────────────────────────────────────────────────────

class TestBugReport:
    def test_report_exists(self):
        assert os.path.exists("/app/bugs_found.txt"), \
            "Bug report file /app/bugs_found.txt not found"

    def test_report_has_substance(self):
        with open("/app/bugs_found.txt") as f:
            content = f.read()
        assert len(content) >= 100, "Bug report is too short (< 100 chars)"
        keywords = ["vote", "voting", "quorum", "majority", "propose", "decide",
                     "cast", "bug", "fix", "agreement"]
        matches = sum(1 for kw in keywords if kw in content.lower())
        assert matches >= 3, (
            f"Bug report should discuss the voting protocol bugs. "
            f"Only found {matches} relevant keywords."
        )


# ── Explorer: file and code quality checks ───────────────────────────

class TestExplorerExists:
    def test_explorer_file_exists(self):
        assert os.path.exists("/app/explorer.py"), \
            "Explorer not found at /app/explorer.py"

    def test_explorer_has_substance(self):
        """Explorer must contain real protocol logic, not be trivially short."""
        with open("/app/explorer.py") as f:
            source = f.read()
        lines = [l for l in source.strip().split("\n")
                 if l.strip() and not l.strip().startswith("#")]
        assert len(lines) >= 50, (
            f"Explorer has only {len(lines)} non-comment lines — "
            f"too simple for a BFS state space explorer"
        )

    def test_explorer_implements_search(self):
        """Explorer must contain BFS/search infrastructure."""
        with open("/app/explorer.py") as f:
            source = f.read()
        search_keywords = ["deque", "queue", "Queue", "BFS", "bfs",
                           "visited", "explored", "seen"]
        assert any(kw in source for kw in search_keywords), \
            "Explorer must implement state space exploration (BFS/DFS)"

    def test_explorer_implements_transitions(self):
        """Explorer must implement all three protocol transitions."""
        with open("/app/explorer.py") as f:
            src_lower = f.read().lower()
        assert "propose" in src_lower, "Must implement Propose transition"
        assert "vote" in src_lower, "Must implement CastVote transition"
        assert "decide" in src_lower, "Must implement Decide transition"


# ── Explorer: output format and schema ───────────────────────────────

class TestExplorerOutput:
    def test_runs_successfully(self):
        r = run_explorer("--nodes", "3", "--values", "2")
        assert r.returncode == 0, f"Explorer failed:\n{r.stderr}"

    def test_output_is_valid_json(self):
        r = run_explorer("--nodes", "3", "--values", "2")
        data = json.loads(r.stdout.strip())
        assert isinstance(data, dict)

    def test_output_has_required_fields(self):
        r = run_explorer("--nodes", "3", "--values", "2")
        data = json.loads(r.stdout.strip())
        for field in ["distinct_states", "violation_found", "violation_type", "max_depth"]:
            assert field in data, f"Missing field '{field}' in explorer output"
        assert isinstance(data["distinct_states"], int)
        assert isinstance(data["violation_found"], bool)
        assert isinstance(data["max_depth"], int)

    def test_no_violation_found(self):
        r = run_explorer("--nodes", "3", "--values", "2")
        data = json.loads(r.stdout.strip())
        assert data["violation_found"] is False, \
            f"Explorer reports a violation: {data.get('violation_type')}"
        assert data["violation_type"] is None

    def test_max_depth_positive(self):
        r = run_explorer("--nodes", "3", "--values", "2")
        data = json.loads(r.stdout.strip())
        assert data["max_depth"] > 0, "max_depth must be positive"


# ── Explorer: correctness validation ────────────────────────────────

class TestExplorerCorrectness:
    def test_state_count_matches_tlc(self):
        """Explorer's distinct state count must exactly match TLC's count."""
        _, stdout, stderr = run_tlc()
        combined = stdout + "\n" + stderr
        match = re.search(r"(\d+)\s+distinct states found", combined)
        assert match, "Could not extract TLC state count"
        tlc_count = int(match.group(1))

        r = run_explorer("--nodes", "3", "--values", "2")
        assert r.returncode == 0, f"Explorer failed:\n{r.stderr}"
        data = json.loads(r.stdout.strip())

        assert data["distinct_states"] == tlc_count, (
            f"Explorer found {data['distinct_states']} distinct states "
            f"but TLC found {tlc_count}. Python implementation diverges from TLA+ spec."
        )

    def test_small_config_exact_count(self):
        """For 2 nodes / 1 value the protocol has exactly 8 reachable states."""
        r = run_explorer("--nodes", "2", "--values", "1")
        assert r.returncode == 0, f"Explorer failed:\n{r.stderr}"
        data = json.loads(r.stdout.strip())
        assert data["distinct_states"] == 8, (
            f"Expected 8 states for 2 nodes / 1 value, got {data['distinct_states']}"
        )
        assert data["violation_found"] is False
        assert data["max_depth"] == 3, (
            f"Expected max_depth 3 for 2 nodes / 1 value, got {data['max_depth']}"
        )

    def test_larger_config_has_more_states(self):
        """3 nodes / 2 values must yield more states than 2 nodes / 1 value."""
        r_small = run_explorer("--nodes", "2", "--values", "1")
        r_large = run_explorer("--nodes", "3", "--values", "2")
        small = json.loads(r_small.stdout.strip())["distinct_states"]
        large = json.loads(r_large.stdout.strip())["distinct_states"]
        assert large > small, (
            f"3n/2v ({large} states) should exceed 2n/1v ({small} states)"
        )
