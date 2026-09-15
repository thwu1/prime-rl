
"""
Tests for the IR optimizer.

Verifies:
1. Correctness: optimized programs produce identical output to originals
2. Validity: optimizer returns well-formed instruction lists
3. Effectiveness: optimizer achieves required instruction count reductions
"""

import sys
import os

# Ensure /app is on the path so ir, ir_interpreter, optimizer, programs can be imported
sys.path.insert(0, '/app')

# Verify the app files exist before attempting import
assert os.path.isfile('/app/ir.py'), "/app/ir.py not found"

import pytest
from ir import Instruction
from ir_interpreter import interpret
from optimizer import optimize
from programs import PROGRAMS


class TestOptimizerCorrectness:
    """Optimized programs must produce the same output as the originals."""

    @pytest.mark.parametrize(
        "prog", PROGRAMS, ids=[p['name'] for p in PROGRAMS]
    )
    def test_output_preserved(self, prog):
        original_output = interpret(
            prog['instructions'], prog.get('stdin', [])
        )
        assert original_output == prog['expected_output'], (
            f"Sanity check failed for '{prog['name']}': "
            f"interpreter output {original_output} != expected {prog['expected_output']}"
        )

        optimized = optimize(list(prog['instructions']))
        optimized_output = interpret(optimized, prog.get('stdin', []))
        assert optimized_output == prog['expected_output'], (
            f"Output mismatch for '{prog['name']}' after optimization: "
            f"got {optimized_output}, expected {prog['expected_output']}"
        )

    @pytest.mark.parametrize(
        "prog", PROGRAMS, ids=[p['name'] for p in PROGRAMS]
    )
    def test_returns_valid_instructions(self, prog):
        optimized = optimize(list(prog['instructions']))
        assert isinstance(optimized, list), "optimize() must return a list"
        for i, insn in enumerate(optimized):
            assert isinstance(insn, Instruction), (
                f"Element {i} is {type(insn).__name__}, not an Instruction"
            )


class TestOptimizerEffectiveness:
    """The optimizer must actually reduce instruction counts."""

    def test_overall_reduction_threshold(self):
        """Total instruction count across all programs must drop by >= 35%."""
        total_original = 0
        total_optimized = 0
        details = []
        for prog in PROGRAMS:
            orig = prog['instructions']
            opt = optimize(list(orig))
            total_original += len(orig)
            total_optimized += len(opt)
            pct = 1.0 - len(opt) / len(orig) if len(orig) > 0 else 0.0
            details.append(f"  {prog['name']}: {len(orig)} -> {len(opt)} ({pct:.0%})")

        reduction = 1.0 - (total_optimized / total_original)
        detail_str = "\n".join(details)
        assert reduction >= 0.35, (
            f"Overall reduction {reduction:.1%} is below the required 35%.\n"
            f"Per-program breakdown:\n{detail_str}"
        )

    @pytest.mark.parametrize(
        "prog", PROGRAMS, ids=[p['name'] for p in PROGRAMS]
    )
    def test_per_program_reduction(self, prog):
        """Each program must meet its individual minimum reduction threshold."""
        orig = prog['instructions']
        opt = optimize(list(orig))
        min_red = prog.get('min_reduction', 0.0)
        if min_red > 0 and len(orig) > 0:
            actual_red = 1.0 - len(opt) / len(orig)
            assert actual_red >= min_red, (
                f"Program '{prog['name']}': reduction {actual_red:.1%} "
                f"is below required {min_red:.0%} "
                f"({len(orig)} -> {len(opt)} instructions)"
            )
