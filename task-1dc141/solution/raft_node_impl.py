"""
Complete Raft consensus node implementation (SOLUTION).

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

ELECTION_TIMEOUT_MIN = 150
ELECTION_TIMEOUT_MAX = 300
HEARTBEAT_INTERVAL = 50


class RaftNode:
    def __init__(self, node_id, peers, transport, seed=42):
        self.id = node_id
        self.peers = peers
        self.transport = transport
        self.rng = random.Random(seed)

        # Persistent state
        self.current_term = 0
        self.voted_for = None
        self.log = []

        # Volatile state
        self.state = NodeState.FOLLOWER
        self.commit_index = 0
        self.last_applied = 0

        # Leader state
        self.next_index = {}
        self.match_index = {}

        # Election bookkeeping
        self.votes_received = set()
        self.election_timeout = self._random_election_timeout()
        self.election_timer = 0
        self.heartbeat_timer = 0

        # State machine
        self.state_machine = StateMachine()

    # -- helpers --

    def _random_election_timeout(self):
        return self.rng.randint(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)

    def _last_log_index(self):
        return len(self.log)

    def _last_log_term(self):
        if self.log:
            return self.log[-1].term
        return 0

    def _get_log_term(self, index):
        if index <= 0 or index > len(self.log):
            return 0
        return self.log[index - 1].term

    def restart(self):
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

    # -- tick loop --

    def tick(self):
        while True:
            result = self.transport.receive(self.id)
            if result is None:
                break
            sender_id, message = result
            self._handle_message(sender_id, message)

        if self.state == NodeState.LEADER:
            self.heartbeat_timer += 1
            if self.heartbeat_timer >= HEARTBEAT_INTERVAL:
                self.heartbeat_timer = 0
                self._send_heartbeats()
        else:
            self.election_timer += 1
            if self.election_timer >= self.election_timeout:
                self._start_election()

        self._apply_committed()

    def _handle_message(self, sender_id, message):
        if isinstance(message, RequestVote):
            self._handle_request_vote(sender_id, message)
        elif isinstance(message, RequestVoteResponse):
            self._handle_request_vote_response(sender_id, message)
        elif isinstance(message, AppendEntries):
            self._handle_append_entries(sender_id, message)
        elif isinstance(message, AppendEntriesResponse):
            self._handle_append_entries_response(sender_id, message)

    def _apply_committed(self):
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            if self.last_applied <= len(self.log):
                entry = self.log[self.last_applied - 1]
                self.state_machine.apply(entry.command)

    # -- core Raft --

    def submit(self, command):
        if self.state != NodeState.LEADER:
            return False
        entry = LogEntry(term=self.current_term, command=command)
        self.log.append(entry)
        self.match_index[self.id] = len(self.log)
        # Immediately replicate
        self._send_heartbeats()
        return True

    def _become_follower(self, term):
        self.state = NodeState.FOLLOWER
        if term > self.current_term:
            self.current_term = term
            self.voted_for = None
        self.election_timer = 0
        self.election_timeout = self._random_election_timeout()
        self.votes_received = set()

    def _become_leader(self):
        self.state = NodeState.LEADER
        self.heartbeat_timer = 0
        for peer in self.peers:
            self.next_index[peer] = self._last_log_index() + 1
            self.match_index[peer] = 0
        self.match_index[self.id] = self._last_log_index()
        self._send_heartbeats()

    def _start_election(self):
        self.current_term += 1
        self.state = NodeState.CANDIDATE
        self.voted_for = self.id
        self.votes_received = {self.id}
        self.election_timer = 0
        self.election_timeout = self._random_election_timeout()

        msg = RequestVote(
            term=self.current_term,
            candidate_id=self.id,
            last_log_index=self._last_log_index(),
            last_log_term=self._last_log_term(),
        )
        for peer in self.peers:
            self.transport.send(self.id, peer, msg)

    def _handle_request_vote(self, sender_id, msg):
        if msg.term > self.current_term:
            self._become_follower(msg.term)

        grant = False
        if msg.term >= self.current_term:
            if self.voted_for is None or self.voted_for == msg.candidate_id:
                # Election restriction: candidate's log must be at least
                # as up-to-date as ours.
                if (msg.last_log_term > self._last_log_term() or
                    (msg.last_log_term == self._last_log_term() and
                     msg.last_log_index >= self._last_log_index())):
                    grant = True
                    self.voted_for = msg.candidate_id
                    self.election_timer = 0  # reset on granting vote

        resp = RequestVoteResponse(term=self.current_term, vote_granted=grant)
        self.transport.send(self.id, sender_id, resp)

    def _handle_request_vote_response(self, sender_id, msg):
        if msg.term > self.current_term:
            self._become_follower(msg.term)
            return

        if self.state != NodeState.CANDIDATE:
            return
        if msg.term != self.current_term:
            return

        if msg.vote_granted:
            self.votes_received.add(sender_id)
            if len(self.votes_received) > (len(self.peers) + 1) // 2:
                self._become_leader()

    def _send_heartbeats(self):
        for peer in self.peers:
            next_idx = self.next_index.get(peer, self._last_log_index() + 1)
            prev_log_index = next_idx - 1
            prev_log_term = self._get_log_term(prev_log_index)

            entries = []
            if next_idx <= len(self.log):
                entries = list(self.log[next_idx - 1:])

            msg = AppendEntries(
                term=self.current_term,
                leader_id=self.id,
                prev_log_index=prev_log_index,
                prev_log_term=prev_log_term,
                entries=entries,
                leader_commit=self.commit_index,
            )
            self.transport.send(self.id, peer, msg)

    def _handle_append_entries(self, sender_id, msg):
        # Step down if we see a higher term
        if msg.term > self.current_term:
            self._become_follower(msg.term)

        # Reject stale-term messages
        if msg.term < self.current_term:
            resp = AppendEntriesResponse(
                term=self.current_term, success=False, match_index=0
            )
            self.transport.send(self.id, sender_id, resp)
            return

        # Valid AppendEntries from current leader -- step down if candidate
        self.state = NodeState.FOLLOWER
        self.election_timer = 0

        # Log consistency check
        if msg.prev_log_index > 0:
            if msg.prev_log_index > len(self.log):
                resp = AppendEntriesResponse(
                    term=self.current_term, success=False, match_index=0
                )
                self.transport.send(self.id, sender_id, resp)
                return
            if self._get_log_term(msg.prev_log_index) != msg.prev_log_term:
                resp = AppendEntriesResponse(
                    term=self.current_term, success=False, match_index=0
                )
                self.transport.send(self.id, sender_id, resp)
                return

        # Append new entries, handling conflicts
        for i, entry in enumerate(msg.entries):
            log_index = msg.prev_log_index + 1 + i  # 1-based
            if log_index <= len(self.log):
                if self.log[log_index - 1].term != entry.term:
                    # Conflict: truncate from here and append
                    self.log = self.log[:log_index - 1]
                    self.log.append(entry)
                # else: entry already matches, no action
            else:
                self.log.append(entry)

        # Advance commit_index
        verified_index = msg.prev_log_index + len(msg.entries)
        if msg.leader_commit > self.commit_index:
            self.commit_index = min(msg.leader_commit, verified_index)

        resp = AppendEntriesResponse(
            term=self.current_term,
            success=True,
            match_index=verified_index,
        )
        self.transport.send(self.id, sender_id, resp)

    def _handle_append_entries_response(self, sender_id, msg):
        if msg.term > self.current_term:
            self._become_follower(msg.term)
            return

        if self.state != NodeState.LEADER:
            return

        if msg.success:
            self.next_index[sender_id] = msg.match_index + 1
            self.match_index[sender_id] = msg.match_index
            self._advance_commit_index()
        else:
            # Decrement nextIndex and retry on next heartbeat
            self.next_index[sender_id] = max(
                1, self.next_index.get(sender_id, 1) - 1
            )

    def _advance_commit_index(self):
        # Find highest N > commit_index such that a majority has
        # match_index >= N AND log[N].term == current_term.
        for n in range(len(self.log), self.commit_index, -1):
            if self._get_log_term(n) != self.current_term:
                continue
            count = 1  # count self
            for peer in self.peers:
                if self.match_index.get(peer, 0) >= n:
                    count += 1
            if count > (len(self.peers) + 1) // 2:
                self.commit_index = n
                break
