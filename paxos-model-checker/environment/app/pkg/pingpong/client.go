package pingpong

import (
	"coms4113/hw5/pkg/base"
)

type PingCommand struct {
	To base.Address
	Id int
}

type ClientTimer struct{}

func (t *ClientTimer) RemainingTime() int { return 0 }
func (t *ClientTimer) Wait(time int)      {}

type Client struct {
	base.CoreNode
	ClientAttribute
}

type ClientAttribute struct {
	address    base.Address
	serverAddr base.Address
	target     int
	ack        int
	hasTimer   bool
}

func NewClient(address, serverAddr base.Address, target int, hasTimer bool) *Client {
	return &Client{
		ClientAttribute: ClientAttribute{
			address:    address,
			serverAddr: serverAddr,
			target:     target,
			hasTimer:   hasTimer,
		},
	}
}

func (c *Client) SendCommand(s *base.State, command_ base.Command) {
	cmd := command_.(PingCommand)
	ping := &PingMessage{
		CoreMessage: base.MakeCoreMessage(c.address, cmd.To),
		Id:          cmd.Id,
	}
	s.Send(ping)
}

func (c *Client) MessageHandler(message base.Message) []base.Node {
	pong, ok := message.(*PongMessage)
	if !ok {
		return []base.Node{c}
	}

	newClient := c.copy()
	newClient.ack++

	if newClient.ack < newClient.target {
		ping := &PingMessage{
			CoreMessage: base.MakeCoreMessage(c.address, c.serverAddr),
			Id:          pong.Id + 1,
		}
		newClient.SetSingleResponse(ping)
	}

	return []base.Node{newClient}
}

func (c *Client) NextTimer() base.Timer {
	if !c.hasTimer {
		return nil
	}
	return &ClientTimer{}
}

func (c *Client) TriggerTimer() []base.Node {
	if !c.hasTimer {
		return nil
	}
	newClient := c.copy()
	ping := &PingMessage{
		CoreMessage: base.MakeCoreMessage(c.address, c.serverAddr),
		Id:          c.ack + 1,
	}
	newClient.SetSingleResponse(ping)
	return []base.Node{newClient}
}

func (c *Client) copy() *Client {
	return &Client{
		ClientAttribute: c.ClientAttribute,
	}
}

func (c *Client) Attribute() interface{} {
	return c.ClientAttribute
}

func (c *Client) Copy() base.Node {
	return c.copy()
}

func (c *Client) Hash() uint64 {
	return base.Hash("client", c.ClientAttribute)
}

func (c *Client) Equals(other base.Node) bool {
	otherClient, ok := other.(*Client)
	return ok && c.ack == otherClient.ack
}

func IsFinal(s *base.State) bool {
	client := s.GetNode("client").(*Client)
	return client.ack >= client.target
}
