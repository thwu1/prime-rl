package raft


import "math/rand"

const (
	ElectionTimeoutMin = 150
	ElectionTimeoutMax = 300
	HeartbeatInterval  = 50
)

// RaftNode is a single consensus node in the cluster simulation.
type RaftNode struct {
	ID        int
	Peers     []int
	Transport *Transport
	rng       *rand.Rand

	CurrentTerm int
	VotedFor    int
	Log         []LogEntry

	State       NodeState
	CommitIndex int
	LastApplied int

	NextIndex  map[int]int
	MatchIndex map[int]int

	VotesReceived   map[int]bool
	ElectionTimeout int
	ElectionTimer   int
	HeartbeatTimer  int

	StateMachine *StateMachine
}

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

func (n *RaftNode) Tick() {
	for {
		env := n.Transport.Receive(n.ID)
		if env == nil {
			break
		}
		n.handleMessage(env.SenderID, env.Msg)
	}

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

func (n *RaftNode) Submit(command map[string]string) bool {
	if n.State != Leader {
		return false
	}
	entry := LogEntry{Term: n.CurrentTerm, Command: command}
	n.Log = append(n.Log, entry)
	n.MatchIndex[n.ID] = len(n.Log)
	n.sendHeartbeats()
	return true
}

func (n *RaftNode) becomeFollower(term int) {
	n.State = Follower
	if term > n.CurrentTerm {
		n.CurrentTerm = term
		n.VotedFor = -1
	}
	n.ElectionTimer = 0
	n.ElectionTimeout = n.randomElectionTimeout()
	n.VotesReceived = make(map[int]bool)
}

func (n *RaftNode) becomeLeader() {
	n.State = Leader
	n.HeartbeatTimer = 0
	for _, peer := range n.Peers {
		n.NextIndex[peer] = n.lastLogIndex() + 1
		n.MatchIndex[peer] = 0
	}
	n.MatchIndex[n.ID] = n.lastLogIndex()
	n.sendHeartbeats()
}

func (n *RaftNode) startElection() {
	n.CurrentTerm++
	n.State = Candidate
	n.VotedFor = n.ID
	n.VotesReceived = map[int]bool{n.ID: true}
	n.ElectionTimer = 0
	n.ElectionTimeout = n.randomElectionTimeout()

	msg := RequestVote{
		Term:         n.CurrentTerm,
		CandidateID:  n.ID,
		LastLogIndex: n.lastLogIndex(),
		LastLogTerm:  n.lastLogTerm(),
	}
	for _, peer := range n.Peers {
		n.Transport.Send(n.ID, peer, msg)
	}
}

func (n *RaftNode) handleRequestVote(senderID int, msg RequestVote) {
	if msg.Term > n.CurrentTerm {
		n.becomeFollower(msg.Term)
	}

	grant := false
	if msg.Term >= n.CurrentTerm {
		if n.VotedFor == -1 || n.VotedFor == msg.CandidateID {
			if msg.LastLogTerm > n.lastLogTerm() ||
				(msg.LastLogTerm == n.lastLogTerm() && msg.LastLogIndex >= n.lastLogIndex()) {
				grant = true
				n.VotedFor = msg.CandidateID
				n.ElectionTimer = 0
			}
		}
	}

	resp := RequestVoteResponse{Term: n.CurrentTerm, VoteGranted: grant}
	n.Transport.Send(n.ID, senderID, resp)
}

func (n *RaftNode) handleRequestVoteResponse(senderID int, msg RequestVoteResponse) {
	if msg.Term > n.CurrentTerm {
		n.becomeFollower(msg.Term)
		return
	}
	if n.State != Candidate {
		return
	}
	if msg.Term != n.CurrentTerm {
		return
	}
	if msg.VoteGranted {
		n.VotesReceived[senderID] = true
		if len(n.VotesReceived) > (len(n.Peers)+1)/2 {
			n.becomeLeader()
		}
	}
}

func (n *RaftNode) sendHeartbeats() {
	for _, peer := range n.Peers {
		nextIdx, ok := n.NextIndex[peer]
		if !ok {
			nextIdx = n.lastLogIndex() + 1
		}
		prevLogIndex := nextIdx - 1
		prevLogTerm := n.getLogTerm(prevLogIndex)

		var entries []LogEntry
		if nextIdx <= len(n.Log) {
			src := n.Log[nextIdx-1:]
			entries = make([]LogEntry, len(src))
			copy(entries, src)
		}

		msg := AppendEntries{
			Term:         n.CurrentTerm,
			LeaderID:     n.ID,
			PrevLogIndex: prevLogIndex,
			PrevLogTerm:  prevLogTerm,
			Entries:      entries,
			LeaderCommit: n.CommitIndex,
		}
		n.Transport.Send(n.ID, peer, msg)
	}
}

func (n *RaftNode) handleAppendEntries(senderID int, msg AppendEntries) {
	if msg.Term > n.CurrentTerm {
		n.becomeFollower(msg.Term)
	}

	if msg.Term < n.CurrentTerm {
		resp := AppendEntriesResponse{Term: n.CurrentTerm, Success: false, MatchIndex: 0}
		n.Transport.Send(n.ID, senderID, resp)
		return
	}

	n.State = Follower
	n.ElectionTimer = 0

	if msg.PrevLogIndex > 0 {
		if msg.PrevLogIndex > len(n.Log) {
			resp := AppendEntriesResponse{Term: n.CurrentTerm, Success: false, MatchIndex: 0}
			n.Transport.Send(n.ID, senderID, resp)
			return
		}
		if n.getLogTerm(msg.PrevLogIndex) != msg.PrevLogTerm {
			resp := AppendEntriesResponse{Term: n.CurrentTerm, Success: false, MatchIndex: 0}
			n.Transport.Send(n.ID, senderID, resp)
			return
		}
	}

	for i, entry := range msg.Entries {
		logIndex := msg.PrevLogIndex + 1 + i
		if logIndex <= len(n.Log) {
			if n.Log[logIndex-1].Term != entry.Term {
				n.Log = n.Log[:logIndex-1]
				n.Log = append(n.Log, entry)
			}
		} else {
			n.Log = append(n.Log, entry)
		}
	}

	verifiedIndex := msg.PrevLogIndex + len(msg.Entries)
	if msg.LeaderCommit > n.CommitIndex {
		commitTo := msg.LeaderCommit
		if verifiedIndex < commitTo {
			commitTo = verifiedIndex
		}
		n.CommitIndex = commitTo
	}

	resp := AppendEntriesResponse{Term: n.CurrentTerm, Success: true, MatchIndex: verifiedIndex}
	n.Transport.Send(n.ID, senderID, resp)
}

func (n *RaftNode) handleAppendEntriesResponse(senderID int, msg AppendEntriesResponse) {
	if msg.Term > n.CurrentTerm {
		n.becomeFollower(msg.Term)
		return
	}
	if n.State != Leader {
		return
	}
	if msg.Success {
		n.NextIndex[senderID] = msg.MatchIndex + 1
		n.MatchIndex[senderID] = msg.MatchIndex
		n.advanceCommitIndex()
	} else {
		ni := n.NextIndex[senderID]
		if ni > 1 {
			ni--
		} else {
			ni = 1
		}
		n.NextIndex[senderID] = ni
	}
}

func (n *RaftNode) advanceCommitIndex() {
	for idx := len(n.Log); idx > n.CommitIndex; idx-- {
		if n.getLogTerm(idx) != n.CurrentTerm {
			continue
		}
		count := 1
		for _, peer := range n.Peers {
			if n.MatchIndex[peer] >= idx {
				count++
			}
		}
		if count > (len(n.Peers)+1)/2 {
			n.CommitIndex = idx
			break
		}
	}
}
