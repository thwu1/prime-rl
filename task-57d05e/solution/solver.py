"""WCA FMC Multi-Tool Analysis Pipeline - Solution."""

import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Rubik's Cube state simulator (cycle-based permutations on 54 facelets)
# Facelet order: URFDLB, 9 per face, reading order from outside each face.
# Cycles are (a, b, c, d) meaning: new[b]=old[a], new[c]=old[b], ...
# ---------------------------------------------------------------------------

SOLVED = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

MOVE_CYCLES = {
    "U": [(0, 2, 8, 6), (1, 5, 7, 3), (18, 36, 45, 9), (19, 37, 46, 10), (20, 38, 47, 11)],
    "R": [(9, 11, 17, 15), (10, 14, 16, 12), (8, 45, 35, 26), (5, 48, 32, 23), (2, 51, 29, 20)],
    "F": [(18, 20, 26, 24), (19, 23, 25, 21), (6, 9, 29, 44), (7, 12, 28, 41), (8, 15, 27, 38)],
    "D": [(27, 29, 35, 33), (28, 32, 34, 30), (24, 15, 51, 42), (44, 26, 17, 53), (25, 16, 52, 43)],
    "L": [(36, 38, 44, 42), (37, 41, 43, 39), (0, 18, 27, 53), (3, 21, 30, 50), (6, 24, 33, 47)],
    "B": [(45, 47, 53, 51), (46, 50, 52, 48), (2, 36, 33, 17), (1, 39, 34, 14), (0, 42, 35, 11)],
}


def apply_cycles(state, cycles, times=1):
    for _ in range(times % 4):
        new = list(state)
        for cycle in cycles:
            n = len(cycle)
            for i in range(n):
                new[cycle[(i + 1) % n]] = state[cycle[i]]
        state = new
    return state


def parse_move(token):
    base = token[0]
    suffix = token[1:]
    if suffix == "":
        return base, 1
    elif suffix in ("'", "\u2019"):
        return base, 3
    elif suffix == "2":
        return base, 2
    elif suffix == "1":
        return base, 1
    elif suffix == "3":
        return base, 3
    else:
        raise ValueError(f"Unknown move: {token}")


def apply_sequence(state_str, sequence):
    state = list(state_str)
    for token in sequence.split():
        face, times = parse_move(token)
        state = apply_cycles(state, MOVE_CYCLES[face], times)
    return "".join(state)


def invert_move(token):
    base = token[0]
    suffix = token[1:]
    if suffix == "":
        return base + "'"
    elif suffix in ("'", "\u2019"):
        return base
    elif suffix == "2":
        return base + "2"
    else:
        raise ValueError(f"Unknown move: {token}")


def invert_sequence(sequence):
    moves = sequence.strip().split()
    return " ".join(invert_move(m) for m in reversed(moves))


def normalize_kociemba_output(sol_str):
    """Convert kociemba output (e.g. 'R1 U3 F2') to Singmaster (R U' F2)."""
    result = []
    for tok in sol_str.strip().split():
        if not tok:
            continue
        base = tok[0]
        suffix = tok[1:] if len(tok) > 1 else ""
        if suffix == "1" or suffix == "":
            result.append(base)
        elif suffix == "2":
            result.append(base + "2")
        elif suffix == "3" or suffix == "'":
            result.append(base + "'")
        else:
            result.append(tok)
    return " ".join(result)


# ---------------------------------------------------------------------------
# Step 1: Create SQLite database from TSV files
# ---------------------------------------------------------------------------

def create_database():
    print("Creating SQLite database...")
    db_path = "/app/fmc.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    # Create tables and import data using sqlite3 CLI
    sql_commands = """
.mode tabs
.import /app/data/fmc_results.tsv results_raw

CREATE TABLE results AS
SELECT
    CAST(id AS INTEGER) AS id,
    CAST(pos AS INTEGER) AS pos,
    CAST(best AS INTEGER) AS best,
    CAST(average AS INTEGER) AS average,
    competition_id,
    round_type_id,
    event_id,
    person_name,
    person_id,
    format_id,
    regional_single_record,
    regional_average_record,
    person_country_id
FROM results_raw
WHERE id != 'id';

DROP TABLE results_raw;

.mode tabs
.import /app/data/fmc_scrambles.tsv scrambles_raw

CREATE TABLE scrambles AS
SELECT
    scramble,
    CAST(id AS INTEGER) AS id,
    competition_id,
    event_id,
    group_id,
    CAST(is_extra AS INTEGER) AS is_extra,
    round_type_id,
    CAST(scramble_num AS INTEGER) AS scramble_num
FROM scrambles_raw
WHERE scramble != 'scramble';

DROP TABLE scrambles_raw;
"""
    proc = subprocess.run(
        ["sqlite3", db_path],
        input=sql_commands,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"sqlite3 error: {proc.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Database created successfully.")


