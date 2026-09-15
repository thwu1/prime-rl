"""Tests for the automated program repair system."""

import sys
sys.path.insert(0, '/app')

import pytest


# ===== Repair: middle() =====

def test_repair_middle():
    """Repair system fixes the buggy middle() function."""
    from pipeline import repair_program

    source = open('/app/programs/middle.py').read()
    test_cases = [
        ((1, 2, 3), 2), ((3, 2, 1), 2), ((2, 1, 3), 2),
        ((1, 3, 2), 2), ((3, 1, 2), 2), ((2, 3, 1), 2),
        ((1, 1, 2), 1), ((2, 1, 1), 1), ((1, 2, 2), 2),
        ((5, 5, 5), 5),
    ]

    repaired = repair_program(source, test_cases, 'middle')
    assert isinstance(repaired, str), "repair_program must return a string"

    ns = {}
    exec(repaired, ns)
    assert 'middle' in ns, "Repaired code must define 'middle'"
    for args, expected in test_cases:
        result = ns['middle'](*args)
        assert result == expected, f"middle{args} = {result}, expected {expected}"


# ===== Repair: gcd() =====

def test_repair_gcd():
    """Repair system fixes the buggy gcd() function."""
    from pipeline import repair_program

    source = open('/app/programs/gcd.py').read()
    test_cases = [
        ((12, 8), 4), ((8, 12), 4), ((7, 5), 1),
        ((100, 75), 25), ((0, 5), 5), ((5, 0), 5),
        ((17, 17), 17), ((1, 1), 1), ((36, 24), 12),
        ((48, 18), 6),
    ]

    repaired = repair_program(source, test_cases, 'gcd')
    assert isinstance(repaired, str)

    ns = {}
    exec(repaired, ns)
    for args, expected in test_cases:
        result = ns['gcd'](*args)
        assert result == expected, f"gcd{args} = {result}, expected {expected}"


# ===== Repair: power() =====

def test_repair_power():
    """Repair system fixes the buggy power() function."""
    from pipeline import repair_program

    source = open('/app/programs/power.py').read()
    test_cases = [
        ((2, 0), 1), ((2, 1), 2), ((2, 3), 8), ((2, 10), 1024),
        ((3, 2), 9), ((3, 3), 27), ((5, 1), 5), ((10, 2), 100),
        ((1, 100), 1), ((7, 3), 343),
    ]

    repaired = repair_program(source, test_cases, 'power')
    assert isinstance(repaired, str)

    ns = {}
    exec(repaired, ns)
    for args, expected in test_cases:
        result = ns['power'](*args)
        assert result == expected, f"power{args} = {result}, expected {expected}"


# ===== Generalization: unseen max_of_three =====

def test_repair_max_of_three():
    """Repair system generalizes to an unseen buggy program."""
    from pipeline import repair_program

    source = (
        "def max_of_three(a, b, c):\n"
        "    if a >= b:\n"
        "        if a >= c:\n"
        "            return a\n"
        "        else:\n"
        "            return c\n"
        "    else:\n"
        "        if b >= c:\n"
        "            return a\n"
        "        else:\n"
        "            return c\n"
    )

    test_cases = [
        ((1, 2, 3), 3), ((1, 3, 2), 3), ((2, 1, 3), 3),
        ((2, 3, 1), 3), ((3, 1, 2), 3), ((3, 2, 1), 3),
        ((1, 1, 2), 2), ((1, 2, 2), 2), ((2, 2, 1), 2),
        ((5, 5, 5), 5),
    ]

    repaired = repair_program(source, test_cases, 'max_of_three')
    assert isinstance(repaired, str)

    ns = {}
    exec(repaired, ns)
    for args, expected in test_cases:
        result = ns['max_of_three'](*args)
        assert result == expected, f"max_of_three{args} = {result}, expected {expected}"


# ===== Generalization: unseen clamp =====

def test_repair_clamp():
    """Repair system generalizes to a second unseen buggy program."""
    from pipeline import repair_program

    source = (
        "def clamp(val, lo, hi):\n"
        "    if val < lo:\n"
        "        return lo\n"
        "    elif val > hi:\n"
        "        return lo\n"
        "    return val\n"
    )

    test_cases = [
        ((5, 0, 10), 5), ((-3, 0, 10), 0), ((15, 0, 10), 10),
        ((0, 0, 10), 0), ((10, 0, 10), 10), ((7, 5, 8), 7),
        ((3, 5, 8), 5), ((12, 5, 8), 8), ((5, 5, 5), 5),
        ((100, -10, 50), 50),
    ]

    repaired = repair_program(source, test_cases, 'clamp')
    assert isinstance(repaired, str)

    ns = {}
    exec(repaired, ns)
    for args, expected in test_cases:
        result = ns['clamp'](*args)
        assert result == expected, f"clamp{args} = {result}, expected {expected}"
