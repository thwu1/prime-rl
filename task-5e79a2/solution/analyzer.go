package paxos

import "protoverify/pkg/base"

func CountReachableStates(init *base.State, depth int) int {
	result := base.BfsFindAll(init, func(s *base.State) bool { return true }, nil, depth)
	return result.N
}

func FindShortestConsensusPath(init *base.State, maxDepth int) (int, []base.StateEdge) {
	result := base.BfsFind(init, func(s *base.State) bool { return true }, goal, maxDepth)
	if !result.Success || len(result.Targets) == 0 {
		return -1, nil
	}
	_, path := base.FindPath(result.Targets[0])
	return result.Targets[0].Depth, path
}

func VerifySafety(init *base.State, depth int) bool {
	result := base.BfsFindAll(init, validate, nil, depth)
	return result.Success
}

func FindNonTerminatingExecution(init *base.State, depth int) (bool, []base.StateEdge) {
	noConsensus := func(s *base.State) bool {
		if s.Depth != depth {
			return false
		}
		for _, node := range s.Nodes() {
			server := node.(*Server)
			if !base.IsNil(server.agreedValue) {
				return false
			}
		}
		return true
	}

	result := base.BfsFind(init, func(s *base.State) bool { return true }, noConsensus, depth)
	if result.Success && len(result.Targets) > 0 {
		_, path := base.FindPath(result.Targets[0])
		return true, path
	}
	return false, nil
}
