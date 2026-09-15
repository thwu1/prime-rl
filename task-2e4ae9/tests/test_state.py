"""
Verification tests for the adder characterization project.
"""
import json
import os
import re
import subprocess

import pytest


def run_cmd(cmd, timeout=300):
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )


# ---- Functional verification of each adder (exhaustive) ----

def test_ripple_carry_functional():
    r = run_cmd(
        "iverilog -DTEST_RIPPLE -o /tmp/vfy_ripple "
        "/tests/verify_adder.v /app/rtl/ripple_carry_adder.v "
        "&& vvp /tmp/vfy_ripple"
    )
    assert "RESULT: PASS" in r.stdout, (
        f"Ripple-carry adder failed exhaustive verification:\n{r.stdout}\n{r.stderr}"
    )


def test_kogge_stone_functional():
    r = run_cmd(
        "iverilog -DTEST_KOGGE -o /tmp/vfy_kogge "
        "/tests/verify_adder.v /app/rtl/kogge_stone_adder.v "
        "&& vvp /tmp/vfy_kogge"
    )
    assert "RESULT: PASS" in r.stdout, (
        f"Kogge-Stone adder failed exhaustive verification:\n{r.stdout}\n{r.stderr}"
    )


def test_brent_kung_functional():
    r = run_cmd(
        "iverilog -DTEST_BRENT -o /tmp/vfy_brent "
        "/tests/verify_adder.v /app/rtl/brent_kung_adder.v "
        "&& vvp /tmp/vfy_brent"
    )
    assert "RESULT: PASS" in r.stdout, (
        f"Brent-Kung adder failed exhaustive verification:\n{r.stdout}\n{r.stderr}"
    )


def test_sklansky_functional():
    r = run_cmd(
        "iverilog -DTEST_SKLANSKY -o /tmp/vfy_sklansky "
        "/tests/verify_adder.v /app/rtl/sklansky_adder.v "
        "&& vvp /tmp/vfy_sklansky"
    )
    assert "RESULT: PASS" in r.stdout, (
        f"Sklansky adder failed exhaustive verification:\n{r.stdout}\n{r.stderr}"
    )


# ---- Ring oscillator ----

def test_ring_oscillator_functional():
    r = run_cmd(
        "iverilog -o /tmp/vfy_rosc "
        "/tests/verify_ring_osc.v /app/rtl/ring_oscillator.v "
        "&& vvp /tmp/vfy_rosc"
    )
    assert "RESULT: PASS" in r.stdout, (
        f"Ring oscillator failed:\n{r.stdout}\n{r.stderr}"
    )


# ---- Synthesis logs ----

def test_synthesis_logs_exist():
    """Verify that Yosys synthesis was run and logs were saved."""
    for name in [
        "ripple_carry_adder",
        "kogge_stone_adder",
        "brent_kung_adder",
        "sklansky_adder",
    ]:
        path = f"/app/results/{name}_synth.log"
        assert os.path.exists(path), f"Missing synthesis log: {path}"
        with open(path) as f:
            content = f.read()
        assert "Number of cells:" in content, (
            f"Synthesis log for {name} missing cell count stats"
        )


# ---- analysis.json ----

def test_analysis_json_exists():
    assert os.path.exists("/app/results/analysis.json"), "analysis.json not found"


def test_analysis_json_structure():
    with open("/app/results/analysis.json") as f:
        data = json.load(f)

    required_adders = {"ripple_carry", "kogge_stone", "brent_kung", "sklansky"}

    assert "adders" in data, "Missing 'adders' key"
    for name in required_adders:
        assert name in data["adders"], f"Missing adder entry: {name}"
        entry = data["adders"][name]
        assert "cell_count" in entry, f"{name}: missing cell_count"
        assert "correct" in entry, f"{name}: missing correct"
        assert entry["correct"] is True, f"{name}: not marked correct"
        assert isinstance(entry["cell_count"], int) and entry["cell_count"] > 0, (
            f"{name}: cell_count must be a positive integer"
        )

    assert "ring_oscillator_functional" in data
    assert data["ring_oscillator_functional"] is True

    assert "area_ranking" in data, "Missing area_ranking"
    assert set(data["area_ranking"]) == required_adders, (
        "area_ranking must be a permutation of the four adder names"
    )


# ---- Source-level checks ----

def test_characterizer_counter_width():
    """Measurement counters must be at least 32 bits."""
    with open("/app/rtl/adder_characterizer.v") as f:
        content = f.read()

    m_osc = re.search(r"\[(\d+):0\]\s*osc_count", content)
    assert m_osc, "osc_count declaration not found"
    assert int(m_osc.group(1)) >= 31, (
        f"osc_count is {int(m_osc.group(1))+1} bits — must be >= 32"
    )

    m_cyc = re.search(r"\[(\d+):0\]\s*cycle_count", content)
    assert m_cyc, "cycle_count declaration not found"
    assert int(m_cyc.group(1)) >= 31, (
        f"cycle_count is {int(m_cyc.group(1))+1} bits — must be >= 32"
    )


def test_sklansky_not_stub():
    """Sklansky adder must be a real implementation, not a zero-output stub."""
    with open("/app/rtl/sklansky_adder.v") as f:
        content = f.read()
    # A stub assigns zeros and has almost no logic
    assert "TODO" not in content, "Sklansky adder still contains TODO markers"
    # Real prefix adder needs multiple wires/assigns for the tree
    wire_count = len(re.findall(r"\bwire\b", content))
    assign_count = len(re.findall(r"\bassign\b", content))
    assert wire_count >= 5 and assign_count >= 10, (
        "Sklansky adder appears to be a stub (too few wires/assigns)"
    )
