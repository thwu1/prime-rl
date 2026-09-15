#!/usr/bin/env python3
"""Compute per-category and overall scoring metrics from classifications."""

import sqlite3

DB_PATH = "/app/benchmark.db"


def compute_metrics():
    """Compute TPR, FPR per category and overall metrics per tool."""
    conn = sqlite3.connect(DB_PATH)

    conn.execute("DROP TABLE IF EXISTS category_metrics")
    conn.execute("""
        CREATE TABLE category_metrics (
            tool_name TEXT,
            category TEXT,
            tp INTEGER, fn INTEGER, fp INTEGER, tn INTEGER,
            tpr REAL, fpr REAL,
            PRIMARY KEY (tool_name, category)
        )
    """)

    conn.execute("DROP TABLE IF EXISTS overall_metrics")
    conn.execute("""
        CREATE TABLE overall_metrics (
            tool_name TEXT PRIMARY KEY,
            macro_tpr REAL,
            macro_fpr REAL,
            youdens_j REAL
        )
    """)

    tools = [row[0] for row in conn.execute("SELECT name FROM tools")]

    for tool_name in tools:
        categories = conn.execute("""
            SELECT category,
                   SUM(CASE WHEN classification = 'TP' THEN 1 ELSE 0 END) as tp,
                   SUM(CASE WHEN classification = 'FN' THEN 1 ELSE 0 END) as fn,
                   SUM(CASE WHEN classification = 'FP' THEN 1 ELSE 0 END) as fp,
                   SUM(CASE WHEN classification = 'TN' THEN 1 ELSE 0 END) as tn
            FROM classifications
            WHERE tool_name = ?
            GROUP BY category
        """, (tool_name,)).fetchall()

        total_tp = total_fn = total_fp = total_tn = 0

        for cat_name, tp, fn, fp, tn in categories:
            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

            conn.execute(
                "INSERT INTO category_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tool_name, cat_name, tp, fn, fp, tn, tpr, fpr)
            )

            total_tp += tp
            total_fn += fn
            total_fp += fp
            total_tn += tn

        # Compute overall metrics from aggregate counts
        overall_tpr = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        overall_fpr = total_fp / (total_fp + total_tn) if (total_fp + total_tn) > 0 else 0.0
        youdens_j = overall_tpr - overall_fpr

        conn.execute(
            "INSERT INTO overall_metrics VALUES (?, ?, ?, ?)",
            (tool_name, overall_tpr, overall_fpr, youdens_j)
        )

    conn.commit()
    conn.close()
    print("Metrics computed")


if __name__ == "__main__":
    compute_metrics()
