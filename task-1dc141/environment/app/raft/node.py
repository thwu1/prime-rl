"""
Raft consensus node — SKELETON.

This module contains the core Raft node with all data structures
initialized and the tick/message-dispatch loop implemented. The
actual Raft algorithm methods are stubs that raise NotImplementedError.

YOUR TASK: implement every method marked with 'raise NotImplementedError'.

The node operates in a deterministic, tick-based simulation:
  - Each tick, the node drains its message inbox, then checks timeouts.
  - Election timeout: randomised in [150, 300] ticks.
  - Heartbeat interval: 50 ticks.
  - Messages sent via self.transport.send() are available to the
    recipient on their next tick.

Key attributes (already initialised in __init__):
  Persistent (survive restart):
    self.current_term   — latest term the node has seen
    self.voted_for      — candidate_id voted for in current term (or None)
    self.log            — list of LogEntry; 0-indexed in Python,
                          but Raft indices are 1-based:
                            Raft index 1 == self.log[0]

  Volatile:
    self.state          — NodeState.FOLLOWER / CANDIDATE / LEADER
    self.commit_index   — highest log index known to be committed
    self.last_applied   — highest log index applied to state machine

  Leader-only volatile:
    self.next_index     — {peer_id: int} next index to send to each peer
    self.match_index    — {peer_id: int} highest index replicated on each peer

  Election bookkeeping:
    self.votes_received — set of node_ids that granted their vote
    self.election_timeout / self.election_timer
    self.heartbeat_timer

Helper methods (already implemented):
    _last_log_index()      — returns len(self.log)  (== last Raft index)
    _last_log_term()       — term of the last log entry (0 if empty)
    _get_log_term(index)   — term at 1-based index  (0 if out of range)
    _random_election_timeout()
    _apply_committed()     — applies entries up to commit_index to the
                             state machine (called automatically each tick)

"""

import random
from .protocol import (
    NodeState,
    LogEntry,
    RequestVote,
    RequestVoteResponse,
    AppendEntries,
    AppendEntriesResponse,
)
from .storage import StateMachine

# Timing constants (in ticks)
ELECTION_TIMEOUT_MIN = 150
ELECTION_TIMEOUT_MAX = 300
HEARTBEAT_INTERVAL = 50


