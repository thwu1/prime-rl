package paxos

import "protoverify/pkg/base"

// globalAgreedValue returns the consensus status:
// -1: conflicting agreed values (safety violation)
//  0: no server has agreed yet
//  1: at least one server has agreed, all agreed on same value
func globalAgreedValue(state *base.State) (int, interface{}) {
	var v interface{}

	for _, node := range state.Nodes() {
		server := node.(*Server)

		if !base.IsNil(server.agreedValue) {
			if base.IsNil(v) {
				v = server.agreedValue
			} else if v != server.agreedValue {
				return -1, nil
			}
		}
	}

	if v == nil {
		return 0, nil
	}

	return 1, v
}

func validate(state *base.State) bool {
	flag, v := globalAgreedValue(state)

	if flag == -1 {
		return false
	}

	old := state.Prev

	if old != nil {
		_, oldV := globalAgreedValue(old)

		if !base.IsNil(oldV) && oldV != v {
			return false
		}
	}

	return true
}

func goal(state *base.State) bool {
	for _, node := range state.Nodes() {
		server := node.(*Server)
		if !base.IsNil(server.agreedValue) {
			return true
		}
	}

	return false
}

func reachState(start *base.State,
	checks []func(s *base.State) bool,
	depthLimit int) *base.State {

	s := start
	for _, check := range checks {
		res := base.BfsFind(s, validate, check, s.Depth+depthLimit)
		if !res.Success {
			return nil
		}
		s = res.Targets[0]
	}

	return s
}
