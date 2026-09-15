"""
Tests for WebRTC signaling state machine security audit.

Verifies that the agent produced correct analysis outputs:
state transition graph, property-based fuzzer, patch evaluations,
and vulnerability report.
"""

import sys
import os
import json
import subprocess

sys.path.insert(0, '/app')

ANALYSIS_DIR = '/app/analysis'

# Expected patch verdicts
EXPECTED_VERDICTS = {
    "patch_a": "effective",
    "patch_b": "insufficient",
    "patch_c": "effective",
    "patch_d": "insufficient",
    "patch_e": "regression",
}

VERDICT_ALIASES = {
    "effective": {
        "effective", "correct", "valid", "sound", "fixes", "fixed",
        "works", "good", "secure", "successful", "pass", "passed",
    },
    "insufficient": {
        "insufficient", "incomplete", "ineffective", "partial",
        "failed", "fails", "broken", "inadequate", "flawed",
        "bypassed", "bypassable", "wrong", "incorrect", "bad",
        "not_fixed", "does_not_fix", "no_fix", "still_vulnerable",
        "vulnerable", "exploitable", "inefficient",
    },
    "regression": {
        "regression", "introduces_regression", "introduces_bug",
        "breaks", "breaks_functionality", "harmful", "destructive",
        "regressive", "causes_regression", "new_bug", "deadlock",
        "breaks_legitimate", "breaks_normal", "side_effect",
    },
}


def _normalize_verdict(v):
    """Normalize a verdict string to: effective, insufficient, or regression."""
    v = v.strip().lower().replace(" ", "_").replace("-", "_")
    for category, aliases in VERDICT_ALIASES.items():
        if v in aliases:
            return category
    return v


# ==================== State Graph Tests ====================

def test_analysis_directory_exists():
    assert os.path.isdir(ANALYSIS_DIR), \
        f"{ANALYSIS_DIR} directory must exist"


def test_state_graph_dot_exists():
    dot_path = os.path.join(ANALYSIS_DIR, "state_graph.dot")
    assert os.path.isfile(dot_path), \
        "state_graph.dot must exist in /app/analysis/"


def test_state_graph_dot_contains_all_states():
    """DOT file must reference all 7 PeerState values."""
    dot_path = os.path.join(ANALYSIS_DIR, "state_graph.dot")
    with open(dot_path) as f:
        content = f.read()

    content_upper = content.upper()
    assert "DIGRAPH" in content_upper or "GRAPH" in content_upper, \
        "DOT file must contain a graph definition"

    required_states = [
        "IDLE", "CALLING_OUT", "INCOMING_CALL",
        "NEGOTIATING", "CONNECTING", "ACTIVE", "ENDED",
    ]
    for state in required_states:
        assert state in content_upper, \
            f"DOT file must include state '{state}'"


def test_state_graph_dot_has_edges():
    dot_path = os.path.join(ANALYSIS_DIR, "state_graph.dot")
    with open(dot_path) as f:
        content = f.read()
    assert "->" in content, \
        "DOT file must contain directed edges (->)"


def test_state_graph_dot_annotates_vulnerabilities():
    """DOT file must visually distinguish vulnerable transitions."""
    dot_path = os.path.join(ANALYSIS_DIR, "state_graph.dot")
    with open(dot_path) as f:
        content = f.read().lower()
    vuln_indicators = [
        "vuln", "red", "vulnerable", "attack", "unauthorized",
        "danger", "exploit", "malicious", "dashed", "penwidth",
    ]
    assert any(ind in content for ind in vuln_indicators), \
        "DOT file must visually annotate vulnerable transitions"


def test_state_graph_dot_renderable():
    """DOT file must be syntactically valid for graphviz."""
    dot_path = os.path.join(ANALYSIS_DIR, "state_graph.dot")
    if not os.path.isfile(dot_path):
        assert False, "state_graph.dot does not exist"
    result = subprocess.run(
        ["dot", "-Tsvg", dot_path],
        capture_output=True, timeout=30,
    )
    assert result.returncode == 0, \
        f"DOT file is not valid graphviz: {result.stderr.decode()[:300]}"


def test_state_graph_png_exists():
    png_path = os.path.join(ANALYSIS_DIR, "state_graph.png")
    assert os.path.isfile(png_path), \
        "state_graph.png must exist in /app/analysis/"
    with open(png_path, "rb") as f:
        magic = f.read(8)
    # Accept PNG or JPEG
    assert magic[:4] == b'\x89PNG' or magic[:2] == b'\xff\xd8', \
        "state_graph.png must be a valid image file"


# ==================== Fuzzer Tests ====================

def test_invariant_fuzzer_exists():
    path = os.path.join(ANALYSIS_DIR, "invariant_fuzzer.py")
    assert os.path.isfile(path), \
        "invariant_fuzzer.py must exist in /app/analysis/"


def test_invariant_fuzzer_structure():
    """Fuzzer must use Hypothesis RuleBasedStateMachine with invariant checks."""
    path = os.path.join(ANALYSIS_DIR, "invariant_fuzzer.py")
    with open(path) as f:
        code = f.read()

    assert "hypothesis" in code, \
        "Fuzzer must import from hypothesis"
    assert "RuleBasedStateMachine" in code, \
        "Fuzzer must use RuleBasedStateMachine"
    assert "invariant" in code, \
        "Fuzzer must define an @invariant check"
    assert "rule" in code, \
        "Fuzzer must define @rule methods"

    consent_terms = ["consent", "transmit", "unauthorized", "media"]
    assert any(t in code.lower() for t in consent_terms), \
        "Fuzzer invariant must check consent/transmission state"


