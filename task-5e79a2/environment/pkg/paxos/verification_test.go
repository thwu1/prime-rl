package paxos

import (
	"protoverify/pkg/base"
	"fmt"
	"testing"
)

// --- Basic Consensus Scenarios ---

func TestBasicConsensus(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, nil)
	s.AddNode(peers[2], server, nil)

	result := base.BfsFind(s, validate, goal, 10)
	if !result.Success {
		t.Fatal("Failed to find consensus with single proposer via BFS")
	}
	fmt.Printf("BasicConsensus: explored %d states, consensus at depth %d\n",
		result.N, result.Targets[0].Depth)
}

func TestDualProposerConsensus(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, "gamma")
	s.AddNode(peers[2], server, nil)

	result := base.BatchRandomWalkFind(s, validate, goal, 10000, 200)
	if !result.Success {
		t.Fatal("Failed to find consensus with dual proposers via random walk")
	}
}

func TestSafetyInvariant(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}

	s := base.NewState(0, true, true)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	server.n_a = 1
	server.v_a = "gamma"
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, nil)
	server.n_a = 1
	server.v_a = "gamma"
	s.AddNode(peers[2], server, nil)

	invariantCheck := func(state *base.State) bool {
		flag, v := globalAgreedValue(state)
		if flag == -1 {
			return false
		}
		if flag == 1 && v != "gamma" {
			return false
		}
		for _, node := range state.Nodes() {
			srv := node.(*Server)
			if srv.v_a != nil && srv.v_a != "gamma" {
				return false
			}
		}
		return true
	}

	result := base.BfsFindAll(s, invariantCheck, nil, 7)
	if !result.Success {
		t.Fatal("Safety invariant violated")
	}
	fmt.Printf("SafetyInvariant: explored %d states, no violations\n", result.N)
}

// --- Analysis Function Tests ---

func TestCountReachableStates(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, nil)
	s.AddNode(peers[2], server, nil)

	count0 := CountReachableStates(s, 0)
	if count0 != 1 {
		t.Fatalf("expected 1 state at depth 0, got %d", count0)
	}

	count1 := CountReachableStates(s, 1)
	if count1 <= 1 {
		t.Fatalf("expected more than 1 state at depth 1, got %d", count1)
	}

	count3 := CountReachableStates(s, 3)
	if count3 <= count1 {
		t.Fatalf("expected more states at depth 3 (%d) than depth 1 (%d)", count3, count1)
	}
	fmt.Printf("CountReachableStates: depth0=%d depth1=%d depth3=%d\n", count0, count1, count3)
}

func TestFindShortestConsensusPath(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, nil)
	s.AddNode(peers[2], server, nil)

	depth, path := FindShortestConsensusPath(s, 12)
	if depth < 0 {
		t.Fatal("expected to find consensus path, got -1")
	}
	if depth < 3 {
		t.Fatalf("consensus should require at least 3 steps, got depth %d", depth)
	}
	if len(path) != depth {
		t.Fatalf("path length %d should match depth %d", len(path), depth)
	}
	fmt.Printf("ShortestConsensusPath: depth=%d\n", depth)
}

func TestVerifySafety(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}

	// Single proposer: should be safe
	s1 := base.NewState(0, false, false)
	server := NewServer(peers, 0, "alpha")
	s1.AddNode(peers[0], server, nil)
	server = NewServer(peers, 1, nil)
	s1.AddNode(peers[1], server, nil)
	server = NewServer(peers, 2, nil)
	s1.AddNode(peers[2], server, nil)

	if !VerifySafety(s1, 7) {
		t.Fatal("Paxos should be safe with single proposer")
	}

	// Dual proposer: should still be safe
	s2 := base.NewState(0, false, false)
	server = NewServer(peers, 0, "alpha")
	s2.AddNode(peers[0], server, nil)
	server = NewServer(peers, 1, nil)
	s2.AddNode(peers[1], server, nil)
	server = NewServer(peers, 2, "gamma")
	s2.AddNode(peers[2], server, nil)

	if !VerifySafety(s2, 6) {
		t.Fatal("Paxos should be safe with dual proposers")
	}
}

func TestFindNonTerminatingExecution(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, "gamma")
	s.AddNode(peers[2], server, nil)

	found, path := FindNonTerminatingExecution(s, 8)
	if !found {
		t.Fatal("expected to find non-terminating execution with competing proposers")
	}
	if len(path) == 0 {
		t.Fatal("expected non-empty path for non-terminating execution")
	}
	fmt.Printf("NonTerminatingExecution: path length=%d\n", len(path))
}

// --- Custom Predicate Tests ---

func TestValueAdoption(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, "gamma")
	s.AddNode(peers[2], server, nil)

	checks := LeadToValueAdoption()
	result := reachState(s, checks, 5)
	if result == nil {
		t.Fatal("cannot find value adoption path")
	}

	// Verify s1 adopted gamma
	s1 := result.Nodes()["s1"].(*Server)
	if s1.proposer.V != "gamma" {
		t.Fatalf("expected s1 to adopt gamma, got %v", s1.proposer.V)
	}
	fmt.Println("ValueAdoption: s1 successfully adopted gamma")
}

func TestProgressiveContention(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, nil)
	s.AddNode(peers[1], server, nil)

	// s3 has already completed one proposal round
	server = NewServer(peers, 2, "gamma")
	server.proposer.N = 1
	server.proposer.SessionId = 1
	s.AddNode(peers[2], server, nil)

	checks := LeadToProgressiveContention()
	result := reachState(s, checks, 5)
	if result == nil {
		t.Fatal("cannot find progressive contention path")
	}
	fmt.Println("ProgressiveContention: found contention path successfully")
}

func TestThreeWayResolution(t *testing.T) {
	peers := []base.Address{"s1", "s2", "s3"}
	s := base.NewState(0, false, false)

	server := NewServer(peers, 0, "alpha")
	s.AddNode(peers[0], server, nil)

	server = NewServer(peers, 1, "beta")
	s.AddNode(peers[1], server, nil)

	server = NewServer(peers, 2, "gamma")
	s.AddNode(peers[2], server, nil)

	// Verify predicates are implemented
	checks := LeadToThreeWayResolution()
	if len(checks) < 1 {
		t.Fatal("LeadToThreeWayResolution must return at least one predicate")
	}

	// Use random walk since BFS may be too expensive with 3 proposers
	allConsensus := func(s *base.State) bool {
		var v interface{}
		for _, node := range s.Nodes() {
			srv := node.(*Server)
			if base.IsNil(srv.agreedValue) {
				return false
			}
			if base.IsNil(v) {
				v = srv.agreedValue
			} else if v != srv.agreedValue {
				return false
			}
		}
		return !base.IsNil(v)
	}

	result := base.BatchRandomWalkFind(s, validate, allConsensus, 10000, 500)
	if !result.Success {
		t.Fatal("Cannot reach all-agree with three competing proposers")
	}

	// Verify the predicate chain is reachable via random walk
	current := s
	for i, check := range checks {
		res := base.BatchRandomWalkFind(current, validate, check, 10000, 100)
		if !res.Success {
			t.Fatalf("Predicate %d in chain not reachable via random walk", i)
		}
		current = res.Targets[0]
	}
	fmt.Println("ThreeWayResolution: all three proposers resolved consensus")
}
