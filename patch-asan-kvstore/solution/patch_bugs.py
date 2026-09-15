#!/usr/bin/env python3
"""
Comprehensive security audit and patch for kvstore.c.
Identifies and fixes 6 memory safety vulnerabilities through
ASan report analysis and manual code review.

Vulnerability 1 (CWE-122): Heap buffer overflow in parse_quoted
  malloc(len-2) omits space for null terminator.

Vulnerability 2 (CWE-416): Use-after-free in cmd_rename
  Value pointer transferred to new entry, then freed via old entry.
  ASan report shows crash in cmd_get (symptom), root cause is here.

Vulnerability 3 (CWE-121): Stack buffer overflow in cmd_keys
  Unbounded copy of user pattern into 64-byte stack buffer.

Vulnerability 4 (CWE-125): Heap over-read in cmd_getrange
  End index not clamped to string length before memcpy.

Vulnerability 5 (CWE-416): Use-after-free in cmd_copy (self-copy)
  When COPY key key, src_e==dst_e; free(dst_e->value) invalidates
  src_e->value before strdup reads it.

Vulnerability 6 (CWE-121): Stack buffer overflow in cmd_mget
  Fixed 512-byte stack buffer receives unbounded sprintf output.
"""

with open("/app/src/kvstore.c", "r") as f:
    lines = f.readlines()

result = []
i = 0
n = len(lines)

current_func = ""
bug2_done = False
bug4_done = False
bug5_done = False

while i < n:
    line = lines[i]

    # Track current function context
    if "static void cmd_rename(" in line:
        current_func = "cmd_rename"
    elif "static void cmd_copy(" in line:
        current_func = "cmd_copy"
    elif "static void cmd_mget(" in line:
        current_func = "cmd_mget"
    elif line.startswith("static ") and "(" in line:
        current_func = ""
    elif "int main(" in line:
        current_func = ""

    # === Bug 1: parse_quoted off-by-one in malloc ===
    if "malloc(len - 2)" in line:
        line = line.replace("malloc(len - 2)", "malloc(len - 1)")
        result.append(line)
        i += 1
        continue

    # === Bug 2: cmd_rename UAF — don't free the transferred value ===
    if (current_func == "cmd_rename"
            and "    free(old_e->value);" in line
            and not bug2_done):
        # Skip this line entirely — value ownership was transferred
        bug2_done = True
        i += 1
        continue

    # === Bug 3: cmd_keys stack overflow — bound the loop ===
    if "for (i = 0; pattern[i]; i++)" in line:
        line = line.replace(
            "for (i = 0; pattern[i]; i++)",
            "for (i = 0; pattern[i] && i < PATTERN_BUF - 1; i++)",
        )
        result.append(line)
        i += 1
        continue

    # === Bug 4: cmd_getrange heap over-read — clamp end ===
    if "    int n = end - start + 1;" in line and not bug4_done:
        result.append("    if (end >= len) end = len - 1;\n")
        result.append(line)
        bug4_done = True
        i += 1
        continue

    # === Bug 5: cmd_copy self-copy UAF — early return guard ===
    if (current_func == "cmd_copy"
            and "        free(dst_e->value);" in line
            and not bug5_done):
        result.append('        if (dst_e == src_e) { printf("OK\\n"); return; }\n')
        result.append(line)
        bug5_done = True
        i += 1
        continue

    # === Bug 6: cmd_mget stack overflow — replace buffer with direct printf ===
    if current_func == "cmd_mget" and "Format all values" in line:
        # Skip the entire fixed-buffer section and replace with direct output
        j = i + 1
        while j < n:
            if 'printf("%s", response)' in lines[j]:
                break
            j += 1
        # Insert replacement: direct printf calls (no intermediate buffer)
        result.append("    for (int i = 0; i < nkeys; i++) {\n")
        result.append("        Entry *e = find_entry(keys[i]);\n")
        result.append("        if (e) {\n")
        result.append('            printf("%d) %s\\n", i + 1, e->value);\n')
        result.append("        } else {\n")
        result.append('            printf("%d) (nil)\\n", i + 1);\n')
        result.append("        }\n")
        result.append("    }\n")
        i = j + 1  # skip past the printf("%s", response) line
        continue

    result.append(line)
    i += 1

with open("/app/src/kvstore.c", "w") as f:
    f.writelines(result)

import sys
print("Patched 6 vulnerabilities in kvstore.c", file=sys.stderr)
