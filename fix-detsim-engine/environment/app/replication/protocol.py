"""Primary-backup log replication protocol.

A simplified protocol inspired by Raft's log-replication mechanism,
designed to run on the deterministic simulation engine.

Protocol overview
-----------------
* A cluster has *N* nodes; one is the **primary** (leader), the rest are
  **followers**.
* The primary assigns a monotonically-increasing **term** each time it
  takes over leadership.
* Client writes go to the primary, which appends to its local log and
  replicates via *AppendEntries* messages.
* An entry is **committed** once acknowledged by a majority (⌊N/2⌋+1).
* On primary failure the test harness externally promotes a follower
  (leader election is not part of this protocol).
* The new primary sends a **SyncLog** to each follower.  The follower
  finds where its log diverges from the leader's, truncates the
  divergent tail, and adopts the leader's entries from the divergence
  point onward.

Invariant
~~~~~~~~~
Once an entry is committed, it must appear on every node after any
sequence of partitions, leader changes, and sync rounds.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Set


# ── data model ──────────────────────────────────────────────────────────────

@dataclass
class Entry:
    """A single log entry."""
    term: int
    index: int
    key: str
    value: str

    def matches(self, other: "Entry") -> bool:
        """True if both entries belong to the same term *and* index."""
        return self.term == other.term and self.index == other.index

    def to_dict(self) -> dict:
        return {"term": self.term, "index": self.index,
                "key": self.key, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict) -> "Entry":
        return cls(term=d["term"], index=d["index"],
                   key=d["key"], value=d["value"])

    def __repr__(self) -> str:
        return f"E(t{self.term},i{self.index},{self.key}={self.value})"


# ── replica node ────────────────────────────────────────────────────────────

class Replica:
    """A single replica participating in log replication."""

    def __init__(self, nid: int, peers: list, network, engine):
        self.nid = nid
        self.peers = [p for p in peers if p != nid]
        self._net = network
        self._eng = engine

        # ── persistent state ──
        self.term: int = 0
        self.log: List[Entry] = []
        self.commit_idx: int = -1          # highest committed log index

        # ── role ──
        self.role: str = "follower"        # "primary" | "follower"

        # ── primary bookkeeping ──
        self._acks: Dict[int, Set[int]] = {}   # idx → set of acking nids

        # ── materialised committed state ──
        self.store: Dict[str, str] = {}

        self._net.register(nid, self._on_msg)

    # ── public interface ────────────────────────────────────────────────────

    def become_primary(self) -> None:
        """Promote this node to primary at a new term."""
        self.term += 1
        self.role = "primary"
        self._acks.clear()

    def write(self, key: str, value: str) -> Optional[int]:
        """Append a write to the log (primary only).  Returns the index."""
        if self.role != "primary":
            return None
        e = Entry(term=self.term, index=len(self.log), key=key, value=value)
        self.log.append(e)
        self._acks[e.index] = {self.nid}   # self-ack
        self._replicate(e)
        return e.index

    def initiate_sync(self) -> None:
        """Send a SyncLog to every peer (call after becoming primary)."""
        log_dicts = [e.to_dict() for e in self.log]
        for p in self.peers:
            self._net.send(self.nid, p, {
                "type": "sync",
                "term": self.term,
                "leader": self.nid,
                "log": log_dicts,
                "commit_idx": self.commit_idx,
            }, tag=f"sync:{self.nid}->{p}")

    def read(self, key: str) -> Optional[str]:
        """Read the committed value for *key*."""
        return self.store.get(key)

    # ── internal: message dispatch ──────────────────────────────────────────

    def _on_msg(self, src: int, dst: int, payload: dict) -> None:
        mtype = payload.get("type")
        if mtype == "append":
            self._on_append(src, payload)
        elif mtype == "append_ack":
            self._on_append_ack(src, payload)
        elif mtype == "sync":
            self._on_sync(src, payload)
        elif mtype == "sync_ack":
            self._on_sync_ack(src, payload)
        elif mtype == "commit_notify":
            self._on_commit_notify(src, payload)

    # ── internal: replication (primary → followers) ─────────────────────────

    def _replicate(self, entry: Entry) -> None:
        prev_idx = entry.index - 1
        prev_term = self.log[prev_idx].term if prev_idx >= 0 else -1
        for p in self.peers:
            self._net.send(self.nid, p, {
                "type": "append",
                "term": self.term,
                "leader": self.nid,
                "entry": entry.to_dict(),
                "prev_idx": prev_idx,
                "prev_term": prev_term,
                "commit_idx": self.commit_idx,
            }, tag=f"append:{self.nid}->{p}:i{entry.index}")

    def _on_append(self, src: int, payload: dict) -> None:
        """Follower: receive AppendEntries from the primary."""
        if payload["term"] < self.term:
            return                               # stale
        self.term = payload["term"]
        self.role = "follower"

        prev_idx = payload["prev_idx"]
        prev_term = payload["prev_term"]

        # consistency check
        if prev_idx >= 0:
            if prev_idx >= len(self.log) or self.log[prev_idx].term != prev_term:
                self._net.send(self.nid, src, {
                    "type": "append_ack",
                    "term": self.term,
                    "success": False,
                    "match_idx": -1,
                }, tag=f"nack:{self.nid}->{src}")
                return

        entry = Entry.from_dict(payload["entry"])
        if entry.index < len(self.log):
            if self.log[entry.index].term != entry.term:
                # conflict – truncate from this index onward
                self.log = self.log[:entry.index]
                self.log.append(entry)
            # else: already have this entry
        elif entry.index == len(self.log):
            self.log.append(entry)
        # else: gap – silently ignore

        # advance commit
        lc = payload["commit_idx"]
        if lc > self.commit_idx and lc < len(self.log):
            self.commit_idx = lc
            self._apply()

        self._net.send(self.nid, src, {
            "type": "append_ack",
            "term": self.term,
            "success": True,
            "match_idx": entry.index,
        }, tag=f"ack:{self.nid}->{src}:i{entry.index}")

    def _on_append_ack(self, src: int, payload: dict) -> None:
        """Primary: receive acknowledgement from a follower."""
        if self.role != "primary":
            return
        if payload["term"] > self.term:
            self.term = payload["term"]
            self.role = "follower"
            return
        if not payload["success"]:
            return

        midx = payload["match_idx"]
        if midx in self._acks:
            self._acks[midx].add(src)
            majority = (len(self.peers) + 1) // 2 + 1
            if len(self._acks[midx]) >= majority and midx > self.commit_idx:
                self.commit_idx = midx
                self._apply()
                self._broadcast_commit()

    def _broadcast_commit(self) -> None:
        for p in self.peers:
            self._net.send(self.nid, p, {
                "type": "commit_notify",
                "term": self.term,
                "commit_idx": self.commit_idx,
            }, tag=f"commit:{self.nid}->{p}")

    def _on_commit_notify(self, src: int, payload: dict) -> None:
        if payload["term"] < self.term:
            return
        ci = payload["commit_idx"]
        if ci > self.commit_idx and ci < len(self.log):
            self.commit_idx = ci
            self._apply()

    # ── internal: sync (new primary → followers after election) ─────────────

    def _on_sync(self, src: int, payload: dict) -> None:
        """Follower: adopt the new primary's log.

        Determines where our log diverges from the leader's, truncates the
        divergent tail, and adopts the leader's entries from the divergence
        point forward.
        """
        if payload["term"] < self.term:
            return
        self.term = payload["term"]
        self.role = "follower"

        leader_log = [Entry.from_dict(d) for d in payload["log"]]

        # Walk forward through both logs to find the divergence point.
        # After the loop, all entries at indices 0 .. diverge-1 are guaranteed
        # to match between our log and the leader's log.
        diverge = 0
        for i in range(min(len(self.log), len(leader_log))):
            if self.log[i].matches(leader_log[i]):
                diverge = i + 1
            else:
                break

        # Truncate entries that diverge from the leader.
        # Keep the confirmed-matching prefix (entries 0 through diverge-1).
        if diverge < len(self.log):
            self.log = self.log[:max(0, diverge - 1)]

        # Adopt the leader's entries starting from the divergence point.
        for entry_d in payload["log"][diverge:]:
            e = Entry.from_dict(entry_d)
            e.index = len(self.log)
            self.log.append(e)

        # Update commit index from the leader.
        lc = payload["commit_idx"]
        if lc >= 0 and self.log:
            self.commit_idx = min(lc, len(self.log) - 1)
        self._apply()

        self._net.send(self.nid, src, {
            "type": "sync_ack",
            "term": self.term,
            "success": True,
            "nid": self.nid,
            "log_len": len(self.log),
        }, tag=f"sync_ack:{self.nid}->{src}")

    def _on_sync_ack(self, src: int, payload: dict) -> None:
        pass  # noted

    # ── internal: state-machine application ─────────────────────────────────

    def _apply(self) -> None:
        """Apply committed entries to the key-value store."""
        for i in range(len(self.log)):
            if i <= self.commit_idx:
                self.store[self.log[i].key] = self.log[i].value
