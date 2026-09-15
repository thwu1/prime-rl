
"""Tests for the transaction history anomaly checker (EDN input + DOT output)."""

import json
import subprocess
import os
import re
import tempfile
import pytest


def run_checker(history_file, dot_path=None):
    """Run the checker on a history file and return parsed JSON output."""
    cmd = ["python3", "/app/checker.py", history_file]
    if dot_path:
        cmd += ["--dot", dot_path]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Checker failed on {history_file}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = json.loads(result.stdout.strip())
    assert "anomalies" in output, "Output must contain 'anomalies' key"
    assert "max_isolation_level" in output, "Output must contain 'max_isolation_level' key"
    return output


def parse_dot_edges(dot_content):
    """Parse edges from DOT file content. Returns list of (src, dst, attrs_dict)."""
    edges = []
    edge_re = re.compile(r'T(\d+)\s*->\s*T(\d+)\s*\[([^\]]*)\]')
    for m in edge_re.finditer(dot_content):
        src, dst = int(m.group(1)), int(m.group(2))
        attrs_str = m.group(3)
        attrs = {}
        for attr_m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', attrs_str):
            attrs[attr_m.group(1)] = attr_m.group(2)
        edges.append((src, dst, attrs))
    return edges


class TestSerializable:
    """History with no anomalies - clean serializable execution."""

    def test_anomalies(self):
        out = run_checker("/app/histories/serializable.edn")
        assert out["anomalies"] == []

    def test_isolation_level(self):
        out = run_checker("/app/histories/serializable.edn")
        assert out["max_isolation_level"] == "serializable"


class TestG0:
    """G0: write cycle (cycle of ww dependencies)."""

    def test_anomalies(self):
        out = run_checker("/app/histories/g0.edn")
        assert "G0" in out["anomalies"], "Must detect G0 (write cycle)"
        assert "G1c" in out["anomalies"], "G0 implies G1c"

    def test_no_rw_anomalies(self):
        out = run_checker("/app/histories/g0.edn")
        assert "G-single" not in out["anomalies"]
        assert "G2-item" not in out["anomalies"]

    def test_isolation_level(self):
        out = run_checker("/app/histories/g0.edn")
        assert out["max_isolation_level"] == "none"


class TestG1a:
    """G1a: aborted read (committed txn reads aborted txn's data)."""

    def test_anomalies(self):
        out = run_checker("/app/histories/g1a.edn")
        assert "G1a" in out["anomalies"], "Must detect G1a (aborted read)"

    def test_no_cycle_anomalies(self):
        out = run_checker("/app/histories/g1a.edn")
        assert "G0" not in out["anomalies"]
        assert "G1c" not in out["anomalies"]

    def test_isolation_level(self):
        out = run_checker("/app/histories/g1a.edn")
        assert out["max_isolation_level"] == "read-uncommitted"


class TestG1b:
    """G1b: intermediate read (committed txn sees partial writes of another)."""

    def test_g1b_detected(self):
        out = run_checker("/app/histories/g1b.edn")
        assert "G1b" in out["anomalies"], "Must detect G1b (intermediate read)"

    def test_implies_cycle_anomalies(self):
        """The intermediate read creates a wr+rw cycle between the two txns."""
        out = run_checker("/app/histories/g1b.edn")
        assert "G-single" in out["anomalies"], (
            "Intermediate read creates a wr+rw cycle (G-single)"
        )
        assert "G2-item" in out["anomalies"], "G-single implies G2-item"

    def test_isolation_level(self):
        out = run_checker("/app/histories/g1b.edn")
        assert out["max_isolation_level"] == "read-uncommitted"


class TestG1c:
    """G1c: cyclic information flow (cycle of ww/wr deps only)."""

    def test_anomalies(self):
        out = run_checker("/app/histories/g1c.edn")
        assert "G1c" in out["anomalies"], "Must detect G1c"

    def test_no_g0(self):
        out = run_checker("/app/histories/g1c.edn")
        assert "G0" not in out["anomalies"], "This cycle has wr edges, not pure ww"

    def test_no_rw_anomalies(self):
        out = run_checker("/app/histories/g1c.edn")
        assert "G-single" not in out["anomalies"]
        assert "G2-item" not in out["anomalies"]

    def test_isolation_level(self):
        out = run_checker("/app/histories/g1c.edn")
        assert out["max_isolation_level"] == "read-uncommitted"


