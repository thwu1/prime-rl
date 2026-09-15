"""Ranking and output generation for the benchmark leaderboard."""
import json
import os


def rank_and_output(leaderboard, details, output_path):
    """Sort leaderboard by performance and write output JSON."""
    # Sort by primary score
    leaderboard.sort(key=lambda x: (x["opt_at_2"], x["model"]))

    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    output = {
        "leaderboard": leaderboard,
        "details": details,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
