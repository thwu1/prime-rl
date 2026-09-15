"""Tests for the assembler — verifies JSON output against expected values.

"""

import subprocess
import json
import pytest

_cache = {}


def run_asm(prog):
    """Run the assembler on a test program and return parsed JSON (cached)."""
    if prog not in _cache:
        r = subprocess.run(
            ["/app/assembler", f"/app/programs/{prog}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0, (
            f"assembler failed on {prog}:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
        _cache[prog] = json.loads(r.stdout)
    return _cache[prog]


# ============================================================
# Program 1: Simple program, no relaxation
# ============================================================

def test_prog1_total():
    assert run_asm("prog1.asm")["total_size"] == 13


def test_prog1_iterations():
    assert run_asm("prog1.asm")["iterations"] == 0


def test_prog1_label_start():
    assert run_asm("prog1.asm")["labels"]["start"] == 0


def test_prog1_label_end():
    assert run_asm("prog1.asm")["labels"]["end"] == 12


def test_prog1_jump():
    j = run_asm("prog1.asm")["jumps"][0]
    assert j["offset"] == 3
    assert j["size"] == 2
    assert j["relaxed"] is False
    assert j["target"] == "end"


# ============================================================
# Program 2
# ============================================================

def test_prog2_total():
    assert run_asm("prog2.asm")["total_size"] == 206


def test_prog2_iterations():
    assert run_asm("prog2.asm")["iterations"] == 1


def test_prog2_label_far():
    assert run_asm("prog2.asm")["labels"]["far"] == 205


def test_prog2_jump():
    j = run_asm("prog2.asm")["jumps"][0]
    assert j["offset"] == 0
    assert j["size"] == 5
    assert j["relaxed"] is True


# ============================================================
# Program 3
# ============================================================

def test_prog3_total():
    assert run_asm("prog3.asm")["total_size"] == 130


def test_prog3_iterations():
    assert run_asm("prog3.asm")["iterations"] == 0


def test_prog3_label_near():
    assert run_asm("prog3.asm")["labels"]["near"] == 129


def test_prog3_jump_not_relaxed():
    j = run_asm("prog3.asm")["jumps"][0]
    assert j["size"] == 2
    assert j["relaxed"] is False


# ============================================================
# Program 4
# ============================================================

def test_prog4_total():
    assert run_asm("prog4.asm")["total_size"] == 135


def test_prog4_iterations():
    assert run_asm("prog4.asm")["iterations"] == 1


def test_prog4_label_top():
    assert run_asm("prog4.asm")["labels"]["top"] == 0


def test_prog4_jump_relaxed():
    j = run_asm("prog4.asm")["jumps"][0]
    assert j["offset"] == 128
    assert j["size"] == 6
    assert j["relaxed"] is True


# ============================================================
# Program 5
# ============================================================

def test_prog5_total():
    assert run_asm("prog5.asm")["total_size"] == 19


def test_prog5_iterations():
    assert run_asm("prog5.asm")["iterations"] == 0


def test_prog5_no_labels():
    assert run_asm("prog5.asm")["labels"] == {}


def test_prog5_no_jumps():
    assert run_asm("prog5.asm")["jumps"] == []


# ============================================================
# Program 6
# ============================================================

def test_prog6_total():
    assert run_asm("prog6.asm")["total_size"] == 128


def test_prog6_iterations():
    assert run_asm("prog6.asm")["iterations"] == 0


def test_prog6_label_target():
    assert run_asm("prog6.asm")["labels"]["target"] == 127


def test_prog6_jump_not_relaxed():
    j = run_asm("prog6.asm")["jumps"][0]
    assert j["size"] == 2
    assert j["relaxed"] is False


# ============================================================
# Program 7
# ============================================================

def test_prog7_total():
    assert run_asm("prog7.asm")["total_size"] == 131


def test_prog7_iterations():
    assert run_asm("prog7.asm")["iterations"] == 0


def test_prog7_label_target():
    assert run_asm("prog7.asm")["labels"]["target"] == 127


def test_prog7_jump_not_relaxed():
    j = run_asm("prog7.asm")["jumps"][0]
    assert j["size"] == 2
    assert j["relaxed"] is False


# ============================================================
# Program 8
# ============================================================

def test_prog8_total():
    assert run_asm("prog8.asm")["total_size"] == 132


def test_prog8_iterations():
    assert run_asm("prog8.asm")["iterations"] == 0


def test_prog8_label_start():
    assert run_asm("prog8.asm")["labels"]["start"] == 8


def test_prog8_label_done():
    assert run_asm("prog8.asm")["labels"]["done"] == 129


def test_prog8_jmp_done_not_relaxed():
    jumps = run_asm("prog8.asm")["jumps"]
    jmp_done = [j for j in jumps if j["target"] == "done"][0]
    assert jmp_done["size"] == 2
    assert jmp_done["relaxed"] is False
    assert jmp_done["offset"] == 0


def test_prog8_jcc_start_not_relaxed():
    jumps = run_asm("prog8.asm")["jumps"]
    jcc_start = [j for j in jumps if j["target"] == "start"][0]
    assert jcc_start["size"] == 2
    assert jcc_start["relaxed"] is False
    assert jcc_start["offset"] == 129


# ============================================================
# Program 9
# ============================================================

def test_prog9_total():
    assert run_asm("prog9.asm")["total_size"] == 261


def test_prog9_iterations():
    assert run_asm("prog9.asm")["iterations"] == 2


def test_prog9_label_mid():
    assert run_asm("prog9.asm")["labels"]["mid"] == 259


def test_prog9_label_end():
    assert run_asm("prog9.asm")["labels"]["end"] == 260


def test_prog9_jmp_mid_relaxed():
    jumps = run_asm("prog9.asm")["jumps"]
    jmp_mid = [j for j in jumps if j["target"] == "mid"][0]
    assert jmp_mid["offset"] == 0
    assert jmp_mid["size"] == 5
    assert jmp_mid["relaxed"] is True


def test_prog9_jmp_end_relaxed():
    jumps = run_asm("prog9.asm")["jumps"]
    jmp_end = [j for j in jumps if j["target"] == "end"][0]
    assert jmp_end["offset"] == 129
    assert jmp_end["size"] == 5
    assert jmp_end["relaxed"] is True


# ============================================================
# Program 10
# ============================================================

def test_prog10_total():
    assert run_asm("prog10.asm")["total_size"] == 212


def test_prog10_iterations():
    assert run_asm("prog10.asm")["iterations"] == 1


def test_prog10_label_far():
    assert run_asm("prog10.asm")["labels"]["far"] == 211


def test_prog10_jmp_relaxed():
    jumps = run_asm("prog10.asm")["jumps"]
    assert jumps[0]["offset"] == 0
    assert jumps[0]["size"] == 5
    assert jumps[0]["relaxed"] is True


def test_prog10_jcc_relaxed():
    jumps = run_asm("prog10.asm")["jumps"]
    assert jumps[1]["offset"] == 5
    assert jumps[1]["size"] == 6
    assert jumps[1]["relaxed"] is True


def test_prog10_asymmetric_sizes():
    """Verify that jmp and jcc have different long encoding sizes."""
    jumps = run_asm("prog10.asm")["jumps"]
    jmp_size = jumps[0]["size"]
    jcc_size = jumps[1]["size"]
    assert jmp_size != jcc_size, "jmp and jcc should have different long sizes"
    assert jmp_size < jcc_size, "jmp long should be smaller than jcc long"
