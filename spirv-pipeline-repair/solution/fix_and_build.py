#!/usr/bin/env python3
"""
Fix SPIR-V validation errors, design and evaluate optimization strategies,
select optimal strategy per platform profile, and produce cross-compiled outputs.
"""
import json
import os
import re
import shutil
import subprocess
import sys

SHADERS = "/app/shaders"
OUTPUT = "/app/output"
PROFILES_PATH = "/app/platform_profiles.json"


def run(cmd, check=True):
    print(f"  >> {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"STDOUT: {r.stdout}")
        print(f"STDERR: {r.stderr}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return r


def glslang_cmd():
    for name in ("glslang", "glslangValidator"):
        if shutil.which(name):
            return name
    raise FileNotFoundError("glslang not found")


def measure_metrics(spv_path):
    """Measure binary_size, instruction_count, and id_count for a SPIR-V binary."""
    binary_size = os.path.getsize(spv_path)
    r = run(["spirv-dis", spv_path])
    lines = r.stdout.splitlines()
    instruction_count = sum(
        1 for line in lines
        if line.strip() and not line.strip().startswith(';')
    )
    id_count = len(set(re.findall(r'%\w+', r.stdout)))
    return {
        "binary_size": binary_size,
        "instruction_count": instruction_count,
        "id_count": id_count
    }


# ── Step 1: Diagnose original errors ─────────────────────────────────────────
print("=== Step 1: Diagnosing original SPIR-V assembly ===")
diag_asm = run(["spirv-as", f"{SHADERS}/particle_update.spvasm",
                "-o", "/tmp/diag.spv"], check=False)
if diag_asm.returncode == 0:
    diag_val = run(["spirv-val", "--target-env", "vulkan1.0",
                    "/tmp/diag.spv"], check=False)
    print("Validation errors found:\n", diag_val.stderr)
else:
    print("Assembly errors found:\n", diag_asm.stderr)


# ── Step 2: Fix SPIR-V assembly ──────────────────────────────────────────────
print("\n=== Step 2: Fixing SPIR-V assembly ===")

with open(f"{SHADERS}/particle_update.spvasm") as f:
    asm_lines = f.readlines()

fixed = []
inserted_exec_mode = False

for line in asm_lines:
    stripped = line.strip()

    # Fix 1: Physical32 -> Logical (Vulkan requires Logical addressing)
    if "OpMemoryModel" in stripped and "Physical32" in stripped:
        line = line.replace("Physical32", "Logical")
        print("  FIX 1: Physical32 -> Logical")

    # Fix 3: Add BufferBlock decoration on Particles SSBO struct
    if "OpMemberDecorate %Particles 0 Offset 0" in stripped:
        fixed.append("               OpDecorate %Particles BufferBlock\n")
        print("  FIX 3: Added BufferBlock on Particles")

    fixed.append(line)

    # Fix 2: Add LocalSize execution mode after OpEntryPoint
    if stripped.startswith("OpEntryPoint GLCompute") and not inserted_exec_mode:
        fixed.append("               OpExecutionMode %main LocalSize 256 1 1\n")
        inserted_exec_mode = True
        print("  FIX 2: Added LocalSize 256 1 1")

    # Fix 4: Add ArrayStride on runtime array after particles Binding
    if "OpDecorate %particles Binding 0" in stripped:
        fixed.append("               OpDecorate %_runtimearr_v4float ArrayStride 16\n")
        print("  FIX 4: Added ArrayStride 16")

    # Fix 5: Add Binding for params uniform
    if "OpDecorate %params DescriptorSet 0" in stripped:
        fixed.append("               OpDecorate %params Binding 1\n")
        print("  FIX 5: Added Binding 1 on params")

os.makedirs(OUTPUT, exist_ok=True)
fixed_path = f"{OUTPUT}/particle_update_fixed.spvasm"
with open(fixed_path, "w") as f:
    f.writelines(fixed)
print(f"  Written {fixed_path}")


# ── Step 3: Assemble and validate ────────────────────────────────────────────
print("\n=== Step 3: Assemble and validate ===")
spv_path = f"{OUTPUT}/particle_update.spv"
run(["spirv-as", fixed_path, "-o", spv_path, "--target-env", "vulkan1.0"])
run(["spirv-val", "--target-env", "vulkan1.0", spv_path])
print("  Validation PASSED")


# ── Step 4: Design and evaluate optimization strategies ──────────────────────
print("\n=== Step 4: Design and evaluate optimization strategies ===")

# Five strategies with different trade-offs:
# - baseline: minimal change (compact IDs only)
# - strip_debug: remove debug info for smaller binary
# - dce_only: aggressive dead code elimination
# - strip_and_dce: combine stripping + DCE for maximum reduction without
#   altering live code semantics
# - perf_full: full performance optimization recipe (-O) which includes
#   DCE, inlining, simplification, constant folding, and more
STRATEGIES = [
    {"name": "baseline",      "passes": ["--compact-ids"]},
    {"name": "strip_debug",   "passes": ["--strip-debug", "--compact-ids"]},
    {"name": "dce_only",      "passes": ["--eliminate-dead-code-aggressive",
                                          "--compact-ids"]},
    {"name": "strip_and_dce", "passes": ["--strip-debug",
                                          "--eliminate-dead-code-aggressive",
                                          "--compact-ids"]},
    {"name": "perf_full",     "passes": ["-O"]},
]

strategy_results = []
for strat in STRATEGIES:
    tmp_spv = f"/tmp/opt_{strat['name']}.spv"
    cmd = ["spirv-opt"] + strat["passes"] + ["-o", tmp_spv, spv_path]
    r = run(cmd, check=False)
    if r.returncode != 0:
        print(f"  WARNING: Strategy '{strat['name']}' failed, skipping")
        continue
    val = run(["spirv-val", "--target-env", "vulkan1.0", tmp_spv], check=False)
    if val.returncode != 0:
        print(f"  WARNING: Strategy '{strat['name']}' produced invalid SPIR-V")
        continue
    metrics = measure_metrics(tmp_spv)
    strategy_results.append({
        "name": strat["name"],
        "passes": strat["passes"],
        "metrics": metrics
    })
    print(f"  {strat['name']:20s} size={metrics['binary_size']:5d}  "
          f"instr={metrics['instruction_count']:3d}  ids={metrics['id_count']:3d}")

assert len(strategy_results) >= 4, \
    f"Need at least 4 working strategies, got {len(strategy_results)}"


# ── Step 5: Score strategies per platform ─────────────────────────────────────
print("\n=== Step 5: Compute platform scores ===")

with open(PROFILES_PATH) as f:
    profiles_data = json.load(f)

metric_names = ["binary_size", "instruction_count", "id_count"]
mins = {m: min(s["metrics"][m] for s in strategy_results) for m in metric_names}
maxs = {m: max(s["metrics"][m] for s in strategy_results) for m in metric_names}

platform_recs = {}
for pname, profile in profiles_data["profiles"].items():
    weights = profile["weights"]
    scores = {}
    for s in strategy_results:
        score = 0.0
        for m in metric_names:
            rng = maxs[m] - mins[m]
            norm = 0.0 if rng == 0 else (s["metrics"][m] - mins[m]) / rng
            score += weights[m] * norm
        scores[s["name"]] = round(score, 6)

    best = min(scores, key=scores.get)
    platform_recs[pname] = {
        "recommended_strategy": best,
        "weighted_score": scores[best],
        "all_scores": scores,
        "justification": (
            f"Strategy '{best}' achieves the lowest weighted score "
            f"({scores[best]:.6f}) under {pname} profile weights "
            f"(binary_size={weights['binary_size']}, "
            f"instruction_count={weights['instruction_count']}, "
            f"id_count={weights['id_count']}). This makes it optimal for "
            f"{profile['description'].lower()}."
        )
    }
    print(f"  {pname}: recommended='{best}' score={scores[best]:.6f}")


# ── Step 6: Produce platform-specific outputs ────────────────────────────────
print("\n=== Step 6: Produce platform-specific outputs ===")

glslang = glslang_cmd()

CROSS_COMPILE = {
    "mobile_vulkan":  (["--version", "310", "--es"], ".glsl"),
    "desktop_vulkan": (["--version", "450", "--vulkan-semantics"], ".glsl"),
    "console_metal":  (["--msl"], ".msl"),
}

for pname, rec in platform_recs.items():
    src = f"/tmp/opt_{rec['recommended_strategy']}.spv"
    dst_spv = f"{OUTPUT}/{pname}.spv"
    shutil.copy2(src, dst_spv)
    cc_args, ext = CROSS_COMPILE[pname]
    dst_cc = f"{OUTPUT}/{pname}{ext}"
    run(["spirv-cross"] + cc_args + [dst_spv, "--output", dst_cc])
    print(f"  {pname}: {os.path.basename(dst_spv)} + "
          f"{os.path.basename(dst_cc)}")


# ── Step 7: Compile and cross-compile postprocess shader ─────────────────────
print("\n=== Step 7: Postprocess shader ===")
pp_spv = f"{OUTPUT}/postprocess.spv"
run([glslang, "-V", f"{SHADERS}/postprocess.frag", "-o", pp_spv])
run(["spirv-val", pp_spv])
pp_es = f"{OUTPUT}/postprocess_es.glsl"
run(["spirv-cross", "--version", "310", "--es", pp_spv, "--output", pp_es])
print("  Compiled and cross-compiled to GLSL 310 ES")


# ── Step 8: Write evaluation report ──────────────────────────────────────────
print("\n=== Step 8: Write evaluation report ===")
report = {
    "strategies": strategy_results,
    "platform_recommendations": platform_recs
}
with open(f"{OUTPUT}/evaluation_report.json", "w") as f:
    json.dump(report, f, indent=2)
print("  Written evaluation_report.json")


print("\n=== Pipeline complete ===")
print(f"Output files in {OUTPUT}/:")
for fname in sorted(os.listdir(OUTPUT)):
    sz = os.path.getsize(f"{OUTPUT}/{fname}")
    print(f"  {fname:40s} {sz:>8d} bytes")
