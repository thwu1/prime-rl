
"""
Tests for the MESI cache coherence protocol simulator.
Each test runs the simulator on a trace file and checks exact statistics.
Default parameters: 4 processors, 4 sets, 2-way associative, 64-byte blocks.
"""

import subprocess
import os
import pytest


SIM = "/app/mesi_sim"
TRACES = "/app/traces"


def run_sim(trace_name, num_procs=4, num_sets=4, assoc=2, block_size=64):
    """Run the simulator and return parsed statistics dict."""
    trace_path = os.path.join(TRACES, trace_name)
    result = subprocess.run(
        [SIM, trace_path, str(num_procs), str(num_sets),
         str(assoc), str(block_size)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Simulator exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return _parse(result.stdout)


def _parse(output):
    stats = {}
    section = None
    for raw in output.strip().split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("PROCESSOR"):
            section = f"P{line.split()[1]}"
            stats[section] = {}
        elif line == "BUS":
            section = "BUS"
            stats[section] = {}
        elif ":" in line and section is not None:
            key, val = line.split(":", 1)
            stats[section][key.strip()] = int(val.strip())
    return stats


# ── Trace 1: basic ──────────────────────────────────────────────────
# 0 R 0x0000  → miss, BusRd, enter E
# 0 R 0x0000  → hit (E)
# 0 W 0x0000  → hit (E→M), silent upgrade
def test_basic():
    s = run_sim("basic.trace")
    p0 = s["P0"]
    assert p0["reads"] == 2
    assert p0["writes"] == 1
    assert p0["read_hits"] == 1
    assert p0["read_misses"] == 1
    assert p0["write_hits"] == 1
    assert p0["write_misses"] == 0
    b = s["BUS"]
    assert b["bus_rd"] == 1
    assert b["bus_rdx"] == 0
    assert b["bus_upgr"] == 0
    assert b["flushes"] == 0


# ── Trace 2: sharing ────────────────────────────────────────────────
# Four reads to same line. First gets E, subsequent get S.
def test_sharing():
    s = run_sim("sharing.trace")
    for i in range(4):
        p = s[f"P{i}"]
        assert p["reads"] == 1
        assert p["read_misses"] == 1
        assert p["read_hits"] == 0
    b = s["BUS"]
    assert b["bus_rd"] == 4
    assert b["bus_rdx"] == 0
    assert b["bus_upgr"] == 0
    assert b["flushes"] == 0


# ── Trace 3: invalidate ─────────────────────────────────────────────
# P0 R, P1 R (both S), P0 W (BusUpgr→M, P1→I), P1 R (miss, Flush M→S)
def test_invalidate():
    s = run_sim("invalidate.trace")
    p0 = s["P0"]
    assert p0["reads"] == 1
    assert p0["writes"] == 1
    assert p0["read_misses"] == 1
    assert p0["read_hits"] == 0
    assert p0["write_hits"] == 1
    assert p0["write_misses"] == 0
    p1 = s["P1"]
    assert p1["reads"] == 2
    assert p1["read_misses"] == 2
    assert p1["read_hits"] == 0
    b = s["BUS"]
    assert b["bus_rd"] == 3
    assert b["bus_rdx"] == 0
    assert b["bus_upgr"] == 1
    assert b["flushes"] == 1


# ── Trace 4: write_miss ─────────────────────────────────────────────
# P0 W miss (BusRdX→M), P1 W miss (BusRdX, Flush P0 M→I, →M),
# P0 R miss (BusRd, Flush P1 M→S, →S)
def test_write_miss():
    s = run_sim("write_miss.trace")
    p0 = s["P0"]
    assert p0["reads"] == 1
    assert p0["writes"] == 1
    assert p0["read_misses"] == 1
    assert p0["write_misses"] == 1
    p1 = s["P1"]
    assert p1["writes"] == 1
    assert p1["write_misses"] == 1
    b = s["BUS"]
    assert b["bus_rd"] == 1
    assert b["bus_rdx"] == 2
    assert b["bus_upgr"] == 0
    assert b["flushes"] == 2


# ── Trace 5: eviction ───────────────────────────────────────────────
# Three writes to set-0 (0x0000,0x0100,0x0200).  2-way assoc ⇒
# third evicts LRU dirty line with Flush.
def test_eviction():
    s = run_sim("eviction.trace")
    p0 = s["P0"]
    assert p0["writes"] == 3
    assert p0["write_misses"] == 3
    assert p0["reads"] == 0
    b = s["BUS"]
    assert b["bus_rd"] == 0
    assert b["bus_rdx"] == 3
    assert b["bus_upgr"] == 0
    assert b["flushes"] == 1


# ── Trace 6: complex ────────────────────────────────────────────────
# 7-access interleaving across 4 processors.
def test_complex():
    s = run_sim("complex.trace")
    p0 = s["P0"]
    assert p0["reads"] == 3
    assert p0["read_misses"] == 3
    assert p0["read_hits"] == 0
    assert p0["writes"] == 0
    p1 = s["P1"]
    assert p1["reads"] == 1
    assert p1["read_misses"] == 1
    assert p1["writes"] == 1
    assert p1["write_misses"] == 1
    p2 = s["P2"]
    assert p2["writes"] == 1
    assert p2["write_misses"] == 1
    p3 = s["P3"]
    assert p3["writes"] == 1
    assert p3["write_misses"] == 1
    b = s["BUS"]
    assert b["bus_rd"] == 4
    assert b["bus_rdx"] == 3
    assert b["bus_upgr"] == 0
    assert b["flushes"] == 3


# ── Trace 7: false_sharing ──────────────────────────────────────────
# Writes to different words within the same 64-byte cache line.
# Each write is a BusRdX miss; each subsequent one flushes the previous M.
def test_false_sharing():
    s = run_sim("false_sharing.trace")
    p0 = s["P0"]
    assert p0["writes"] == 2
    assert p0["write_misses"] == 2
    p1 = s["P1"]
    assert p1["writes"] == 2
    assert p1["write_misses"] == 2
    b = s["BUS"]
    assert b["bus_rd"] == 0
    assert b["bus_rdx"] == 4
    assert b["bus_upgr"] == 0
    assert b["flushes"] == 3


# ── Trace 8: upgrade (MESI E→M silent) ──────────────────────────────
# Each processor reads then writes its own private line.
# Write hits Exclusive ⇒ silent upgrade to M, zero bus traffic on writes.
def test_upgrade():
    s = run_sim("upgrade.trace")
    for pid in [0, 1]:
        p = s[f"P{pid}"]
        assert p["reads"] == 1
        assert p["writes"] == 1
        assert p["read_misses"] == 1
        assert p["read_hits"] == 0
        assert p["write_hits"] == 1
        assert p["write_misses"] == 0
    b = s["BUS"]
    assert b["bus_rd"] == 2
    assert b["bus_rdx"] == 0
    assert b["bus_upgr"] == 0
    assert b["flushes"] == 0
