#!/usr/bin/env python3

"""Classify each example function under Stacked Borrows and Tree Borrows by running Miri."""

import json
import os
import shutil
import subprocess

os.environ["PATH"] = "/usr/local/cargo/bin:/root/.cargo/bin:" + os.environ.get("PATH", "")
os.environ.setdefault("CARGO_HOME", "/usr/local/cargo")
os.environ.setdefault("RUSTUP_HOME", "/usr/local/rustup")

CARGO = shutil.which("cargo")
if CARGO is None:
    raise RuntimeError("cargo not found in PATH. Ensure Rust is installed.")

os.chdir("/app")

EXAMPLES = [
    "retag_two_phase",
    "write_then_ref",
    "local_addr_of",
    "double_unique",
    "raw_after_reborrow",
    "sound_mutation",
]

classification = {}

for name in EXAMPLES:
    # Test under Stacked Borrows (default)
    env_sb = os.environ.copy()
    env_sb["MIRIFLAGS"] = ""
    sb_result = subprocess.run(
        [CARGO, "miri", "run", "--example", name],
        capture_output=True,
        text=True,
        timeout=120,
        env=env_sb,
    )
    sb_ok = sb_result.returncode == 0

    # Test under Tree Borrows
    env_tb = os.environ.copy()
    env_tb["MIRIFLAGS"] = "-Zmiri-tree-borrows"
    tb_result = subprocess.run(
        [CARGO, "miri", "run", "--example", name],
        capture_output=True,
        text=True,
        timeout=120,
        env=env_tb,
    )
    tb_ok = tb_result.returncode == 0

    classification[name] = {
        "stacked_borrows": "ok" if sb_ok else "ub",
        "tree_borrows": "ok" if tb_ok else "ub",
    }
    print(f"{name}: SB={'ok' if sb_ok else 'UB'}, TB={'ok' if tb_ok else 'UB'}")

with open("/app/classification.json", "w") as f:
    json.dump(classification, f, indent=2)

print("\nClassification written to /app/classification.json")
print(json.dumps(classification, indent=2))
