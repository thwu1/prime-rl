#!/usr/bin/env python3
"""Create the evaluation SQLite database."""
import sqlite3
import json
import os

DB_PATH = "/app/data/benchmark.db"

RETRIEVAL_RECORDS = [
    {
        "id": "r_001", "model": "gpt4o_mini", "category": "cat1", "jurisdiction": "scotus",
        "model_output": "Based on my analysis, the key precedents are Strickland v. Washington, 466 U.S. 668 (1984), and Teague v. Lane, 489 U.S. 288 (1989).",
        "ground_truth": ["466 U.S. 668", "489 U.S. 288", "378 U.S. 478"]
    },
    {
        "id": "r_002", "model": "gpt4o_mini", "category": "cat1", "jurisdiction": "state_supreme",
        "model_output": "Relevant authorities include 205 A.3d 445 and 162 Idaho 763.",
        "ground_truth": ["205 A.3d 445", "162 Idaho 763"]
    },
    {
        "id": "r_003", "model": "gpt4o_mini", "category": "cat1", "jurisdiction": "state_appellate",
        "model_output": "The court relied on 36 So.3d 84 and 130 So.3d 1277 as controlling authority.",
        "ground_truth": ["36 So.3d 84", "84 So.3d 1032", "79 So.3d 745", "130 So.3d 1277"]
    },
    {
        "id": "r_004", "model": "gpt4o_mini", "category": "cat2", "jurisdiction": "state_appellate",
        "model_output": "Additional citations include 56 S.W.3d 842 and 524 U.S. 666.",
        "ground_truth": ["56 S.W.3d 842", "372 S.W.3d 177", "524 U.S. 666"]
    },
    {
        "id": "r_005", "model": "gpt4o_mini", "category": "cat2", "jurisdiction": "state_supreme",
        "model_output": "Refer to 276 P.3d 808 and 813 P.2d 1384 for the applicable standard.",
        "ground_truth": ["127 Hawai'i 126", "813 P.2d 1384"]
    },
    {
        "id": "r_006", "model": "deepseek_v3", "category": "cat1", "jurisdiction": "scotus",
        "model_output": "See 104 S. Ct. 2052; 500 U.S. 44; 401 U.S. 560.",
        "ground_truth": ["466 U.S. 668", "489 U.S. 288", "378 U.S. 478"]
    },
    {
        "id": "r_007", "model": "deepseek_v3", "category": "cat1", "jurisdiction": "state_supreme",
        "model_output": "Consider 205 A.3d 440 and 350 S.C. 138 for guidance.",
        "ground_truth": ["205 A.3d 445", "162 Idaho 763"]
    },
    {
        "id": "r_008", "model": "deepseek_v3", "category": "cat1", "jurisdiction": "state_appellate",
        "model_output": "Key cases include 36 So.3d 84; 79 So.3d 700; 150 So.3d 908.",
        "ground_truth": ["36 So.3d 84", "84 So.3d 1032", "79 So.3d 745", "130 So.3d 1277"]
    },
    {
        "id": "r_009", "model": "deepseek_v3", "category": "cat2", "jurisdiction": "state_appellate",
        "model_output": "You should also cite 56 S.W.3d 842; 372 S.W.3d 177; 300 S.W.2d 150.",
        "ground_truth": ["56 S.W.3d 842", "372 S.W.3d 177", "524 U.S. 666"]
    },
    {
        "id": "r_010", "model": "deepseek_v3", "category": "cat2", "jurisdiction": "state_supreme",
        "model_output": "The relevant case is 127 Hawai'i 120.",
        "ground_truth": ["127 Hawai'i 126", "813 P.2d 1384"]
    },
    {
        "id": "r_011", "model": "llama_70b", "category": "cat1", "jurisdiction": "scotus",
        "model_output": "I'm not able to provide specific case citations without access to verified legal databases.",
        "ground_truth": ["466 U.S. 668", "489 U.S. 288", "378 U.S. 478"]
    },
    {
        "id": "r_012", "model": "llama_70b", "category": "cat1", "jurisdiction": "state_supreme",
        "model_output": "I cannot confirm these citations without access to legal databases.",
        "ground_truth": ["205 A.3d 445", "162 Idaho 763"]
    },
    {
        "id": "r_013", "model": "llama_70b", "category": "cat1", "jurisdiction": "state_appellate",
        "model_output": "Without verified access, I cannot list specific Florida case authorities.",
        "ground_truth": ["36 So.3d 84", "84 So.3d 1032", "79 So.3d 745", "130 So.3d 1277"]
    },
    {
        "id": "r_014", "model": "llama_70b", "category": "cat2", "jurisdiction": "state_appellate",
        "model_output": "Unable to verify Texas case citations without a legal database.",
        "ground_truth": ["56 S.W.3d 842", "372 S.W.3d 177", "524 U.S. 666"]
    },
    {
        "id": "r_015", "model": "llama_70b", "category": "cat2", "jurisdiction": "state_supreme",
        "model_output": "I do not have access to verified case law for this jurisdiction.",
        "ground_truth": ["127 Hawai'i 126", "813 P.2d 1384"]
    },
]

PARALLEL_CITATIONS = [
    ("466 U.S. 668", "104 S. Ct. 2052"),
    ("489 U.S. 288", "109 S. Ct. 1060"),
    ("378 U.S. 478", "84 S. Ct. 1758"),
    ("524 U.S. 666", "118 S. Ct. 2091"),
    ("127 Hawai'i 126", "276 P.3d 808"),
    ("162 Idaho 763", "367 P.3d 1243"),
]


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE model_responses (
            id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            category TEXT NOT NULL,
            jurisdiction TEXT NOT NULL,
            model_output TEXT NOT NULL,
            reference_citations TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX idx_resp_model ON model_responses(model)")
    c.execute("CREATE INDEX idx_resp_category ON model_responses(category)")
    c.execute("CREATE INDEX idx_resp_jurisdiction ON model_responses(jurisdiction)")

    c.execute("""
        CREATE TABLE parallel_citations (
            citation_a TEXT NOT NULL,
            citation_b TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX idx_parallel_a ON parallel_citations(citation_a)")
    c.execute("CREATE INDEX idx_parallel_b ON parallel_citations(citation_b)")

    for rec in RETRIEVAL_RECORDS:
        c.execute(
            "INSERT INTO model_responses VALUES (?, ?, ?, ?, ?, ?)",
            (rec["id"], rec["model"], rec["category"], rec["jurisdiction"],
             rec["model_output"], json.dumps(rec["ground_truth"]))
        )

    for cit_a, cit_b in PARALLEL_CITATIONS:
        c.execute(
            "INSERT INTO parallel_citations VALUES (?, ?)",
            (cit_a, cit_b)
        )

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
