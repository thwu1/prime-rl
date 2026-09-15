#!/usr/bin/env python3
"""
audit_and_fix.py

1. Parse original firmware source + disassembly to identify
   security-critical memset calls eliminated by -O2 dead-store
   optimisation, timing side-channels, and missing hardening.
2. Write /app/audit_report.json.
3. Generate /app/firmware_fixed/ with all vulnerabilities remediated.
"""

import json
import os
import re
import shutil

SRC_DIR = "/app/firmware"
FIX_DIR = "/app/firmware_fixed"
DIS_PATH = os.path.join(SRC_DIR, "keyfob.dis")
REPORT_PATH = "/app/audit_report.json"

# ── helpers ──────────────────────────────────────────────────────────

def read(path: str) -> str:
    with open(path) as f:
        return f.read()


def extract_function_disasm(dis_text: str, func: str) -> str:
    """Return the disassembly block for *func*."""
    lines = dis_text.splitlines()
    collecting = False
    result: list[str] = []
    for line in lines:
        if re.search(rf"<{re.escape(func)}>:", line):
            collecting = True
            result.append(line)
            continue
        if collecting:
            if line.strip() == "" and result:
                break
            if re.match(r"^[0-9a-f]+ <", line):
                break
            result.append(line)
    return "\n".join(result)


# ── Step 1: analyse ──────────────────────────────────────────────────

dis_text = read(DIS_PATH)
src_text = read(os.path.join(SRC_DIR, "secure_keyfob.c"))

# Functions that contain memset on local buffers in source
security_funcs = [
    "verify_pin",
    "process_unlock_command",
    "pair_device",
    "compute_challenge_response",
]

# Count memset calls in source per function (quick heuristic)
func_source_memsets: dict[str, int] = {}
for func in security_funcs:
    m = re.search(rf"{func}\s*\([^)]*\)\s*\{{", src_text)
    if not m:
        continue
    start = m.end()
    depth = 1
    i = start
    while i < len(src_text) and depth > 0:
        if src_text[i] == "{":
            depth += 1
        elif src_text[i] == "}":
            depth -= 1
        i += 1
    body = src_text[start:i]
    func_source_memsets[func] = body.count("memset")

# Count memset branch-and-link calls in disassembly per function
func_binary_memsets: dict[str, int] = {}
for func in security_funcs:
    block = extract_function_disasm(dis_text, func)
    func_binary_memsets[func] = len(re.findall(r"bl\s+[0-9a-f]+\s+<memset", block))

# Identify optimised-away memsets
optimised_away: dict[str, dict] = {}
for func in security_funcs:
    src_count = func_source_memsets.get(func, 0)
    bin_count = func_binary_memsets.get(func, 0)
    if src_count > bin_count:
        optimised_away[func] = {
            "source_calls": src_count,
            "binary_calls": bin_count,
            "eliminated": src_count - bin_count,
        }

# Check for memcmp in verify_pin disassembly
verify_dis = extract_function_disasm(dis_text, "verify_pin")
has_memcmp = "memcmp" in verify_dis

# Check Makefile for stack protector
makefile = read(os.path.join(SRC_DIR, "Makefile"))
has_stack_protector = "-fstack-protector" in makefile

# ── Step 2: write audit report ───────────────────────────────────────

findings = []

for func, info in optimised_away.items():
    findings.append({
        "id": f"VULN-MEMSET-{func.upper()}",
        "type": "compiler-optimization",
        "severity": "high",
        "function": func,
        "description": (
            f"The source code contains {info['source_calls']} memset() call(s) "
            f"intended to scrub sensitive data from the stack, but "
            f"{info['eliminated']} of them are eliminated as dead stores "
            f"by the compiler at -O2. The secret material (keys, HMAC "
            f"buffers) remains on the stack after {func}() returns."
        ),
        "recommendation": (
            "Replace memset with a volatile-based secure_wipe() function "
            "or insert an asm volatile memory clobber barrier after the "
            "memset to prevent dead-store elimination."
        ),
    })

if has_memcmp:
    findings.append({
        "id": "VULN-TIMING-VERIFY-PIN",
        "type": "timing-side-channel",
        "severity": "high",
        "function": "verify_pin",
        "description": (
            "verify_pin() uses memcmp() to compare the computed PIN hash "
            "against the stored hash. memcmp() performs a byte-by-byte "
            "comparison and returns as soon as a mismatch is found, "
            "creating a timing oracle that leaks which prefix bytes are "
            "correct. An attacker with physical access can brute-force "
            "the PIN hash one byte at a time."
        ),
        "recommendation": (
            "Replace memcmp() with a constant-time comparison that XOR-"
            "accumulates all byte differences and only checks the result "
            "after the full buffer has been compared."
        ),
    })

if not has_stack_protector:
    findings.append({
        "id": "VULN-NO-STACK-CANARY",
        "type": "missing-hardening",
        "severity": "medium",
        "function": "(all)",
        "description": (
            "The Makefile does not enable stack canary protection "
            "(-fstack-protector-strong or -fstack-protector-all). "
            "Buffer overflows in any function can overwrite the return "
            "address without detection."
        ),
        "recommendation": (
            "Add -fstack-protector-strong to CFLAGS and provide a "
            "randomised __stack_chk_guard value and a "
            "__stack_chk_fail handler."
        ),
    })

