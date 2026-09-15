#!/usr/bin/env python3
"""Apply targeted fixes to the Unix process bugs in pipeline.c."""

import sys

with open("/app/pipeline.c", "r") as f:
    code = f.read()

original = code
changes = 0

# Fix 1: MAP_PRIVATE -> MAP_SHARED
old = "MAP_PRIVATE | MAP_ANONYMOUS"
new = "MAP_SHARED | MAP_ANONYMOUS"
if old in code:
    code = code.replace(old, new)
    changes += 1

# Fix 2: Add fflush(outf) after header fprintf, before fork loop
old = '    fprintf(outf, "PIPELINE workers=%d datasize=%d\\n", nworkers, count);\n\n    int pfd[2];'
new = '    fprintf(outf, "PIPELINE workers=%d datasize=%d\\n", nworkers, count);\n    fflush(outf);\n\n    int pfd[2];'
if old in code:
    code = code.replace(old, new)
    changes += 1

# Fix 3: Parent must close pipe write end before reading
old = "    /* Read worker results from pipe */\n    FILE *rpipe"
new = "    close(pfd[1]);\n\n    /* Read worker results from pipe */\n    FILE *rpipe"
if old in code:
    code = code.replace(old, new)
    changes += 1

# Fix 4: _exit(0) instead of exit(0) in forked children
old = "            exit(0);"
new = "            _exit(0);"
if old in code:
    code = code.replace(old, new)
    changes += 1

if code == original:
    print("ERROR: No changes were applied", file=sys.stderr)
    sys.exit(1)

with open("/app/pipeline.c", "w") as f:
    f.write(code)

print(f"Applied {changes} fixes to /app/pipeline.c")
