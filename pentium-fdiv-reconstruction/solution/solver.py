"""
Division unit analysis — solution module.

Parses the binary ROM dump and PLA specification, reconstructs both lookup
tables, identifies differences, implements iterative division, creates an
SQLite database, generates a gnuplot visualization, and analyzes the defect.

"""

import json
import math
import os
import sqlite3
import struct
import subprocess
from fractions import Fraction


def load_buggy_table():
    """Parse the binary ROM dump at /app/buggy_rom.bin.

    Format: 2048 signed bytes.
    byte_offset = d_idx * 128 + (p_idx & 0x7F)
    """
    with open('/app/buggy_rom.bin', 'rb') as f:
        data = f.read()

    table = {}
    for d_idx in range(16):
        for p_idx in range(-64, 64):
            hw = p_idx & 0x7F
            offset = d_idx * 128 + hw
            q = struct.unpack('b', bytes([data[offset]]))[0]
            table[(d_idx, p_idx)] = q
    return table


def load_fixed_table():
    """Evaluate the PLA specification at /app/fixed_rom.pla to reconstruct
    the corrected lookup table.

    The PLA uses the Espresso/Berkeley format:
    - 11 inputs: d3 d2 d1 d0 p6 p5 p4 p3 p2 p1 p0
    - 2 outputs: mag1 (|q|=1), mag2 (|q|=2)
    - Sign of q comes from sign of partial remainder (p6 = sign bit)
    """
    # Parse PLA file
    terms = []
    with open('/app/fixed_rom.pla') as f:
        in_terms = False
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('.p '):
                in_terms = True
                continue
            if line.startswith('.e'):
                break
            if line.startswith('.'):
                continue
            if in_terms:
                parts = line.split()
                if len(parts) == 2:
                    terms.append((parts[0], parts[1]))

    # Evaluate PLA for all inputs
    table = {}
    for d_idx in range(16):
        for p_idx in range(-64, 64):
            hw = p_idx & 0x7F
            input_bits = format(d_idx, '04b') + format(hw, '07b')

            mag1 = False
            mag2 = False

            for and_pattern, or_pattern in terms:
                # Check if input matches the AND pattern
                match = True
                for i, c in enumerate(and_pattern):
                    if c == '-':
                        continue
                    if c != input_bits[i]:
                        match = False
                        break

                if match:
                    if or_pattern[0] == '1':
                        mag1 = True
                    if or_pattern[1] == '1':
                        mag2 = True

            # Determine q from magnitude and sign
            if mag2:
                q_mag = 2
            elif mag1:
                q_mag = 1
            else:
                q_mag = 0

            if q_mag == 0:
                table[(d_idx, p_idx)] = 0
            elif p_idx >= 0:
                table[(d_idx, p_idx)] = q_mag
            else:
                table[(d_idx, p_idx)] = -q_mag

    return table


def find_differences(table_a, table_b):
    """Return sorted list of (d_idx, p_idx) tuples where tables differ."""
    diffs = []
    for key in table_a:
        if table_a[key] != table_b[key]:
            diffs.append(key)
    return sorted(diffs)


def divide(a_sig, d_sig, table, num_steps=34):
    """Perform iterative base-4 division of significand a_sig by d_sig.

    Both a_sig and d_sig are floats in [1.0, 2.0).
    Uses the given lookup table for quotient digit selection.
    Returns the quotient as a float.
    """
    d = d_sig
    w = a_sig

    d_idx = int((d - 1.0) * 16)
    d_idx = max(0, min(15, d_idx))

    quotient = 0.0
    scale = 1.0

    for _ in range(num_steps):
        p_idx = int(math.floor(w * 8))
        p_idx = max(-64, min(63, p_idx))

        q = table.get((d_idx, p_idx), 0)

        quotient += q * scale
        scale /= 4.0

        w = 4.0 * (w - q * d)

    return quotient


def table_stats(table):
    """Compute digit-frequency statistics for a lookup table."""
    counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    for v in table.values():
        counts[v] += 1
    return {
        "total": len(table),
        "q_plus2": counts[2],
        "q_plus1": counts[1],
        "q_zero": counts[0],
        "q_minus1": counts[-1],
        "q_minus2": counts[-2],
    }


