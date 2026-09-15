#!/usr/bin/env python3
"""Create the citation evaluation SQLite database.

Ground truth is stored externally in ground_truth_manifest.jsonl,
NOT in this database.
"""

import json
import sqlite3

DB_PATH = "/app/citation_eval.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Instance metadata
    c.execute("""
        CREATE TABLE instances (
            instance_id TEXT PRIMARY KEY,
            category TEXT NOT NULL CHECK(category IN ('cat1', 'cat2', 'cat3')),
            variant TEXT,
            perturbation_type TEXT,
            question_text TEXT NOT NULL
        )
    """)

    # Model responses
    c.execute("""
        CREATE TABLE model_responses (
            response_id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            model_name TEXT NOT NULL DEFAULT 'evaluated-model',
            response_text TEXT NOT NULL,
            response_timestamp TEXT,
            FOREIGN KEY (instance_id) REFERENCES instances(instance_id)
        )
    """)

    # Jurisdiction metadata
    c.execute("""
        CREATE TABLE instance_jurisdictions (
            instance_id TEXT PRIMARY KEY,
            primary_jurisdiction TEXT NOT NULL,
            reporter_systems TEXT,
            FOREIGN KEY (instance_id) REFERENCES instances(instance_id)
        )
    """)

    c.execute("CREATE INDEX idx_resp_instance ON model_responses(instance_id)")
    c.execute("CREATE INDEX idx_inst_category ON instances(category)")

    jurisdictions = {
        "C1_001": ("florida", "federal,southern"),
        "C1_002": ("south_carolina", "state,federal"),
        "C1_003": ("florida", "southern"),
        "C1_004": ("north_dakota", "neutral,northwestern"),
        "C1_005": ("montana", "state,federal,neutral"),
        "C1_006": ("new_jersey", "federal,state"),
        "C1_007": ("south_carolina", "state,pacific,washington,northeastern"),
        "C1_008": ("hawaii", "state,federal"),
        "C1_009": ("texas", "southwestern,federal"),
        "C1_010": ("multi", "atlantic,state,pacific,southern"),
        "C2_001": ("florida", "southern"),
        "C2_002": ("kansas", "state,federal"),
        "C2_003": ("arkansas", "southwestern,federal,neutral"),
        "C2_004": ("hawaii", "state"),
        "C2_005": ("south_carolina", "state"),
        "C2_006": ("north_dakota", "neutral"),
        "C2_007": ("florida", "southern"),
        "C2_008": ("texas", "southwestern"),
        "C2_009": ("south_carolina", "federal,state"),
        "C2_010": ("florida", "southern,state"),
        "C3_001": ("kentucky", "southwestern"),
        "C3_002": ("florida", "southern"),
        "C3_003": ("federal", "federal"),
        "C3_004": ("north_dakota", "northwestern"),
        "C3_005": ("missouri", "southwestern"),
        "C3_006": ("north_dakota", "northwestern"),
        "C3_007": ("new_hampshire", "state"),
        "C3_008": ("oregon", "state"),
        "C3_009": ("rhode_island", "atlantic"),
        "C3_010": ("idaho", "state"),
    }

    with open("/tmp/instances.jsonl") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            inst = json.loads(line)
            iid = inst["id"]
            cat = inst["category"]

            qa_style = inst.get("qa_style", "")
            variant = None
            perturb = None
            if qa_style == "3-true":
                variant = "true"
            elif qa_style == "3-fake":
                variant = "fake"
                perturb = inst.get("fake_type")

            c.execute(
                "INSERT INTO instances VALUES (?, ?, ?, ?, ?)",
                (iid, cat, variant, perturb, inst["question"])
            )

            if iid in jurisdictions:
                pj, rs = jurisdictions[iid]
                c.execute(
                    "INSERT INTO instance_jurisdictions VALUES (?, ?, ?)",
                    (iid, pj, rs)
                )

    with open("/tmp/responses.jsonl") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            resp = json.loads(line)
            c.execute(
                "INSERT INTO model_responses "
                "(instance_id, model_name, response_text, response_timestamp) "
                "VALUES (?, ?, ?, ?)",
                (resp["id"], "evaluated-model", resp["model_output"],
                 "2024-11-15T10:00:00Z")
            )

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
