#!/usr/bin/env python3
"""Fix all bugs in the evaluation harness."""

# Fix 1: extractor.py
# - re.MULTILINE does not make '.' match newlines; re.DOTALL does.
#   Without re.DOTALL the regex cannot match multi-line code blocks.
# - The fallback substring search uses range(i+1, len(lines)) which
#   excludes the last line. Must be range(i+1, len(lines)+1).
with open('/app/harness/extractor.py', 'r') as f:
    src = f.read()
src = src.replace('re.MULTILINE', 're.DOTALL')
src = src.replace('range(i + 1, len(lines))', 'range(i + 1, len(lines) + 1)')
with open('/app/harness/extractor.py', 'w') as f:
    f.write(src)

# Fix 2: metrics.py
# - The boundary condition 'if c >= k' is wrong.
#   The correct condition is 'if n - c < k' (when there are fewer
#   failures than k, pass@k is trivially 1.0).
with open('/app/harness/metrics.py', 'r') as f:
    src = f.read()
src = src.replace('if c >= k:', 'if n - c < k:')
with open('/app/harness/metrics.py', 'w') as f:
    f.write(src)

# Fix 3: sandbox.py
# - The check program concatenation is missing a newline between the
#   completion code and the test function, causing SyntaxError when
#   the last line of code merges with 'def check(candidate):'.
with open('/app/harness/sandbox.py', 'r') as f:
    src = f.read()
src = src.replace(
    "        + problem['test']",
    "        + '\\n' + problem['test']"
)
with open('/app/harness/sandbox.py', 'w') as f:
    f.write(src)

print("All harness bugs fixed.")
