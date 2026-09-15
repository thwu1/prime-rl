
import json
import os
import re
import shutil
import subprocess

import pytest


@pytest.fixture(scope="module")
def tlc_result():
    """Run TLC on the agent's spec with all three invariants."""
    cfg_content = (
        "CONSTANT RM = {r1, r2, r3}\n"
        "SPECIFICATION TPSpec\n"
        "CHECK_DEADLOCK FALSE\n"
        "INVARIANT TPTypeOK\n"
        "INVARIANT TPConsistent\n"
        "INVARIANT TPSafety\n"
    )
    with open("/tmp/verify_all.cfg", "w") as f:
        f.write(cfg_content)

    result = subprocess.run(
        [
            "java", "-cp", "/app/tla2tools.jar", "tlc2.TLC",
            "/app/TwoPhase.tla",
            "-config", "/tmp/verify_all.cfg",
            "-workers", "1",
            "-cleanup",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    return result


@pytest.fixture(scope="module")
def spec_content():
    """Read the agent's TwoPhase.tla file."""
    with open("/app/TwoPhase.tla", "r") as f:
        return f.read()


# ---- TLC correctness tests ----

def test_tlc_exits_successfully(tlc_result):
    """TLC model check must complete with exit code 0 (no errors)."""
    assert tlc_result.returncode == 0, (
        f"TLC exited with code {tlc_result.returncode}.\n"
        f"stdout:\n{tlc_result.stdout[-2000:]}\n"
        f"stderr:\n{tlc_result.stderr[-1000:]}"
    )


def test_distinct_state_count(tlc_result):
    """The correct Two-Phase Commit spec with 3 RMs has exactly 288 distinct states."""
    match = re.search(r"([\d,]+) distinct states found", tlc_result.stdout)
    assert match, (
        f"Could not find distinct state count in TLC output.\n"
        f"stdout:\n{tlc_result.stdout[-2000:]}"
    )
    distinct = int(match.group(1).replace(",", ""))
    assert distinct == 288, f"Expected 288 distinct states, got {distinct}"


def test_total_state_count(tlc_result):
    """The correct Two-Phase Commit spec with 3 RMs generates exactly 1146 states."""
    match = re.search(r"([\d,]+) states generated", tlc_result.stdout)
    assert match, (
        f"Could not find total state count in TLC output.\n"
        f"stdout:\n{tlc_result.stdout[-2000:]}"
    )
    total = int(match.group(1).replace(",", ""))
    assert total == 1146, f"Expected 1146 total states, got {total}"


# ---- TPSafety invariant design tests ----

def test_tpsafety_defined(spec_content):
    """TwoPhase.tla must contain a TPSafety operator definition."""
    assert re.search(r"TPSafety\s*==", spec_content), (
        "Could not find 'TPSafety ==' definition in /app/TwoPhase.tla"
    )


def test_tpsafety_meaningful(spec_content):
    """TPSafety must reference tmState and msgs — not just restate TPConsistent."""
    # Extract the TPSafety definition block
    match = re.search(
        r"(TPSafety\s*==[\s\S]*?)(?=\n[A-Z]\w*[\s(==]|\n----|=====|\Z)",
        spec_content,
    )
    assert match, "Could not extract TPSafety definition"
    tpsafety_body = match.group(1)

    assert "tmState" in tpsafety_body, (
        "TPSafety must reference tmState to assert the TM is committed"
    )
    assert "msgs" in tpsafety_body or '"Commit"' in tpsafety_body, (
        "TPSafety must reference msgs or Commit message presence"
    )


def test_tpsafety_catches_tmabort_mutation(spec_content):
    """
    TPSafety must detect a violation when TMAbort sends a Commit message
    instead of Abort. This validates that TPSafety is strong enough to
    catch the causal-chain violation described in the task.
    """
    # Mutate: change TMAbort's Abort message to Commit.
    # The pattern [type |-> "Abort"]} uniquely targets the TMAbort msg send
    # (RMRcvAbortMsg uses [type |-> "Abort"] \in msgs — no trailing })
    mutated = re.sub(
        r'(\[type\s*\|->\s*)"Abort"(\s*\]\s*\})',
        r'\1"Commit"\2',
        spec_content,
        count=1,
    )
    if mutated == spec_content:
        pytest.fail(
            "Could not apply mutation to TMAbort. "
            'Expected to find [type |-> "Abort"]} pattern in the spec.'
        )

    with open("/tmp/mutated_tp.tla", "w") as f:
        f.write(mutated)
    shutil.copy("/app/TCommit.tla", "/tmp/TCommit.tla")

    with open("/tmp/mutated_tp.cfg", "w") as f:
        f.write(
            "CONSTANT RM = {r1, r2, r3}\n"
            "SPECIFICATION TPSpec\n"
            "CHECK_DEADLOCK FALSE\n"
            "INVARIANT TPSafety\n"
        )

    result = subprocess.run(
        [
            "java", "-cp", "/app/tla2tools.jar", "tlc2.TLC",
            "/tmp/mutated_tp.tla",
            "-config", "/tmp/mutated_tp.cfg",
            "-workers", "1",
            "-cleanup",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/tmp",
    )
    assert result.returncode != 0, (
        "TPSafety should detect a violation when TMAbort sends a Commit "
        "message instead of Abort. Your TPSafety invariant is too weak — "
        "it must assert that committed RMs require tmState = \"committed\"."
    )


# ---- Configuration completeness test ----

def test_cfg_complete():
    """The agent's .cfg must list all three invariants and disable deadlock."""
    with open("/app/TwoPhase.cfg", "r") as f:
        cfg = f.read()

    for inv in ("TPTypeOK", "TPConsistent", "TPSafety"):
        assert re.search(rf"INVARIANT\s+{inv}", cfg), (
            f"Config /app/TwoPhase.cfg missing INVARIANT {inv}"
        )

    assert re.search(r"CHECK_DEADLOCK", cfg), (
        "Config must include CHECK_DEADLOCK FALSE"
    )


# ---- Results file tests ----

def test_results_json_exists():
    """The agent must write /app/results.json."""
    assert os.path.exists("/app/results.json"), "/app/results.json not found"


def test_results_json_schema_and_values():
    """results.json must have correct schema and match the TLC output."""
    with open("/app/results.json", "r") as f:
        data = json.load(f)

    for key in ("distinct_states", "total_states", "state_depth"):
        assert key in data, f"results.json missing key '{key}'"
        assert isinstance(data[key], int), (
            f"results.json['{key}'] must be an integer, got {type(data[key]).__name__}"
        )

    assert data["distinct_states"] == 288, (
        f"results.json distinct_states should be 288, got {data['distinct_states']}"
    )
    assert data["total_states"] == 1146, (
        f"results.json total_states should be 1146, got {data['total_states']}"
    )
    assert data["state_depth"] == 11, (
        f"results.json state_depth should be 11, got {data['state_depth']}"
    )
