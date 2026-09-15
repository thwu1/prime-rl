package pingpong

import "coms4113/hw5/pkg/base"

type PingMessage struct {
	base.CoreMessage
	Id int
}

func (m *PingMessage) Hash() uint64 {
	return base.Hash("ping", *m)
}

func (m *PingMessage) Equals(other base.Message) bool {
	o, ok := other.(*PingMessage)
	if !ok {
		return false
	}
	return m.CoreMessage.Equals(&o.CoreMessage) && m.Id == o.Id
}

type PongMessage struct {
	base.CoreMessage
	Id int
}

func (m *PongMessage) Hash() uint64 {
	return base.Hash("pong", *m)
}

func (m *PongMessage) Equals(other base.Message) bool {
	o, ok := other.(*PongMessage)
	if !ok {
		return false
	}
	return m.CoreMessage.Equals(&o.CoreMessage) && m.Id == o.Id
}
