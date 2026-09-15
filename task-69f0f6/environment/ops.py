
"""
Operations for the hitchhiker tree messaging layer.
"""

from dataclasses import dataclass, field
from typing import Any
import uuid


@dataclass(frozen=False)
class InsertOp:
    key: Any
    value: Any
    tag: str = field(default_factory=lambda: str(uuid.uuid4()))

    def affects_key(self):
        return self.key

    def apply_to_collection(self, coll: dict) -> dict:
        """Apply this insert to a dict-like collection."""
        result = dict(coll)
        result[self.key] = self.value
        return result

    def __repr__(self):
        return f"InsertOp(key={self.key!r}, value={self.value!r})"


@dataclass(frozen=False)
class DeleteOp:
    key: Any
    tag: str = field(default_factory=lambda: str(uuid.uuid4()))

    def affects_key(self):
        return self.key

    def apply_to_collection(self, coll: dict) -> dict:
        """Apply this delete to a dict-like collection."""
        result = dict(coll)
        result.pop(self.key, None)
        return result

    def __repr__(self):
        return f"DeleteOp(key={self.key!r})"


Op = InsertOp | DeleteOp
