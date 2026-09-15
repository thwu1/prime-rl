#!/usr/bin/env python3
"""Deploy solution files, update vschema, run reshard, verify with vdiff."""

import json
import shutil
import subprocess
import sys

# ── 1. Deploy implementations ──────────────────────────────────────────────

shutil.copy("/solution/reshard_impl.py", "/app/reshard.py")
print("Deployed /app/reshard.py")

shutil.copy("/solution/vdiff_impl.py", "/app/vdiff.py")
print("Deployed /app/vdiff.py")

shutil.copy("/solution/forget_user_fixed.py", "/app/jobs/forget_user.py")
print("Deployed fixed /app/jobs/forget_user.py")

# ── 2. Update vschema.json ──────────────────────────────────────────────────

with open("/app/vschema.json") as f:
    vschema = json.load(f)

vschema["shards"] = ["-40", "40-80", "80-"]

with open("/app/vschema.json", "w") as f:
    json.dump(vschema, f, indent=2)
print("Updated vschema.json -> shards: ['-40', '40-80', '80-']")

# ── 3. Execute resharding ──────────────────────────────────────────────────

print("\n=== Resharding -80 -> -40, 40-80 ===")
r = subprocess.run(
    [sys.executable, "/app/reshard.py",
     "--source-shard=-80", "--target-shards=-40,40-80"],
    capture_output=True, text=True,
)
print(r.stdout)
if r.returncode != 0:
    print(f"RESHARD FAILED:\n{r.stderr}")
    sys.exit(1)

# ── 4. Verify with vdiff ───────────────────────────────────────────────────

print("\n=== VDiff verification ===")
r = subprocess.run(
    [sys.executable, "/app/vdiff.py",
     "--source=-80", "--targets=-40,40-80"],
    capture_output=True, text=True,
)
print(r.stdout)
if r.returncode != 0:
    print(f"VDIFF FAILED:\n{r.stderr}")
    sys.exit(1)

print("\n=== Solution complete ===")
