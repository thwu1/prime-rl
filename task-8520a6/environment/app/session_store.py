
"""Session persistence for the editor engine."""


class SessionStore:
    """Manages editing sessions stored in a SQLite database."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def list_sessions(self):
        """Return all sessions."""
        raise NotImplementedError

    def replay_session(self, session_id: str):
        """Replay operations for a session and return the resulting UndoTree."""
        raise NotImplementedError

    def record_operation(self, session_id, seq, op_type,
                         offset=None, length=None, text=None, branch=0):
        """Record an editing operation."""
        raise NotImplementedError
