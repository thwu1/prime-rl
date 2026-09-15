
"""Tests for assembler with binary emission (/app/relax.py)."""

import json
import os
import subprocess
import tempfile

import pytest

RELAX_PY = "/app/relax.py"
REFERENCE_ASM = "/app/reference_asm"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_relax(asm_content: str) -> dict:
    """Write assembly to a temp file, run relax.py, return parsed JSON output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".asm", delete=False) as f:
        f.write(asm_content)
        f.flush()
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["python3", RELAX_PY, tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"relax.py exited with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        output = json.loads(result.stdout)
        assert "labels" in output, "Output JSON must contain 'labels'"
        assert "total_size" in output, "Output JSON must contain 'total_size'"
        return output
    finally:
        os.unlink(tmp_path)


def run_reference(asm_content: str) -> dict:
    """Write assembly to a temp file, run reference assembler JSON mode."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".asm", delete=False) as f:
        f.write(asm_content)
        f.flush()
        tmp_path = f.name

    try:
        result = subprocess.run(
            [REFERENCE_ASM, "-j", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"reference_asm exited with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        return json.loads(result.stdout)
    finally:
        os.unlink(tmp_path)


def run_relax_binary(asm_content: str) -> bytes:
    """Run relax.py -b -o to get binary output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".asm", delete=False) as f:
        f.write(asm_content)
        f.flush()
        tmp_path = f.name
    out_path = tmp_path + ".sol.bin"

    try:
        result = subprocess.run(
            ["python3", RELAX_PY, "-b", tmp_path, "-o", out_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"relax.py -b exited with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        with open(out_path, "rb") as bf:
            return bf.read()
    finally:
        os.unlink(tmp_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def run_reference_binary(asm_content: str) -> bytes:
    """Run reference_asm -o to get binary output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".asm", delete=False) as f:
        f.write(asm_content)
        f.flush()
        tmp_path = f.name
    out_path = tmp_path + ".ref.bin"

    try:
        result = subprocess.run(
            [REFERENCE_ASM, "-o", out_path, tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"reference_asm -o exited with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        with open(out_path, "rb") as bf:
            return bf.read()
    finally:
        os.unlink(tmp_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def binary_diff_msg(sol: bytes, ref: bytes) -> str:
    """Create a helpful diff message for binary mismatches."""
    if len(sol) != len(ref):
        return f"Size mismatch: solution={len(sol)} bytes, reference={len(ref)} bytes"
    for i, (s, r) in enumerate(zip(sol, ref)):
        if s != r:
            ctx = min(i, 4)
            return (
                f"First mismatch at byte {i}: sol=0x{s:02x} ref=0x{r:02x}\n"
                f"  sol[{i-ctx}:{i+8}]: {sol[i-ctx:i+8].hex(' ')}\n"
                f"  ref[{i-ctx}:{i+8}]: {ref[i-ctx:i+8].hex(' ')}"
            )
    return "identical"


# ===========================================================================
# PART 1: Relaxation correctness (JSON label/size verification)
# ===========================================================================


# ---------------------------------------------------------------------------
# Basic: no relaxation needed
# ---------------------------------------------------------------------------


def test_trivial_no_relaxation():
    """All jumps easily fit in short form."""
    asm = """\
start:
    nop
    jmp end
    nop
end:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["start"] == 0
    assert result["labels"]["end"] == 4
    assert result["total_size"] == 5


def test_multiple_short_jumps():
    """Several short jumps, all within range."""
    asm = """\
    jmp A
    jz B
    jnz C
A:
    nop
B:
    nop
C:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["A"] == 6
    assert result["labels"]["B"] == 7
    assert result["labels"]["C"] == 8
    assert result["total_size"] == 9


def test_backward_short_jump():
    """Backward jump that fits in short form."""
    asm = """\
loop:
    nop
    nop
    jmp loop
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["loop"] == 0
    assert result["total_size"] == 5


# ---------------------------------------------------------------------------
# Simple long-form encoding
# ---------------------------------------------------------------------------


def test_forward_jmp_long():
    """Forward jmp must use long form (5 bytes) due to displacement."""
    asm = """\
start:
    jmp target
    .fill 200
target:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["start"] == 0
    assert result["labels"]["target"] == 205
    assert result["total_size"] == 206


def test_backward_jmp_long():
    """Backward jmp must use long form."""
    asm = """\
loop:
    .fill 200
    jmp loop
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["loop"] == 0
    assert result["total_size"] == 206


def test_forward_jcc_long():
    """Conditional jump (jz) uses 6-byte long form, not 5."""
    asm = """\
    jz target
    .fill 200
target:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["target"] == 206
    assert result["total_size"] == 207


def test_different_long_form_sizes():
    """jmp long = 5 bytes; jz long = 6 bytes."""
    asm = """\
    jmp A
    jz B
    .fill 200
A:
    nop
B:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["A"] == 211
    assert result["labels"]["B"] == 212
    assert result["total_size"] == 213


# ---------------------------------------------------------------------------
# Interdependent encoding choices
# ---------------------------------------------------------------------------


def test_interdependent_jumps():
    """Both jumps must use long form due to mutually-dependent offsets."""
    asm = """\
    jmp A
    jz B
    .fill 124
A:
    .fill 4
B:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["A"] == 135
    assert result["labels"]["B"] == 139
    assert result["total_size"] == 140


def test_three_stage_cascade():
    """Three jumps where each encoding decision depends on the previous."""
    asm = """\
    jmp A
    jz B
    jnz C
    .fill 118
A:
    .fill 5
B:
    .fill 5
C:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["A"] == 135
    assert result["labels"]["B"] == 140
    assert result["labels"]["C"] == 145
    assert result["total_size"] == 146


# ---------------------------------------------------------------------------
# Alignment interaction
# ---------------------------------------------------------------------------


def test_alignment_no_relaxation():
    """Alignment adds padding but jump still fits in short form."""
    asm = """\
    jmp target
    .fill 120
    .align 16
target:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["target"] == 128
    assert result["total_size"] == 129


def test_alignment_forces_long():
    """Alignment padding pushes displacement beyond short-form range."""
    asm = """\
    jmp target
    .fill 127
    .align 16
target:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["target"] == 144
    assert result["total_size"] == 145


def test_alignment_padding_shift():
    """Encoding changes shift alignment boundaries, producing cascades."""
    asm = """\
    jmp A
    jnz B
    .fill 122
    .align 8
A:
    jle C
    .fill 120
C:
    .fill 3
B:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["A"] == 136
    assert result["labels"]["C"] == 258
    assert result["labels"]["B"] == 261
    assert result["total_size"] == 262


# ---------------------------------------------------------------------------
# Signed boundary conditions: +127/-128 edges
# ---------------------------------------------------------------------------


def test_forward_boundary_exact_fit():
    """Forward displacement is exactly +127 (maximum short-form value)."""
    asm = """\
    jmp target
    .fill 127
target:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["target"] == 129
    assert result["total_size"] == 130


def test_forward_boundary_overflow():
    """Forward displacement is +128 — one past the short-form limit."""
    asm = """\
    jmp target
    .fill 128
target:
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["target"] == 133
    assert result["total_size"] == 134


def test_backward_boundary_exact_fit():
    """Backward displacement is exactly -128 (minimum short-form value)."""
    asm = """\
target:
    .fill 126
    jmp target
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["target"] == 0
    assert result["total_size"] == 129


def test_backward_boundary_overflow():
    """Backward displacement is -129 — one past the short-form limit."""
    asm = """\
target:
    .fill 127
    jmp target
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["target"] == 0
    assert result["total_size"] == 133


# ---------------------------------------------------------------------------
# Complex multi-feature program
# ---------------------------------------------------------------------------


def test_complex_program():
    """Program with push/pop, mov, call, alignment, mixed jumps."""
    asm = """\
    push r0
    push r1
    mov r0, 0
    jmp loop_start
    .align 16
setup:
    mov r1, 100
    call helper
    jz done
    .fill 130
loop_start:
    add r0, 1
    cmp r0, r1
    jl loop_start
    jmp done
    .fill 50
helper:
    nop
    ret
done:
    pop r1
    pop r0
    ret
"""
    result = run_relax(asm)
    assert result["labels"]["setup"] == 16
    assert result["labels"]["loop_start"] == 160
    assert result["labels"]["helper"] == 219
    assert result["labels"]["done"] == 221
    assert result["total_size"] == 226


# ---------------------------------------------------------------------------
# Reference assembler cross-validation (JSON)
# ---------------------------------------------------------------------------


def test_matches_reference_stress():
    """JSON output must match reference on a stress-test input."""
    asm = """\
    push r0
    push r1
    mov r0, 42
    jmp entry
    .fill 50
    .align 32
entry:
    jz short_path
    jnz far_path
    nop
short_path:
    add r0, 1
    jmp exit
    .fill 200
far_path:
    sub r0, r1
    call entry
    jle short_path
    .fill 80
    .align 16
exit:
    pop r1
    pop r0
    ret
"""
    ref = run_reference(asm)
    sol = run_relax(asm)
    assert sol["labels"] == ref["labels"], (
        f"Labels mismatch:\n  solution:  {sol['labels']}\n  reference: {ref['labels']}"
    )
    assert sol["total_size"] == ref["total_size"], (
        f"Size mismatch: solution={sol['total_size']}, reference={ref['total_size']}"
    )


def test_matches_reference_deep_cascade():
    """Reference cross-check on deep interdependencies."""
    asm = """\
    jmp L1
    jz L2
    jnz L3
    jl L4
    .fill 110
    .align 16
L1:
    nop
    .fill 5
L2:
    nop
    .fill 5
L3:
    nop
    .fill 5
L4:
    jge L1
    .fill 100
    jmp L1
    ret
"""
    ref = run_reference(asm)
    sol = run_relax(asm)
    assert sol["labels"] == ref["labels"], (
        f"Labels mismatch:\n  solution:  {sol['labels']}\n  reference: {ref['labels']}"
    )
    assert sol["total_size"] == ref["total_size"], (
        f"Size mismatch: solution={sol['total_size']}, reference={ref['total_size']}"
    )


# ===========================================================================
# PART 2: Binary emission correctness (byte-for-byte reference comparison)
# ===========================================================================


def test_binary_nop_ret():
    """Binary output for minimal nop+ret program."""
    asm = "nop\nret\n"
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert len(sol) == 2, f"Expected 2 bytes, got {len(sol)}"
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_push_pop():
    """Binary output for push/pop with various registers."""
    asm = "push r0\npush r3\npush r7\npop r2\npop r5\nret\n"
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert len(sol) == 11, f"Expected 11 bytes, got {len(sol)}"
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_register_arithmetic():
    """Binary output for register-register instructions."""
    asm = """\
mov r0, r1
add r2, r3
sub r4, r5
cmp r6, r7
ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert len(sol) == 9, f"Expected 9 bytes, got {len(sol)}"
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_immediate_instructions():
    """Binary output for register-immediate instructions."""
    asm = """\
mov r0, 42
add r1, -1
sub r2, 100
cmp r3, 0
ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert len(sol) == 13, f"Expected 13 bytes, got {len(sol)}"
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_call_instruction():
    """Binary output with call and PC-relative encoding."""
    asm = """\
    call target
    nop
target:
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert len(sol) == 7, f"Expected 7 bytes, got {len(sol)}"
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_short_jumps_all_types():
    """Binary output with all short-form jump types."""
    asm = """\
    jmp target
    jz target
    jnz target
    jl target
    jg target
    jle target
    jge target
target:
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_long_jmp_with_fill():
    """Binary output with long-form unconditional jump."""
    asm = """\
    jmp target
    .fill 200
target:
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_long_conditionals():
    """Binary output with long-form conditional jumps (2-byte prefix)."""
    asm = """\
    jz tgt_z
    jnz tgt_nz
    jl tgt_l
    jg tgt_g
    jle tgt_le
    jge tgt_ge
    .fill 200
tgt_z:
    nop
tgt_nz:
    nop
tgt_l:
    nop
tgt_g:
    nop
tgt_le:
    nop
tgt_ge:
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_alignment_padding():
    """Binary output with alignment producing padding bytes."""
    asm = """\
    nop
    nop
    nop
    .align 8
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    # 3 nops + 5 padding bytes + 1 ret = 9 bytes
    assert len(sol) == 9, f"Expected 9 bytes, got {len(sol)}"
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_complex_program():
    """Binary output for complex program with relaxation, call, alignment."""
    asm = """\
    push r0
    push r1
    mov r0, 0
    jmp loop_start
    .align 16
setup:
    mov r1, 100
    call helper
    jz done
    .fill 130
loop_start:
    add r0, 1
    cmp r0, r1
    jl loop_start
    jmp done
    .fill 50
helper:
    nop
    ret
done:
    pop r1
    pop r0
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert len(sol) == len(ref), (
        f"Size mismatch: solution={len(sol)}, reference={len(ref)}"
    )
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_reference_all_instructions():
    """Binary output for a program using every instruction type."""
    asm = """\
    nop
    push r0
    push r3
    pop r7
    pop r2
    mov r0, r1
    mov r5, r6
    mov r0, 42
    mov r3, -1
    add r2, r4
    add r0, 10
    sub r1, r7
    sub r5, -5
    cmp r3, r6
    cmp r0, 0
    call helper
    jmp end
    jz end
    jnz end
    jl end
    jg end
    jle end
    jge end
helper:
    nop
    ret
end:
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_backward_call():
    """Binary output with backward call (negative PC-relative offset)."""
    asm = """\
helper:
    nop
    ret
main:
    call helper
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert sol == ref, binary_diff_msg(sol, ref)


def test_binary_stress_mixed():
    """Binary cross-validation on stress program with all features."""
    asm = """\
    push r0
    push r1
    mov r0, 42
    jmp entry
    .fill 50
    .align 32
entry:
    jz short_path
    jnz far_path
    nop
short_path:
    add r0, 1
    jmp exit
    .fill 200
far_path:
    sub r0, r1
    call entry
    jle short_path
    .fill 80
    .align 16
exit:
    pop r1
    pop r0
    ret
"""
    ref = run_reference_binary(asm)
    sol = run_relax_binary(asm)
    assert len(sol) == len(ref), (
        f"Size mismatch: solution={len(sol)}, reference={len(ref)}"
    )
    assert sol == ref, binary_diff_msg(sol, ref)
