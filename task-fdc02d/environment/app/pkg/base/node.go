package base

type Node interface {
	MessageHandler(message Message) []Node
	NextTimer() Timer
	TriggerTimer() []Node
	HandlerResponse() []Message
	Attribute() interface{}
	Copy() Node
	Hash() uint64
	Equals(other Node) bool
}

type CoreNode struct {
	Response []Message
}

func (node *CoreNode) HandlerResponse() []Message {
	res := node.Response
	node.Response = nil
	return res
}

func (node *CoreNode) SetResponse(response []Message) {
	node.Response = make([]Message, 0, len(response))
	node.Response = append(node.Response, response...)
}

func (node *CoreNode) SetSingleResponse(response Message) {
	node.Response = []Message{response}
}