class RaftNode:
    """A single Raft consensus node."""

    def __init__(self, node_id, peers, transport, seed=42):
        self.id = node_id
        self.peers = peers
        self.transport = transport
        self.rng = random.Random(seed)

        # --- Persistent state (survives restart) ---
        self.current_term = 0
        self.voted_for = None
        self.log = []  # List[LogEntry]

        # --- Volatile state ---
        self.state = NodeState.FOLLOWER
        self.commit_index = 0
        self.last_applied = 0

        # --- Leader-only volatile state ---
        self.next_index = {}   # peer_id → int
        self.match_index = {}  # peer_id → int

        # --- Election bookkeeping ---
        self.votes_received = set()
        self.election_timeout = self._random_election_timeout()
        self.election_timer = 0
        self.heartbeat_timer = 0

        # --- State machine ---
        self.state_machine = StateMachine()

    # ----------------------------------------------------------------
    # Helpers (complete — do not modify)
    # ----------------------------------------------------------------

    def _random_election_timeout(self):
        return self.rng.randint(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)

    def _last_log_index(self):
        """Last Raft log index (1-based). 0 means the log is empty."""
        return len(self.log)

    def _last_log_term(self):
        """Term of the last log entry, or 0 if the log is empty."""
        if self.log:
            return self.log[-1].term
        return 0

    def _get_log_term(self, index):
        """Term of the log entry at the given 1-based index.
        Returns 0 if the index is out of range."""
        if index <= 0 or index > len(self.log):
            return 0
        return self.log[index - 1].term

    def restart(self):
        """Simulate a node restart.

        Persistent state (current_term, voted_for, log) is kept.
        Everything else is reset as if the process just started.
        """
        self.state = NodeState.FOLLOWER
        self.commit_index = 0
        self.last_applied = 0
        self.next_index = {}
        self.match_index = {}
        self.votes_received = set()
        self.election_timeout = self._random_election_timeout()
        self.election_timer = 0
        self.heartbeat_timer = 0
        self.state_machine = StateMachine()

    # ----------------------------------------------------------------
    # Tick loop & message dispatch (complete — do not modify)
    # ----------------------------------------------------------------

    def tick(self):
        """One simulation tick: drain inbox, then check timeouts."""
        # 1. Process all pending messages
        while True:
            result = self.transport.receive(self.id)
            if result is None:
                break
            sender_id, message = result
            self._handle_message(sender_id, message)

        # 2. Timeouts
        if self.state == NodeState.LEADER:
            self.heartbeat_timer += 1
            if self.heartbeat_timer >= HEARTBEAT_INTERVAL:
                self.heartbeat_timer = 0
                self._send_heartbeats()
        else:
            self.election_timer += 1
            if self.election_timer >= self.election_timeout:
                self._start_election()

        # 3. Apply committed-but-not-yet-applied entries
        self._apply_committed()

    def _handle_message(self, sender_id, message):
        """Dispatch an incoming message to the correct handler."""
        if isinstance(message, RequestVote):
            self._handle_request_vote(sender_id, message)
        elif isinstance(message, RequestVoteResponse):
            self._handle_request_vote_response(sender_id, message)
        elif isinstance(message, AppendEntries):
            self._handle_append_entries(sender_id, message)
        elif isinstance(message, AppendEntriesResponse):
            self._handle_append_entries_response(sender_id, message)

    def _apply_committed(self):
        """Apply all committed-but-unapplied entries to the state machine."""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            if self.last_applied <= len(self.log):
                entry = self.log[self.last_applied - 1]
                self.state_machine.apply(entry.command)

    # ================================================================
    # TODO — implement every method below.
    #
    # Each method raises NotImplementedError.  Replace the raise with
    # a correct Raft implementation.
    # ================================================================

    def submit(self, command):
        """Submit a client command for replication (leader only).

        Append the command as a new LogEntry and begin replicating it.
        Return True if accepted (this node is the leader), False otherwise.
        """
        raise NotImplementedError("Implement submit()")

    def _start_election(self):
        """Transition to candidate, increment term, vote for self,
        and send RequestVote RPCs to all peers."""
        raise NotImplementedError("Implement _start_election()")

    def _handle_request_vote(self, sender_id, msg):
        """Process an incoming RequestVote RPC.

        Grant the vote only if the candidate's term is current and
        its log is at least as up-to-date as ours.
        Always send a RequestVoteResponse back to the sender.
        """
        raise NotImplementedError("Implement _handle_request_vote()")

    def _handle_request_vote_response(self, sender_id, msg):
        """Process a RequestVoteResponse.

        If we're still a candidate and have received a majority of
        votes, transition to leader.
        """
        raise NotImplementedError("Implement _handle_request_vote_response()")

    def _send_heartbeats(self):
        """Send AppendEntries RPCs to every peer.

        Include any log entries the peer hasn't received yet
        (based on next_index).  An empty entries list acts as a
        heartbeat.
        """
        raise NotImplementedError("Implement _send_heartbeats()")

    def _handle_append_entries(self, sender_id, msg):
        """Process an incoming AppendEntries RPC.

        Verify the leader's term and log consistency, append any
        new entries, and advance commit_index.
        Always send an AppendEntriesResponse back to the sender.
        """
        raise NotImplementedError("Implement _handle_append_entries()")

    def _handle_append_entries_response(self, sender_id, msg):
        """Process an AppendEntriesResponse.

        On success, update next_index and match_index for the peer,
        then try to advance commit_index.
        On failure, decrement next_index for the peer so the next
        AppendEntries will include earlier entries.
        """
        raise NotImplementedError("Implement _handle_append_entries_response()")

    def _advance_commit_index(self):
        """(Leader only) Advance commit_index.

        Find the highest N such that a majority of match_index[i] >= N
        AND log[N].term == current_term, then set commit_index = N.
        """
        raise NotImplementedError("Implement _advance_commit_index()")

    def _become_follower(self, term):
        """Transition to follower state.

        If *term* is higher than current_term, update current_term
        and clear voted_for.  Reset election timer.
        """
        raise NotImplementedError("Implement _become_follower()")

    def _become_leader(self):
        """Transition to leader state after winning an election.

        Initialise next_index and match_index for every peer,
        then send initial heartbeats.
        """
        raise NotImplementedError("Implement _become_leader()")
