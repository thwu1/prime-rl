#!/usr/bin/env python3
"""
Post-process COCO experiment results.

Generates performance profiles and comparison tables from experiment data
logged by the COCO observer system.

Usage:
    python3 /app/experiment/analyze.py <exdata_dir> [exdata_dir2 ...]

Each exdata_dir should contain subdirectories with COCO-format .dat/.tdat files.
"""
import sys
import os
import subprocess


def find_algo_dirs(data_dirs):
    """Find algorithm result subdirectories within data directories."""
    algo_dirs = []
    for d in data_dirs:
        if not os.path.isdir(d):
            print(f"Warning: {d} is not a directory, skipping")
            continue
        for entry in sorted(os.listdir(d)):
            full = os.path.join(d, entry)
            if os.path.isdir(full) and not entry.startswith("."):
                algo_dirs.append(full)
    return algo_dirs


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    data_dirs = sys.argv[1:]
    algo_dirs = find_algo_dirs(data_dirs)

    if not algo_dirs:
        print("No algorithm data directories found.")
        print("Run an experiment first:")
        print("  python3 /app/experiment/run_benchmark.py /path/to/optimizer.py")
        sys.exit(1)

    print(f"Found {len(algo_dirs)} algorithm dataset(s):")
    for ad in algo_dirs:
        print(f"  {ad}")

    # Try cocopp for post-processing
    try:
        cmd = ["python3", "-m", "cocopp", "--no-svg"] + algo_dirs
        print(f"\nRunning: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0 and result.stderr:
            print(f"cocopp stderr:\n{result.stderr}")
        elif result.returncode == 0:
            print("Post-processing complete.")
            ppdata = os.path.join(os.getcwd(), "ppdata")
            if os.path.isdir(ppdata):
                print(f"Results in: {ppdata}/")
    except FileNotFoundError:
        print("cocopp not available.")
        print("Install: pip3 install cocopp")
    except subprocess.TimeoutExpired:
        print("cocopp timed out after 120s")

    # Also print raw data file structure for manual inspection
    print("\nRaw data structure:")
    for ad in algo_dirs:
        print(f"\n  {ad}/")
        for root, dirs, files in os.walk(ad):
            level = root.replace(ad, "").count(os.sep)
            indent = "    " + "  " * level
            print(f"{indent}{os.path.basename(root)}/")
            sub_indent = "    " + "  " * (level + 1)
            for f in sorted(files)[:10]:
                print(f"{sub_indent}{f}")
            if len(files) > 10:
                print(f"{sub_indent}... ({len(files)} files total)")


if __name__ == "__main__":
    main()
