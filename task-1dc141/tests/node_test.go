package raft


import (
	"fmt"
	"testing"
)

func recoverPanic(t *testing.T) {
	t.Helper()
	if r := recover(); r != nil {
		t.Fatalf("panic: %v", r)
	}
}

// ----------------------------------------------------------------
//  Leader election
// ----------------------------------------------------------------

func TestInitialElectionThreeNodes(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(3, 1)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader elected within 3000 ticks")
	}
	if cluster.Nodes[leader].State != Leader {
		t.Fatalf("Node %d is not actually leader", leader)
	}
}

func TestInitialElectionFiveNodes(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(5, 2)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader elected within 3000 ticks")
	}
}

func TestElectionSafety(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(5, 3)
	cluster.WaitForLeader(3000)
	cluster.Tick(2000)

	termLeaders := make(map[int]int)
	for nid := 0; nid < 5; nid++ {
		node := cluster.Nodes[nid]
		if node.State == Leader {
			term := node.CurrentTerm
			if prev, exists := termLeaders[term]; exists {
				if prev != nid {
					t.Fatalf("Two leaders in term %d: node %d and node %d", term, prev, nid)
				}
			} else {
				termLeaders[term] = nid
			}
		}
	}
}

func TestReelectionAfterLeaderFailure(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(3, 4)
	leader1 := cluster.WaitForLeader(3000)
	if leader1 < 0 {
		t.Fatal("No initial leader elected")
	}

	cluster.KillNode(leader1)
	leader2 := cluster.WaitForLeader(4000)
	if leader2 < 0 {
		t.Fatal("No new leader elected after failure")
	}
	if leader2 == leader1 {
		t.Fatal("New leader should be different from crashed leader")
	}
}

func TestCascadingLeaderFailures(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(5, 5)
	leader1 := cluster.WaitForLeader(3000)
	if leader1 < 0 {
		t.Fatal("No initial leader")
	}

	cluster.KillNode(leader1)
	leader2 := cluster.WaitForLeader(4000)
	if leader2 < 0 {
		t.Fatal("No leader after first failure")
	}
	if leader2 == leader1 {
		t.Fatal("Second leader same as first")
	}

	cluster.KillNode(leader2)
	leader3 := cluster.WaitForLeader(4000)
	if leader3 < 0 {
		t.Fatal("No leader after second failure")
	}
	if leader3 == leader1 || leader3 == leader2 {
		t.Fatal("Third leader same as a crashed leader")
	}
}

// ----------------------------------------------------------------
//  Log replication
// ----------------------------------------------------------------

func TestBasicReplication(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(3, 10)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader")
	}

	ok := cluster.Submit(map[string]string{"op": "set", "key": "x", "value": "hello"}, leader)
	if !ok {
		t.Fatal("Submit failed")
	}
	cluster.Tick(600)

	for nid := 0; nid < 3; nid++ {
		val, exists := cluster.GetCommittedValue(nid, "x")
		if !exists || val != "hello" {
			t.Fatalf("Node %d: x=%q, expected \"hello\"", nid, val)
		}
	}
}

func TestMultipleEntriesInOrder(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(3, 11)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader")
	}

	for i := 0; i < 10; i++ {
		cluster.Submit(map[string]string{
			"op": "set", "key": fmt.Sprintf("k%d", i), "value": fmt.Sprintf("%d", i),
		}, leader)
		cluster.Tick(100)
	}
	cluster.Tick(600)

	for nid := 0; nid < 3; nid++ {
		for i := 0; i < 10; i++ {
			val, exists := cluster.GetCommittedValue(nid, fmt.Sprintf("k%d", i))
			expected := fmt.Sprintf("%d", i)
			if !exists || val != expected {
				t.Fatalf("Node %d: k%d=%q, expected %q", nid, i, val, expected)
			}
		}
	}
}

func TestReplicationSurvivesLeaderChange(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(3, 12)
	leader1 := cluster.WaitForLeader(3000)
	if leader1 < 0 {
		t.Fatal("No leader")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "persist", "value": "yes"}, leader1)
	cluster.Tick(600)

	val, exists := cluster.GetCommittedValue(leader1, "persist")
	if !exists || val != "yes" {
		t.Fatalf("Value not committed on leader: %q", val)
	}

	cluster.KillNode(leader1)
	leader2 := cluster.WaitForLeader(4000)
	if leader2 < 0 {
		t.Fatal("No new leader")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "new", "value": "entry"}, leader2)
	cluster.Tick(600)

	val, exists = cluster.GetCommittedValue(leader2, "persist")
	if !exists || val != "yes" {
		t.Fatalf("Value lost after leader change: %q", val)
	}
}

