#!/usr/bin/env python3
"""
LLVM IR instruction counter.

Counts instructions by parsing LLVM IR textual representation. Optionally
applies optimization passes via `opt` before counting.

Usage:
  python3 instcount.py <file.ll>                # Count instructions in file
  python3 instcount.py <file.ll> <passes>       # Apply passes then count
  python3 instcount.py <file.ll> -Oz            # Apply -Oz then count

Can also be imported as a module:
  from instcount import get_instruction_count, count_instructions_in_ir
"""

import subprocess
import sys
import re
import os


def count_instructions_in_ir(ir_text):
    """Parse LLVM IR text and count instructions.

    Counts all lines inside function bodies that are actual instructions
    (not labels, comments, or structural syntax).
    """
    count = 0
    in_function = False
    depth = 0
    for line in ir_text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        # Detect function body start
        if re.match(r'^define\s', stripped):
            if '{' in stripped:
                in_function = True
                depth = 1
            continue
        if not in_function:
            continue
        # Track brace depth for nested structures
        open_b = stripped.count('{')
        close_b = stripped.count('}')
        depth += open_b - close_b
        if depth <= 0:
            in_function = False
            depth = 0
            continue
        # Skip comments
        if stripped.startswith(';'):
            continue
        # Skip basic block labels: "name:" optionally followed by comment/preds
        if re.match(r'^[\w.$-]+:\s*(;.*)?$', stripped):
            continue
        # Everything else inside a function body is an instruction
        count += 1
    return count


def get_instruction_count(ll_file, passes=None):
    """Get instruction count for an IR file, optionally after applying passes.

    Args:
        ll_file: Path to LLVM IR (.ll) file
        passes: Optional pass specification. Either an optimization level
                like '-Oz' or comma-separated pass names like
                'instcombine,gvn,simplifycfg'

    Returns:
        Integer instruction count, or None on failure.
    """
    if passes:
        if passes.startswith('-O') or passes == '-Os' or passes == '-Oz':
            cmd = ['opt', passes, '-S', ll_file]
        else:
            cmd = ['opt', '--passes=' + passes, '-S', ll_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return None
            return count_instructions_in_ir(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
    else:
        try:
            with open(ll_file, 'r') as f:
                return count_instructions_in_ir(f.read())
        except (IOError, OSError):
            return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 instcount.py <file.ll> [passes]", file=sys.stderr)
        sys.exit(1)

    ll_file = sys.argv[1]
    passes = sys.argv[2] if len(sys.argv) > 2 else None

    count = get_instruction_count(ll_file, passes)
    if count is not None:
        print(count)
    else:
        print("ERROR: Could not count instructions", file=sys.stderr)
        sys.exit(1)
