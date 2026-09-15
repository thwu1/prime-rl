
"""LLVM IR instruction counting module.

Provides functions to compile C to LLVM IR, optimize IR with specified
pass sequences, and count instructions in the resulting IR.
"""

import subprocess
import shutil
import tempfile
import os

# Find LLVM tools
OPT = shutil.which("opt") or shutil.which("opt-18") or "opt"
CLANG = shutil.which("clang") or shutil.which("clang-18") or "clang"


def compile_to_ir(c_file, output_ll):
    """Compile a C source file to LLVM IR (unoptimized, without optnone)."""
    cmd = [CLANG, "-S", "-emit-llvm", "-O0", "-Xclang",
           "-disable-O0-optnone", c_file, "-o", output_ll]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Compilation failed: {result.stderr}")


def optimize_ir(input_ll, output_ll, passes):
    """Run LLVM opt with the given pass sequence.

    Args:
        input_ll: Path to input LLVM IR file.
        output_ll: Path to write the optimized IR.
        passes: List of pass names (strings). Empty list means no optimization.
    """
    if not passes:
        shutil.copy(input_ll, output_ll)
        return
    passes_str = ",".join(passes)
    cmd = [OPT, f"-passes={passes_str}", "-S", input_ll, "-o", output_ll]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"opt failed: {result.stderr}")


def parse_instruction_count(ll_file):
    """Count instructions in an LLVM IR file by parsing the text.

    Counts indented non-comment lines inside function bodies.
    Labels (at column 0) and metadata are excluded.
    """
    count = 0
    in_function = False
    with open(ll_file, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('define '):
                in_function = True
                continue
            if in_function and stripped == '}':
                in_function = False
                continue
            if in_function and line[0] in (' ', '\t') and not stripped.startswith(';'):
                count += 1
    return count


def count_instructions(ir_file, passes):
    """Count instructions in an IR file after applying the given passes.

    Args:
        ir_file: Path to LLVM IR (.ll) file.
        passes: List of pass names to apply before counting.

    Returns:
        Integer instruction count of the optimized IR.
    """
    with tempfile.NamedTemporaryFile(suffix='.ll', delete=False) as tmp:
        output_file = tmp.name
    try:
        optimize_ir(ir_file, output_file, passes)
        return parse_instruction_count(ir_file)
    finally:
        if os.path.exists(output_file):
            os.unlink(output_file)
