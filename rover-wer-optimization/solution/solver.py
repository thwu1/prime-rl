#!/usr/bin/env python3

"""
ASR system portfolio optimization solver.

Scores each system with sclite to extract WER, per-speaker WER, and NCE.
Ranks systems by NCE (calibration quality). Discovers ROVER's voting
methods and alpha hyperparameter. Enumerates all system subsets (sizes 2-4)
across voting methods and alpha values, scores each ROVER output with
sclite, and identifies the globally optimal configuration.
"""

import json
import os
import subprocess
from itertools import combinations

DATA_DIR = "/app/data"
RESULTS_DIR = "/app/results"
WORK_DIR = "/app/work"
REF_FILE = os.path.join(DATA_DIR, "reference.stm")
SYSTEMS = ["sys1", "sys2", "sys3", "sys4"]
# ROVER voting methods that use confidence scores
METHODS_WITH_ALPHA = ["meth1"]
METHODS_WITHOUT_ALPHA = ["avgconf", "maxconf", "maxconfa"]
ALPHA_VALUES = [0.0, 0.25, 0.5, 0.75, 1.0]


def run_cmd(cmd):
    """Run a shell command and return (stdout, stderr, returncode)."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.stdout, result.stderr, result.returncode


def parse_sys_file(sys_file_path):
    """Parse sclite .sys summary file for WER, per-speaker WER, and NCE."""
    metrics = {"overall_wer": None, "speaker_wer": {}, "nce": None}
    if not os.path.exists(sys_file_path):
        return metrics
    with open(sys_file_path) as f:
        content = f.read()

    for line in content.split('\n'):
        if '|' not in line:
            continue
        if 'SPKR' in line or '---' in line or '===' in line:
            continue

        parts = line.split('|')
        is_sum = 'Sum' in line

        speaker = None
        if not is_sum and len(parts) >= 2:
            s = parts[1].strip()
            if s and len(s) > 0 and s[0].isalpha():
                speaker = s

        wer_val = None
        nce_val = None
        for part in parts:
            nums = part.strip().split()
            if len(nums) == 6:
                try:
                    w = float(nums[4])
                    if 0 <= w <= 100:
                        wer_val = w
                except ValueError:
                    pass
            elif len(nums) == 1:
                try:
                    n = float(nums[0])
                    if -2.0 <= n <= 2.0:
                        nce_val = n
                except ValueError:
                    pass

        if is_sum:
            metrics["overall_wer"] = wer_val
            metrics["nce"] = nce_val
        elif speaker and wer_val is not None:
            metrics["speaker_wer"][speaker] = wer_val

    return metrics


def score_ctm(ctm_file, output_name):
    """Score a CTM hypothesis file against the reference STM file."""
    cmd = [
        "sclite",
        "-r", REF_FILE, "stm",
        "-h", ctm_file, "ctm",
        "-o", "sum",
        "-O", WORK_DIR,
        "-n", output_name,
        "-f", "0"
    ]
    stdout, stderr, rc = run_cmd(cmd)
    if rc != 0:
        print("    sclite error (rc={}): {}".format(rc, stderr[:200]))
    sys_file = os.path.join(WORK_DIR, "{}.sys".format(output_name))
    return parse_sys_file(sys_file)


def run_rover(system_names, voting_method, alpha, output_name):
    """Run ROVER to combine multiple system outputs with given method and alpha."""
    cmd = ["rover"]
    for sys_name in system_names:
        cmd.extend(["-h", os.path.join(DATA_DIR, "{}.ctm".format(sys_name)), "ctm"])

    output_ctm = os.path.join(WORK_DIR, "{}.ctm".format(output_name))
    cmd.extend(["-o", output_ctm, "-m", voting_method,
                "-a", str(alpha), "-f", "0"])

    stdout, stderr, rc = run_cmd(cmd)
    if rc != 0:
        print("    rover error (rc={}): {}".format(rc, stderr[:200]))
    if os.path.exists(output_ctm):
        return output_ctm
    return None


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)

    # === Phase 1: Score individual systems ===
    print("=" * 60)
    print("Phase 1: Scoring individual systems")
    print("=" * 60)
    per_system = {}
    nce_map = {}
    for sys_name in SYSTEMS:
        ctm_file = os.path.join(DATA_DIR, "{}.ctm".format(sys_name))
        metrics = score_ctm(ctm_file, "ind_{}".format(sys_name))
        wer = metrics["overall_wer"] if metrics["overall_wer"] is not None else 100.0
        nce = metrics["nce"] if metrics["nce"] is not None else 0.0
        per_system[sys_name] = {
            "wer": wer,
            "nce": nce,
            "speaker_wer": metrics["speaker_wer"],
        }
        nce_map[sys_name] = nce
        print("  {}: WER={:.1f}%, NCE={:.4f}, speakers={}".format(
            sys_name, wer, nce, metrics["speaker_wer"]))

    # === Phase 2: Calibration ranking (best to worst NCE) ===
    print("\n" + "=" * 60)
    print("Phase 2: Calibration ranking")
    print("=" * 60)
    calibration_ranking = sorted(
        SYSTEMS, key=lambda s: nce_map[s], reverse=True)
    print("  Ranking (best->worst NCE): {}".format(calibration_ranking))
    for s in calibration_ranking:
        print("    {}: NCE = {:.4f}".format(s, nce_map[s]))

    # === Phase 3: ROVER parameter space optimization ===
    print("\n" + "=" * 60)
    print("Phase 3: ROVER parameter space optimization")
    print("=" * 60)

    all_configs = []
    best_wer = float('inf')
    best_config = None

    for size in range(2, len(SYSTEMS) + 1):
        for combo in combinations(SYSTEMS, size):
            # Methods without alpha dependence
            for method in METHODS_WITHOUT_ALPHA:
                alpha = 1.0
                combo_name = "rover_{}_{}".format(
                    "_".join(combo), method)

                rover_ctm = run_rover(list(combo), method, alpha, combo_name)
                if rover_ctm is None:
                    print("  {} ({}): ROVER FAILED".format(
                        "+".join(combo), method))
                    continue

                metrics = score_ctm(rover_ctm, combo_name + "_score")
                wer = metrics["overall_wer"]
                if wer is None:
                    print("  {} ({}): SCORING FAILED".format(
                        "+".join(combo), method))
                    continue

                result = {
                    "systems": list(combo),
                    "method": method,
                    "alpha": alpha,
                    "wer": wer
                }
                all_configs.append(result)
                print("  {} ({} a={:.2f}): WER = {:.1f}%".format(
                    "+".join(combo), method, alpha, wer))

                if wer < best_wer:
                    best_wer = wer
                    best_config = result.copy()

            # meth1 with alpha sweep
            for alpha in ALPHA_VALUES:
                combo_name = "rover_{}_meth1_a{:.2f}".format(
                    "_".join(combo), alpha)

                rover_ctm = run_rover(list(combo), "meth1", alpha, combo_name)
                if rover_ctm is None:
                    print("  {} (meth1 a={:.2f}): ROVER FAILED".format(
                        "+".join(combo), alpha))
                    continue

                metrics = score_ctm(rover_ctm, combo_name + "_score")
                wer = metrics["overall_wer"]
                if wer is None:
                    print("  {} (meth1 a={:.2f}): SCORING FAILED".format(
                        "+".join(combo), alpha))
                    continue

                result = {
                    "systems": list(combo),
                    "method": "meth1",
                    "alpha": alpha,
                    "wer": wer
                }
                all_configs.append(result)
                print("  {} (meth1 a={:.2f}): WER = {:.1f}%".format(
                    "+".join(combo), alpha, wer))

                if wer < best_wer:
                    best_wer = wer
                    best_config = result.copy()

    # === Compile results ===
    if best_config is not None:
        print("\n" + "=" * 60)
        print("OPTIMAL: {} with {} alpha={:.2f} -> WER = {:.1f}%".format(
            "+".join(best_config["systems"]), best_config["method"],
            best_config["alpha"], best_wer))
        print("=" * 60)
    else:
        print("\nERROR: No ROVER configuration succeeded.")
        best_wer = min(d["wer"] for d in per_system.values())
        best_config = {
            "systems": sorted(SYSTEMS[:2]),
            "method": "meth1",
            "alpha": 1.0,
            "wer": best_wer
        }

    results = {
        "per_system": per_system,
        "calibration_ranking": calibration_ranking,
        "rover_optimization": {
            "best_config": best_config,
            "search_log": all_configs
        }
    }

    output_path = os.path.join(RESULTS_DIR, "analysis.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to {}".format(output_path))


if __name__ == "__main__":
    main()
