package base

type Timer interface {
	RemainingTime() int
	Wait(t int)
}
