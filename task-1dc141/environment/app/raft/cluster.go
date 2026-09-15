package raft


import "math/rand"

// Cluster manages a group of consensus nodes in a deterministic,
// tick-based simulation. No threads or async — the cluster drives
// the simulation by ticking all nodes in round-robin order.
type Cluster struct {
	Transport *Transport
	NNodes    int
	Nodes     map[int]*RaftNode
	rng       *rand.Rand
	deadNodes map[int]bool
}

// NewCluster creates a new cluster with n nodes using the given
// random seed for deterministic behaviour.
func NewCluster(nNodes int, seed int64) *Cluster {
	rng := rand.New(rand.NewSource(seed))
	transport := NewTransport()
	nodes := make(map[int]*RaftNode)
	deadNodes := make(map[int]bool)

	for i := 0; i < nNodes; i++ {
		peers := make([]int, 0, nNodes-1)
		for p := 0; p < nNodes; p++ {
			if p != i {
				peers = append(peers, p)
			}
		}
		nodes[i] = NewRaftNode(i, peers, transport, rng.Int63())
	}

	return &Cluster{
		Transport: transport,
		NNodes:    nNodes,
		Nodes:     nodes,
		rng:       rng,
		deadNodes: deadNodes,
	}
}

// Tick advances the simulation by n ticks. Each tick, every live
// node processes its pending messages and checks its timeouts.
func (c *Cluster) Tick(n int) {
	for t := 0; t < n; t++ {
		for i := 0; i < c.NNodes; i++ {
			if !c.deadNodes[i] {
				c.Nodes[i].Tick()
			}
		}
	}
}

// GetLeader returns the current leader's node ID, or -1 if there
// is no single leader (zero or multiple).
func (c *Cluster) GetLeader() int {
	leaders := []int{}
	for i := 0; i < c.NNodes; i++ {
		if !c.deadNodes[i] && c.Nodes[i].State == Leader {
			leaders = append(leaders, i)
		}
	}
	if len(leaders) == 1 {
		return leaders[0]
	}
	return -1
}

// WaitForLeader ticks until exactly one leader exists, or gives up
// after maxTicks. Returns the leader's node ID, or -1 on timeout.
func (c *Cluster) WaitForLeader(maxTicks int) int {
	for t := 0; t < maxTicks; t++ {
		c.Tick(1)
		leader := c.GetLeader()
		if leader >= 0 {
			return leader
		}
	}
	return -1
}

// Submit sends a command to a specific node for replication.
// Returns true if the node accepted the command (i.e., it is the leader).
func (c *Cluster) Submit(command map[string]string, leaderID int) bool {
	if leaderID < 0 {
		return false
	}
	return c.Nodes[leaderID].Submit(command)
}

// KillNode simulates a node crash. The node stops ticking and
// its inbox is cleared.
func (c *Cluster) KillNode(nodeID int) {
	c.deadNodes[nodeID] = true
	c.Transport.Clear(nodeID)
}

// RestartNode restarts a previously killed node. Persistent state
// (CurrentTerm, VotedFor, Log) is preserved; volatile state is reset.
func (c *Cluster) RestartNode(nodeID int) {
	if c.deadNodes[nodeID] {
		delete(c.deadNodes, nodeID)
		c.Transport.Clear(nodeID)
		c.Nodes[nodeID].Restart()
	}
}

// Partition creates a network partition between two groups of nodes.
func (c *Cluster) Partition(groupA, groupB []int) {
	c.Transport.Partition(groupA, groupB)
}

// Heal removes all network partitions.
func (c *Cluster) Heal() {
	c.Transport.Heal()
}

// GetCommittedValue reads a committed value from a node's state machine.
func (c *Cluster) GetCommittedValue(nodeID int, key string) (string, bool) {
	return c.Nodes[nodeID].StateMachine.Get(key)
}
