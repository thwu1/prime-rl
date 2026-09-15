#!/usr/bin/env python3

"""
Solution for CSV Dialect Detection Adversarial Analysis.

Creates:
  /app/score_report.py          -- analysis tool
  /app/challenges/*.csv         -- four adversarial CSV files
  /app/results.json             -- combined analysis output
"""

import csv
import json
import os
import subprocess
import sys


# ─────────────────────────── helpers ───────────────────────────

def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        f.write(text)


# ─────────────── 1. score_report.py ────────────────────────────

SCORE_REPORT_CODE = r'''#!/usr/bin/env python3
"""
Analyse a CSV file's dialect detection scores using CleverCSV internals.

Usage:  python score_report.py <csv_file>
Output: JSON to stdout.
"""

import json, sys
from clevercsv import field_size_limit
from clevercsv.consistency import ConsistencyDetector
from clevercsv.detect import Detector, DetectionMethod
from clevercsv.potential_dialects import get_dialects


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python score_report.py <csv_file>")

    with open(sys.argv[1], "r") as fh:
        data = fh.read()

    # --- detect dialect & method ---
    det = Detector()
    dialect = det.detect(data)
    method = det.method_.value if hasattr(det, "method_") else "unknown"

    # --- enumerate candidates & compute consistency scores ---
    dialects = get_dialects(data)
    old_limit = field_size_limit(len(data) + 1)
    cd = ConsistencyDetector(skip=False)
    scores = cd.compute_consistency_scores(data, dialects)
    field_size_limit(old_limit)

    candidates = []
    for d, sc in sorted(
        scores.items(),
        key=lambda x: x[1].Q if x[1].Q is not None else float("-inf"),
        reverse=True,
    ):
        candidates.append(
            {
                "delimiter": d.delimiter,
                "quotechar": d.quotechar,
                "escapechar": d.escapechar,
                "pattern_score": sc.P,
                "type_score": sc.T,
                "consistency_score": sc.Q,
            }
        )

    winner = None
    if dialect is not None:
        winner = {
            "delimiter": dialect.delimiter,
            "quotechar": dialect.quotechar,
            "escapechar": dialect.escapechar,
        }

    json.dump(
        {"candidates": candidates, "winner": winner, "method": method},
        sys.stdout,
        indent=2,
    )
    print()  # trailing newline


if __name__ == "__main__":
    main()
'''


# ─────────────── 2. challenge CSV files ────────────────────────

def create_pipe_consistency() -> None:
    """
    Pipe-delimited, no quotechar, no escapechar.
    The backslash-comma in row 8 makes cells non-elementary (backslash and
    comma are not in CleverCSV's elementary character set), so ALL five
    normal forms fail.  The consistency measure then runs and selects pipe
    because it gives a perfect 4-column pattern with high type scores.
    """
    rows = [
        "id|name|dept|salary",
        "1|Alice|Engineering|95000",
        "2|Bob|Marketing|82000",
        "3|Charlie|Finance|90000",
        "4|Diana|Operations|105000",
        "5|Eve|Research|78000",
        "6|Frank|HR|72000",
        "7|Grace|Sales|88000",
        "8|Henry|Corp\\,Ltd|93000",
    ]
    _write("/app/challenges/pipe_consistency.csv", "\n".join(rows) + "\n")


def create_mixed_quoting() -> None:
    """
    Semicolon-delimited with single-quote quoting.  Some cells in each
    data row are quoted and some are not.
    """
    rows = [
        "id;name;city;department;score",
        "1;'Alice';'New York';Engineering;95.5",
        "2;Bob;London;'Marketing & Sales';88.2",
        "3;'Charlie';'Sao Paulo';Finance;72.0",
        "4;Diana;Tokyo;Operations;91.3",
        "5;'Eve';Berlin;'Research & Dev';85.9",
        "6;Frank;'Los Angeles';HR;79.4",
    ]
    _write("/app/challenges/mixed_quoting.csv", "\n".join(rows) + "\n")


