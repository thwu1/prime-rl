"""
Data loader for the clinical evidence evaluation framework.

Reads gold annotation data from a SQLite database and submission
data from JSON files.
"""
import sqlite3
import json


def load_gold_from_db(db_path):
    """
    Load gold annotation data from SQLite database.

    Reads cases, note sentences, answer sentences with citations,
    and per-annotator relevance labels from the normalized schema.

    Args:
        db_path: path to the SQLite database file

    Returns:
        dict with "cases" key containing list of case dicts
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cases = []
    case_rows = conn.execute(
        "SELECT case_id FROM cases ORDER BY case_id"
    ).fetchall()

    for case_row in case_rows:
        case_id = case_row["case_id"]

        # Load note sentences
        note_sentences = [
            {"id": r["sentence_id"], "text": r["sentence_text"]}
            for r in conn.execute(
                "SELECT sentence_id, sentence_text FROM note_sentences "
                "WHERE case_id = ? ORDER BY sentence_id",
                (case_id,),
            )
        ]

        # Load answer sentences with citations
        answer_sentences = []
        ans_rows = conn.execute(
            "SELECT answer_id, answer_text FROM answer_sentences "
            "WHERE case_id = ? ORDER BY answer_id",
            (case_id,),
        ).fetchall()
        for ar in ans_rows:
            citations = [
                r["evidence_id"]
                for r in conn.execute(
                    "SELECT evidence_id FROM answer_citations "
                    "WHERE case_id = ? AND answer_id = ? ORDER BY evidence_id",
                    (case_id, ar["answer_id"]),
                )
            ]
            answer_sentences.append(
                {
                    "id": ar["answer_id"],
                    "text": ar["answer_text"],
                    "citations": citations,
                }
            )

        # Load annotator labels from database
        annotators = {}
        label_rows = conn.execute(
            "SELECT annotator_id, sentence_id, relevance "
            "FROM annotator_labels "
            "WHERE case_id = ? AND relevance IN ('essential', 'supplementary') "
            "ORDER BY annotator_id, sentence_id",
            (case_id,),
        ).fetchall()
        for lr in label_rows:
            ann_id = lr["annotator_id"]
            if ann_id not in annotators:
                annotators[ann_id] = []
            annotators[ann_id].append(
                {"sentence_id": lr["sentence_id"], "relevance": lr["relevance"]}
            )

        cases.append(
            {
                "case_id": case_id,
                "note_sentences": note_sentences,
                "answer_sentences": answer_sentences,
                "annotators": annotators,
            }
        )

    conn.close()
    return {"cases": cases}


def load_submission(filepath):
    """Load a JSON submission file."""
    with open(filepath) as f:
        return json.load(f)
