#!/usr/bin/env python3
"""Create the SQLite annotation database from the JSON gold annotations."""
import sqlite3
import json

with open("/app/data/gold_annotations.json") as f:
    data = json.load(f)

conn = sqlite3.connect("/app/data/annotations.db")
c = conn.cursor()

c.execute("CREATE TABLE cases (case_id TEXT PRIMARY KEY)")
c.execute("""CREATE TABLE note_sentences (
    case_id TEXT, sentence_id TEXT, sentence_text TEXT,
    PRIMARY KEY (case_id, sentence_id),
    FOREIGN KEY (case_id) REFERENCES cases(case_id))""")
c.execute("""CREATE TABLE answer_sentences (
    case_id TEXT, answer_id TEXT, answer_text TEXT,
    PRIMARY KEY (case_id, answer_id),
    FOREIGN KEY (case_id) REFERENCES cases(case_id))""")
c.execute("""CREATE TABLE answer_citations (
    case_id TEXT, answer_id TEXT, evidence_id TEXT,
    PRIMARY KEY (case_id, answer_id, evidence_id))""")
c.execute("""CREATE TABLE annotator_labels (
    case_id TEXT, annotator_id TEXT, sentence_id TEXT, relevance TEXT,
    PRIMARY KEY (case_id, annotator_id, sentence_id))""")

for case in data["cases"]:
    cid = case["case_id"]
    c.execute("INSERT INTO cases VALUES (?)", (cid,))
    for s in case["note_sentences"]:
        c.execute("INSERT INTO note_sentences VALUES (?,?,?)",
                  (cid, s["id"], s["text"]))
    for a in case["answer_sentences"]:
        c.execute("INSERT INTO answer_sentences VALUES (?,?,?)",
                  (cid, a["id"], a["text"]))
        for ci in a["citations"]:
            c.execute("INSERT INTO answer_citations VALUES (?,?,?)",
                      (cid, a["id"], ci))
    for ann_id, labels in case["annotators"].items():
        for l in labels:
            c.execute("INSERT INTO annotator_labels VALUES (?,?,?,?)",
                      (cid, ann_id, l["sentence_id"], l["relevance"]))

conn.commit()
conn.close()
print("Database created at /app/data/annotations.db")
