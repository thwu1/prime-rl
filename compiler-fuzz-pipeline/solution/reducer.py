#!/usr/bin/env python3

"""Delta-debugging test case reducer.

Reduces a C source file by iteratively removing contiguous chunks of lines
while preserving an interestingness property (checked via external script).
"""

import subprocess
import sys
import os
import tempfile


def is_interesting(lines, test_script, tmpdir):
    """Write lines to a temp file and check interestingness."""
    tmp_path = os.path.join(tmpdir, "candidate.c")
    with open(tmp_path, "w") as f:
        f.writelines(lines)
    try:
        result = subprocess.run(
            [test_script, tmp_path],
            capture_output=True,
            timeout=60,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def reduce(lines, test_script, tmpdir):
    """Delta debugging: remove largest possible contiguous chunks."""
    for pass_num in range(15):
        old_len = len(lines)
        chunk_size = max(1, len(lines) // 2)
        while chunk_size >= 1:
            i = 0
            while i + chunk_size <= len(lines):
                candidate = lines[:i] + lines[i + chunk_size:]
                if is_interesting(candidate, test_script, tmpdir):
                    lines = candidate
                else:
                    i += chunk_size
            chunk_size //= 2
        if len(lines) == old_len:
            break
        print(f"  pass {pass_num + 1}: {len(lines)} lines remaining")
    return lines


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <test_script> <input.c> <output.c>")
        sys.exit(1)

    test_script = os.path.abspath(sys.argv[1])
    input_file = sys.argv[2]
    output_file = sys.argv[3]

    with open(input_file) as f:
        lines = f.readlines()

    print(f"Starting reduction: {len(lines)} lines")

    tmpdir = tempfile.mkdtemp(prefix="reducer_")
    try:
        if not is_interesting(lines, test_script, tmpdir):
            print("ERROR: input file is not interesting, cannot reduce")
            sys.exit(1)
        reduced = reduce(lines, test_script, tmpdir)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    with open(output_file, "w") as f:
        f.writelines(reduced)

    print(f"Reduction complete: {len(reduced)} lines -> {output_file}")


if __name__ == "__main__":
    main()