# Ineffective -z noexecstack on bare-metal
if "-z" in makefile and "noexecstack" in makefile:
    findings.append({
        "id": "VULN-NOEXECSTACK-INEFFECTIVE",
        "type": "missing-hardening",
        "severity": "medium",
        "function": "(linker)",
        "description": (
            "The Makefile passes -Wl,-z,noexecstack which only sets a "
            "flag in the ELF program header. On bare-metal Cortex-M "
            "there is no loader to honour this flag; the SRAM remains "
            "executable. Proper non-executable stack requires "
            "configuring the Memory Protection Unit (MPU) at runtime."
        ),
        "recommendation": (
            "Configure the MPU during firmware initialisation to mark "
            "the stack region as eXecute Never (XN)."
        ),
    })

report = {
    "audit_target": "keyfob firmware (ARM Cortex-M4, TM4C123GXL)",
    "compiler": "arm-none-eabi-gcc -O2",
    "findings": findings,
}

with open(REPORT_PATH, "w") as f:
    json.dump(report, f, indent=2)

print(f"[+] Wrote audit report with {len(findings)} finding(s) to {REPORT_PATH}")

# ── Step 3: generate fixed firmware ──────────────────────────────────

if os.path.exists(FIX_DIR):
    shutil.rmtree(FIX_DIR)
shutil.copytree(SRC_DIR, FIX_DIR)

# --- 3a. Patch secure_keyfob.c ---

fixed_src = read(os.path.join(FIX_DIR, "secure_keyfob.c"))

# Insert secure_wipe and constant_time_eq after the includes
INSERT_AFTER = '#include "crypto.h"'
SECURITY_HELPERS = r'''
/* ---- Security helpers ---- */

/*
 * secure_wipe — zero memory through a volatile pointer so the compiler
 * cannot eliminate the stores as dead writes.
 */
static void secure_wipe(void *buf, size_t len) {
    volatile uint8_t *p = (volatile uint8_t *)buf;
    while (len--) *p++ = 0;
}

/*
 * constant_time_eq — compare two buffers in constant time.
 * Returns 1 if equal, 0 otherwise.  Never short-circuits.
 */
static int constant_time_eq(const uint8_t *a, const uint8_t *b, size_t len) {
    volatile uint8_t acc = 0;
    for (size_t i = 0; i < len; i++)
        acc |= a[i] ^ b[i];
    return acc == 0;
}
'''

fixed_src = fixed_src.replace(INSERT_AFTER, INSERT_AFTER + SECURITY_HELPERS, 1)

# Replace memcmp in verify_pin with constant_time_eq
fixed_src = fixed_src.replace(
    "bool valid = (memcmp(computed_hash, PIN_HASH, 32) == 0);",
    "bool valid = constant_time_eq(computed_hash, PIN_HASH, 32);",
)

# Replace all security-critical memset(..., 0, ...) with secure_wipe(...)
# We target the specific patterns in the four vulnerable functions.
# Each memset(X, 0, sizeof(X)) becomes secure_wipe(X, sizeof(X)).
memset_replacements = [
    # verify_pin
    ("memset(computed_hash, 0, sizeof(computed_hash));",
     "secure_wipe(computed_hash, sizeof(computed_hash));"),
    # process_unlock_command
    ("memset(session_key, 0, sizeof(session_key));",
     "secure_wipe(session_key, sizeof(session_key));"),
    ("memset(&ctx, 0, sizeof(ctx));",
     "secure_wipe(&ctx, sizeof(ctx));"),
    ("memset(mac_buf, 0, sizeof(mac_buf));",
     "secure_wipe(mac_buf, sizeof(mac_buf));"),
    # pair_device
    ("memset(pair_key, 0, sizeof(pair_key));",
     "secure_wipe(pair_key, sizeof(pair_key));"),
    ("memset(auth_resp, 0, sizeof(auth_resp));",
     "secure_wipe(auth_resp, sizeof(auth_resp));"),
    # compute_challenge_response
    ("memset(full_mac, 0, sizeof(full_mac));",
     "secure_wipe(full_mac, sizeof(full_mac));"),
]

for old, new in memset_replacements:
    fixed_src = fixed_src.replace(old, new)

with open(os.path.join(FIX_DIR, "secure_keyfob.c"), "w") as f:
    f.write(fixed_src)

print("[+] Patched secure_keyfob.c (secure_wipe + constant_time_eq)")

# --- 3b. Patch Makefile: add -fstack-protector-strong ---

fixed_makefile = read(os.path.join(FIX_DIR, "Makefile"))
fixed_makefile = fixed_makefile.replace(
    "-O2 -Wall -Wextra -Wno-unused-parameter",
    "-O2 -Wall -Wextra -Wno-unused-parameter -fstack-protector-strong",
)

with open(os.path.join(FIX_DIR, "Makefile"), "w") as f:
    f.write(fixed_makefile)

print("[+] Patched Makefile (added -fstack-protector-strong)")

# Clean build artefacts in fixed dir (copied from original build)
for artefact in ["keyfob.elf", "keyfob.dis", "keyfob.bin",
                 "startup.o", "crypto.o", "secure_keyfob.o"]:
    p = os.path.join(FIX_DIR, artefact)
    if os.path.exists(p):
        os.remove(p)

print("[+] Fixed firmware written to", FIX_DIR)
