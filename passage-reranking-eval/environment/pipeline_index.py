"""Inverted index for document frequency and length statistics."""

import sqlite3
from collections import Counter
from tokenizer import tokenize_doc


class InvertedIndex:
    def __init__(self):
        self.df = Counter()
        self.N = 0
        self.doc_lens = {}
        self.avg_dl = 0.0

    def build_from_db(self, db_path):
        """Build inverted index from the corpus database."""
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Get total number of documents in collection
        c.execute("SELECT COUNT(*) FROM collection")
        self.N = c.fetchone()[0]

        # Index passages that appear in candidate sets
        c.execute("""
            SELECT cand.pid, col.text
            FROM candidates cand
            JOIN collection col ON cand.pid = col.pid
        """)

        total_len = 0
        processed = 0
        for pid, text in c.fetchall():
            tokens = tokenize_doc(text)
            self.doc_lens[pid] = len(tokens)
            total_len += len(tokens)
            processed += 1
            for term in set(tokens):
                self.df[term] += 1

        self.avg_dl = total_len / processed if processed > 0 else 1.0
        conn.close()
