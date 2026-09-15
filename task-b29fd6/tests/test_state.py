
"""
Verification tests for the Numerical Precision Challenge.
Checks each answer against a reference value to 10 significant digits.
"""

import math
import os
import pytest


REFS = [
    0.3233674316777787613993700879521704466510,
    -3.306868647475237280076113770898515657166,
    0.7250783462684011674686877192511609688691,
]

REQUIRED_DIGITS = 10


def _significant_digits(computed, reference):
    """Return the number of matching significant digits."""
    if reference == 0:
        if computed == 0:
            return float("inf")
        return -math.log10(abs(computed))
    rel_err = abs((computed - reference) / reference)
    if rel_err == 0:
        return float("inf")
    return -math.log10(rel_err)


def _load_answers():
    path = "/app/answers.txt"
    assert os.path.exists(path), f"Answer file not found at {path}"
    with open(path) as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) >= 3, f"Expected >= 3 lines in answers.txt, got {len(lines)}"
    values = []
    for i, line in enumerate(lines[:3]):
        try:
            values.append(float(line))
        except ValueError:
            pytest.fail(f"Line {i+1} is not a valid number: {line!r}")
    return values


# ---- format tests ----

def test_file_exists():
    assert os.path.exists("/app/answers.txt"), "/app/answers.txt not found"


def test_has_three_answers():
    with open("/app/answers.txt") as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) >= 3, f"Need 3 answers, got {len(lines)}"


def test_all_parseable():
    with open("/app/answers.txt") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                float(line)
            except ValueError:
                pytest.fail(f"Line {i+1} not a valid float: {line!r}")


# ---- precision tests ----

def test_challenge_c1():
    ans = _load_answers()
    digits = _significant_digits(ans[0], REFS[0])
    assert digits >= REQUIRED_DIGITS, (
        f"C1: got {digits:.1f} sig-digits (need {REQUIRED_DIGITS}). "
        f"computed={ans[0]:.16e}, ref={REFS[0]:.16e}"
    )


def test_challenge_c2():
    ans = _load_answers()
    digits = _significant_digits(ans[1], REFS[1])
    assert digits >= REQUIRED_DIGITS, (
        f"C2: got {digits:.1f} sig-digits (need {REQUIRED_DIGITS}). "
        f"computed={ans[1]:.16e}, ref={REFS[1]:.16e}"
    )


def test_challenge_c3():
    ans = _load_answers()
    digits = _significant_digits(ans[2], REFS[2])
    assert digits >= REQUIRED_DIGITS, (
        f"C3: got {digits:.1f} sig-digits (need {REQUIRED_DIGITS}). "
        f"computed={ans[2]:.16e}, ref={REFS[2]:.16e}"
    )