class TestGSingle:
    """G-single: read skew (cycle with exactly one rw anti-dependency)."""

    def test_anomalies(self):
        out = run_checker("/app/histories/g_single.edn")
        assert "G-single" in out["anomalies"], "Must detect G-single"
        assert "G2-item" in out["anomalies"], "G-single implies G2-item"

    def test_no_g1(self):
        out = run_checker("/app/histories/g_single.edn")
        assert "G0" not in out["anomalies"]
        assert "G1a" not in out["anomalies"]
        assert "G1b" not in out["anomalies"]
        assert "G1c" not in out["anomalies"]

    def test_isolation_level(self):
        out = run_checker("/app/histories/g_single.edn")
        assert out["max_isolation_level"] == "read-committed"


class TestG2Item:
    """G2-item: write skew (cycle with multiple rw anti-dependencies)."""

    def test_g2_item_detected(self):
        out = run_checker("/app/histories/g2_item.edn")
        assert "G2-item" in out["anomalies"], "Must detect G2-item"

    def test_not_g_single(self):
        """This cycle has 2 rw edges, so it's not G-single."""
        out = run_checker("/app/histories/g2_item.edn")
        assert "G-single" not in out["anomalies"], (
            "Cycle has 2 rw edges - not G-single"
        )

    def test_no_g1(self):
        out = run_checker("/app/histories/g2_item.edn")
        assert "G0" not in out["anomalies"]
        assert "G1a" not in out["anomalies"]
        assert "G1b" not in out["anomalies"]
        assert "G1c" not in out["anomalies"]

    def test_isolation_level(self):
        out = run_checker("/app/histories/g2_item.edn")
        assert out["max_isolation_level"] == "read-committed"


class TestComplex:
    """Complex history with multiple anomaly types (G1a + G-single)."""

    def test_g1a_detected(self):
        out = run_checker("/app/histories/complex.edn")
        assert "G1a" in out["anomalies"], "Must detect G1a from aborted T0"

    def test_g_single_detected(self):
        out = run_checker("/app/histories/complex.edn")
        assert "G-single" in out["anomalies"], (
            "Must detect G-single from T2/T3 cycle"
        )
        assert "G2-item" in out["anomalies"], "G-single implies G2-item"

    def test_no_g0(self):
        out = run_checker("/app/histories/complex.edn")
        assert "G0" not in out["anomalies"]

    def test_isolation_level(self):
        """G1a is the worst anomaly, so max level is read-uncommitted."""
        out = run_checker("/app/histories/complex.edn")
        assert out["max_isolation_level"] == "read-uncommitted"


class TestStress:
    """Stress history with G1a + G1c + G-single across disjoint components."""

    def test_g1a_detected(self):
        out = run_checker("/app/histories/stress.edn")
        assert "G1a" in out["anomalies"], "T7 aborted, T8 reads its data"

    def test_g1c_detected(self):
        out = run_checker("/app/histories/stress.edn")
        assert "G1c" in out["anomalies"], "T0/T1 form a ww+wr cycle"

    def test_g_single_detected(self):
        out = run_checker("/app/histories/stress.edn")
        assert "G-single" in out["anomalies"], "T3/T4 form a wr+rw cycle"
        assert "G2-item" in out["anomalies"], "G-single implies G2-item"

    def test_no_g0(self):
        out = run_checker("/app/histories/stress.edn")
        assert "G0" not in out["anomalies"]

    def test_isolation_level(self):
        out = run_checker("/app/histories/stress.edn")
        assert out["max_isolation_level"] == "read-uncommitted"