func TestManyEntriesAcrossLeaderChange(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(5, 13)
	leader1 := cluster.WaitForLeader(3000)
	if leader1 < 0 {
		t.Fatal("No leader")
	}

	for i := 0; i < 5; i++ {
		cluster.Submit(map[string]string{
			"op": "set", "key": fmt.Sprintf("a%d", i), "value": fmt.Sprintf("%d", i),
		}, leader1)
		cluster.Tick(150)
	}
	cluster.Tick(600)

	cluster.KillNode(leader1)
	leader2 := cluster.WaitForLeader(4000)
	if leader2 < 0 {
		t.Fatal("No new leader")
	}

	for i := 0; i < 5; i++ {
		cluster.Submit(map[string]string{
			"op": "set", "key": fmt.Sprintf("b%d", i), "value": fmt.Sprintf("%d", i+100),
		}, leader2)
		cluster.Tick(150)
	}
	cluster.Tick(600)

	for nid := 0; nid < 5; nid++ {
		if nid == leader1 {
			continue
		}
		for i := 0; i < 5; i++ {
			val, exists := cluster.GetCommittedValue(nid, fmt.Sprintf("a%d", i))
			if !exists || val != fmt.Sprintf("%d", i) {
				t.Fatalf("Node %d lost a%d", nid, i)
			}
			val, exists = cluster.GetCommittedValue(nid, fmt.Sprintf("b%d", i))
			if !exists || val != fmt.Sprintf("%d", i+100) {
				t.Fatalf("Node %d lost b%d", nid, i)
			}
		}
	}
}

// ----------------------------------------------------------------
//  Follower recovery
// ----------------------------------------------------------------

func TestFollowerCatchesUp(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(3, 30)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "a", "value": "1"}, leader)
	cluster.Tick(600)

	follower := -1
	for i := 0; i < 3; i++ {
		if i != leader {
			follower = i
			break
		}
	}

	cluster.KillNode(follower)

	cluster.Submit(map[string]string{"op": "set", "key": "b", "value": "2"}, leader)
	cluster.Submit(map[string]string{"op": "set", "key": "c", "value": "3"}, leader)
	cluster.Tick(600)

	cluster.RestartNode(follower)
	cluster.Tick(1500)

	expected := map[string]string{"a": "1", "b": "2", "c": "3"}
	for key, want := range expected {
		got, exists := cluster.GetCommittedValue(follower, key)
		if !exists || got != want {
			t.Fatalf("Follower %d: %s=%q, expected %q", follower, key, got, want)
		}
	}
}

// ----------------------------------------------------------------
//  Network partitions
// ----------------------------------------------------------------

func TestPartitionMajorityContinues(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(5, 20)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "before", "value": "partition"}, leader)
	cluster.Tick(600)

	minority := []int{leader, (leader + 1) % 5}
	majority := []int{}
	for i := 0; i < 5; i++ {
		inMinority := false
		for _, m := range minority {
			if i == m {
				inMinority = true
				break
			}
		}
		if !inMinority {
			majority = append(majority, i)
		}
	}

	cluster.Partition(minority, majority)

	newLeader := -1
	for tick := 0; tick < 5000; tick++ {
		cluster.Tick(1)
		for _, nid := range majority {
			if cluster.Nodes[nid].State == Leader {
				newLeader = nid
				break
			}
		}
		if newLeader >= 0 {
			break
		}
	}
	if newLeader < 0 {
		t.Fatal("No leader in majority partition")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "during", "value": "partition"}, newLeader)
	cluster.Tick(600)

	for _, nid := range majority {
		val, exists := cluster.GetCommittedValue(nid, "during")
		if !exists || val != "partition" {
			t.Fatalf("Majority node %d missing 'during' entry", nid)
		}
	}
}

