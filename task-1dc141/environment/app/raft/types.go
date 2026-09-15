// Package raft implements a deterministic, tick-based distributed consensus
// cluster simulation.
//
package raft

// NodeState represents the possible states of a consensus node.
type NodeState int

const (
	Follower NodeState = iota
	Candidate
	Leader
)

func (s NodeState) String() string {
	switch s {
	case Follower:
		return "follower"
	case Candidate:
		return "candidate"
	case Leader:
		return "leader"
	default:
		return "unknown"
	}
}

// LogEntry represents a single entry in the replicated log.
type LogEntry struct {
	Term    int
	Command map[string]string
}

// Message is the interface implemented by all RPC message types.
type Message interface {
	isRaftMessage()
}

// RequestVote is the vote request RPC sent by candidates.
type RequestVote struct {
	Term         int
	CandidateID  int
	LastLogIndex int
	LastLogTerm  int
}

func (RequestVote) isRaftMessage() {}

// RequestVoteResponse is the response to a vote request.
type RequestVoteResponse struct {
	Term        int
	VoteGranted bool
}

func (RequestVoteResponse) isRaftMessage() {}

// AppendEntries is the log replication / heartbeat RPC sent by leaders.
type AppendEntries struct {
	Term         int
	LeaderID     int
	PrevLogIndex int
	PrevLogTerm  int
	Entries      []LogEntry
	LeaderCommit int
}

func (AppendEntries) isRaftMessage() {}

// AppendEntriesResponse is the response to a log replication RPC.
type AppendEntriesResponse struct {
	Term       int
	Success    bool
	MatchIndex int
}

func (AppendEntriesResponse) isRaftMessage() {}
