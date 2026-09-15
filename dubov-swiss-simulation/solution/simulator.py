#!/usr/bin/env python3
"""
FIDE Dubov Swiss Tournament Simulator.

Builds TRF16 files iteratively, generates pairings via the CPPDubovSystem
engine, applies deterministic outcomes, and produces analysis outputs.

"""

import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys


def load_spec():
    with open("/app/tournament_spec.json", "r") as f:
        return json.load(f)


def compute_outcome(id_a, id_b):
    """Deterministic outcome: returns winner ID (0 = draw)."""
    i = min(id_a, id_b)
    j = max(id_a, id_b)
    k = (3 * i + 7 * j) % 10
    if k <= 5:
        return i
    elif k <= 7:
        return 0
    else:
        return j


def make_trf_header(spec):
    """Generate the TRF tournament header lines."""
    n = len(spec["players"])
    lines = [
        "012 " + spec["tournament_name"],
        "022 Benchmark City",
        "032 International",
        "042 2026/01/01",
        "052 2026/01/07",
        "062 " + str(n),
        "072 " + str(n),
        "082 0",
        "092 Individual FIDE Dubov",
        "102 Chief Arbiter (00000000)",
        "112 ",
        "122 90/40+30",
        "TNR " + str(spec["total_rounds"]),
    ]
    return lines


def format_game_string(opponent_id, color, result):
    """
    Format a single round's game entry for a TRF player line.

    The CPPDubovSystem parser reads round data starting at byte offset 92
    (relative to the start of the line), in strides of 10:
      - 3 chars opponent at offset +0 from stride start
      - skip 1
      - 1 char color at offset +4
      - skip 1
      - 1 char result at offset +6
      - skip 3 (padding to next stride)

    The game block starts at position 89 in the line (after rankpos).
    Each block is: 2-char prefix ("  ") + 8-char game data = 10 chars.
    The 2-char prefix plus left-padding aligns opponent to parser offset 92.
    """
    if opponent_id == 0:
        game = "0000 - +"
    else:
        game = str(opponent_id) + " " + color + " " + result
    # Left-pad game string to exactly 8 characters
    while len(game) < 8:
        game = " " + game
    return "  " + game  # 2-char prefix + 8-char game = 10 chars


def make_player_line(player, points, rank_pos, games):
    """
    Construct a TRF16 player line matching the RTG output format.

    Layout (0-indexed byte positions):
      0-3:   "001 "
      4-7:   starting rank (right-justified, 4 chars)
      8-13:  "      " (sex/title/padding)
      14-46: name (left-justified, padded to 33 chars)
      47:    " "
      48-51: rating (right-justified, 4 chars)
      52-79: " FED ----------- 0000/00/00 " (28 chars)
      80-83: points (right-justified, 4 chars, e.g. " 3.5")
      84:    " "
      85-88: rank position (right-justified, 4 chars)
      89+:   round data (10 chars each)
    """
    line = "001 "

    # Starting rank / TPN (4 chars, right-justified)
    line += str(player["id"]).rjust(4)

    # Sex, title, padding (6 chars)
    line += "      "

    # Name (33 chars, left-justified, space-padded)
    name = player["name"]
    while len(name) <= 32:
        name += " "
    line += name

    # Space + rating (1 + 4 = 5 chars)
    line += " " + str(player["rating"]).rjust(4)

    # Federation, FIDE ID, birthday (28 chars)
    fed = player.get("federation", "INT")
    line += " " + fed + " ----------- 0000/00/00 "

    # Points (4 chars, right-justified)
    pts_str = "{:.1f}".format(points)
    line += pts_str.rjust(4)

    # Space + rank position (1 + 4 = 5 chars)
    line += " " + str(rank_pos).rjust(4)

    # Round data
    for g in games:
        line += format_game_string(g[0], g[1], g[2])

    return line


def compute_rank_positions(players, points):
    """Rank by descending score, then ascending TPN for ties."""
    sorted_p = sorted(players, key=lambda p: (-points[p["id"]], p["id"]))
    return {p["id"]: rank for rank, p in enumerate(sorted_p, 1)}


def write_trf(filepath, header_lines, players, points, rank_positions, all_games):
    """Write a complete TRF16 file."""
    with open(filepath, "w") as f:
        for hl in header_lines:
            f.write(hl + "\n")
        for p in players:
            pid = p["id"]
            line = make_player_line(
                p, points[pid], rank_positions[pid], all_games[pid]
            )
            f.write(line + "\n")


def parse_pairings_csv(csv_path):
    """Parse engine CSV output into list of (white_id, black_id) tuples."""
    pairings = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairings.append((int(row["White"]), int(row["Black"])))
    return pairings


def compute_aro(player_id, all_games, ratings_by_id):
    """
    Compute Average Rating of Opponents.
    Only counts over-the-board games (result in {1, 0, =}).
    Rounds to nearest integer; 0.5 rounds up (banker's rounding up).
    """
    otb_ratings = []
    for opp_id, color, result in all_games[player_id]:
        if result in ("1", "0", "="):
            if opp_id in ratings_by_id:
                otb_ratings.append(ratings_by_id[opp_id])
    if not otb_ratings:
        return 0
    return math.floor(sum(otb_ratings) / len(otb_ratings) + 0.5)