# ---------------------------------------------------------------------------
# Step 2: Compute database statistics using SQL queries
# ---------------------------------------------------------------------------

def compute_db_stats():
    print("Computing database statistics...")
    db_path = "/app/fmc.db"

    def query(sql):
        proc = subprocess.run(
            ["sqlite3", "-json", db_path, sql],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"SQL error: {proc.stderr}", file=sys.stderr)
            return []
        return json.loads(proc.stdout) if proc.stdout.strip() else []

    def query_scalar(sql):
        rows = query(sql)
        if rows:
            return list(rows[0].values())[0]
        return None

    stats = {}
    stats["total_result_rows"] = query_scalar("SELECT COUNT(*) AS c FROM results")
    stats["valid_results"] = query_scalar("SELECT COUNT(*) AS c FROM results WHERE best > 0")
    stats["unique_competitors"] = query_scalar("SELECT COUNT(DISTINCT person_id) AS c FROM results")
    stats["unique_competitions"] = query_scalar("SELECT COUNT(DISTINCT competition_id) AS c FROM results")
    stats["best_single_ever"] = query_scalar("SELECT MIN(best) AS c FROM results WHERE best > 0")
    stats["sub20_count"] = query_scalar("SELECT COUNT(*) AS c FROM results WHERE best > 0 AND best < 20")

    # Median via LIMIT/OFFSET
    valid_count = stats["valid_results"]
    median_offset = valid_count // 2
    stats["median_single"] = query_scalar(
        f"SELECT best AS c FROM results WHERE best > 0 ORDER BY best LIMIT 1 OFFSET {median_offset}"
    )

    # Top 5 singles
    top5_rows = query(
        "SELECT person_name, best, competition_id FROM results "
        "WHERE best > 0 ORDER BY best ASC, person_name ASC LIMIT 5"
    )
    stats["top5_singles"] = top5_rows

    # Records count
    stats["records_count"] = query_scalar(
        "SELECT COUNT(*) AS c FROM results WHERE regional_single_record != 'NULL' AND regional_single_record != ''"
    )

    # Scramble count
    stats["scramble_count"] = query_scalar("SELECT COUNT(*) AS c FROM scrambles")

    return stats


# ---------------------------------------------------------------------------
# Step 3: Scramble analysis with jq + kociemba
# ---------------------------------------------------------------------------

def analyze_scrambles():
    print("Analyzing scrambles...")
    import kociemba

    # Use jq to extract scramble data
    jq_cmd = 'jq -c ".[]" /app/data/target_scrambles.json'
    proc = subprocess.run(jq_cmd, shell=True, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"jq error: {proc.stderr}", file=sys.stderr)
        sys.exit(1)

    scramble_entries = [json.loads(line) for line in proc.stdout.strip().split("\n")]

    results = []
    for entry in scramble_entries:
        comp_id = entry["competition_id"]
        snum = entry["scramble_num"]
        scramble = entry["scramble"]

        # Compute facelet string
        facelet = apply_sequence(SOLVED, scramble)

        # Use kociemba to find solution
        try:
            raw_sol = kociemba.solve(facelet)
            kociemba_sol = normalize_kociemba_output(raw_sol)
        except Exception as e:
            print(f"Kociemba failed for {comp_id} #{snum}: {e}", file=sys.stderr)
            kociemba_sol = ""

        kociemba_moves = kociemba_sol.split() if kociemba_sol else []
        kociemba_len = len(kociemba_moves)

        # Verify kociemba solution
        if kociemba_sol:
            after_sol = apply_sequence(facelet, kociemba_sol)
            verified = (after_sol == SOLVED)
        else:
            verified = False

        # Compute inverse solution
        inv_sol = invert_sequence(scramble)
        inv_len = len(inv_sol.split())

        results.append({
            "competition_id": comp_id,
            "scramble_num": snum,
            "scramble": scramble,
            "facelet_string": facelet,
            "kociemba_solution": kociemba_sol,
            "kociemba_length": kociemba_len,
            "verified": verified,
            "inverse_solution": inv_sol,
            "inverse_length": inv_len,
        })

        print(f"  {comp_id} #{snum}: kociemba={kociemba_len} moves, inverse={inv_len} moves")

    return results


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    os.makedirs("/app/output", exist_ok=True)

    # Step 1: Create database
    create_database()

    # Step 2: Database statistics
    db_stats = compute_db_stats()
    with open("/app/output/db_stats.json", "w") as f:
        json.dump(db_stats, f, indent=2)
    print(f"Database stats written. Best single: {db_stats['best_single_ever']}")

    # Step 3: Scramble analysis
    analysis = analyze_scrambles()
    with open("/app/output/scramble_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"Scramble analysis written. {len(analysis)} scrambles analyzed.")

    # Write the pipeline script marker
    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()
