"""Main BM25 reranking pipeline. Reads from SQLite, scores, evaluates."""

import os
import sys
import sqlite3
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tokenizer import tokenize_query
from index import InvertedIndex
from bm25 import BM25Scorer


def main():
    db_path = "/app/data/corpus.db"
    output_dir = "/app/pipeline/output"
    os.makedirs(output_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print("Building inverted index...")
    idx = InvertedIndex()
    idx.build_from_db(db_path)
    print(f"Index: N={idx.N}, unique_terms={len(idx.df)}, avg_dl={idx.avg_dl:.1f}")

    scorer = BM25Scorer(idx)

    c.execute("SELECT qid, text FROM queries ORDER BY qid")
    all_queries = c.fetchall()
    print(f"Scoring {len(all_queries)} queries...")

    run_path = os.path.join(output_dir, "pipeline_run.tsv")
    with open(run_path, "w") as f:
        for qid, q_text in all_queries:
            q_tokens = tokenize_query(q_text)

            c.execute("SELECT pid FROM candidates WHERE qid = ?", (qid,))
            candidate_pids = [row[0] for row in c.fetchall()]

            scored = []
            for pid in candidate_pids:
                c2 = conn.cursor()
                c2.execute("SELECT text FROM collection WHERE pid = ?", (pid,))
                p_text = c2.fetchone()[0]
                s = scorer.score(q_tokens, p_text, pid)
                scored.append((pid, s))

            scored.sort(key=lambda x: (-x[1], x[0]))

            for rank, (pid, score) in enumerate(scored):
                f.write(f"{qid}\t{pid}\t{rank}\n")

    conn.close()

    print("\nEvaluating with official MS MARCO script...")
    result = subprocess.run(
        ["python3", "/app/data/ms_marco_eval.py",
         "/app/data/qrels.tsv", run_path],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    print(f"Output: {run_path}")


if __name__ == "__main__":
    main()
