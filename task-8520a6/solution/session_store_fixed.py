
"""Fixed SQLite-backed session persistence for the editor engine."""

import sqlite3
from history import UndoTree


class SessionStore:
    """Manages editing sessions stored in a SQLite database."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def list_sessions(self):
        """Return all sessions as list of dicts with session_id and initial_text."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT session_id, initial_text FROM sessions ORDER BY session_id"
            ).fetchall()
            return [
                {"session_id": r["session_id"], "initial_text": r["initial_text"]}
                for r in rows
            ]
        finally:
            conn.close()

    def replay_session(self, session_id: str):
        """Replay all operations for a session, return the resulting UndoTree."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT initial_text FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown session: {session_id}")

            tree = UndoTree(row["initial_text"])

            ops = conn.execute(
                "SELECT op_type, offset, length, text, branch "
                "FROM operations WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ).fetchall()

            for op in ops:
                op_type = op["op_type"]
                if op_type == "insert":
                    tree.apply_insert(op["offset"], op["text"])
                elif op_type == "delete":
                    tree.apply_delete(op["offset"], op["length"])
                elif op_type == "undo":
                    tree.undo()
                elif op_type == "redo":
                    tree.redo(op["branch"] if op["branch"] is not None else 0)

            return tree
        finally:
            conn.close()

    def record_operation(self, session_id, seq, op_type,
                         offset=None, length=None, text=None, branch=0):
        """Insert an operation row into the operations table."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT INTO operations "
                "(session_id, seq, op_type, offset, length, text, branch) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, seq, op_type, offset, length, text, branch),
            )
            conn.commit()
        finally:
            conn.close()
