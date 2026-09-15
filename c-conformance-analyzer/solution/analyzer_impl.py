#!/usr/bin/env python3
"""C Compiler Conformance Differential Analyzer.

Classifies C probe files under different standard modes (c11, c17, c2x)
as standard/extension/rejected using GCC's pedantic conformance behavior.
"""

import json
import os
import subprocess

PROBES_DIR = "/app/probes"
STANDARDS = ["c11", "c17", "c2x"]
REPORT_PATH = "/app/conformance_report.json"


def get_gcc_version():
    result = subprocess.run(["gcc", "--version"], capture_output=True, text=True)
    return result.stdout.strip().split("\n")[0]


def compile_check(probe_path, std, pedantic_errors=False):
    cmd = ["gcc", "-std={}".format(std), "-fsyntax-only"]
    if pedantic_errors:
        cmd.append("-pedantic-errors")
    cmd.append(probe_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0


def classify(probe_path, std):
    if compile_check(probe_path, std, pedantic_errors=True):
        return "standard"
    if compile_check(probe_path, std, pedantic_errors=False):
        return "extension"
    return "rejected"


def run_probe(probe_path, std):
    binary = "/tmp/_analyzer_probe"
    compile_cmd = ["gcc", "-std={}".format(std), "-o", binary, probe_path]
    result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None, None, None
    try:
        run_result = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
        return True, run_result.returncode, run_result.stdout
    except subprocess.TimeoutExpired:
        return False, None, None
    finally:
        if os.path.exists(binary):
            os.remove(binary)


def extract_description(probe_path):
    with open(probe_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("/* Probe:"):
                desc = line[len("/* Probe:") :].rstrip("*/").strip()
                return desc
    return "unknown feature"


def main():
    gcc_version = get_gcc_version()
    probe_files = sorted(f for f in os.listdir(PROBES_DIR) if f.endswith(".c"))

    report = {
        "compiler": {"name": "gcc", "version": gcc_version},
        "probes": {},
        "summary": {"total_probes": len(probe_files)},
    }

    for std in STANDARDS:
        for cat in ["standard", "extension", "rejected"]:
            report["summary"]["{}_{}".format(std, cat)] = 0

    for pf in probe_files:
        name = pf[:-2]
        probe_path = os.path.join(PROBES_DIR, pf)
        description = extract_description(probe_path)

        probe_data = {"description": description, "results": {}}

        for std in STANDARDS:
            cls = classify(probe_path, std)

            runs, exit_code, output = None, None, None
            if cls != "rejected":
                runs, exit_code, output = run_probe(probe_path, std)

            probe_data["results"][std] = {
                "classification": cls,
                "runs": runs,
                "exit_code": exit_code,
                "output": output,
            }
            report["summary"]["{}_{}".format(std, cls)] += 1

        report["probes"][name] = probe_data

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print("Conformance report written to {}".format(REPORT_PATH))
    print("Compiler: {}".format(gcc_version))
    print("Probes analyzed: {}".format(len(probe_files)))
    for std in STANDARDS:
        s = report["summary"]
        print(
            "  {}: {} standard, {} extension, {} rejected".format(
                std,
                s["{}_standard".format(std)],
                s["{}_extension".format(std)],
                s["{}_rejected".format(std)],
            )
        )


if __name__ == "__main__":
    main()
