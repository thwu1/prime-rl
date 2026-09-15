"""Write-ahead journal for filesystem transactions."""

from storage.filesystem import FileSystem
from crypto.hash import sha256


class Journal:
    """Transaction journal with integrity checksums."""

    def __init__(self, fs: FileSystem):
        self.fs = fs
        self.entries = []

    def log_operation(self, operation: str, filename: str, data: bytes = b"") -> int:
        """Log a filesystem operation and return the entry ID."""
        checksum = sha256(data)
        entry = {
            "op": operation,
            "file": filename,
            "checksum": checksum,
            "committed": False,
        }
        self.entries.append(entry)
        return len(self.entries) - 1

    def commit(self, entry_id: int) -> None:
        """Mark a journal entry as committed."""
        if entry_id < len(self.entries):
            self.entries[entry_id]["committed"] = True

    def get_uncommitted(self) -> list:
        """Return all uncommitted journal entries."""
        return [e for e in self.entries if not e["committed"]]
