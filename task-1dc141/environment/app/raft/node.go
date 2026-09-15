package raft


import "math/rand"

// Timing constants (in ticks).
const (
	ElectionTimeoutMin = 150
	ElectionTimeoutMax = 300
	HeartbeatInterval  = 50
)

// RaftNode is a single consensus node in the cluster simulation.
//
// Key fields (initialised by NewRaftNode):
//
//	Persistent (survive Restart):
//	  CurrentTerm  – latest term the node has seen
//	  VotedFor     – ID of the candidate voted for in current term (-1 = none)
//	  Log          – slice of LogEntry; 0-indexed in Go, but protocol
//	                 indices are 1-based (protocol index 1 == Log[0])
//
//	Volatile:
//	  State        – Follower / Candidate / Leader
//	  CommitIndex  – highest log index known to be committed
//	  LastApplied  – highest log index applied to state machine
//
//	Leader-only volatile:
//	  NextIndex    – map[peerID]int, next index to send to each peer
//	  MatchIndex   – map[peerID]int, highest index replicated on each peer
//
//	Election bookkeeping:
//	  VotesReceived   – set of node IDs that granted their vote
//	  ElectionTimeout / ElectionTimer
//	  HeartbeatTimer
type RaftNode struct {
	ID        int
	Peers     []int
	Transport *Transport
	rng       *rand.Rand

	// Persistent state (survives Restart)
	CurrentTerm int
	VotedFor    int // -1 means no vote cast
	Log         []LogEntry

	// Volatile state
	State       NodeState
	CommitIndex int
	LastApplied int

	// Leader-only volatile state
	NextIndex  map[int]int
	MatchIndex map[int]int

	// Election bookkeeping
	VotesReceived   map[int]bool
	ElectionTimeout int
	ElectionTimer   int
	HeartbeatTimer  int

	// State machine
	StateMachine *StateMachine
}

// NewRaftNode creates a new consensus node.
func NewRaftNode(nodeID int, peers []int, transport *Transport, seed int64) *RaftNode {
	rng := rand.New(rand.NewSource(seed))
	n := &RaftNode{
		ID:        nodeID,
		Peers:     peers,
		Transport: transport,
		rng:       rng,

		CurrentTerm: 0,
		VotedFor:    -1,
		Log:         nil,

		State:       Follower,
		CommitIndex: 0,
		LastApplied: 0,

		NextIndex:  make(map[int]int),
		MatchIndex: make(map[int]int),

		VotesReceived:  make(map[int]bool),
		ElectionTimer:  0,
		HeartbeatTimer: 0,

		StateMachine: NewStateMachine(),
	}
	n.ElectionTimeout = n.randomElectionTimeout()
	return n
}

// ----------------------------------------------------------------
// Helpers (complete — do not modify)
// ----------------------------------------------------------------

func (n *RaftNode) randomElectionTimeout() int {
	return n.rng.Intn(ElectionTimeoutMax-ElectionTimeoutMin+1) + ElectionTimeoutMin
}

func (n *RaftNode) lastLogIndex() int {
	return len(n.Log)
}

func (n *RaftNode) lastLogTerm() int {
	if len(n.Log) > 0 {
		return n.Log[len(n.Log)-1].Term
	}
	return 0
}

func (n *RaftNode) getLogTerm(index int) int {
	if index <= 0 || index > len(n.Log) {
		return 0
	}
	return n.Log[index-1].Term
}

// Restart simulates a node restart. Persistent state (CurrentTerm,
// VotedFor, Log) is kept. Everything else is reset.
func (n *RaftNode) Restart() {
	n.State = Follower
	n.CommitIndex = 0
	n.LastApplied = 0
	n.NextIndex = make(map[int]int)
	n.MatchIndex = make(map[int]int)
	n.VotesReceived = make(map[int]bool)
	n.ElectionTimeout = n.randomElectionTimeout()
	n.ElectionTimer = 0
	n.HeartbeatTimer = 0
	n.StateMachine = NewStateMachine()
}

// ----------------------------------------------------------------
// Tick loop and message dispatch (complete — do not modify)
// ----------------------------------------------------------------

// Tick runs one simulation tick: drain inbox, check timeouts,
// apply committed entries.
func (n *RaftNode) Tick() {
	// 1. Process all pending messages
	for {
		env := n.Transport.Receive(n.ID)
		if env == nil {
			break
		}
		n.handleMessage(env.SenderID, env.Msg)
	}

	// 2. Timeouts
	if n.State == Leader {
		n.HeartbeatTimer++
		if n.HeartbeatTimer >= HeartbeatInterval {
			n.HeartbeatTimer = 0
			n.sendHeartbeats()
		}
	} else {
		n.ElectionTimer++
		if n.ElectionTimer >= n.ElectionTimeout {
			n.startElection()
		}
	}

	// 3. Apply committed-but-not-yet-applied entries
	n.applyCommitted()
}

func (n *RaftNode) handleMessage(senderID int, msg Message) {
	switch m := msg.(type) {
	case RequestVote:
		n.handleRequestVote(senderID, m)
	case RequestVoteResponse:
		n.handleRequestVoteResponse(senderID, m)
	case AppendEntries:
		n.handleAppendEntries(senderID, m)
	case AppendEntriesResponse:
		n.handleAppendEntriesResponse(senderID, m)
	}
}

func (n *RaftNode) applyCommitted() {
	for n.LastApplied < n.CommitIndex {
		n.LastApplied++
		if n.LastApplied <= len(n.Log) {
			entry := n.Log[n.LastApplied-1]
			n.StateMachine.Apply(entry.Command)
		}
	}
}

// ================================================================
// Implement every method below. Each currently panics.
// ================================================================

// Submit accepts a client command for replication (leader only).
func (n *RaftNode) Submit(command map[string]string) bool {
	panic("not implemented: Submit")
}

// startElection begins a new election.
func (n *RaftNode) startElection() {
	panic("not implemented: startElection")
}

// handleRequestVote processes a vote request from another node.
func (n *RaftNode) handleRequestVote(senderID int, msg RequestVote) {
	panic("not implemented: handleRequestVote")
}

// handleRequestVoteResponse processes a vote response.
func (n *RaftNode) handleRequestVoteResponse(senderID int, msg RequestVoteResponse) {
	panic("not implemented: handleRequestVoteResponse")
}

// sendHeartbeats sends periodic replication messages to all peers.
func (n *RaftNode) sendHeartbeats() {
	panic("not implemented: sendHeartbeats")
}

// handleAppendEntries processes an entries message from the leader.
func (n *RaftNode) handleAppendEntries(senderID int, msg AppendEntries) {
	panic("not implemented: handleAppendEntries")
}

// handleAppendEntriesResponse processes the response to an entries message.
func (n *RaftNode) handleAppendEntriesResponse(senderID int, msg AppendEntriesResponse) {
	panic("not implemented: handleAppendEntriesResponse")
}

// advanceCommitIndex updates the commit index based on replication state (leader only).
func (n *RaftNode) advanceCommitIndex() {
	panic("not implemented: advanceCommitIndex")
}

// becomeFollower transitions the node to follower state.
func (n *RaftNode) becomeFollower(term int) {
	panic("not implemented: becomeFollower")
}

// becomeLeader transitions the node to leader state after winning an election.
func (n *RaftNode) becomeLeader() {
	panic("not implemented: becomeLeader")
}
