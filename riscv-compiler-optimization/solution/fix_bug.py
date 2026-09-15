#!/usr/bin/env python3
"""Fix the signed-overflow UB in scale_value() in math_utils.c."""

import re

SRC = "/app/src/math_utils.c"

with open(SRC, "r") as f:
    content = f.read()

# Match the entire scale_value function body
pattern = re.compile(
    r"(int scale_value\(int x, int factor\)\s*\{)"  # signature
    r".*?"                                            # body
    r"(\n\})",                                        # closing brace
    re.DOTALL,
)

fixed_body = r"""int scale_value(int x, int factor) {
    int64_t wide_result = (int64_t)x * (int64_t)factor;
    if (wide_result > INT_MAX) return INT_MAX;
    if (wide_result < INT_MIN) return INT_MIN;
    return (int)wide_result;
}"""

content = pattern.sub(fixed_body, content)

with open(SRC, "w") as f:
    f.write(content)

print("Fixed scale_value() UB bug.")
