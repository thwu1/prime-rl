#!/usr/bin/env python3
"""FightingICE Tournament Replay Analyzer.

Parses binary protobuf replay files, computes match analytics (including
combo detection with damage proration), tournament rankings, and Elo ratings.
Outputs results.json.
"""

import json
import os
import sys
import glob

sys.path.insert(0, '/app/proto')
import game_pb2


def parse_replay(filepath):
    """Parse a single binary replay file into a MatchReplay object."""
    replay = game_pb2.MatchReplay()
    with open(filepath, 'rb') as f:
        replay.ParseFromString(f.read())
    return replay


def determine_winner(p1_hp, p2_hp, p1_name, p2_name):
    """Determine round winner based on remaining HP."""
    if p1_hp > p2_hp:
        return p1_name
    elif p2_hp > p1_hp:
        return p2_name
    else:
        return "draw"


def detect_combos(frames, player_side):
    """Detect combo sequences for a given player (1 or 2) across all frames.

    Returns list of combos, where each combo is a list of raw damage values.
    A combo requires 2+ consecutive hits where the receiver is in stun.
    """
    rounds = {}
    for frame in frames:
        rounds.setdefault(frame.round_number, []).append(frame)

    all_combos = []
    for rnd_num in sorted(rounds.keys()):
        rnd_frames = sorted(rounds[rnd_num], key=lambda f: f.frame_number)
        current_combo = []

        for frame in rnd_frames:
            if player_side == 1:
                attacker = frame.p1
                receiver = frame.p2
            else:
                attacker = frame.p2
                receiver = frame.p1

            if attacker.attack_landed and attacker.damage_dealt > 0:
                if receiver.stun_remaining > 0:
                    # Combo continuation
                    current_combo.append(attacker.damage_dealt)
                else:
                    # New hit outside stun - save previous combo if valid
                    if len(current_combo) >= 2:
                        all_combos.append(list(current_combo))
                    current_combo = [attacker.damage_dealt]

        # Save last combo of this round
        if len(current_combo) >= 2:
            all_combos.append(list(current_combo))

    return all_combos


def compute_combo_stats(combos, scaling_factor):
    """Compute max combo length, raw damage, and scaled damage from combo list."""
    if not combos:
        return 0, 0, 0.0

    max_length = max(len(c) for c in combos)
    max_raw = max(sum(c) for c in combos)
    max_scaled = max(
        sum(d * scaling_factor ** i for i, d in enumerate(c))
        for c in combos
    )
    return max_length, max_raw, max_scaled


def analyze_match(replay, combo_scaling):
    """Compute analytics for a single match."""
    result = {
        "match_id": replay.match_id,
        "p1_name": replay.p1_name,
        "p2_name": replay.p2_name,
        "rounds": [],
        "p1_total_damage": 0,
        "p2_total_damage": 0,
        "p1_total_hits": 0,
        "p2_total_hits": 0,
        "p1_max_combo_length": 0,
        "p2_max_combo_length": 0,
        "p1_max_combo_raw_damage": 0,
        "p2_max_combo_raw_damage": 0,
        "p1_max_combo_scaled_damage": 0.0,
        "p2_max_combo_scaled_damage": 0.0,
    }

    # Round results
    for rr in replay.round_results:
        winner = determine_winner(rr.p1_remaining_hp, rr.p2_remaining_hp,
                                  replay.p1_name, replay.p2_name)
        result["rounds"].append({
            "round": rr.round_number,
            "p1_hp": rr.p1_remaining_hp,
            "p2_hp": rr.p2_remaining_hp,
            "frames": rr.elapsed_frames,
            "winner": winner,
        })

    # Frame-level damage and hit totals
    for frame in replay.frames:
        if frame.p1.attack_landed:
            result["p1_total_damage"] += frame.p1.damage_dealt
            result["p1_total_hits"] += 1
        if frame.p2.attack_landed:
            result["p2_total_damage"] += frame.p2.damage_dealt
            result["p2_total_hits"] += 1

    # Combo detection with proration
    p1_combos = detect_combos(replay.frames, 1)
    p2_combos = detect_combos(replay.frames, 2)

    l, r, s = compute_combo_stats(p1_combos, combo_scaling)
    result["p1_max_combo_length"] = l
    result["p1_max_combo_raw_damage"] = r
    result["p1_max_combo_scaled_damage"] = round(s, 6)

    l, r, s = compute_combo_stats(p2_combos, combo_scaling)
    result["p2_max_combo_length"] = l
    result["p2_max_combo_raw_damage"] = r
    result["p2_max_combo_scaled_damage"] = round(s, 6)

    return result


