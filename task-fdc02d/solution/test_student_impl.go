package paxos

import (
	"coms4113/hw5/pkg/base"
)

func noneAgreed(s *base.State) bool {
	for _, node := range s.Nodes() {
		server := node.(*Server)
		if server.agreedValue != nil {
			return false
		}
	}
	return true
}

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
	s2HigherNp := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		return s2.n_p > s1.proposer.N
	}
	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, s2HigherNp}
}

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

func NotTerminate1() []func(s *base.State) bool {
	p1Propose := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Propose && noneAgreed(s)
	}
	p1Accept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && noneAgreed(s)
	}
	p3Propose := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s3 := s.Nodes()["s3"].(*Server)
		s1 := s.Nodes()["s1"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}
	allNpHigherThanS1 := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		for _, node := range s.Nodes() {
			srv := node.(*Server)
			if srv.n_p <= s1.proposer.N {
				return false
			}
		}
		return true
	}
	p3Accept := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept && noneAgreed(s)
	}
	s1SomeRejects := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 2 && s1.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, allNpHigherThanS1, p3Accept, s1SomeRejects}
}

func NotTerminate2() []func(s *base.State) bool {
	p1ProposeHigher := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.proposer.Phase == Propose && s1.proposer.N > s3.proposer.N
	}
	allNpHigherThanS3 := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s3 := s.Nodes()["s3"].(*Server)
		for _, node := range s.Nodes() {
			srv := node.(*Server)
			if srv.n_p <= s3.proposer.N {
				return false
			}
		}
		return true
	}
	s3SomeRejects := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept && s3.proposer.ResponseCount >= 2 && s3.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p1ProposeHigher, allNpHigherThanS3, s3SomeRejects}
}

func NotTerminate3() []func(s *base.State) bool {
	p3ProposeHigher := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s3 := s.Nodes()["s3"].(*Server)
		s1 := s.Nodes()["s1"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}
	allNpHigherThanS1 := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		for _, node := range s.Nodes() {
			srv := node.(*Server)
			if srv.n_p <= s1.proposer.N {
				return false
			}
		}
		return true
	}
	p3Accept := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept && noneAgreed(s)
	}
	s1InAccept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && noneAgreed(s)
	}
	s1SomeRejects := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 2 && s1.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p3ProposeHigher, allNpHigherThanS1, p3Accept, s1InAccept, s1SomeRejects}
}

func concurrentProposer1() []func(s *base.State) bool {
	p1Propose := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Propose && noneAgreed(s)
	}
	p1Accept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && noneAgreed(s)
	}
	p3Propose := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s3 := s.Nodes()["s3"].(*Server)
		s1 := s.Nodes()["s1"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}
	allNpHigherThanS1 := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		for _, node := range s.Nodes() {
			srv := node.(*Server)
			if srv.n_p <= s1.proposer.N {
				return false
			}
		}
		return true
	}
	p3Accept := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept && noneAgreed(s)
	}
	s1SomeRejects := func(s *base.State) bool {
		if !noneAgreed(s) {
			return false
		}
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 2 && s1.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, allNpHigherThanS1, p3Accept, s1SomeRejects}
}

func concurrentProposer2() []func(s *base.State) bool {
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
