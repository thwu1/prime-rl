package pingpong

import "coms4113/hw5/pkg/base"

type PingMessage struct {
	base.CoreMessage
	Id int
}

func (p *PingMessage) Hash() uint64 {
	return base.Hash("ping", *p)
}

func (p *PingMessage) Equals(o base.Message) bool {
	other, ok := o.(*PingMessage)
	if !ok {
		return false
	}
	return p.CoreMessage.Equals(&other.CoreMessage) && p.Id == other.Id
}

type PongMessage struct {
	base.CoreMessage
	Id int
}

func (p *PongMessage) Hash() uint64 {
	return base.Hash("pong", *p)
}

func (p *PongMessage) Equals(o base.Message) bool {
	other, ok := o.(*PongMessage)
	if !ok {
		return false
	}
	return p.CoreMessage.Equals(&other.CoreMessage) && p.Id == other.Id
}

type PingCommand struct {
	To base.Address
	Id int
}