def compute_standard_rankings(match_results, config):
    """Compute Standard league rankings from round-robin results."""
    competitors = config["standard_league"]["competitors"]
    prefix = config["standard_league"]["match_prefix"]

    stats = {ai: {"round_wins": 0, "total_hp": 0} for ai in competitors}

    for m in match_results:
        if not m["match_id"].startswith(prefix):
            continue
        for rnd in m["rounds"]:
            winner = rnd["winner"]
            if m["p1_name"] in stats:
                stats[m["p1_name"]]["total_hp"] += rnd["p1_hp"]
                if winner == m["p1_name"]:
                    stats[m["p1_name"]]["round_wins"] += 1
            if m["p2_name"] in stats:
                stats[m["p2_name"]]["total_hp"] += rnd["p2_hp"]
                if winner == m["p2_name"]:
                    stats[m["p2_name"]]["round_wins"] += 1

    ranked = sorted(stats.items(),
                    key=lambda x: (x[1]["round_wins"], x[1]["total_hp"]),
                    reverse=True)

    f1_points = config["f1_scoring"]["points"]
    rankings = []
    for i, (ai, s) in enumerate(ranked):
        pts = f1_points[i] if i < len(f1_points) else 0
        rankings.append({
            "rank": i + 1,
            "ai": ai,
            "round_wins": s["round_wins"],
            "total_remaining_hp": s["total_hp"],
            "f1_points": pts,
        })

    return rankings


def compute_speedrunning_rankings(match_results, config):
    """Compute Speedrunning league rankings."""
    competitors = config["speedrunning_league"]["competitors"]
    baseline = config["speedrunning_league"]["baseline_ai"]
    prefix = config["speedrunning_league"]["match_prefix"]
    penalty = config["speedrunning_league"]["penalty_frames"]

    round_frames = {ai: [] for ai in competitors}

    for m in match_results:
        if not m["match_id"].startswith(prefix):
            continue

        if m["p1_name"] in competitors and m["p2_name"] == baseline:
            competitor = m["p1_name"]
        elif m["p2_name"] in competitors and m["p1_name"] == baseline:
            competitor = m["p2_name"]
        else:
            continue

        for rnd in m["rounds"]:
            if rnd["winner"] == competitor:
                round_frames[competitor].append(rnd["frames"])
            else:
                round_frames[competitor].append(penalty)

    averages = {}
    for ai, frames_list in round_frames.items():
        if frames_list:
            averages[ai] = sum(frames_list) / len(frames_list)
        else:
            averages[ai] = float(penalty)

    ranked = sorted(averages.items(), key=lambda x: x[1])

    f1_points = config["f1_scoring"]["points"]
    rankings = []
    for i, (ai, avg) in enumerate(ranked):
        pts = f1_points[i] if i < len(f1_points) else 0
        rankings.append({
            "rank": i + 1,
            "ai": ai,
            "avg_frames": round(avg, 6),
            "f1_points": pts,
        })

    return rankings


