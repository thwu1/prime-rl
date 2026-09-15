package paxos

import (
	"coms4113/hw5/pkg/base"
)

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
	p3ProposeHigher := func(s *base.State) bool {
		s2 := s.Nodes()["s2"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s2.n_p
	}
	s2HigherNp := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		return s2.n_p > s1.proposer.N
	}
	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, p3ProposeHigher, s2HigherNp}
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
	p3HigherN := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}
	allNpHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.n_p > s1.proposer.N && s2.n_p > s1.proposer.N && s3.n_p > s1.proposer.N
	}
	s1TwoRejects := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 2 && s1.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, p3HigherN, allNpHigher, s1TwoRejects}
}

func NotTerminate2() []func(s *base.State) bool {
	p3Accept := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept
	}
	p1ProposeHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.proposer.Phase == Propose && s1.proposer.N > s3.proposer.N
	}
	allNpHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.n_p > s3.proposer.N && s2.n_p > s3.proposer.N && s3.n_p > s3.proposer.N
	}
	s3TwoRejects := func(s *base.State) bool {
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Accept && s3.proposer.ResponseCount >= 2 && s3.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p3Accept, p1ProposeHigher, allNpHigher, s3TwoRejects}
}

func NotTerminate3() []func(s *base.State) bool {
	p1Accept := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept
	}
	p3ProposeHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}
	allNpHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.n_p > s1.proposer.N && s2.n_p > s1.proposer.N && s3.n_p > s1.proposer.N
	}
	s1TwoRejects := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 2 && s1.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p1Accept, p3ProposeHigher, allNpHigher, s1TwoRejects}
}

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
	p3HigherN := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s3.proposer.Phase == Propose && s3.proposer.N > s1.proposer.N
	}
	allNpHigher := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		s2 := s.Nodes()["s2"].(*Server)
		s3 := s.Nodes()["s3"].(*Server)
		return s1.n_p > s1.proposer.N && s2.n_p > s1.proposer.N && s3.n_p > s1.proposer.N
	}
	s1TwoRejects := func(s *base.State) bool {
		s1 := s.Nodes()["s1"].(*Server)
		return s1.proposer.Phase == Accept && s1.proposer.ResponseCount >= 2 && s1.proposer.SuccessCount == 0
	}
	return []func(s *base.State) bool{p1Propose, p1Accept, p3Propose, p3HigherN, allNpHigher, s1TwoRejects}
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