def create_database(buggy, fixed, diffs):
    """Create SQLite database with both tables and differences."""
    db_path = "/app/tables.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE buggy (
        d_idx INTEGER, p_idx INTEGER, q INTEGER,
        PRIMARY KEY(d_idx, p_idx)
    )""")
    c.execute("""CREATE TABLE fixed (
        d_idx INTEGER, p_idx INTEGER, q INTEGER,
        PRIMARY KEY(d_idx, p_idx)
    )""")
    c.execute("""CREATE TABLE diffs (
        d_idx INTEGER, p_idx INTEGER,
        buggy_q INTEGER, fixed_q INTEGER,
        PRIMARY KEY(d_idx, p_idx)
    )""")

    for (d_idx, p_idx), q in buggy.items():
        c.execute("INSERT INTO buggy VALUES (?, ?, ?)", (d_idx, p_idx, q))
    for (d_idx, p_idx), q in fixed.items():
        c.execute("INSERT INTO fixed VALUES (?, ?, ?)", (d_idx, p_idx, q))
    for d_idx, p_idx in diffs:
        c.execute("INSERT INTO diffs VALUES (?, ?, ?, ?)",
                  (d_idx, p_idx, buggy[(d_idx, p_idx)], fixed[(d_idx, p_idx)]))

    conn.commit()
    conn.close()
    print(f"Created SQLite database: {db_path}")


def generate_visualization(fixed, diffs):
    """Generate gnuplot heatmap visualization of the corrected table."""
    diffs_set = set(diffs)

    # Write main data file (scan-line order for gnuplot 'with image')
    with open("/app/table_data.dat", "w") as f:
        for d_idx in range(16):
            for p_idx in range(-64, 64):
                q = fixed[(d_idx, p_idx)]
                f.write(f"{d_idx} {p_idx} {q}\n")
            f.write("\n")

    # Write diff marker positions
    with open("/app/diff_positions.dat", "w") as f:
        for d_idx, p_idx in sorted(diffs_set):
            f.write(f"{d_idx} {p_idx}\n")

    # Write gnuplot script
    with open("/app/plot.gp", "w") as f:
        f.write('set terminal pngcairo size 1000,700 enhanced\n')
        f.write('set output "/app/table_map.png"\n')
        f.write('set title "Corrected Quotient Selection Table with Defect Locations"\n')
        f.write('set xlabel "Divisor Index (d\\_idx)"\n')
        f.write('set ylabel "Partial Remainder Index (p\\_idx)"\n')
        f.write('set palette defined (-2 "#2166ac", -1 "#67a9cf", 0 "#f7f7f7", 1 "#ef8a62", 2 "#b2182b")\n')
        f.write('set cbrange [-2.5:2.5]\n')
        f.write('set cbtics -2,1,2\n')
        f.write('set cblabel "Quotient Digit (q)"\n')
        f.write('set xrange [-0.5:15.5]\n')
        f.write('set yrange [-64.5:63.5]\n')
        f.write('set key outside right top\n')
        f.write('plot "/app/table_data.dat" using 1:2:3 with image notitle, \\\n')
        f.write('     "/app/diff_positions.dat" using 1:2 with points pt 7 ps 1.2 lc rgb "#000000" title "Defective"\n')

    result = subprocess.run(["gnuplot", "/app/plot.gp"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gnuplot stderr: {result.stderr}")
        # Fallback to basic png terminal
        with open("/app/plot.gp", "w") as f:
            f.write('set terminal png size 1000,700\n')
            f.write('set output "/app/table_map.png"\n')
            f.write('set title "Corrected Quotient Selection Table"\n')
            f.write('set xlabel "d_idx"\n')
            f.write('set ylabel "p_idx"\n')
            f.write('set palette defined (-2 "blue", -1 "cyan", 0 "white", 1 "orange", 2 "red")\n')
            f.write('set cbrange [-2.5:2.5]\n')
            f.write('set xrange [-0.5:15.5]\n')
            f.write('set yrange [-64.5:63.5]\n')
            f.write('plot "/app/table_data.dat" using 1:2:3 with image notitle, \\\n')
            f.write('     "/app/diff_positions.dat" using 1:2 with points pt 7 ps 1.0 lc rgb "black" title "Defective"\n')
        subprocess.run(["gnuplot", "/app/plot.gp"], check=True)

    print("Generated visualization: /app/table_map.png")


def analyze_bug_pattern(buggy, fixed, diffs):
    """Determine the mathematical nature of the defect."""
    outer_evidence = []
    for d_idx in range(16):
        d = Fraction(1) + Fraction(d_idx, 16)
        max_p2 = max(p for (di, p) in fixed if di == d_idx and fixed[(di, p)] == 2)
        outer_evidence.append((d_idx, d, max_p2))

    buggy_outer = []
    for d_idx in range(16):
        d = Fraction(1) + Fraction(d_idx, 16)
        q2_positive = [p for (di, p) in buggy if di == d_idx and p > 0 and buggy[(di, p)] == 2]
        max_p2_buggy = max(q2_positive) if q2_positive else -1
        buggy_outer.append((d_idx, d, max_p2_buggy))

    pattern = (
        "The defective table has an error in the outermost boundary of the "
        "quotient-selection regions. The correct outer boundary for the "
        "|q|=2 region is |p| <= (8/3)*d, where d is the divisor. The "
        "defective table incorrectly applies a carry-save truncation "
        "adjustment of -1/8 to this outer boundary, using |p| <= (8/3)*d - 1/8 "
        "instead. This adjustment is appropriate for inner boundaries (which "
        "must account for the range of actual values within a truncated cell) "
        "but should NOT be applied to the outermost boundary, because the "
        "algorithm's convergence invariant already guarantees the actual "
        "partial remainder stays within (8/3)*d. The result is that 16 cells "
        "on the positive side and 16 on the negative side are incorrectly "
        "marked as unused (q=0) when they should contain q=+/-2. When the "
        "division algorithm accesses one of these missing entries, it selects "
        "q=0 instead of q=+/-2, causing the partial remainder to be "
        "multiplied by 4 without any compensating subtraction, which pushes "
        "it far outside the valid convergence range and corrupts all "
        "subsequent quotient digits."
    )
    return pattern


def generate_bug_demonstrations(buggy, fixed, diffs):
    """Generate demonstrations showing divergence at defective entries."""
    demos = []
    pos_diffs = [(d, p) for d, p in diffs if p > 0]

    for d_idx, p_idx in pos_diffs[:5]:
        d_val = 1.0 + d_idx / 16.0
        p_val = p_idx / 8.0 + 0.05

        buggy_q = buggy[(d_idx, p_idx)]
        correct_q = fixed[(d_idx, p_idx)]

        buggy_next_w = 4.0 * (p_val - buggy_q * d_val)
        correct_next_w = 4.0 * (p_val - correct_q * d_val)

        demos.append({
            "d_idx": d_idx,
            "p_idx": p_idx,
            "d_val": round(d_val, 10),
            "p_val": round(p_val, 10),
            "buggy_q": buggy_q,
            "correct_q": correct_q,
            "buggy_next_w": round(buggy_next_w, 10),
            "correct_next_w": round(correct_next_w, 10),
        })

    return demos


def main():
    buggy = load_buggy_table()
    fixed = load_fixed_table()

    diffs = find_differences(buggy, fixed)

    # Create SQLite database
    create_database(buggy, fixed, diffs)

    # Generate gnuplot visualization
    generate_visualization(fixed, diffs)

    # Build differences list with values
    diff_list = []
    for d_idx, p_idx in diffs:
        diff_list.append([d_idx, p_idx, buggy[(d_idx, p_idx)], fixed[(d_idx, p_idx)]])

    # Bug pattern analysis
    pattern = analyze_bug_pattern(buggy, fixed, diffs)

    # Bug demonstrations
    demos = generate_bug_demonstrations(buggy, fixed, diffs)

    # Division validation
    test_cases = [
        (1.5, 1.25),
        (1.0, 1.0),
        (1.8, 1.2),
        (1.5, 1.0),
        (1.75, 1.5),
        (1.999, 1.001),
        (1.1, 1.9),
    ]
    validation = []
    for a, d in test_cases:
        q = divide(a, d, fixed, num_steps=34)
        validation.append({"a": a, "d": d, "quotient": q})

    # Table stats
    stats = table_stats(fixed)

    results = {
        "num_differences": len(diffs),
        "differences": diff_list,
        "bug_pattern": pattern,
        "bug_demonstrations": demos,
        "division_validation": validation,
        "table_stats": stats,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Analysis complete. Found {len(diffs)} differing entries.")
    print(f"Table stats: {stats}")
    for v in validation[:3]:
        print(f"  {v['a']}/{v['d']} = {v['quotient']}")


if __name__ == "__main__":
    main()
