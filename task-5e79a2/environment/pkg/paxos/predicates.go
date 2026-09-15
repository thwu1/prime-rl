package paxos

import "protoverify/pkg/base"

// LeadToValueAdoption returns a chain of predicates that guide the model checker
// to a state where proposer s1 adopts a value from a previous proposal round
// instead of using its initial value.
//
// Setup: s1 proposes "alpha", s3 proposes "gamma", s2 is passive, no partitions.
//
// The predicate chain should guide exploration through these phases:
// 1. s3 proposes first and wins the prepare phase
// 2. s3's value "gamma" is accepted by s2
// 3. s1 times out and re-proposes with a higher proposal number
// 4. s1 learns about "gamma" from s2's ProposeResponse and adopts it
// 5. s1 enters Accept phase with V="gamma" (adopted value, not its initial "alpha")
func LeadToValueAdoption() []func(*base.State) bool {
	// TODO: implement predicate chain
	panic("implement me")
}

// LeadToProgressiveContention returns a chain of predicates that guide the
// model checker to a state where proposer s1's Accept phase is disrupted by
// a competing proposal from s3 that updates acceptor n_p values.
//
// Setup: s1 proposes "alpha", s3 proposes "gamma" (s3 starts with proposer.N=1,
// SessionId=1 to simulate having completed one round), s2 is passive, no partitions.
//
// The predicate chain should guide exploration through:
// 1. s1 enters Propose phase
// 2. s1 enters Accept phase (got majority prepare-ok)
// 3. s3 proposes with higher N, causing s2's n_p to exceed s1's proposal number
// 4. s1 receives an AcceptResponse rejection from s2
func LeadToProgressiveContention() []func(*base.State) bool {
	// TODO: implement predicate chain
	panic("implement me")
}

// LeadToThreeWayResolution returns a chain of predicates that guide the model
// checker to consensus when all three servers are competing proposers.
//
// Setup: s1 proposes "alpha", s2 proposes "beta", s3 proposes "gamma", no partitions.
//
// The predicate chain should find a path to:
// 1. At least one server reaching consensus
// 2. All three servers agreeing on the same value
func LeadToThreeWayResolution() []func(*base.State) bool {
	// TODO: implement predicate chain
	panic("implement me")
}
