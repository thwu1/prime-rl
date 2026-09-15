package paxos

import "protoverify/pkg/base"

func LeadToValueAdoption() []func(*base.State) bool {
	// s3 enters Propose phase (timer fires)
	p3Propose := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose
	}

	// s3 enters Accept phase with V="gamma"
	p3Accept := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept && s3.proposer.V == "gamma"
	}

	// s2 has accepted gamma (v_a = "gamma")
	s2AcceptsGamma := func(s *base.State) bool {
		s2 := s.Nodes()["s2"].(*Server)
		return s2.v_a == "gamma"
	}

	// s1 proposes with N > 1 (after timeout)
	p1Repropose := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Propose && s1.proposer.N > 1
	}

	// s1 adopts gamma in Accept phase
	p1AdoptsGamma := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.V == "gamma"
	}

	return []func(*base.State) bool{p3Propose, p3Accept, s2AcceptsGamma, p1Repropose, p1AdoptsGamma}
}

func LeadToProgressiveContention() []func(*base.State) bool {
	// s1 enters Propose phase
	p1Propose := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Propose
	}

	// s1 enters Accept phase
	p1Accept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept
	}

	// s2's n_p exceeds s1's proposal number (s3 proposed with higher N)
	s2HigherNp := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		return s1.proposer.Phase == Accept && s2.n_p > s1.proposer.N
	}

	// s1 receives AcceptResponse rejection from s2
	p1Rejected := func(s *base.State) bool {
		event := s.Event
		if event.Action != base.Handle && event.Action != base.HandleDuplicate {
			return false
		}
		m, ok := event.Instance.(*AcceptResponse)
		return ok && !m.Ok && m.From() == "s2" && m.To() == "s1"
	}

	return []func(*base.State) bool{p1Propose, p1Accept, s2HigherNp, p1Rejected}
}

func LeadToThreeWayResolution() []func(*base.State) bool {
	// Any server reaches consensus
	anyConsensus := func(s *base.State) bool {
		for _, node := range s.Nodes() {
			server := node.(*Server)
			if !base.IsNil(server.agreedValue) {
				return true
			}
		}
		return false
	}

	// All three agree on the same value
	allAgree := func(s *base.State) bool {
		var v interface{}
		for _, node := range s.Nodes() {
			server := node.(*Server)
			if base.IsNil(server.agreedValue) {
				return false
			}
			if base.IsNil(v) {
				v = server.agreedValue
			} else if v != server.agreedValue {
				return false
			}
		}
		return !base.IsNil(v)
	}

	return []func(*base.State) bool{anyConsensus, allAgree}
}
