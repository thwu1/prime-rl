package pingpong

import "coms4113/hw5/pkg/base"

type ClientAttribute struct {
	address  base.Address
	server   base.Address
	total    int
	ack      int
	useTimer bool
}

type Client struct {
	base.CoreNode
	ClientAttribute
}

func NewClient(address, server base.Address, total int, useTimer bool) *Client {
	return &Client{
		ClientAttribute: ClientAttribute{
			address:  address,
			server:   server,
			total:    total,
			ack:      0,
			useTimer: useTimer,
		},
	}
}

func (client *Client) SendCommand(s *base.State, command_ base.Command) {
	command, ok := command_.(PingCommand)
	if !ok {
		return
	}

	s.Receive([]base.Message{
		&PingMessage{
			CoreMessage: base.MakeCoreMessage(client.address, command.To),
			Id:          command.Id,
		},
	})
}

func (client *Client) MessageHandler(message base.Message) []base.Node {
	pong, ok := message.(*PongMessage)
	if !ok {
		newClient := client.copy()
		return []base.Node{newClient}
	}

	newClient := client.copy()
	if pong.Id == newClient.ack+1 {
		newClient.ack++
		if newClient.ack < newClient.total {
			newClient.SetSingleResponse(&PingMessage{
				CoreMessage: base.MakeCoreMessage(newClient.address, newClient.server),
				Id:          newClient.ack + 1,
			})
		}
	}

	return []base.Node{newClient}
}

func (client *Client) NextTimer() base.Timer {
	if !client.useTimer || client.ack >= client.total {
		return nil
	}
	return &PingTimer{}
}

func (client *Client) TriggerTimer() []base.Node {
	if !client.useTimer || client.ack >= client.total {
		return nil
	}

	newClient := client.copy()
	newClient.SetSingleResponse(&PingMessage{
		CoreMessage: base.MakeCoreMessage(newClient.address, newClient.server),
		Id:          newClient.ack + 1,
	})

	return []base.Node{newClient}
}

func (client *Client) Attribute() interface{} {
	return client.ClientAttribute
}

func (client *Client) Copy() base.Node {
	return client.copy()
}

func (client *Client) copy() *Client {
	return &Client{
		ClientAttribute: client.ClientAttribute,
	}
}

func (client *Client) Hash() uint64 {
	return base.Hash("client", client.ClientAttribute)
}

func (client *Client) Equals(other base.Node) bool {
	otherClient, ok := other.(*Client)
	return ok && client.ack == otherClient.ack
}

func (client *Client) Address() base.Address {
	return client.address
}
