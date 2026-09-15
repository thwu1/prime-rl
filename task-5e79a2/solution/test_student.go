package paxos

import (
	"coms4113/hw5/pkg/base"
)

func checkNoConsensus(s *base.State) bool {
	for _, node := range s.Nodes() {
		server := node.(*Server)
		if server.agreedValue != nil {
			return false
		}
	}
	return true
}

// Fill in the function to lead the program to a state where A2 rejects the Accept Request of P1
func ToA2RejectP1() []func(s *base.State) bool {
	p1Propose := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Propose
	}

	p1Accept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept
	}

	p3Propose := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose
	}

	p3ProposeHigherN := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}

	s2AcceptsP3 := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		return s2.n_p > s1.proposer.N
	}

	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, p3ProposeHigherN, s2AcceptsP3}
}

// Fill in the function to lead the program to a state where a consensus is reached in Server 3.
func ToConsensusCase5() []func(s *base.State) bool {
	p3Accept := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept
	}

	p3Decide := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Decide
	}

	return []func(s *base.State) bool{p3Accept, p3Decide}
}

// Fill in the function to lead the program to a state where all the Accept Requests of P1 are rejected
func NotTerminate1() []func(s *base.State) bool {
	p1Propose := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Propose
	}

	p1Accept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept
	}

	p3Propose := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose
	}

	p3ProposeHigherN := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}

	p3AcceptHigherN := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		s1 := s.Nodes()["s1"].(*Server)
		return s3.proposer.Phase == Accept && s3.proposer.N > s1.proposer.N
	}

	s1SomeRejects := func(s *base.State) bool {
		if !checkNoConsensus(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 1 && s1.proposer.SuccessCount == 0
	}

	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, p3ProposeHigherN, p3AcceptHigherN, s1SomeRejects}
}

// Fill in the function to lead the program to a state where all the Accept Requests of P3 are rejected
func NotTerminate2() []func(s *base.State) bool {
	p1ProposeHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.proposer.Phase == Propose && s1.proposer.N > s3.proposer.N
	}

	p1AcceptHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.N > s3.proposer.N
	}

	s3SomeRejects := func(s *base.State) bool {
		if !checkNoConsensus(s) {
			return false
		}
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept && s3.proposer.ResponseCount >= 1 && s3.proposer.SuccessCount == 0
	}

	return []func(s *base.State) bool{p1ProposeHigher, p1AcceptHigher, s3SomeRejects}
}

// Fill in the function to lead the program to a state where all the Accept Requests of P1 are rejected again.
func NotTerminate3() []func(s *base.State) bool {
	p3ProposeHigher := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		s1 := s.Nodes()["s1"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}

	p3AcceptHigher := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		s1 := s.Nodes()["s1"].(*Server)
		return s3.proposer.Phase == Accept && s3.proposer.N > s1.proposer.N
	}

	s1SomeRejects := func(s *base.State) bool {
		if !checkNoConsensus(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 1 && s1.proposer.SuccessCount == 0
	}

	return []func(s *base.State) bool{p3ProposeHigher, p3AcceptHigher, s1SomeRejects}
}

// Fill in the function to lead the program to make P1 propose first, then P3 proposes, but P1 get rejects in
// Accept phase
func concurrentProposer1() []func(s *base.State) bool {
	p1Propose := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Propose
	}

	p1Accept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept
	}

	p3Propose := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose
	}

	p3ProposeHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}

	p3AcceptHigher := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		s1 := s.Nodes()["s1"].(*Server)
		return s3.proposer.Phase == Accept && s3.proposer.N > s1.proposer.N
	}

	s1SomeRejects := func(s *base.State) bool {
		if !checkNoConsensus(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 1 && s1.proposer.SuccessCount == 0
	}

	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, p3ProposeHigher, p3AcceptHigher, s1SomeRejects}
}

// Fill in the function to lead the program continue  P3's proposal  and reaches consensus at the value of "v3".
func concurrentProposer2() []func(s *base.State) bool {
	p3Decide := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Decide
	}

	return []func(s *base.State) bool{p3Decide}
}