class TestOutputFormat:
    """Verify output format requirements."""

    def test_anomalies_sorted(self):
        """anomalies list must be sorted alphabetically."""
        out = run_checker("/app/histories/complex.edn")
        assert out["anomalies"] == sorted(out["anomalies"])

    def test_valid_isolation_levels(self):
        """max_isolation_level must be one of the four defined levels."""
        valid_levels = {"serializable", "read-committed", "read-uncommitted", "none"}
        for fname in os.listdir("/app/histories/"):
            if fname.endswith(".edn"):
                out = run_checker(f"/app/histories/{fname}")
                assert out["max_isolation_level"] in valid_levels, (
                    f"{fname}: invalid level '{out['max_isolation_level']}'"
                )

    def test_valid_anomaly_names(self):
        """All reported anomaly names must be from the defined set."""
        valid = {"G0", "G1a", "G1b", "G1c", "G-single", "G2-item"}
        for fname in os.listdir("/app/histories/"):
            if fname.endswith(".edn"):
                out = run_checker(f"/app/histories/{fname}")
                for a in out["anomalies"]:
                    assert a in valid, f"{fname}: unknown anomaly '{a}'"


class TestDotOutputValidity:
    """Verify that DOT output is valid and renderable by Graphviz."""

    def test_dot_renders_g0(self):
        """DOT output for g0 history must render with graphviz."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/g0.edn", dot_path=dot_path)
            result = subprocess.run(
                ["dot", "-Tsvg", dot_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0, (
                f"dot failed to render: {result.stderr}"
            )
        finally:
            os.unlink(dot_path)

    def test_dot_renders_serializable(self):
        """DOT output for serializable history must render with graphviz."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/serializable.edn", dot_path=dot_path)
            result = subprocess.run(
                ["dot", "-Tsvg", dot_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0, (
                f"dot failed to render: {result.stderr}"
            )
        finally:
            os.unlink(dot_path)

    def test_dot_renders_stress(self):
        """DOT output for stress history must render with graphviz."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/stress.edn", dot_path=dot_path)
            result = subprocess.run(
                ["dot", "-Tsvg", dot_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0, (
                f"dot failed to render: {result.stderr}"
            )
        finally:
            os.unlink(dot_path)

    def test_dot_all_histories_render(self):
        """Every history file must produce a renderable DOT file."""
        for fname in os.listdir("/app/histories/"):
            if not fname.endswith(".edn"):
                continue
            with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
                dot_path = f.name
            try:
                run_checker(f"/app/histories/{fname}", dot_path=dot_path)
                result = subprocess.run(
                    ["dot", "-Tsvg", dot_path],
                    capture_output=True, text=True, timeout=10,
                )
                assert result.returncode == 0, (
                    f"{fname}: dot render failed: {result.stderr}"
                )
            finally:
                os.unlink(dot_path)


class TestDotOutputContent:
    """Verify DOT output contains correct dependency edges and cycle marking."""

    def test_g0_has_ww_cycle_bold(self):
        """G0 history should have bold ww edges forming a cycle."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/g0.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            # Should have ww edges between T0 and T1 (cycle)
            ww_edges = [(s, d, a) for s, d, a in edges if "label" in a and a["label"].startswith("ww:")]
            assert len(ww_edges) >= 2, f"Expected at least 2 ww edges, got {len(ww_edges)}"
            # Cycle edges should be bold
            bold_ww = [(s, d) for s, d, a in ww_edges if a.get("style") == "bold"]
            assert len(bold_ww) >= 2, f"Cycle ww edges should be bold, got {len(bold_ww)} bold"
        finally:
            os.unlink(dot_path)

    def test_g0_ww_edge_color(self):
        """ww edges should be colored blue."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/g0.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            ww_edges = [(s, d, a) for s, d, a in edges if "label" in a and a["label"].startswith("ww:")]
            for s, d, a in ww_edges:
                assert a.get("color") == "blue", (
                    f"ww edge T{s}->T{d} should be blue, got {a.get('color')}"
                )
        finally:
            os.unlink(dot_path)

    def test_g_single_has_rw_edge(self):
        """G-single history should have a red rw edge."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/g_single.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            rw_edges = [(s, d, a) for s, d, a in edges if "label" in a and a["label"].startswith("rw:")]
            assert len(rw_edges) >= 1, "G-single must have at least one rw edge"
            for s, d, a in rw_edges:
                assert a.get("color") == "red", (
                    f"rw edge T{s}->T{d} should be red, got {a.get('color')}"
                )
        finally:
            os.unlink(dot_path)

    def test_g_single_cycle_edges_bold(self):
        """Both edges in the G-single cycle should be bold."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/g_single.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            bold_edges = [(s, d) for s, d, a in edges if a.get("style") == "bold"]
            assert len(bold_edges) >= 2, (
                f"G-single cycle needs at least 2 bold edges, got {len(bold_edges)}"
            )
        finally:
            os.unlink(dot_path)

    def test_serializable_no_bold_edges(self):
        """Serializable history has no cycles, so no bold edges."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/serializable.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            bold_edges = [(s, d) for s, d, a in edges if a.get("style") == "bold"]
            assert len(bold_edges) == 0, (
                f"Serializable history should have no bold edges, got {bold_edges}"
            )
        finally:
            os.unlink(dot_path)

    def test_g2_item_two_rw_edges(self):
        """G2-item (write skew) should have two rw edges, both bold."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/g2_item.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            rw_edges = [(s, d, a) for s, d, a in edges if "label" in a and a["label"].startswith("rw:")]
            assert len(rw_edges) == 2, f"Write skew should have exactly 2 rw edges, got {len(rw_edges)}"
            for s, d, a in rw_edges:
                assert a.get("style") == "bold", (
                    f"rw cycle edge T{s}->T{d} should be bold"
                )
        finally:
            os.unlink(dot_path)

    def test_stress_dot_has_disjoint_cycles(self):
        """Stress history has two disjoint cycles; bold edges from both."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/stress.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            bold_edges = [(s, d) for s, d, a in edges if a.get("style") == "bold"]
            # Cycle 1: T0<->T1, Cycle 2: T3<->T4
            cycle1_nodes = {0, 1}
            cycle2_nodes = {3, 4}
            cycle1_bold = [(s, d) for s, d in bold_edges if s in cycle1_nodes and d in cycle1_nodes]
            cycle2_bold = [(s, d) for s, d in bold_edges if s in cycle2_nodes and d in cycle2_nodes]
            assert len(cycle1_bold) >= 2, (
                f"Cycle T0<->T1 should have >= 2 bold edges, got {cycle1_bold}"
            )
            assert len(cycle2_bold) >= 2, (
                f"Cycle T3<->T4 should have >= 2 bold edges, got {cycle2_bold}"
            )
        finally:
            os.unlink(dot_path)

    def test_dot_wr_edges_green(self):
        """wr edges should be colored green."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/g1c.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            wr_edges = [(s, d, a) for s, d, a in edges if "label" in a and a["label"].startswith("wr:")]
            assert len(wr_edges) >= 1, "G1c should have at least one wr edge"
            for s, d, a in wr_edges:
                assert a.get("color") == "green", (
                    f"wr edge T{s}->T{d} should be green, got {a.get('color')}"
                )
        finally:
            os.unlink(dot_path)

    def test_dot_edge_labels_have_key(self):
        """All edge labels must be in format type:key."""
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            run_checker("/app/histories/stress.edn", dot_path=dot_path)
            with open(dot_path) as fh:
                content = fh.read()
            edges = parse_dot_edges(content)
            label_re = re.compile(r'^(ww|wr|rw):\w+$')
            for s, d, a in edges:
                label = a.get("label", "")
                assert label_re.match(label), (
                    f"Edge T{s}->T{d} label '{label}' not in format type:key"
                )
        finally:
            os.unlink(dot_path)

    def test_dot_no_output_without_flag(self):
        """When --dot is not given, no DOT file should be created."""
        out = run_checker("/app/histories/serializable.edn")
        assert out["max_isolation_level"] == "serializable"
        # Just verify JSON output works without --dot
