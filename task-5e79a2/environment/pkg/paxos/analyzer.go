package paxos

import "protoverify/pkg/base"

// CountReachableStates counts all unique states reachable from init via BFS
// up to the given depth. Returns the total number of explored states.
func CountReachableStates(init *base.State, depth int) int {
	// TODO: Use BfsFindAll to count all unique reachable states up to given depth.
	panic("implement me")
}

// FindShortestConsensusPath finds the minimum-depth path from init to a state
// where at least one server has reached consensus.
// Returns (depth, path) or (-1, nil) if consensus is not reachable within maxDepth.
func FindShortestConsensusPath(init *base.State, maxDepth int) (int, []base.StateEdge) {
	// TODO: Use BfsFind with the goal predicate to find the shortest consensus path.
	panic("implement me")
}

// VerifySafety checks that no reachable state (up to given depth) violates the
// consensus agreement safety property: if consensus is reached, no two servers
// may agree on different values, and a decided value cannot change.
func VerifySafety(init *base.State, depth int) bool {
	// TODO: Use BfsFindAll with the validate predicate to verify safety.
	panic("implement me")
}

// FindNonTerminatingExecution searches for an execution path of exactly the
// given depth where no server has reached consensus at the final state.
// Returns (true, path) if found, (false, nil) otherwise.
func FindNonTerminatingExecution(init *base.State, depth int) (bool, []base.StateEdge) {
	// TODO: Use BfsFind to find a state at the target depth with no consensus.
	panic("implement me")
}
