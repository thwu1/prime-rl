#!/usr/bin/env python3

"""
Competitive programming judge with DMOJ-format configs, testlib checkers,
prlimit resource enforcement, and /usr/bin/time -v measurement.
"""

import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

PROBLEMS_DIR = Path("/app/problems")
SUBMISSIONS_DIR = Path("/app/submissions")
OUTPUT_FILE = Path("/app/results.jsonl")
TESTLIB_PATH = "/app/testlib.h"

VERDICT_PRIORITY = {"CE": 4, "TLE": 3, "RE": 2, "WA": 1, "AC": 0}


def compile_cpp(source_path, output_path=None):
    """Compile a C++ source file. Returns (binary_path | None, success)."""
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".bin")
        os.close(fd)
    try:
        result = subprocess.run(
            ["g++", "-O2", "-std=c++17", "-o", output_path, str(source_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            if os.path.exists(output_path):
                os.unlink(output_path)
            return None, False
        return output_path, True
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.unlink(output_path)
        return None, False


def compile_testlib_checker(checker_source, problem_dir):
    """Compile a testlib.h-based C++ checker. Returns binary path or None."""
    source_path = problem_dir / checker_source
    fd, output_path = tempfile.mkstemp(suffix=".checker")
    os.close(fd)
    try:
        result = subprocess.run(
            ["g++", "-O2", "-std=c++17", "-I", "/app",
             "-o", output_path, str(source_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"Checker compilation failed: {result.stderr}")
            if os.path.exists(output_path):
                os.unlink(output_path)
            return None
        return output_path
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path):
            os.unlink(output_path)
        return None


def parse_time_output(time_file):
    """Parse /usr/bin/time -v output for wall time and peak memory."""
    time_ms = -1
    memory_kb = -1
    try:
        with open(time_file, "r") as f:
            content = f.read()

        # Wall clock: "Elapsed (wall clock) time (h:mm:ss or m:ss): 0:00.12"
        wall_match = re.search(
            r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*"
            r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", content
        )
        if wall_match:
            hours = int(wall_match.group(1) or 0)
            minutes = int(wall_match.group(2))
            seconds = float(wall_match.group(3))
            time_ms = int((hours * 3600 + minutes * 60 + seconds) * 1000)

        # Peak memory: "Maximum resident set size (kbytes): 1234"
        mem_match = re.search(
            r"Maximum resident set size \(kbytes\):\s*(\d+)", content
        )
        if mem_match:
            memory_kb = int(mem_match.group(1))
    except Exception:
        pass
    return time_ms, memory_kb


def run_testcase(command, input_file, time_limit, memory_limit_kb):
    """
    Run a submission on a single test case with prlimit resource limits
    and /usr/bin/time -v measurement.

    Returns (verdict, time_ms, memory_kb, stdout_data).
    """
    cpu_limit = math.ceil(time_limit)
    mem_bytes = memory_limit_kb * 1024
    wall_timeout = time_limit * 3 + 5

    fd_out, stdout_path = tempfile.mkstemp(suffix=".stdout")
    os.close(fd_out)
    fd_time, time_path = tempfile.mkstemp(suffix=".time")
    os.close(fd_time)

    try:
        full_cmd = [
            "/usr/bin/time", "-v", "-o", time_path, "--",
            "prlimit", f"--cpu={cpu_limit}", f"--as={mem_bytes}", "--",
        ] + command

        with open(str(input_file), "r") as fin, \
             open(stdout_path, "w") as fout:
            try:
                proc = subprocess.run(
                    full_cmd,
                    stdin=fin, stdout=fout, stderr=subprocess.DEVNULL,
                    timeout=wall_timeout,
                )
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                return "TLE", -1, -1, ""

        time_ms, memory_kb = parse_time_output(time_path)

        # SIGXCPU=24 -> exit 128+24=152, SIGKILL=9 -> exit 137
        if exit_code in (137, 152):
            return "TLE", -1, -1, ""

        # Wall time exceeded limit
        if time_ms > 0 and time_ms > time_limit * 1000:
            return "TLE", -1, -1, ""

        if exit_code != 0:
            return "RE", max(time_ms, 0), max(memory_kb, 0), ""

        with open(stdout_path, "r") as f:
            stdout_data = f.read()

        return "OK", max(time_ms, 0), max(memory_kb, 0), stdout_data

    finally:
        for p in [stdout_path, time_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


def check_standard(expected_path, actual_output):
    """Standard checker: whitespace-normalized line-by-line comparison."""
    with open(str(expected_path), "r") as f:
        expected = f.read()

    def normalize(text):
        lines = text.rstrip("\n").split("\n")
        lines = [line.rstrip() for line in lines]
        while lines and lines[-1] == "":
            lines.pop()
        return lines

    return normalize(expected) == normalize(actual_output)


def check_bridged(checker_bin, input_file, expected_file, actual_output):
    """Bridged (testlib) checker: write contestant output to file, invoke checker."""
    fd, actual_path = tempfile.mkstemp(suffix=".contestant")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(actual_output)
        result = subprocess.run(
            [checker_bin, str(input_file), actual_path, str(expected_file)],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False
    finally:
        try:
            os.unlink(actual_path)
        except OSError:
            pass


def parse_init_yml(problem_dir):
    """Parse DMOJ-style init.yml from a problem directory."""
    config_path = problem_dir / "init.yml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config


def judge_submission(submission_path, problem_dir):
    """Judge a single submission against a problem."""
    problem_id = problem_dir.name
    submission_id = f"{problem_id}/{submission_path.name}"
    is_cpp = submission_path.suffix == ".cpp"

    config = parse_init_yml(problem_dir)
    time_limit = config.get("time_limit", 5.0)
    memory_limit = config.get("memory_limit", 262144)
    checker_type = config.get("checker", "standard")

    # --- Compilation ---
    binary_path = None
    if is_cpp:
        binary_path, compiled = compile_cpp(submission_path)
        if not compiled:
            return {
                "submission_id": submission_id,
                "problem_id": problem_id,
                "verdict": "CE",
                "score": 0.0,
                "testcase_results": [],
            }

    # --- Build run command ---
    if is_cpp:
        cmd = [binary_path]
    else:
        cmd = ["python3", str(submission_path)]

    # --- Compile testlib checker if bridged ---
    checker_bin = None
    if checker_type == "bridged":
        custom_judge = config.get("custom_judge", "checker.cpp")
        checker_bin = compile_testlib_checker(custom_judge, problem_dir)

    # --- Parse test cases ---
    test_cases_config = config.get("test_cases", [])

    is_batched = any(
        isinstance(tc, dict) and "batched" in tc
        for tc in test_cases_config
    )

    test_cases = []
    if is_batched:
        subtask_id = 0
        for group in test_cases_config:
            subtask_id += 1
            points = group.get("points", 0)
            for tc in group.get("batched", []):
                test_cases.append({
                    "in": problem_dir / tc["in"],
                    "out": problem_dir / tc["out"],
                    "subtask": subtask_id,
                    "points": points,
                })
    else:
        for tc in test_cases_config:
            test_cases.append({
                "in": problem_dir / tc["in"],
                "out": problem_dir / tc["out"],
                "subtask": None,
                "points": tc.get("points", 0),
            })

    # --- Run test cases ---
    testcase_results = []
    for idx, tc in enumerate(test_cases, 1):
        verdict, time_ms, memory_kb, stdout_data = run_testcase(
            cmd, tc["in"], time_limit, memory_limit
        )

        if verdict == "OK":
            if checker_type == "bridged" and checker_bin:
                if check_bridged(checker_bin, tc["in"], tc["out"], stdout_data):
                    verdict = "AC"
                else:
                    verdict = "WA"
            else:
                if check_standard(tc["out"], stdout_data):
                    verdict = "AC"
                else:
                    verdict = "WA"

        testcase_results.append({
            "testcase": idx,
            "verdict": verdict,
            "time_ms": time_ms,
            "memory_kb": memory_kb,
        })

    # --- Cleanup ---
    if binary_path and os.path.exists(binary_path):
        os.unlink(binary_path)
    if checker_bin and os.path.exists(checker_bin):
        os.unlink(checker_bin)

    # --- Compute score ---
    if is_batched:
        subtask_results = {}
        subtask_points = {}
        for tc_info, tc_result in zip(test_cases, testcase_results):
            st = tc_info["subtask"]
            if st not in subtask_results:
                subtask_results[st] = True
                subtask_points[st] = tc_info["points"]
            if tc_result["verdict"] != "AC":
                subtask_results[st] = False

        total_points = sum(subtask_points.values())
        earned = sum(
            subtask_points[st] for st, passed in subtask_results.items()
            if passed
        )
        score = earned / total_points if total_points > 0 else 0.0
    else:
        all_ac = all(r["verdict"] == "AC" for r in testcase_results)
        score = 1.0 if all_ac else 0.0

    # --- Overall verdict ---
    if not testcase_results:
        overall_verdict = "AC"
    else:
        overall_verdict = max(
            testcase_results,
            key=lambda r: VERDICT_PRIORITY.get(r["verdict"], 0),
        )["verdict"]

    return {
        "submission_id": submission_id,
        "problem_id": problem_id,
        "verdict": overall_verdict,
        "score": score,
        "testcase_results": testcase_results,
    }


def main():
    results = []

    for problem_dir in sorted(PROBLEMS_DIR.iterdir()):
        if not problem_dir.is_dir():
            continue
        if not (problem_dir / "init.yml").exists():
            continue

        problem_id = problem_dir.name
        subs_dir = SUBMISSIONS_DIR / problem_id
        if not subs_dir.exists():
            continue

        for sub_file in sorted(subs_dir.iterdir()):
            if sub_file.suffix in (".cpp", ".py"):
                print(f"Judging {problem_id}/{sub_file.name}...")
                result = judge_submission(sub_file, problem_dir)
                results.append(result)

    results.sort(key=lambda r: r["submission_id"])

    with open(OUTPUT_FILE, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"Judged {len(results)} submissions. Results in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
