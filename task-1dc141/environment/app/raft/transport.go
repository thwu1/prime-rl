package raft


// Envelope wraps a message with sender information.
type Envelope struct {
	SenderID int
	Msg      Message
}

// Transport provides in-process message passing between nodes.
// It supports simulating network partitions by dropping messages
// between partitioned groups.
type Transport struct {
	inboxes      map[int][]Envelope
	partitions   map[[2]int]bool
	droppedCount int
}

// NewTransport creates a new Transport.
func NewTransport() *Transport {
	return &Transport{
		inboxes:    make(map[int][]Envelope),
		partitions: make(map[[2]int]bool),
	}
}

func sortedPair(a, b int) [2]int {
	if a > b {
		a, b = b, a
	}
	return [2]int{a, b}
}

// Send delivers a message from one node to another.
// Messages between partitioned nodes are silently dropped.
func (t *Transport) Send(fromID, toID int, msg Message) {
	pair := sortedPair(fromID, toID)
	if t.partitions[pair] {
		t.droppedCount++
		return
	}
	t.inboxes[toID] = append(t.inboxes[toID], Envelope{SenderID: fromID, Msg: msg})
}

// Receive returns the next pending message for a node, or nil if empty.
func (t *Transport) Receive(nodeID int) *Envelope {
	inbox := t.inboxes[nodeID]
	if len(inbox) == 0 {
		return nil
	}
	env := inbox[0]
	t.inboxes[nodeID] = inbox[1:]
	return &env
}

// Partition creates a network partition between two groups.
// All messages between any node in groupA and any node in groupB
// will be silently dropped.
func (t *Transport) Partition(groupA, groupB []int) {
	for _, a := range groupA {
		for _, b := range groupB {
			t.partitions[sortedPair(a, b)] = true
		}
	}
}

// Heal removes all network partitions.
func (t *Transport) Heal() {
	t.partitions = make(map[[2]int]bool)
}

// Clear removes all pending messages for a node.
func (t *Transport) Clear(nodeID int) {
	delete(t.inboxes, nodeID)
}

// DroppedCount returns the total number of messages dropped due to partitions.
func (t *Transport) DroppedCount() int {
	return t.droppedCount
}
