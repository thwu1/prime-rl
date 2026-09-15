#!/usr/bin/env python3
"""
SCTK scoring pipeline: compute all required metrics.
"""
import subprocess
import os
import re
import sys
import itertools
import tempfile

DATA_DIR = "/app/data"
RESULTS_DIR = "/app/results"
SCLITE = "/usr/local/bin/sclite"
ROVER = "/usr/local/bin/rover"

os.makedirs(RESULTS_DIR, exist_ok=True)


def run_cmd(cmd, cwd=None):
    """Run a command and return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return result.stdout, result.stderr, result.returncode


def parse_sum_report(sum_file):
    """Parse sclite sum report to extract overall WER."""
    with open(sum_file, "r") as f:
        content = f.read()
    # Look for Sum/Avg line
    # Format: | Sum/Avg|   N   NWRD | Corr    Sub    Del    Ins    Err  S.Err |
    match = re.search(
        r"Sum/Avg\|.*?\|\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\|",
        content,
    )
    if match:
        corr, sub, dele, ins, err, serr = [float(x) for x in match.groups()]
        return {"corr": corr, "sub": sub, "del": dele, "ins": ins, "err": err, "serr": serr}
    return None


def parse_sum_nce(sum_file):
    """Parse sclite sum report to extract NCE score."""
    with open(sum_file, "r") as f:
        content = f.read()
    # NCE is in the last column when confidence scores are present
    # | Sum/Avg|   N   NWRD | Corr    Sub    Del    Ins    Err  S.Err |  NCE   |
    match = re.search(
        r"Sum/Avg\|.*?\|\s*[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s*\|\s*([-\d.]+)\s*\|",
        content,
    )
    if match:
        return float(match.group(1))
    return None


def parse_lur_report(lur_file):
    """Parse sclite LUR report to extract per-category WER."""
    with open(lur_file, "r") as f:
        content = f.read()
    # The LUR report has category columns with headers and WER values
    # Look for the Set Sum/Avg row
    results = {}
    # Parse header to find category positions
    lines = content.split("\n")

    # Find header line with category names
    header_pattern = re.compile(r"\|\s*SPKR\s*\|")
    category_labels = []
    header_idx = None

    for i, line in enumerate(lines):
        if header_pattern.search(line):
            header_idx = i
            break

    if header_idx is None:
        return results

    # The line before has category names
    # Parse the Sum/Avg line
    for line in lines:
        if "Sum/Avg" in line or "Set Sum" in line:
            # Extract all [N] WER pairs
            pairs = re.findall(r"\[(\d+)\]\s+([\d.]+)", line)
            break

    # Now map pairs to categories by parsing the header structure
    # Re-parse more carefully using the table structure
    # Look for the categories in the report header section
    cat_names = []
    for line in lines:
        # Lines like: |    With Alt     ->   Segments Containing Alternations   |
        m = re.match(r"\|\s*(.+?)\s*->\s*(.+?)\s*\|", line.strip())
        if m:
            cat_names.append(m.group(1).strip())

    # Alternative: extract from column headers
    for line in lines:
        if "#Wrd %WE" in line:
            # This header line has column labels
            cols = re.findall(r"#Wrd %WE", line)
            break

    # Try to extract per-label data from the full table
    # Parse the report line by line to find the structure
    for line in lines:
        if "Set Sum" in line or "Sum/Avg" in line:
            # Extract all percentage values after [N]
            numbers = re.findall(r"\[\s*(\d+)\]\s+([\d.]+)", line)
            if numbers:
                # First pair is Overall
                if len(numbers) >= 1:
                    results["O"] = float(numbers[0][1])
                # Subsequent pairs are the category groups
                for idx, (n, wer) in enumerate(numbers[1:], 1):
                    results[f"cat{idx}"] = float(wer)
            break

    return results


def score_system(sys_name, workdir):
    """Score a single system with sclite and return WER + NCE."""
    ref = os.path.join(DATA_DIR, "ref.stm")
    hyp = os.path.join(DATA_DIR, f"{sys_name}.ctm")
    out_name = sys_name

    cmd = (
        f"{SCLITE} -r {ref} stm -h {hyp} ctm "
        f"-o sum lur -O {workdir} -f 0 -n {out_name}"
    )
    stdout, stderr, rc = run_cmd(cmd)
    if rc != 0:
        print(f"sclite failed for {sys_name}: {stderr}", file=sys.stderr)
        return None, None, None

    # Parse sum report
    sum_file = os.path.join(workdir, f"{out_name}.sys")
    metrics = parse_sum_report(sum_file)
    wer = metrics["err"] if metrics else None

    # Parse NCE
    nce = parse_sum_nce(sum_file)

    # Parse LUR for per-category WER
    lur_file = os.path.join(workdir, f"{out_name}.lur")
    lur_metrics = {}
    if os.path.exists(lur_file):
        lur_metrics = parse_lur_report(lur_file)

    return wer, nce, lur_metrics


def parse_lur_detailed(lur_file):
    """Parse LUR report more carefully to extract per-label WER."""
    if not os.path.exists(lur_file):
        return {}

    with open(lur_file, "r") as f:
        content = f.read()

    results = {}
    lines = content.split("\n")

    # Find category header mappings from the report header
    cat_map = {}
    for line in lines:
        m = re.match(r"\|\s*(.+?)\s*->\s*(.+?)\s*\|", line.strip())
        if m:
            short = m.group(1).strip()
            desc = m.group(2).strip()
            cat_map[short] = desc

    # Find the table header line with column names
    col_headers = []
    for i, line in enumerate(lines):
        if "#Wrd %WE" in line:
            # Column names are on the line immediately above
            prev_line = lines[i - 1] if i > 0 else ""
            # Column names are separated by |
            parts = re.split(r"\|", prev_line)
            for p in parts:
                p = p.strip()
                if p and p != "SPKR":
                    col_headers.append(p)
            break

    # Find Set Sum/Avg line and extract values
    for line in lines:
        if "Set Sum" in line or "Sum/Avg" in line:
            # Extract [N] WER pairs
            pairs = re.findall(r"\[\s*(\d+)\]\s+([\d.]+)", line)
            # Map to column headers
            for idx, (nwrd, wer) in enumerate(pairs):
                if idx < len(col_headers):
                    results[col_headers[idx]] = float(wer)
                else:
                    results[f"col{idx}"] = float(wer)
            break

    return results


def run_rover_and_score(sys_names, method, method_args, workdir):
    """Run ROVER on given systems, then score result."""
    hyp_args = " ".join(
        f"-h {os.path.join(DATA_DIR, s + '.ctm')} ctm" for s in sys_names
    )
    rover_out = os.path.join(workdir, "rover_out.ctm")

    cmd = f"{ROVER} {hyp_args} -o {rover_out} {method_args}"
    stdout, stderr, rc = run_cmd(cmd)
    if rc != 0:
        print(f"ROVER failed for {sys_names} {method}: {stderr}", file=sys.stderr)
        return None

    # Score ROVER output
    ref = os.path.join(DATA_DIR, "ref.stm")
    score_name = "rover_score"
    cmd = (
        f"{SCLITE} -r {ref} stm -h {rover_out} ctm "
        f"-o sum -O {workdir} -f 0 -n {score_name}"
    )
    stdout, stderr, rc = run_cmd(cmd)
    if rc != 0:
        print(f"sclite failed for ROVER output: {stderr}", file=sys.stderr)
        return None

    sum_file = os.path.join(workdir, f"{score_name}.sys")
    metrics = parse_sum_report(sum_file)
    return metrics["err"] if metrics else None


def main():
    # Step 1: Score each system individually
    print("=== Step 1: Scoring individual systems ===")
    system_wers = {}
    system_nces = {}
    system_lurs = {}
    systems = ["sys1", "sys2", "sys3", "sys4", "sys5"]

    for sys_name in systems:
        workdir = tempfile.mkdtemp(prefix=f"score_{sys_name}_")
        wer, nce, lur = score_system(sys_name, workdir)
        if wer is not None:
            system_wers[sys_name] = wer
            print(f"  {sys_name}: WER={wer}%")
        if nce is not None:
            system_nces[sys_name] = nce
            print(f"  {sys_name}: NCE={nce}")
        if lur:
            system_lurs[sys_name] = lur

    # Write individual_wer.csv
    with open(os.path.join(RESULTS_DIR, "individual_wer.csv"), "w") as f:
        for sys_name in systems:
            if sys_name in system_wers:
                f.write(f"{sys_name},{system_wers[sys_name]:.1f}\n")

    # Write nce_scores.csv
    with open(os.path.join(RESULTS_DIR, "nce_scores.csv"), "w") as f:
        for sys_name in systems:
            if sys_name in system_nces:
                f.write(f"{sys_name},{system_nces[sys_name]:.3f}\n")

    # Step 2: Find best 3-system ROVER combination
    print("\n=== Step 2: Testing ROVER combinations ===")
    best_combo = None
    best_wer = float("inf")
    combo_results = {}

    for combo in itertools.combinations(systems, 3):
        workdir = tempfile.mkdtemp(prefix="rover_combo_")
        wer = run_rover_and_score(combo, "avgconf", "-m avgconf", workdir)
        if wer is not None:
            combo_key = ",".join(combo)
            combo_results[combo_key] = wer
            print(f"  {combo_key}: WER={wer}%")
            if wer < best_wer:
                best_wer = wer
                best_combo = combo

    if best_combo is None:
        print("ERROR: No ROVER combination succeeded!", file=sys.stderr)
        sys.exit(1)

    best_combo_str = ",".join(sorted(best_combo, key=lambda x: int(x[3:])))
    print(f"\nBest combination: {best_combo_str} with WER={best_wer}%")

    # Write best_rover_combination.txt
    with open(os.path.join(RESULTS_DIR, "best_rover_combination.txt"), "w") as f:
        f.write(f"{best_combo_str}\n")

    # Write best_rover_wer.txt
    with open(os.path.join(RESULTS_DIR, "best_rover_wer.txt"), "w") as f:
        f.write(f"{best_wer:.1f}\n")

    # Step 3: Compare voting methods for best combination
    print("\n=== Step 3: Comparing voting methods ===")
    voting_methods = {
        "avgconf": "-m avgconf",
        "maxconf": "-m maxconf",
        "word_frequency": "-m avgconf -a 1.0 -c 0.0",
    }
    voting_results = {}

    for method_name, method_args in voting_methods.items():
        workdir = tempfile.mkdtemp(prefix=f"rover_{method_name}_")
        wer = run_rover_and_score(best_combo, method_name, method_args, workdir)
        if wer is not None:
            voting_results[method_name] = wer
            print(f"  {method_name}: WER={wer}%")

    # Write voting_comparison.csv
    with open(os.path.join(RESULTS_DIR, "voting_comparison.csv"), "w") as f:
        for method_name in ["avgconf", "maxconf", "word_frequency"]:
            if method_name in voting_results:
                f.write(f"{method_name},{voting_results[method_name]:.1f}\n")

    # Step 4: Per-category WER for best individual system
    print("\n=== Step 4: Per-category WER for best system ===")
    best_sys = min(system_wers, key=system_wers.get)
    print(f"Best individual system: {best_sys} (WER={system_wers[best_sys]}%)")

    # Re-run sclite with LUR output for the best system
    workdir = tempfile.mkdtemp(prefix="category_")
    ref = os.path.join(DATA_DIR, "ref.stm")
    hyp = os.path.join(DATA_DIR, f"{best_sys}.ctm")

    cmd = (
        f"{SCLITE} -r {ref} stm -h {hyp} ctm "
        f"-o sum lur -O {workdir} -f 0 -n {best_sys}"
    )
    stdout, stderr, rc = run_cmd(cmd)

    # Parse the LUR file more carefully
    lur_file = os.path.join(workdir, f"{best_sys}.lur")
    if os.path.exists(lur_file):
        with open(lur_file, "r") as f:
            lur_content = f.read()
        print(f"LUR content:\n{lur_content}")

        # Parse LUR for category WER values
        # The LUR table has columns for each label category
        # Find Sum/Avg row and extract all [N] WER pairs
        lines = lur_content.split("\n")

        # First, find the category labels from the header
        label_order = []
        for line in lines:
            m = re.match(r"\|\s+(\S+)\s+->", line)
            if m:
                label_order.append(m.group(1))

        # Find SPKR header line to get column label positions
        col_labels = []
        for i, line in enumerate(lines):
            if "#Wrd %WE" in line:
                # The line immediately above has the column labels (SPKR | Overall || Male | Female || ...)
                prev = lines[i - 1] if i >= 1 else ""
                # Extract labels between pipes
                parts = [p.strip() for p in prev.split("|") if p.strip()]
                col_labels = [p for p in parts if p != "SPKR"]
                break

        # Find Set Sum/Avg line
        for line in lines:
            if "Set Sum" in line or "Sum/Avg" in line:
                pairs = re.findall(r"\[\s*(\d+)\]\s+([\d.]+)", line)
                cat_wer = {}
                for idx, (nwrd, wer) in enumerate(pairs):
                    if idx < len(col_labels):
                        cat_wer[col_labels[idx]] = float(wer)
                print(f"Category WER: {cat_wer}")

                # Map column labels to label IDs
                # The label_order from the header maps short names
                # We need the label IDs: O, M, F, CL, NS
                # The LUR header shows mapping like:
                #   Overall -> All Segments  (ID: O)
                #   Male -> Male Speakers (ID: M)
                # etc.
                label_id_map = {}
                for line2 in lines:
                    m2 = re.match(
                        r"\|\s+(\S+)\s+->.*$", line2
                    )
                    if m2:
                        short = m2.group(1).strip()
                        label_id_map[short] = short

                break

        # Write category_wer.csv
        # Map the column headers to label IDs
        # The STM defines labels with IDs O, M, F, CL, NS
        # The LUR report uses the LABEL title as column header
        # From STM: LABEL "O" "Overall", LABEL "M" "Male", etc.
        label_title_to_id = {
            "Overall": "O",
            "Male": "M",
            "Female": "F",
            "Clean": "CL",
            "Noisy": "NS",
        }

        with open(os.path.join(RESULTS_DIR, "category_wer.csv"), "w") as f:
            for col_title, wer_val in cat_wer.items():
                label_id = label_title_to_id.get(col_title, col_title)
                f.write(f"{label_id},{wer_val:.1f}\n")
                print(f"  {label_id}: {wer_val}%")

    print("\n=== Done! Results written to /app/results/ ===")


if __name__ == "__main__":
    main()
