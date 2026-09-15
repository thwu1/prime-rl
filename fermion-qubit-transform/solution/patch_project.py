#!/usr/bin/env python3
"""
Patch the broken project: fix Makefile, config, and source code.
Copies corrected implementations into place so make all succeeds.
"""

import shutil
import re

# 1. Fix config.yaml: change chemist to physicist (data is in physicist notation)
config_path = "/app/config.yaml"
with open(config_path) as f:
    cfg = f.read()
cfg = cfg.replace("integral_convention: chemist", "integral_convention: physicist")
with open(config_path, "w") as f:
    f.write(cfg)
print("Fixed config.yaml: integral_convention -> physicist")

# 2. Fix Makefile
with open("/app/Makefile") as f:
    mf = f.read()

# Fix variable reference: DB_PATH -> DATABASE
mf = mf.replace("$(DB_PATH)", "$(DATABASE)")

# Fix RESULTS path: /app/output/results.json -> /app/results.json
mf = mf.replace("/app/output/results.json", "/app/results.json")

# Fix all target to include audit
mf = re.sub(r"^(all:\s*)run summary", r"\1audit run summary", mf, flags=re.MULTILINE)

# Fix script name: run_pipeline.py -> pipeline.py
mf = mf.replace("run_pipeline.py", "pipeline.py")

# Fix jq field names
mf = mf.replace(".value.energy", ".value.ground_state_energy")
mf = mf.replace(".value.spectral", ".value.spectral_match")

with open("/app/Makefile", "w") as f:
    f.write(mf)
print("Fixed Makefile: variable refs, paths, targets, jq fields")

# 3. Copy fixed source files
shutil.copy("/solution/fixed_qubit_encoding.py", "/app/src/qubit_encoding.py")
shutil.copy("/solution/fixed_analysis.py", "/app/src/analysis.py")
print("Copied fixed qubit_encoding.py and analysis.py")

print("Project patched successfully.")
