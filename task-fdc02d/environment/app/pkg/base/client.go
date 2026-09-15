package base

type Client interface {
	SendCommand(s *State, command Command)
}
