package main


type InsType byte

const (
	Plus          InsType = '+'
	Minus         InsType = '-'
	Right         InsType = '>'
	Left          InsType = '<'
	PutChar       InsType = '.'
	ReadChar      InsType = ','
	JumpIfZero    InsType = '['
	JumpIfNotZero InsType = ']'
)

type Instruction struct {
	Type     InsType
	Argument int
}

func InsTypeName(t InsType) string {
	switch t {
	case Plus:
		return "Plus"
	case Minus:
		return "Minus"
	case Right:
		return "Right"
	case Left:
		return "Left"
	case PutChar:
		return "PutChar"
	case ReadChar:
		return "ReadChar"
	case JumpIfZero:
		return "JumpIfZero"
	case JumpIfNotZero:
		return "JumpIfNotZero"
	default:
		return string(rune(t))
	}
}
