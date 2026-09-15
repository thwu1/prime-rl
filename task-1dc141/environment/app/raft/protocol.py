"""
Protocol definitions for the Raft consensus implementation.

Defines message types, node states, and log entries used throughout
the Raft system.

"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List


class NodeState(Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


@dataclass
class LogEntry:
    """A single entry in the Raft log."""
    term: int
    command: Any  # e.g. {"op": "set", "key": "x", "value": "1"}


@dataclass
class RequestVote:
    """RequestVote RPC arguments (Section 5.2 of the Raft paper)."""
    term: int = 0
    candidate_id: int = 0
    last_log_index: int = 0
    last_log_term: int = 0


@dataclass
class RequestVoteResponse:
    """RequestVote RPC response."""
    term: int = 0
    vote_granted: bool = False


@dataclass
class AppendEntries:
    """AppendEntries RPC arguments (Section 5.3 of the Raft paper)."""
    term: int = 0
    leader_id: int = 0
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    leader_commit: int = 0


@dataclass
class AppendEntriesResponse:
    """AppendEntries RPC response."""
    term: int = 0
    success: bool = False
    match_index: int = 0  # Highest index verified by this RPC
