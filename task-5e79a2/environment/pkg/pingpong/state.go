package pingpong

import "coms4113/hw5/pkg/base"

func IsFinal(s *base.State) bool {
	client := s.GetNode("client").(*Client)
	return client.ack >= client.total
}