func TestPartitionHealConvergence(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(5, 21)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "pre", "value": "1"}, leader)
	cluster.Tick(600)

	minority := []int{leader, (leader + 1) % 5}
	majority := []int{}
	for i := 0; i < 5; i++ {
		inMinority := false
		for _, m := range minority {
			if i == m {
				inMinority = true
				break
			}
		}
		if !inMinority {
			majority = append(majority, i)
		}
	}

	cluster.Partition(minority, majority)

	newLeader := -1
	for tick := 0; tick < 5000; tick++ {
		cluster.Tick(1)
		for _, nid := range majority {
			if cluster.Nodes[nid].State == Leader {
				newLeader = nid
				break
			}
		}
		if newLeader >= 0 {
			break
		}
	}
	if newLeader < 0 {
		t.Fatal("No leader in majority")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "maj", "value": "2"}, newLeader)
	cluster.Tick(600)

	cluster.Heal()
	cluster.Tick(2000)

	for nid := 0; nid < 5; nid++ {
		val, exists := cluster.GetCommittedValue(nid, "pre")
		if !exists || val != "1" {
			t.Fatalf("Node %d lost 'pre'", nid)
		}
		val, exists = cluster.GetCommittedValue(nid, "maj")
		if !exists || val != "2" {
			t.Fatalf("Node %d missing 'maj' after heal", nid)
		}
	}
}

// ----------------------------------------------------------------
//  Log consistency
// ----------------------------------------------------------------

func TestCommittedLogsAgree(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(3, 40)
	leader := cluster.WaitForLeader(3000)
	if leader < 0 {
		t.Fatal("No leader")
	}

	for i := 0; i < 15; i++ {
		cluster.Submit(map[string]string{
			"op": "set", "key": fmt.Sprintf("key%d", i), "value": fmt.Sprintf("val%d", i),
		}, leader)
		cluster.Tick(100)
	}
	cluster.Tick(800)

	leaderNode := cluster.Nodes[leader]
	leaderCI := leaderNode.CommitIndex

	for nid := 0; nid < 3; nid++ {
		node := cluster.Nodes[nid]
		ci := leaderCI
		if node.CommitIndex < ci {
			ci = node.CommitIndex
		}
		if ci == 0 {
			t.Fatalf("Node %d has commit_index %d", nid, node.CommitIndex)
		}
		for idx := 0; idx < ci; idx++ {
			if node.Log[idx].Term != leaderNode.Log[idx].Term {
				t.Fatalf("Term mismatch at index %d: node %d term=%d, leader term=%d",
					idx+1, nid, node.Log[idx].Term, leaderNode.Log[idx].Term)
			}
		}
	}
}

func TestOverwrittenStaleEntries(t *testing.T) {
	defer recoverPanic(t)
	cluster := NewCluster(5, 41)
	leader1 := cluster.WaitForLeader(3000)
	if leader1 < 0 {
		t.Fatal("No leader")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "base", "value": "ok"}, leader1)
	cluster.Tick(600)

	companion := (leader1 + 1) % 5
	minority := []int{leader1, companion}
	majority := []int{}
	for i := 0; i < 5; i++ {
		if i != leader1 && i != companion {
			majority = append(majority, i)
		}
	}

	cluster.Partition(minority, majority)

	cluster.Submit(map[string]string{"op": "set", "key": "stale", "value": "bad"}, leader1)
	cluster.Tick(200)

	newLeader := -1
	for tick := 0; tick < 5000; tick++ {
		cluster.Tick(1)
		for _, nid := range majority {
			if cluster.Nodes[nid].State == Leader {
				newLeader = nid
				break
			}
		}
		if newLeader >= 0 {
			break
		}
	}
	if newLeader < 0 {
		t.Fatal("No leader in majority")
	}

	cluster.Submit(map[string]string{"op": "set", "key": "correct", "value": "good"}, newLeader)
	cluster.Tick(600)

	cluster.Heal()
	cluster.Tick(2000)

	for nid := 0; nid < 5; nid++ {
		val, exists := cluster.GetCommittedValue(nid, "correct")
		if !exists || val != "good" {
			t.Fatalf("Node %d missing 'correct'", nid)
		}
		val, exists = cluster.GetCommittedValue(nid, "base")
		if !exists || val != "ok" {
			t.Fatalf("Node %d missing 'base'", nid)
		}
	}

	for nid := 0; nid < 5; nid++ {
		_, exists := cluster.GetCommittedValue(nid, "stale")
		if exists {
			t.Fatalf("Node %d incorrectly committed stale entry", nid)
		}
	}
}
