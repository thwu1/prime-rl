package raft


// StateMachine is a simple key-value store that serves as the
// replicated state machine. Commands are applied in log order
// after commitment.
type StateMachine struct {
	data map[string]string
}

// NewStateMachine creates a new empty StateMachine.
func NewStateMachine() *StateMachine {
	return &StateMachine{data: make(map[string]string)}
}

// Apply applies a command to the state machine and returns the result.
func (sm *StateMachine) Apply(command map[string]string) string {
	if command == nil {
		return ""
	}
	op := command["op"]
	switch op {
	case "set":
		sm.data[command["key"]] = command["value"]
		return command["value"]
	case "get":
		return sm.data[command["key"]]
	case "delete":
		val := sm.data[command["key"]]
		delete(sm.data, command["key"])
		return val
	case "noop":
		return ""
	default:
		return ""
	}
}

// Get reads a value from the state machine.
// Returns the value and whether the key exists.
func (sm *StateMachine) Get(key string) (string, bool) {
	val, ok := sm.data[key]
	return val, ok
}

// Snapshot returns a copy of the current state.
func (sm *StateMachine) Snapshot() map[string]string {
	snap := make(map[string]string)
	for k, v := range sm.data {
		snap[k] = v
	}
	return snap
}
