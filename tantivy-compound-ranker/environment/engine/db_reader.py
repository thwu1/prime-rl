"""Database reader module for loading corpus from SQLite."""

import sqlite3


def read_corpus(db_path):
    """Read document corpus from SQLite database.

    Joins documents with their metadata records to ensure only properly
    catalogued documents are included in the search index.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT d.id, d.title, d.body
        FROM documents d
        INNER JOIN document_metadata m ON d.id = m.doc_id
        ORDER BY d.id
    """

    rows = conn.execute(query).fetchall()
    conn.close()

    return [{"id": row["id"], "title": row["title"], "body": row["body"]} for row in rows]
