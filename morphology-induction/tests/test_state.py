"""
Test the xenogenetic code recovery outputs against gold standard.

"""

import os
import pytest


TRANSLATED_PATH = "/app/results/translated.txt"
CODON_TABLE_PATH = "/app/results/codon_table.tsv"
GOLD_TRANSLATED_PATH = "/tests/gold_translated.txt"
GOLD_CODON_TABLE_PATH = "/tests/gold_codon_table.tsv"


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def test_translation():
    """Test that translated protein sequences match gold standard."""
    gold = read_lines(GOLD_TRANSLATED_PATH)
    assert len(gold) == 25, f"Gold file should have 25 lines, got {len(gold)}"

    result = read_lines(TRANSLATED_PATH)
    assert len(result) > 0, (
        f"No output found at {TRANSLATED_PATH}. "
        "Make sure your program writes results there."
    )
    assert len(result) == 25, (
        f"Expected 25 translated sequences, got {len(result)}"
    )

    correct = 0
    mismatches = []
    for i, (expected, actual) in enumerate(zip(gold, result), 1):
        if expected == actual:
            correct += 1
        else:
            mismatches.append(f"  Seq {i}: expected '{expected}', got '{actual}'")

    assert correct >= 20, (
        f"Only {correct}/25 translations correct (need >= 20).\n"
        f"Mismatches:\n" + "\n".join(mismatches)
    )


def test_codon_table():
    """Test that the discovered codon table matches gold standard."""
    gold_lines = read_lines(GOLD_CODON_TABLE_PATH)
    gold_entries = {}
    for line in gold_lines:
        parts = line.split("\t")
        if len(parts) == 2 and len(parts[0]) == 3 and parts[0] != "cod":
            gold_entries[parts[0]] = parts[1]

    assert len(gold_entries) == 64, (
        f"Gold codon table should have 64 entries, got {len(gold_entries)}"
    )

    result_lines = read_lines(CODON_TABLE_PATH)
    assert len(result_lines) > 0, (
        f"No output found at {CODON_TABLE_PATH}. "
        "Make sure your program writes the codon table there."
    )

    result_entries = {}
    for line in result_lines:
        parts = line.split("\t")
        if len(parts) >= 2 and len(parts[0]) == 3:
            result_entries[parts[0]] = parts[1]

    assert len(result_entries) >= 60, (
        f"Expected ~64 codon entries, got {len(result_entries)}"
    )

    correct = 0
    mismatches = []
    for codon in sorted(gold_entries.keys()):
        if codon in result_entries and result_entries[codon] == gold_entries[codon]:
            correct += 1
        else:
            got = result_entries.get(codon, "MISSING")
            mismatches.append(
                f"  {codon}: expected '{gold_entries[codon]}', got '{got}'"
            )

    assert correct >= 58, (
        f"Only {correct}/64 codon assignments correct (need >= 58).\n"
        f"Mismatches:\n" + "\n".join(mismatches[:20])
    )
