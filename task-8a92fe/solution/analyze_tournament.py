#!/usr/bin/env python3
"""
FIDE Dubov Swiss Tournament Analyzer.
Parses TRF16 files, computes per-player statistics per FIDE regulations,
generates next-round pairings via the CPPDubovSystem engine,
and writes results to /app/results.json.
"""

import json
import math
import os
import subprocess
import sys


def round_half_up(x):
    """Round to nearest integer, 0.5 rounds up (FIDE convention)."""
    return math.floor(x + 0.5)


def parse_trf(filepath):
    """Parse a TRF16 file and return tournament metadata and player data."""
    players = {}
    total_rounds = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if len(line) < 3:
                continue
            line_code = line[:3]
            if line_code in ("TNR", "XXR"):
                total_rounds = int(line[3:].strip())
            elif line_code == "001":
                player = parse_player_line(line)
                players[player["id"]] = player

    return {"total_rounds": total_rounds, "players": players}


def parse_player_line(line):
    """Parse a TRF16 player line (code 001) with fixed-width fields."""
    rank_str = line[4:8].strip()
    player_id = int(rank_str)
    name = line[14:47].strip()
    rating = int(line[48:52].strip())
    points = float(line[80:84].strip())

    rounds = []
    pos = 91
    round_num = 1
    while pos < len(line):
        if pos + 8 > len(line) + 1:
            break
        opp_str = line[pos:pos + 4].strip()
        color_char = line[pos + 5] if pos + 5 < len(line) else " "
        result_char = line[pos + 7] if pos + 7 < len(line) else " "

        opp_id = None
        if opp_str and opp_str != "0000":
            try:
                opp_id = int(opp_str)
            except ValueError:
                opp_id = None

        rounds.append({
            "round": round_num,
            "opponent_id": opp_id,
            "color": color_char.lower(),
            "result": result_char,
        })
        pos += 10
        round_num += 1

    return {
        "id": player_id,
        "name": name,
        "rating": rating,
        "points": points,
        "rounds": rounds,
    }


def is_otb_result(result_char):
    """Check if a result is over-the-board (not forfeit/bye)."""
    return result_char in ("1", "0", "=")


def result_value(result_char):
    """Convert result character to numeric value for tiebreak computation."""
    if result_char in ("1", "+"):
        return 1.0
    elif result_char == "=":
        return 0.5
    else:
        return 0.0


def compute_player_stats(player, all_players, total_rounds):
    """Compute ARO, color balance, due color, Buchholz Cut 1, and SB."""
    otb_opp_ratings = []
    otb_colors = []
    all_opp_scores = []
    sb_total = 0.0

    for rd in player["rounds"]:
        opp_id = rd["opponent_id"]
        result = rd["result"]
        color = rd["color"]

        if opp_id is not None and opp_id in all_players:
            opp_score = all_players[opp_id]["points"]
            all_opp_scores.append(opp_score)
            sb_total += opp_score * result_value(result)

            if is_otb_result(result):
                otb_opp_ratings.append(all_players[opp_id]["rating"])
                if color in ("w", "b"):
                    otb_colors.append(color)

    # ARO: mean of OTB opponent ratings only
    if len(otb_opp_ratings) > 0:
        aro = round_half_up(sum(otb_opp_ratings) / len(otb_opp_ratings))
    else:
        aro = 0

    # Color balance: whites minus blacks (OTB only)
    num_white = otb_colors.count("w")
    num_black = otb_colors.count("b")
    color_balance = num_white - num_black

    # Due color
    if num_white == 0 and num_black == 0:
        due_color = "none"
    elif color_balance < 0:
        due_color = "white"
    elif color_balance > 0:
        due_color = "black"
    else:
        last_color = otb_colors[-1] if otb_colors else None
        if last_color == "w":
            due_color = "black"
        elif last_color == "b":
            due_color = "white"
        else:
            due_color = "none"

    # Buchholz: sum of all opponents' scores
    buchholz = sum(all_opp_scores)
    # Buchholz Cut 1: Buchholz minus the lowest opponent score
    if all_opp_scores:
        buchholz_cut1 = buchholz - min(all_opp_scores)
    else:
        buchholz_cut1 = 0.0

    return {
        "aro": aro,
        "color_balance": color_balance,
        "due_color": due_color,
        "buchholz_cut1": buchholz_cut1,
        "sonneborn_berger": sb_total,
    }


def find_engine_binary():
    """Find the CPPDubovSystem binary."""
    candidates = [
        "/app/CPPDubovSystem/build/CPPDubovSystem",
        "/app/CPPDubovSystem/CPPDubovSystem",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    for root, dirs, files in os.walk("/app"):
        if "CPPDubovSystem" in files:
            candidate = os.path.join(root, "CPPDubovSystem")
            if os.access(candidate, os.X_OK):
                return candidate
    return None


def generate_pairings(engine_path, trf_path):
    """Run the engine to generate next-round pairings."""
    csv_output = "/app/pairings_output.csv"
    result = subprocess.run(
        [engine_path, "--pairings", trf_path, "--output", csv_output],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"Engine stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(
            f"Engine failed with code {result.returncode}: {result.stderr}"
        )

    pairings = []
    with open(csv_output, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("White"):
                continue
            parts = line.split(",")
            if len(parts) == 2:
                white_id = int(parts[0].strip())
                black_id = int(parts[1].strip())
                pairings.append({"white": white_id, "black": black_id})

    return pairings


def main():
    trf_path = "/app/tournament.trf"
    tournament = parse_trf(trf_path)
    all_players = tournament["players"]
    total_rounds = tournament["total_rounds"]

    # Determine completed rounds
    if all_players:
        first_player = next(iter(all_players.values()))
        completed_rounds = len(first_player["rounds"])
    else:
        completed_rounds = 0

    # Compute per-player statistics
    results_standings = {}
    for pid, player in all_players.items():
        stats = compute_player_stats(player, all_players, total_rounds)
        results_standings[str(pid)] = {
            "name": player["name"],
            "rating": player["rating"],
            "points": player["points"],
            "buchholz_cut1": stats["buchholz_cut1"],
            "sonneborn_berger": stats["sonneborn_berger"],
            "aro": stats["aro"],
            "color_balance": stats["color_balance"],
            "due_color": stats["due_color"],
        }

    # Compute standings order: points desc, BC1 desc, SB desc
    standings_order = sorted(
        results_standings.keys(),
        key=lambda pid: (
            results_standings[pid]["points"],
            results_standings[pid]["buchholz_cut1"],
            results_standings[pid]["sonneborn_berger"],
        ),
        reverse=True,
    )

    # Generate pairings via engine
    engine = find_engine_binary()
    if engine is None:
        raise RuntimeError("CPPDubovSystem binary not found")

    pairings = generate_pairings(engine, trf_path)

    # Write results
    output = {
        "standings": results_standings,
        "standings_order": standings_order,
        "tournament_params": {
            "total_rounds": total_rounds,
            "completed_rounds": completed_rounds,
        },
        "next_round_pairings": pairings,
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Results written to /app/results.json")
    print(f"Total players: {len(results_standings)}")
    print(f"Completed rounds: {completed_rounds}")
    print(f"Pairings generated: {len(pairings)}")


if __name__ == "__main__":
    main()