def compute_elo_ratings(match_results, config):
    """Compute Elo ratings from standard league round-by-round results.

    Process matches in lexicographic match_id order, rounds sequentially.
    K=32, starting rating 1500.
    """
    competitors = config["standard_league"]["competitors"]
    prefix = config["standard_league"]["match_prefix"]
    K = 32

    ratings = {ai: 1500.0 for ai in competitors}

    std_matches = sorted(
        [m for m in match_results if m["match_id"].startswith(prefix)],
        key=lambda m: m["match_id"]
    )

    for m in std_matches:
        p1 = m["p1_name"]
        p2 = m["p2_name"]
        for rnd in m["rounds"]:
            r1 = ratings[p1]
            r2 = ratings[p2]
            e1 = 1.0 / (1.0 + 10.0 ** ((r2 - r1) / 400.0))
            e2 = 1.0 - e1

            winner = rnd["winner"]
            if winner == p1:
                s1, s2 = 1.0, 0.0
            elif winner == p2:
                s1, s2 = 0.0, 1.0
            else:
                s1, s2 = 0.5, 0.5

            ratings[p1] = r1 + K * (s1 - e1)
            ratings[p2] = r2 + K * (s2 - e2)

    return {ai: round(r, 1) for ai, r in ratings.items()}


def compute_final_rankings(standard_rankings, speedrunning_rankings, elo_ratings):
    """Combine F1 points from both leagues with Elo-based bonus."""
    std_pts = {r["ai"]: r["f1_points"] for r in standard_rankings}
    spd_pts = {r["ai"]: r["f1_points"] for r in speedrunning_rankings}

    # Elo bonus: +2 for highest rated, +1 for second highest
    elo_sorted = sorted(elo_ratings.items(), key=lambda x: x[1], reverse=True)
    elo_bonus = {}
    for i, (ai, _) in enumerate(elo_sorted):
        if i == 0:
            elo_bonus[ai] = 2
        elif i == 1:
            elo_bonus[ai] = 1
        else:
            elo_bonus[ai] = 0

    all_ais = set(std_pts.keys()) | set(spd_pts.keys())
    results = []
    for ai in all_ais:
        sf = std_pts.get(ai, 0)
        spf = spd_pts.get(ai, 0)
        eb = elo_bonus.get(ai, 0)
        total = sf + spf + eb
        results.append({
            "ai": ai,
            "std_f1": sf,
            "spd_f1": spf,
            "elo_bonus": eb,
            "total_points": total,
            "elo": elo_ratings.get(ai, 1500.0),
        })

    # Sort by total_points descending, tiebreak by Elo descending
    results.sort(key=lambda x: (x["total_points"], x["elo"]), reverse=True)

    rankings = []
    for i, r in enumerate(results):
        rankings.append({
            "rank": i + 1,
            "ai": r["ai"],
            "std_f1": r["std_f1"],
            "spd_f1": r["spd_f1"],
            "elo_bonus": r["elo_bonus"],
            "total_points": r["total_points"],
        })

    return rankings


def main():
    with open('/app/tournament.json') as f:
        config = json.load(f)

    combo_scaling = config.get("combo_scaling_factor", 1.0)

    replay_files = sorted(glob.glob('/app/replays/*.bin'))
    if not replay_files:
        print("ERROR: No replay files found in /app/replays/")
        sys.exit(1)

    match_results = []
    for filepath in replay_files:
        replay = parse_replay(filepath)
        analysis = analyze_match(replay, combo_scaling)
        match_results.append(analysis)

    match_results.sort(key=lambda m: m["match_id"])

    std_rankings = compute_standard_rankings(match_results, config)
    spd_rankings = compute_speedrunning_rankings(match_results, config)
    elo_ratings = compute_elo_ratings(match_results, config)
    final_rankings = compute_final_rankings(std_rankings, spd_rankings, elo_ratings)

    output = {
        "matches": match_results,
        "standard_league": {"rankings": std_rankings},
        "speedrunning_league": {"rankings": spd_rankings},
        "elo_ratings": elo_ratings,
        "final_rankings": final_rankings,
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Analysis complete. Processed {len(match_results)} matches.")
    print(f"Results written to /app/output/results.json")


if __name__ == '__main__':
    main()