def compute_color_diff(player_id, all_games):
    """Color difference: white games - black games."""
    diff = 0
    for _, color, _ in all_games[player_id]:
        if color == "w":
            diff += 1
        elif color == "b":
            diff -= 1
    return diff


def main():
    if len(sys.argv) < 2:
        print("Usage: simulator.py <engine_binary_path>")
        sys.exit(1)

    engine_bin = sys.argv[1]
    spec = load_spec()
    players = spec["players"]
    n_players = len(players)
    ratings_by_id = {p["id"]: p["rating"] for p in players}
    n_simulate = spec["simulate_rounds"]

    # State
    points = {p["id"]: 0.0 for p in players}
    all_games = {p["id"]: [] for p in players}

    header_lines = make_trf_header(spec)
    trf_path = "/app/tournament.trf"

    for round_num in range(1, n_simulate + 1):
        rank_positions = compute_rank_positions(players, points)
        write_trf(trf_path, header_lines, players, points, rank_positions, all_games)

        csv_path = "/tmp/round{}.csv".format(round_num)
        result = subprocess.run(
            [engine_bin, "--pairings", trf_path, "--output", csv_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print("ERROR: Engine failed for round {}".format(round_num))
            print("  returncode: {}".format(result.returncode))
            print("  stdout: {}".format(result.stdout[:500]))
            print("  stderr: {}".format(result.stderr[:500]))
            sys.exit(1)

        pairings = parse_pairings_csv(csv_path)

        for white_id, black_id in pairings:
            if black_id == -1:
                # Pairing-Allocated Bye (should not occur with even players)
                all_games[white_id].append((0, "-", "+"))
                points[white_id] += 1.0
            else:
                winner = compute_outcome(white_id, black_id)
                if winner == 0:
                    # Draw
                    all_games[white_id].append((black_id, "w", "="))
                    all_games[black_id].append((white_id, "b", "="))
                    points[white_id] += 0.5
                    points[black_id] += 0.5
                elif winner == white_id:
                    all_games[white_id].append((black_id, "w", "1"))
                    all_games[black_id].append((white_id, "b", "0"))
                    points[white_id] += 1.0
                else:
                    all_games[white_id].append((black_id, "w", "0"))
                    all_games[black_id].append((white_id, "b", "1"))
                    points[black_id] += 1.0

        print("Round {} complete.".format(round_num))

    # Write final TRF
    rank_positions = compute_rank_positions(players, points)
    write_trf(trf_path, header_lines, players, points, rank_positions, all_games)
    print("Final TRF written to {}".format(trf_path))

    # Generate round 6 pairings
    r6_csv = "/tmp/round6.csv"
    result = subprocess.run(
        [engine_bin, "--pairings", trf_path, "--output", r6_csv],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print("ERROR: Engine failed for round 6 pairings")
        print("  returncode: {}".format(result.returncode))
        print("  stdout: {}".format(result.stdout[:500]))
        print("  stderr: {}".format(result.stderr[:500]))
        sys.exit(1)

    shutil.copy(r6_csv, "/app/round6_pairings.csv")
    print("Round 6 pairings written to /app/round6_pairings.csv")

    r6_pairings = parse_pairings_csv(r6_csv)

    # Compute analysis
    aro = {}
    color_diff = {}
    for p in players:
        pid = p["id"]
        aro[str(pid)] = compute_aro(pid, all_games, ratings_by_id)
        color_diff[str(pid)] = compute_color_diff(pid, all_games)

    scoregroups = {}
    for p in players:
        pid = p["id"]
        score_key = "{:.1f}".format(points[pid])
        if score_key not in scoregroups:
            scoregroups[score_key] = []
        scoregroups[score_key].append(pid)
    for key in scoregroups:
        scoregroups[key].sort()

    r6_pairs_list = [[w, b] for w, b in r6_pairings]

    analysis = {
        "aro": aro,
        "color_diff": color_diff,
        "scoregroups": scoregroups,
        "round6_pairings": r6_pairs_list,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("Analysis written to /app/analysis.json")

    # Verify FPC for all rounds
    print("\nRunning FPC verification...")
    all_ok = True
    for r in range(1, n_simulate + 1):
        result = subprocess.run(
            [engine_bin, "--fpc", trf_path, "--fpc_rounds", str(r)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        if "ERRORS TOTAL DETECTED IN TOURNAMENT PAIRINGS: 0" in output:
            matched = re.search(r"TOTAL GAMES NOT_MATCHED/TOTAL:\s*(\d+)/", output)
            if matched and int(matched.group(1)) == 0:
                print("  Round {}: FPC OK".format(r))
            else:
                print("  Round {}: FPC OK (errors=0) but unmatched pairings exist".format(r))
                all_ok = False
        else:
            print("  Round {}: FPC ISSUES".format(r))
            all_ok = False

    if all_ok:
        print("\nAll rounds pass FPC. Simulation complete.")
    else:
        print("\nWARNING: Some rounds have FPC issues.")


if __name__ == "__main__":
    main()
