"""
Tests for the collaborative editing trace merger.

"""

import json
import os
import random
import subprocess
import tempfile

import pytest

TRACE_DIR = "/app/traces"
APP_DIR = "/app"
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 30

# Expected outputs for the static trace files.
_ORACLE = {
    "linear.json": "Hello, World!",
    "simple_fork.json": ">> Hello World",
    "diamond.json": "[ABxxCDyyE]",
    "conflict.json": "aXYb",
    "delete_merge.json": "ad",
    "interleave.json": "aZd",
    "cascade.json": "#>abcXdef!",
    "multi_agent.json": "A quick red fox jumps",
}

# Traces that contain at least one merge transaction (multi-parent).
_CONCURRENT_TRACES = [
    n for n in _ORACLE if n != "linear.json"
]


@pytest.fixture(scope="session", autouse=True)
def build_project():
    """Build the Rust project once before all tests."""
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=BUILD_TIMEOUT,
    )
    assert result.returncode == 0, (
        f"cargo build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def _run_trace(trace_path: str) -> str:
    """Run the merger binary on a trace file and return stdout."""
    result = subprocess.run(
        ["cargo", "run", "--release", "--", trace_path],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, (
        f"Execution failed on {os.path.basename(trace_path)}:\n"
        f"stderr: {result.stderr}"
    )
    return result.stdout


def _load_trace(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


# ── Static trace correctness ─────────────────────────────────────────


@pytest.mark.parametrize(
    "trace_name,expected",
    list(_ORACLE.items()),
    ids=lambda x: x if isinstance(x, str) and x.endswith(".json") else "",
)
def test_static_trace(trace_name, expected):
    """Output must match the oracle for every shipped trace."""
    path = os.path.join(TRACE_DIR, trace_name)
    assert os.path.isfile(path), f"Trace file missing: {path}"
    output = _run_trace(path)
    assert output == expected, (
        f"Mismatch for {trace_name}:\n"
        f"  expected: {expected!r}\n"
        f"  got:      {output!r}"
    )


# ── Convergence: parent-order independence on static traces ──────────


@pytest.mark.parametrize("trace_name", _CONCURRENT_TRACES)
def test_static_convergence(trace_name):
    """Reversing parent lists of merge txns must still produce the
    correct oracle output, proving order-independence."""
    expected = _ORACLE[trace_name]
    trace = _load_trace(os.path.join(TRACE_DIR, trace_name))

    modified = json.loads(json.dumps(trace))
    for txn in modified["txns"]:
        if len(txn["parents"]) > 1:
            txn["parents"] = list(reversed(txn["parents"]))

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", dir="/tmp", delete=False
    ) as f:
        json.dump(modified, f)
        tmp_path = f.name

    try:
        output = _run_trace(tmp_path)
        assert output == expected, (
            f"Convergence failure for {trace_name} with reversed parents:\n"
            f"  expected: {expected!r}\n"
            f"  got:      {output!r}"
        )
    finally:
        os.unlink(tmp_path)


# ── Dynamic tests: generated at test time ────────────────────────────


def _make_sequential_trace(patches_per_txn):
    """Build a single-agent linear trace from a list of patch-lists."""
    txns = []
    for i, patches in enumerate(patches_per_txn):
        txns.append({
            "parents": [i - 1] if i > 0 else [],
            "agent": 0,
            "patches": patches,
        })
    return {"numAgents": 1, "txns": txns}


def _run_on_trace_dict(trace: dict) -> str:
    """Write a trace dict to a temp file, run the binary, return output."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", dir="/tmp", delete=False
    ) as f:
        json.dump(trace, f)
        tmp_path = f.name
    try:
        return _run_trace(tmp_path)
    finally:
        os.unlink(tmp_path)


def test_dynamic_sequential():
    """Generate a random sequential trace at test time; verify output
    against a Python reference replayer.  The trace does not exist
    anywhere in the Docker image."""
    rng = random.Random(7729)
    ops = []
    doc = ""
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"

    for _ in range(25):
        if len(doc) == 0 or rng.random() < 0.55:
            pos = rng.randint(0, len(doc))
            k = rng.randint(1, 6)
            chars = "".join(rng.choices(alphabet, k=k))
            ops.append([[pos, 0, chars]])
            doc = doc[:pos] + chars + doc[pos:]
        else:
            pos = rng.randint(0, len(doc) - 1)
            del_len = rng.randint(1, min(4, len(doc) - pos))
            ops.append([[pos, del_len]])
            doc = doc[:pos] + doc[pos + del_len:]

    trace = _make_sequential_trace(ops)
    output = _run_on_trace_dict(trace)
    assert output == doc, (
        f"Dynamic sequential mismatch:\n"
        f"  expected ({len(doc)} chars): {doc!r}\n"
        f"  got      ({len(output)} chars): {output!r}"
    )


def test_dynamic_convergence():
    """Fork two branches that insert at the same position; verify that
    swapping parent order produces identical output and both inserts
    are present."""
    trace = {
        "numAgents": 2,
        "txns": [
            {"parents": [], "agent": 0,
             "patches": [[0, 0, "PREFIX_SUFFIX"]]},
            {"parents": [0], "agent": 0,
             "patches": [[7, 0, "_alpha_"]]},
            {"parents": [0], "agent": 1,
             "patches": [[7, 0, "_beta_"]]},
            {"parents": [1, 2], "agent": 0, "patches": []},
        ],
    }

    trace_rev = json.loads(json.dumps(trace))
    trace_rev["txns"][3]["parents"] = [2, 1]

    out_fwd = _run_on_trace_dict(trace)
    out_rev = _run_on_trace_dict(trace_rev)

    assert out_fwd == out_rev, (
        f"Convergence failure:\n"
        f"  forward:  {out_fwd!r}\n"
        f"  reversed: {out_rev!r}"
    )
    assert "_alpha_" in out_fwd, "Agent 0 insert missing from merged output"
    assert "_beta_" in out_fwd, "Agent 1 insert missing from merged output"
    assert out_fwd.startswith("PREFIX_"), "Prefix corrupted"
    assert out_fwd.endswith("SUFFIX"), "Suffix corrupted"


def test_dynamic_concurrent_delete():
    """Two branches delete overlapping ranges; union of deletes must be
    applied exactly once."""
    trace = {
        "numAgents": 2,
        "txns": [
            {"parents": [], "agent": 0,
             "patches": [[0, 0, "ABCDEFGH"]]},
            # Agent 0 deletes BCD (pos 1, len 3)
            {"parents": [0], "agent": 0, "patches": [[1, 3]]},
            # Agent 1 deletes CDE (pos 2, len 3)
            {"parents": [0], "agent": 1, "patches": [[2, 3]]},
            {"parents": [1, 2], "agent": 0, "patches": []},
        ],
    }

    output = _run_on_trace_dict(trace)
    # Union of {B,C,D} and {C,D,E} = {B,C,D,E}; remaining = AFGH
    assert output == "AFGH", (
        f"Concurrent delete: expected 'AFGH', got {output!r}"
    )


def test_dynamic_insert_ordering():
    """Two agents insert multi-character strings at the same position;
    the lower-indexed agent's text must appear leftward."""
    trace = {
        "numAgents": 2,
        "txns": [
            {"parents": [], "agent": 0,
             "patches": [[0, 0, "XY"]]},
            {"parents": [0], "agent": 0,
             "patches": [[1, 0, "abc"]]},
            {"parents": [0], "agent": 1,
             "patches": [[1, 0, "123"]]},
            {"parents": [1, 2], "agent": 0, "patches": []},
        ],
    }

    output = _run_on_trace_dict(trace)
    assert output == "Xabc123Y", (
        f"Insert ordering: expected 'Xabc123Y', got {output!r}"
    )


def test_dynamic_three_way_delete_insert():
    """Three agents: one inserts, one deletes overlapping region,
    one deletes a different region.  Merged result must retain the
    new insert and apply both deletions."""
    trace = {
        "numAgents": 3,
        "txns": [
            {"parents": [], "agent": 0,
             "patches": [[0, 0, "0123456789"]]},
            # Agent 0: insert "NEW" at pos 5
            {"parents": [0], "agent": 0,
             "patches": [[5, 0, "NEW"]]},
            # Agent 1: delete chars at pos 3..6 (chars '3','4','5')
            {"parents": [0], "agent": 1,
             "patches": [[3, 3]]},
            # Agent 2: delete chars at pos 7..9 (chars '7','8')
            {"parents": [0], "agent": 2,
             "patches": [[7, 2]]},
            {"parents": [1, 2, 3], "agent": 0, "patches": []},
        ],
    }

    output = _run_on_trace_dict(trace)
    # Agent 0 inserts "NEW" between '4' and '5' → '01234NEW56789'
    # but that's the per-agent view.  In the base "0123456789":
    # Agent 0 inserts at pos 5 → between '4' and '5'.
    # Agent 1 deletes pos 3,4,5 → '3','4','5' gone.
    # Agent 2 deletes pos 7,8 → '7','8' gone.
    # Union of deletes: {3,4,5,7,8}.
    # NEW is a fresh insert between origin '4' and '5'.
    # '4' is deleted, '5' is deleted, but NEW survives (fresh chars).
    # Remaining originals: 0,1,2,6,9  plus NEW in the right spot.
    # Order: 0,1,2,NEW,6,9
    assert output == "012NEW69", (
        f"Three-way delete-insert: expected '012NEW69', got {output!r}"
    )
