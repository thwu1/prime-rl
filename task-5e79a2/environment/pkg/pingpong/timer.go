package pingpong

type PingTimer struct {
}

func (timer *PingTimer) RemainingTime() int {
	return 0
}

func (timer *PingTimer) Wait(t int) {
	return
}