def create_sniffer_disagree() -> None:
    """
    Tab-delimited file with commas embedded inside field values.

    Python's csv.Sniffer uses character-frequency heuristics.  Each row
    has 3 tabs and 2 commas, both perfectly consistent.  Sniffer picks
    comma (higher perceived delimiter quality for its heuristic).

    CleverCSV uses the consistency measure: parsing with tab gives 4
    columns of clean types (name, city+state, score, status), while
    parsing with comma gives 3 columns containing tabs — all unknown
    types.  Tab wins on type score.
    """
    rows = [
        "name\tcity,state\tscore,rank\tstatus",
        "Alice\tNew York,NY\t95,1\tactive",
        "Bob\tLos Angeles,CA\t88,2\tpending",
        "Charlie\tChicago,IL\t92,3\tactive",
        "Diana\tHouston,TX\t85,4\tclosed",
        "Eve\tPhoenix,AZ\t91,5\tactive",
        "Frank\tPhiladelphia,PA\t87,6\tpending",
    ]
    _write("/app/challenges/sniffer_disagree.csv", "\n".join(rows) + "\n")


def create_many_candidates() -> None:
    """
    Uses diverse special characters to maximise the candidate space.

    Potential delimiters (Unicode category NOT in block_cat, char NOT in
    block_char):  ,  ;  #  ~  |  (empty)   -> 6
    Potential quotechars (',",~ in data plus empty):  '  "  ~  (empty)  -> 4
    No escape characters (no backslash in data).

    Total candidates = 6 x 4 = 24  >= 20.
    """
    rows = [
        "1,Alice,'95.5',NYC|East,active;#01~\"info\"",
        "2,Bob,'88.2',LAX|West,pending;#02~\"info\"",
        "3,Charlie,'92.1',CHI|Central,active;#03~\"info\"",
        "4,Diana,'85.7',HOU|South,closed;#04~\"info\"",
        "5,Eve,'91.3',PHX|West,active;#05~\"info\"",
    ]
    _write("/app/challenges/many_candidates.csv", "\n".join(rows) + "\n")


# ─────────────── 3. verify sniffer disagreement ────────────────

def verify_sniffer_disagree() -> bool:
    from clevercsv.detect import Detector as D

    with open("/app/challenges/sniffer_disagree.csv") as f:
        data = f.read()

    clever = D().detect(data)
    print(f"[verify] CleverCSV delimiter: {clever.delimiter!r}")

    try:
        sniffed = csv.Sniffer().sniff(data)
        print(f"[verify] Sniffer   delimiter: {sniffed.delimiter!r}")
        if sniffed.delimiter == clever.delimiter:
            print("[verify] WARNING — they agree; test will fail")
            return False
    except csv.Error as exc:
        print(f"[verify] Sniffer error: {exc}")
        return False

    print("[verify] OK — they disagree")
    return True


# ─────────────── 4. generate results.json ──────────────────────

def generate_results() -> None:
    results = {}
    for name in (
        "pipe_consistency.csv",
        "mixed_quoting.csv",
        "sniffer_disagree.csv",
        "many_candidates.csv",
    ):
        fpath = f"/app/challenges/{name}"
        proc = subprocess.run(
            [sys.executable, "/app/score_report.py", fpath],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            print(f"score_report.py failed on {name}:\n{proc.stderr}",
                  file=sys.stderr)
            results[name] = {"error": proc.stderr}
        else:
            results[name] = json.loads(proc.stdout)

    _write("/app/results.json", json.dumps(results, indent=2) + "\n")


# ─────────────── main ─────────────────────────────────────────

def main() -> None:
    print("=== Creating score_report.py ===")
    _write("/app/score_report.py", SCORE_REPORT_CODE)

    print("=== Creating challenge CSV files ===")
    create_pipe_consistency()
    create_mixed_quoting()
    create_sniffer_disagree()
    create_many_candidates()

    print("=== Verifying sniffer disagreement ===")
    verify_sniffer_disagree()

    print("=== Generating results.json ===")
    generate_results()

    print("=== Done ===")


if __name__ == "__main__":
    main()
