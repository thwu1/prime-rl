#!/usr/bin/env python3
"""Export scored results from SQLite to the final scorecard JSON."""

import json
import os
import sqlite3

DB_PATH = "/app/benchmark.db"


def export_scorecard():
    """Read metrics from the database and produce scorecard.json."""
    conn = sqlite3.connect(DB_PATH)

    tools_output = []
    tools = conn.execute("SELECT name, commercial FROM tools").fetchall()

    for tool_name, commercial in tools:
        categories = {}
        for row in conn.execute(
            "SELECT category, tp, fn, fp, tn, tpr, fpr "
            "FROM category_metrics WHERE tool_name = ? ORDER BY category",
            (tool_name,)
        ):
            cat_name, tp, fn, fp, tn, tpr, fpr = row
            categories[cat_name] = {
                "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                "tpr": tpr, "fpr": fpr,
            }

        overall = conn.execute(
            "SELECT macro_tpr, macro_fpr, youdens_j "
            "FROM overall_metrics WHERE tool_name = ?",
            (tool_name,)
        ).fetchone()

        tools_output.append({
            "name": tool_name,
            "commercial": bool(commercial),
            "categories": categories,
            "overall": {
                "macro_tpr": overall[0],
                "macro_fpr": overall[1],
                "youdens_j": overall[2],
            }
        })

    # Rank tools by Youden's J
    ranked = sorted(tools_output, key=lambda t: t["overall"]["youdens_j"])
    ranking = [
        {"rank": i + 1, "name": t["name"], "youdens_j": t["overall"]["youdens_j"]}
        for i, t in enumerate(ranked)
    ]

    os.makedirs("/app/output", exist_ok=True)
    output = {"tools": tools_output, "ranking": ranking}
    with open("/app/output/scorecard.json", "w") as f:
        json.dump(output, f, indent=2)

    conn.close()
    print("Scorecard exported to /app/output/scorecard.json")


if __name__ == "__main__":
    export_scorecard()
