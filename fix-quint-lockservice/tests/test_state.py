
import subprocess
import json
import os
import re

QNT_FILE = "/app/lock_manager.qnt"
DIAGNOSIS_FILE = "/app/diagnosis.json"

INVARIANTS = [
    "singleLeader",
    "epochMonotonicity",
    "fencingTokenOrder",
    "splitBrainPrevention",
    "voteConsistency",
]


def run_quint(args, timeout=120):
    """Run a quint CLI command and return the result."""
    return subprocess.run(
        ["quint"] + args,
        capture_output=True, text=True, timeout=timeout
    )


def read_spec():
    with open(QNT_FILE) as f:
        return f.read()


def extract_action_body(content, action_name):
    """Extract the full text of an action definition."""
    pattern = r'action\s+' + re.escape(action_name) + r'\b'
    start_match = re.search(pattern, content)
    if not start_match:
        return ""
    start = start_match.start()
    rest = content[start_match.end():]
    next_def = re.search(r'\n\s*(?:action|val)\s+\w', rest)
    if next_def:
        end = start_match.end() + next_def.start()
    else:
        module_end = rest.find('\n}')
        end = start_match.end() + module_end if module_end != -1 else len(content)
    return content[start:end]


def extract_invariant_body(content, inv_name):
    """Extract the body of an invariant definition (everything after '=')."""
    pattern = r'val\s+' + re.escape(inv_name) + r'\s*=(.*?)(?=\n\s*val\s+\w|\n\})'
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


# ============================================================
# Test: spec file exists and is non-trivial
# ============================================================
class TestSpecExists:
    def test_spec_file_exists(self):
        assert os.path.exists(QNT_FILE), f"{QNT_FILE} not found"

    def test_spec_is_substantial(self):
        assert os.path.getsize(QNT_FILE) > 2000, "Spec file is too small"


# ============================================================
# Test: quint typecheck passes
# ============================================================
class TestTypecheck:
    def test_quint_typecheck_passes(self):
        result = run_quint(["typecheck", QNT_FILE])
        assert result.returncode == 0, \
            f"Typecheck failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"


# ============================================================
# Test: simulation — each invariant passes quint run
# ============================================================
class TestSimulation:
    def test_singleLeader_simulation(self):
        result = run_quint([
            "run", QNT_FILE,
            "--invariant=singleLeader",
            "--max-steps=20", "--max-samples=200"
        ])
        assert result.returncode == 0, \
            f"singleLeader violated:\n{result.stdout}\n{result.stderr}"

    def test_epochMonotonicity_simulation(self):
        result = run_quint([
            "run", QNT_FILE,
            "--invariant=epochMonotonicity",
            "--max-steps=20", "--max-samples=200"
        ])
        assert result.returncode == 0, \
            f"epochMonotonicity violated:\n{result.stdout}\n{result.stderr}"

    def test_fencingTokenOrder_simulation(self):
        result = run_quint([
            "run", QNT_FILE,
            "--invariant=fencingTokenOrder",
            "--max-steps=20", "--max-samples=200"
        ])
        assert result.returncode == 0, \
            f"fencingTokenOrder violated:\n{result.stdout}\n{result.stderr}"

    def test_splitBrainPrevention_simulation(self):
        result = run_quint([
            "run", QNT_FILE,
            "--invariant=splitBrainPrevention",
            "--max-steps=20", "--max-samples=200"
        ])
        assert result.returncode == 0, \
            f"splitBrainPrevention violated:\n{result.stdout}\n{result.stderr}"

    def test_voteConsistency_simulation(self):
        result = run_quint([
            "run", QNT_FILE,
            "--invariant=voteConsistency",
            "--max-steps=20", "--max-samples=200"
        ])
        assert result.returncode == 0, \
            f"voteConsistency violated:\n{result.stdout}\n{result.stderr}"


# ============================================================
# Test: structural checks — action fixes are correct
# ============================================================
class TestActionFixes:
    def test_castVote_updates_voter_epoch(self):
        """castVote must update the voter's epoch to the candidate's epoch."""
        content = read_spec()
        body = extract_action_body(content, "castVote")
        assert body, "Could not find castVote body"
        assert "epoch.set" in body, \
            "castVote must update the voter's epoch via epoch.set"

    def test_grantLock_increments_fencing_token(self):
        """grantLock must increment fencingToken on each grant."""
        content = read_spec()
        body = extract_action_body(content, "grantLock")
        assert body, "Could not find grantLock body"
        assert "fencingToken + 1" in body or "fencingToken+1" in body, \
            "grantLock must increment fencingToken"

    def test_partitionNode_steps_down(self):
        """partitionNode must step down leader/candidate to follower."""
        content = read_spec()
        body = extract_action_body(content, "partitionNode")
        assert body, "Could not find partitionNode body"
        assert "role.set" in body and '"follower"' in body, \
            "partitionNode must set the node's role to follower via role.set"


# ============================================================
# Test: structural checks — invariant fixes are correct
# ============================================================
class TestInvariantFixes:
    def test_epochMonotonicity_uses_gte(self):
        """epochMonotonicity must use >= (not >) for leader vs lockEpoch."""
        content = read_spec()
        body = extract_invariant_body(content, "epochMonotonicity")
        assert body, "Could not find epochMonotonicity body"
        assert re.search(r'>=\s*lockEpoch', body), \
            "epochMonotonicity must use >= (not >) for leader epoch vs lockEpoch"

    def test_voteConsistency_is_nontrivial(self):
        """voteConsistency must be a real predicate, not trivially true."""
        content = read_spec()
        body = extract_invariant_body(content, "voteConsistency")
        assert body, "Could not find voteConsistency body"
        assert body != "true" and body != "false", \
            "voteConsistency must not be trivially true or false"
        assert "votesReceived" in body, \
            "voteConsistency must reference votesReceived"
        assert "epoch" in body, \
            "voteConsistency must reference epoch for same-epoch comparison"
        assert "intersect" in body, \
            "voteConsistency must check set intersection for disjointness"


# ============================================================
# Test: diagnosis file
# ============================================================
class TestDiagnosis:
    def test_diagnosis_exists(self):
        assert os.path.exists(DIAGNOSIS_FILE), f"{DIAGNOSIS_FILE} not found"

    def test_diagnosis_structure(self):
        with open(DIAGNOSIS_FILE) as f:
            diagnosis = json.load(f)
        assert isinstance(diagnosis, list), "diagnosis.json must be a JSON array"
        assert len(diagnosis) >= 5, \
            f"Expected at least 5 bug reports, got {len(diagnosis)}"

        definitions_found = set()
        for entry in diagnosis:
            assert "definition" in entry, "Each entry must have 'definition'"
            assert "bug" in entry, "Each entry must have 'bug'"
            assert "fix" in entry, "Each entry must have 'fix'"
            assert isinstance(entry["bug"], str) and len(entry["bug"]) >= 60, \
                f"'bug' for {entry.get('definition', '?')} must be >= 60 chars"
            assert isinstance(entry["fix"], str) and len(entry["fix"]) >= 60, \
                f"'fix' for {entry.get('definition', '?')} must be >= 60 chars"
            definitions_found.add(entry["definition"])

        required = {"castVote", "grantLock", "partitionNode",
                     "epochMonotonicity", "voteConsistency"}
        for def_name in required:
            found = any(def_name in d for d in definitions_found)
            assert found, f"Diagnosis missing report for: {def_name}"
