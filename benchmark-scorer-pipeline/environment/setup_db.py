#!/usr/bin/env python3
"""Create benchmark.db SQLite database from JSON data files with analytical views."""

import json
import os
import sqlite3

DATA_DIR = "/tmp/benchdata"
DB_PATH = "/app/benchmark.db"


def main():
    os.makedirs("/app/output", exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE papers (
        paper_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        repo_first_commit TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE snippets (
        snippet_id TEXT PRIMARY KEY,
        paper_id TEXT NOT NULL REFERENCES papers(paper_id),
        lines_of_code INTEGER NOT NULL,
        function_name TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE models (
        model_id TEXT PRIMARY KEY,
        knowledge_cutoff TEXT NOT NULL,
        is_open INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE results (
        model_id TEXT NOT NULL REFERENCES models(model_id),
        snippet_id TEXT NOT NULL REFERENCES snippets(snippet_id),
        with_paper INTEGER NOT NULL,
        without_paper INTEGER NOT NULL,
        PRIMARY KEY (model_id, snippet_id)
    )""")

    # Analytical views for data exploration
    c.execute("""CREATE VIEW v_paper_complexity AS
        SELECT p.paper_id, p.title, p.repo_first_commit,
               COUNT(s.snippet_id) AS num_snippets,
               SUM(s.lines_of_code) AS total_loc,
               ROUND(AVG(s.lines_of_code), 1) AS avg_loc
        FROM papers p
        JOIN snippets s ON p.paper_id = s.paper_id
        GROUP BY p.paper_id
    """)

    c.execute("""CREATE VIEW v_model_paper_contamination AS
        SELECT m.model_id, p.paper_id, p.repo_first_commit, m.knowledge_cutoff,
               CASE
                   WHEN p.repo_first_commit > m.knowledge_cutoff THEN 'safe'
                   ELSE 'contaminated'
               END AS safety_status
        FROM models m
        CROSS JOIN papers p
    """)

    c.execute("""CREATE VIEW v_results_detail AS
        SELECT r.model_id, r.snippet_id, s.paper_id, s.lines_of_code,
               s.function_name, r.with_paper, r.without_paper,
               p.repo_first_commit, p.title AS paper_title
        FROM results r
        JOIN snippets s ON r.snippet_id = s.snippet_id
        JOIN papers p ON s.paper_id = p.paper_id
    """)

    with open(os.path.join(DATA_DIR, "papers.json")) as f:
        for p in json.load(f):
            c.execute("INSERT INTO papers VALUES (?, ?, ?)",
                      (p["paper_id"], p["title"], p["repo_first_commit"]))

    with open(os.path.join(DATA_DIR, "snippets.json")) as f:
        for s in json.load(f):
            c.execute("INSERT INTO snippets VALUES (?, ?, ?, ?)",
                      (s["snippet_id"], s["paper_id"], s["lines_of_code"],
                       s["function_name"]))

    with open(os.path.join(DATA_DIR, "models.json")) as f:
        models = json.load(f)
    for m in models:
        c.execute("INSERT INTO models VALUES (?, ?, ?)",
                  (m["model_id"], m["knowledge_cutoff"], 1 if m["is_open"] else 0))

    results_dir = os.path.join(DATA_DIR, "results")
    for m in models:
        mid = m["model_id"]
        with open(os.path.join(results_dir, f"{mid}.json")) as f:
            results = json.load(f)
        for sid, res in results.items():
            c.execute("INSERT INTO results VALUES (?, ?, ?, ?)",
                      (mid, sid, 1 if res["with_paper"] else 0,
                       1 if res["without_paper"] else 0))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