def test_invariant_fuzzer_detects_violations():
    """The fuzzer must detect consent violations in the original vulnerable code."""
    result = subprocess.run(
        ["python3", "-c", r"""
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/analysis')

from hypothesis import settings, HealthCheck
from hypothesis.stateful import RuleBasedStateMachine
import importlib.util

spec = importlib.util.spec_from_file_location(
    "fuzzer", "/app/analysis/invariant_fuzzer.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

cls = None
for name in dir(mod):
    obj = getattr(mod, name)
    if (isinstance(obj, type)
            and issubclass(obj, RuleBasedStateMachine)
            and obj is not RuleBasedStateMachine):
        cls = obj
        break

if cls is None:
    print("NO_FUZZER_CLASS")
    sys.exit(2)

tc = cls.TestCase
tc.settings = settings(
    max_examples=300,
    stateful_step_count=15,
    suppress_health_check=list(HealthCheck),
    database=None,
)
try:
    tc("runTest").runTest()
    print("NO_VIOLATION")
    sys.exit(1)
except Exception as e:
    print(f"VIOLATION_FOUND: {type(e).__name__}")
    sys.exit(0)
"""],
        capture_output=True, text=True, timeout=120, cwd="/app",
    )
    assert result.returncode == 0, \
        (f"Fuzzer should detect violations in original code.\n"
         f"stdout: {result.stdout[:400]}\nstderr: {result.stderr[:400]}")


# ==================== Patch Verdict Tests ====================

def test_patch_verdicts_file_exists():
    path = os.path.join(ANALYSIS_DIR, "patch_verdicts.json")
    assert os.path.isfile(path), \
        "patch_verdicts.json must exist in /app/analysis/"


def test_patch_verdicts_has_five_entries():
    path = os.path.join(ANALYSIS_DIR, "patch_verdicts.json")
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        entries = data.get("verdicts", data.get("patches",
                  data.get("patch_verdicts", [])))
    else:
        entries = data

    assert isinstance(entries, list), \
        "patch_verdicts.json must contain a list"
    assert len(entries) == 5, \
        f"Expected 5 patch verdicts, found {len(entries)}"


def test_patch_verdicts_correct():
    """Each patch verdict must correctly classify the patch."""
    path = os.path.join(ANALYSIS_DIR, "patch_verdicts.json")
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        entries = data.get("verdicts", data.get("patches",
                  data.get("patch_verdicts", [])))
    else:
        entries = data

    # Build mapping from patch_id to verdict
    verdicts = {}
    for entry in entries:
        pid = entry.get("patch_id", entry.get("patch",
              entry.get("id", "")))
        pid = str(pid).strip().lower().replace("-", "_")
        if not pid.startswith("patch_"):
            pid = f"patch_{pid}"

        verdict = entry.get("verdict", entry.get("classification",
                  entry.get("result", entry.get("status", ""))))
        verdicts[pid] = _normalize_verdict(str(verdict))

    for patch_id, expected in EXPECTED_VERDICTS.items():
        actual = verdicts.get(patch_id)
        assert actual is not None, \
            f"Missing verdict for {patch_id}. Found keys: {list(verdicts.keys())}"
        assert actual == expected, \
            f"Verdict for {patch_id}: expected '{expected}', got '{actual}'"


def test_patch_verdicts_have_reasoning():
    """Each verdict must include an explanation."""
    path = os.path.join(ANALYSIS_DIR, "patch_verdicts.json")
    with open(path) as f:
        data = json.load(f)

    entries = (data if isinstance(data, list) else
               data.get("verdicts", data.get("patches", [])))

    for entry in entries:
        pid = entry.get("patch_id", entry.get("patch", "?"))
        has_reasoning = any(k in entry for k in (
            "reasoning", "explanation", "rationale",
            "analysis", "details", "description",
        ))
        assert has_reasoning, \
            f"Verdict for {pid} must include reasoning/explanation"


# ==================== Report Tests ====================

def test_report_exists():
    path = os.path.join(ANALYSIS_DIR, "report.json")
    assert os.path.isfile(path), \
        "report.json must exist in /app/analysis/"


def test_report_identifies_three_vulnerabilities():
    """Report must describe at least 3 distinct vulnerabilities."""
    path = os.path.join(ANALYSIS_DIR, "report.json")
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, list):
        vulns = data
    else:
        vulns = data.get("vulnerabilities", data.get("findings", []))

    assert isinstance(vulns, list), \
        "Report must contain a list of vulnerabilities"
    assert len(vulns) >= 3, \
        f"Expected at least 3 vulnerabilities, found {len(vulns)}"


def test_report_vulnerability_fields():
    """Each vulnerability must have required descriptive fields."""
    path = os.path.join(ANALYSIS_DIR, "report.json")
    with open(path) as f:
        data = json.load(f)

    vulns = (data if isinstance(data, list) else
             data.get("vulnerabilities", data.get("findings", [])))

    for vuln in vulns:
        has_id = any(k in vuln for k in (
            "vulnerability_id", "id", "vuln_id", "name", "title",
        ))
        has_desc = any(k in vuln for k in (
            "mechanism", "description", "details", "explanation",
        ))

        assert has_id, \
            f"Vulnerability must have an identifier: {list(vuln.keys())}"
        assert has_desc, \
            f"Vulnerability must have a mechanism/description: {list(vuln.keys())}"
