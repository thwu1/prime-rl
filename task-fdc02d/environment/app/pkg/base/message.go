package base

type Address string

type Message interface {
	From() Address

	To() Address

	Hash() uint64

	Equals(Message) bool
}

type CoreMessage struct {
	from Address
	to   Address
}

func MakeCoreMessage(from, to Address) CoreMessage {
	return CoreMessage{
		from: from,
		to:   to,
	}
}

func (m *CoreMessage) From() Address {
	return m.from
}

func (m *CoreMessage) To() Address {
	return m.to
}

func (m *CoreMessage) Equals(other *CoreMessage) bool {
	return m.from == other.from && m.to == other.to
}
